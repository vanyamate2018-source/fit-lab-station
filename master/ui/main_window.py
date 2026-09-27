from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl, QSize, QProcess, QPropertyAnimation, QEasingCurve, QEvent
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut, QIcon
from PySide6.QtNetwork import QHostAddress, QUdpSocket, QAbstractSocket
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QScroller, QSpinBox, QStackedWidget,
    QTabWidget, QVBoxLayout, QWidget, QApplication, QToolButton, QGraphicsOpacityEffect, QSizePolicy,
)

from master.camera import CameraManager, valid_host
from master.core import StationCore
from master.discovery import DiscoveryServer
from master.session import StationSession
from master.ui.brand import icon, ui_icon
from master.ui.touch import TouchSupport
from master.ui.display import DisplayLayout
from master.ui.camera_settings import CameraSettings
from master.ui.radio_settings import RadioSettings
from master.ui.modules import ModulesPage
from master.ui.choices import ChoicePicker
from master.usb_monitor import UsbMonitor
from master.ui.video import TrafficChart, VideoCanvas, ActivityDot
from master.ui.receiver_indicator import ReceiverIndicator, LinkQuality
from master.ui.widgets import MetricChip, StatusBadge, repolish, MotionButton, MotionToolButton, InlineMetric, ElidingLabel
from shared.config import StationConfig
from shared.storage import ensure_directories, probe_storage


def label(text, prop=None):
    item = QLabel(text)
    if prop:
        item.setProperty(prop, True)
    return item


def button(text, callback, role="ghost"):
    item = MotionButton(text)
    item.setProperty("role", role)
    item.clicked.connect(callback)
    return item


def action_icon(name):
    return ui_icon(name)


def icon_button(name, tooltip, callback, role="ghost"):
    item = button("", callback, role)
    item.setIcon(action_icon(name))
    item.setIconSize(QSize(24, 24))
    item.setFixedSize(64, 56)
    item.setProperty("iconOnly", True)
    item.setToolTip(tooltip)
    item.setAccessibleName(tooltip)
    return item


def dock_button(name, text, callback, role="ghost"):
    item = MotionToolButton()
    item.setText(text)
    item.setAccessibleName(text)
    item.setToolTip(text)
    item.setProperty("role", role)
    item.setProperty("dockAction", True)
    item.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    item.setIcon(action_icon(name))
    item.setIconSize(QSize(30, 30))
    item.setMinimumSize(90, 64)
    item.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    item.clicked.connect(callback)
    return item


def panel():
    item = QFrame()
    item.setProperty("card", True)
    layout = QVBoxLayout(item)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(14)
    return item, layout


class FullscreenVideo(QDialog):
    def __init__(self, source, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("FIT-LAB · Видео")
        self.setStyleSheet("QDialog { background: #000; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.video = VideoCanvas()
        self.video.set_frame(source.image)
        self.video.stale = source.stale
        self.video.title, self.video.subtitle = source.title, source.subtitle
        layout.addWidget(self.video)
        self.leave = icon_button("expand", "Выйти из полного экрана · Esc", self.close)
        self.leave.setParent(self)
        self.leave.raise_()
        self.video.doubleClicked.connect(self.close)
        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        QShortcut(QKeySequence("F11"), self, activated=self.close)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.leave.move(self.width() - 68, 20)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FIT-LAB Station")
        self.embedded_receiver = os.environ.get('FIT_LAB_EMBEDDED_RECEIVER') == '1'
        if self.embedded_receiver:
            QApplication.instance().aboutToQuit.connect(lambda: self._desktop_panel(True))
        if self.embedded_receiver:
            self.setWindowTitle('FIT-LAB · Видеомодуль WFB')
        self.setWindowIcon(icon())
        self.resize(1380, 850)
        if self.embedded_receiver and QApplication.primaryScreen():
            self.resize(QApplication.primaryScreen().geometry().size())
        self.setMinimumSize(800, 480)
        self.config = StationConfig.load()
        ensure_directories(self.config.data_root, self.config.required_directories())
        self.preferences_path = self.config.data_root / "config" / "interface.json"
        try:
            self.preferences = json.loads(self.preferences_path.read_text())
            if not isinstance(self.preferences, dict):
                self.preferences = {}
        except (OSError, ValueError):
            self.preferences = {}
        self.station = StationCore()
        self.discovery = DiscoveryServer(self.station)
        self.session = StationSession(self.config.data_root, self)
        self.camera = CameraManager(self.config.data_root, self.preferences.get("camera_host", "192.168.1.10"), self)
        from master.camera_credentials import CameraCredentialStore
        self.camera.credentials_store = CameraCredentialStore(self.config.data_root)
        self.auto_login_attempts = set()
        self.auto_login_pending = False
        self.auto_login_context = None
        self.auto_login_failures = {}
        self.auto_login_retry_at = 0
        self.login_dialog_open = False
        self.camera.transport = self.preferences.get('camera_transport', 'radio')
        self.camera_browser = None
        self.camera_profile = None
        self.pairing_requested = False
        self.pairing_resume = False
        self.pairing_after_login = False
        self.lan_candidate_fingerprint = None
        self.known_camera_fingerprints = set()
        for path in (self.config.data_root / 'config/cameras').glob('*.json'):
            try:
                self.known_camera_fingerprints.add(json.loads(path.read_text()).get('fingerprint'))
            except (OSError, ValueError):
                pass
        self.camera_auth = None
        self.resume_after_radio = False
        self.radio_switch = None
        self.radio_switch_path = self.config.data_root / 'config/pending-radio-switch.json'
        self.radio_switch_timer = QTimer(self)
        self.radio_switch_timer.setInterval(500)
        self.radio_switch_timer.timeout.connect(self._tick_radio_switch)
        self.record_directory = Path(self.preferences.get("record_directory", self.config.data_root / "recordings"))
        self.previous_phase = "idle"
        self.last_camera_state = None
        self.last_chart = 0.0
        self.recent_notifications = {}
        from master.sounds import EventSounds
        self.sounds = EventSounds(self.config.data_root, self.preferences.get('event_sounds', True), self)
        self.sounds.voice_enabled = bool(self.preferences.get('event_voice', False))
        self.sounds.event_enabled = dict(self.preferences.get('sound_events', {}))
        self.sounds.set_voice_volume(int(self.preferences.get('voice_volume', 100)))
        self.sounds.set_volume(int(self.preferences.get('event_volume', 16 if self.embedded_receiver else 8)))
        self.camera_labels = {}
        self.announced_cameras = set()
        self.fullscreen_video = None
        self.cached_fullscreen_video = None
        self.native_focus = False
        self.system_volume = None
        self.nav = {}
        self.module_states = {}
        root = QWidget()
        root.setObjectName("stationRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.sidebar = self._sidebar()
        content = QWidget()
        content.setObjectName("stationContent")
        column = QVBoxLayout(content)
        self.content_column = column
        column.setContentsMargins(12, 4, 12, 8)
        column.setSpacing(6)
        top = QHBoxLayout()
        self.header_row = top
        self.brand_wordmark = label("FIT-LAB")
        self.brand_wordmark.setObjectName("brandWordmark")
        top.addWidget(self.brand_wordmark)
        from master.ui.system_meter import SystemMeter
        self.system_meter = SystemMeter(self)
        top.addWidget(self.system_meter)
        top.addSpacing(18)
        self.product_label = label("FPV GROUND STATION", "eyebrow")
        top.addWidget(self.product_label)
        top.addSpacing(18)
        self.page_title = label("Видеоприём", "title")
        top.addWidget(self.page_title)
        self.module_summary = StatusBadge("МОДУЛИ · 0", "warning")
        self.module_summary.setToolTip("Состояние устройств — в разделе «Модули»")
        top.addWidget(self.module_summary)
        self.status = StatusBadge("ГОТОВ", "ready")
        top.addSpacing(12)
        self.status.setFixedHeight(28)
        top.addWidget(self.status)
        self.minimize_button = icon_button('minimize', 'Свернуть приложение', self.showMinimized)
        self.minimize_button.setAccessibleName('Свернуть приложение')
        self.minimize_button.setFixedSize(44, 38)
        self.minimize_button.setStyleSheet('min-height: 28px; min-width: 34px; padding: 0;')
        top.addWidget(self.minimize_button)
        self.power_button = icon_button('power', 'Питание приложения', self._power_menu)
        self.power_button.setAccessibleName('Питание приложения')
        self.power_button.setFixedSize(44, 38)
        self.power_button.setStyleSheet('min-height: 28px; min-width: 34px; padding: 0;')
        top.addWidget(self.power_button)
        column.addLayout(top)
        self.toast = ElidingLabel()
        self.toast.setObjectName("toast")
        self.toast.setTextFormat(Qt.TextFormat.PlainText)
        self.toast.setFixedHeight(24)
        self.toast.setStyleSheet("padding: 2px 10px;")
        # The flexible notification area follows the title; placing it before
        # the title pushed section names against the right-hand status badges.
        top.insertWidget(top.indexOf(self.page_title) + 1, self.toast, 1)
        self.toast_opacity = QGraphicsOpacityEffect(self.toast)
        self.toast.setGraphicsEffect(self.toast_opacity)
        self.toast_animation = QPropertyAnimation(self.toast_opacity, b"opacity", self)
        self.toast_animation.setDuration(220)
        self.toast_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self._fade_notification)
        from master.notifications import NotificationQueue
        self.notification_queue = NotificationQueue()
        self.notification_timer = QTimer(self)
        self.notification_timer.setInterval(250)
        self.notification_timer.timeout.connect(self._deliver_notification)
        self.pages = QStackedWidget()
        self.page_keys = {}
        builders = [("live", self._live_page), ("camera", self._camera_page), ("radio", self._radio_page),
                    ("network", self._network_page), ("modules", self._modules_page), ("system", self._system_page),
                    ("journal", self._journal_page)]
        for key, build in builders:
            page = build()
            if key not in ("live", "camera", "radio", "system"):
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.Shape.NoFrame)
                scroll.setWidget(page)
                page = scroll
            if self.embedded_receiver and QApplication.platformName() == 'xcb':
                # Native video makes its ancestors native too. Give every
                # stacked page its own opaque window so hidden settings cannot
                # remain in the video page's backing store after navigation.
                page.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
                page.setAutoFillBackground(True)
                page.setProperty('stationPage', True)
            self.page_keys[key] = self.pages.addWidget(page)
        for scroll in self.pages.findChildren(QScrollArea):
            from master.ui.scrolling import configure_touch_scrolling
            configure_touch_scrolling(scroll)
        column.addWidget(self.pages, 1)
        layout.addWidget(content, 1)
        layout.addWidget(self.sidebar)
        self.session.frame.connect(self.video.set_frame)
        if self.embedded_receiver and QApplication.platformName() == 'xcb' and os.environ.get('FIT_LAB_NATIVE_VIDEO') == '1':
            self.session.set_video_window(self.video.native_handle(), self.video.width(), self.video.height())
            self.video.nativeResized.connect(lambda width, height: self.session.set_video_window(self.video.native_handle(), width, height) if self.fullscreen_video is None else None)
        self.session.set_audio(int(self.preferences.get('camera_audio_volume', 35)), bool(self.preferences.get('camera_audio_muted', False)))
        self.video.audio_controls.set_values(self.session.audio_volume, self.session.audio_muted)
        self.video.audio_controls.changed.connect(self._set_camera_audio)
        self.video.doubleClicked.connect(self._focus)
        self.native_leave = icon_button('expand', 'Вернуться к управлению', self._focus)
        self.native_leave.setParent(self.video)
        if self.session.video_window_handle:
            self.native_leave.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.native_leave.hide()
        self.session.changed.connect(self._session_changed)
        self.session.cameraSelected.connect(self._radio_camera_selected)
        self.session.camerasDiscovered.connect(lambda cameras: self._camera_availability([c['identity'] for c in cameras]))
        self.session.cameraChoiceRequired.connect(self._choose_camera_for_start)
        self.session.message.connect(self.notify)
        self.session.diagnostic.connect(self._append_journal)
        self.camera.changed.connect(self._camera_changed)
        self.camera_sync_timer = QTimer(self)
        self.camera_sync_timer.setInterval(20000)
        self.camera_sync_timer.timeout.connect(self._sync_camera_settings)
        self.camera_sync_timer.start()
        self.camera.lanDiscovered.connect(self._lan_camera_found)
        self.camera.commandChanged.connect(self._camera_command_changed)
        from master.camera_lan import LanDeviceDiscovery
        self.lan_discovery = LanDeviceDiscovery(self, data_root=self.config.data_root)
        self.lan_discovery.changed.connect(self._lan_devices_changed)
        self.lan_discovery.scanningChanged.connect(self._lan_scan_changed)
        from master.viewer_server import ViewerService
        self.viewer_service = ViewerService(self.session)
        self.session.external_viewer = True
        self._refresh_interfaces()
        self.discovery_socket = QUdpSocket(self)
        self.discovery_ready = self.discovery_socket.bind(QHostAddress(QHostAddress.SpecialAddress.AnyIPv4), 60400)
        if self.discovery_ready:
            self.discovery_socket.readyRead.connect(self._discover_modules)
        else:
            self.notify("Обнаружение модулей недоступно: порт 60400 занят")
        self.health_timer = QTimer(self)
        self.health_timer.setInterval(5000)
        self.health_timer.timeout.connect(self._health)
        self.health_timer.start()
        self.touch = TouchSupport(self, self.config.data_root)
        self.touch.statusChanged.connect(self.touch_device_label.setText)
        self.usb_devices = []
        self.usb_monitor = UsbMonitor(self)
        self.usb_monitor.changed.connect(self._usb_changed)
        self.modules_timer = QTimer(self)
        self.modules_timer.setInterval(1000)
        self.modules_timer.timeout.connect(self._update_modules)
        self.modules_timer.start()
        self._health()
        self._update_modules()
        self._session_changed(self.session.state)
        self.show_page("live")
        QTimer.singleShot(5500, self.session.discover_cameras)
        QTimer.singleShot(0, lambda: self._append_journal('FIT-LAB запущен · видеоприём и запись запускаются вручную'))
        self.display_layout = DisplayLayout(self)
        from master.ui.swipe import SectionSwipe
        self.section_swipe = SectionSwipe(self.sidebar, list(self.nav.values()), self._swipe_section)
        QShortcut(QKeySequence("Escape"), self, activated=self._exit_focus)
        QShortcut(QKeySequence("F11"), self, activated=self._focus)

    def _sidebar(self):
        bar = QFrame()
        bar.setObjectName("sidebar")
        box = QHBoxLayout(bar)
        box.setContentsMargins(12, 5, 12, 5)
        box.setSpacing(4)
        for key, text, symbol in (("live", "Видео", "video"), ("radio", "Радиолиния", "radio"),
                                  ("osd", "OSD", "osd"), ("modules", "Модули", "modules"), ("system", "Система", "gear")):
            item = MotionToolButton()
            if key == 'modules' and self.embedded_receiver:
                text = 'Приёмник'
            item.setText(text)
            item.setIcon(action_icon(symbol))
            item.setIconSize(QSize(26, 26))
            item.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            item.setMinimumWidth(90)
            item.setFixedHeight(78)
            item.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            item.setAccessibleName(text)
            item.setProperty("nav", True)
            item.clicked.connect(lambda checked=False, k=key: self.show_page(k))
            self.nav[key] = item
            box.addWidget(item, 1)
        return bar

    def _swipe_section(self, direction):
        keys = list(self.nav)
        selected = next((key for key, item in self.nav.items() if item.property('selected')), 'live')
        index = min(len(keys)-1, max(0, keys.index(selected) + direction))
        self.show_page(keys[index])

    def _live_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        self.source = ChoicePicker('Источник приёма')
        self.source.addItems(["Встроенный модуль WFB", "Внешний модуль · LAN"])
        self.source.setCurrentIndex(1 if self.preferences.get('receiver_source') == 'lan' else 0)
        self.source.currentIndexChanged.connect(self._save_preferences)
        self.source.setMinimumWidth(175)
        self.live_toolbar_widget = QWidget()
        self.live_toolbar_column = QVBoxLayout(self.live_toolbar_widget)
        self.live_toolbar_column.setContentsMargins(0, 0, 0, 0)
        self.live_toolbar_column.setSpacing(0)
        self.live_toolbar = QHBoxLayout()
        self.live_toolbar_column.addLayout(self.live_toolbar)
        self.live_toolbar.setContentsMargins(0, 0, 0, 0)
        self.live_toolbar.setSpacing(7)
        self.compact_quality = LinkQuality(compact=True)

        self.live_rail = QWidget()
        rail = QVBoxLayout(self.live_rail)
        rail.setContentsMargins(0, 0, 0, 0)
        rail.setSpacing(8)
        radio, box = panel()
        self.live_radio_summary = radio
        radio.setObjectName("radioInspector")
        box.setContentsMargins(16, 8, 16, 8)
        box.setSpacing(0)
        heading = QHBoxLayout()
        antenna = label("")
        antenna.setPixmap(action_icon("radio").pixmap(23, 23))
        heading.addWidget(antenna)
        heading.addWidget(label("РАДИОЛИНИЯ", "eyebrow"))
        heading.addStretch()
        self.live_frequency = label("— MHz")
        self.live_frequency.setProperty("instrumentValue", True)
        heading.addWidget(self.live_frequency)
        box.addLayout(heading)
        self.rx_rail_layout = QVBoxLayout()
        self.rx_rail_layout.setContentsMargins(0, 0, 0, 0)
        self.rx_rail_layout.setSpacing(0)
        box.addLayout(self.rx_rail_layout)
        self.rx_rail_layout.setSpacing(7)
        self.rx_tiles = []
        for name in ("RX1", "RX2", "RX3"):
            tile = ReceiverIndicator(name)
            self.rx_rail_layout.addWidget(tile)
            tile.setVisible(name != "RX3")
            self.rx_tiles.append(tile)
        self.metrics = {}
        self.rail_quality = LinkQuality()
        self.snr_metric = self.rail_quality.fields['snr']
        for key in ('fec', 'loss'):
            self.metrics[key] = self.rail_quality.fields[key]
        box.addWidget(self.rail_quality)
        rail.addWidget(radio)
        tx, tx_box = panel()
        tx_box.setContentsMargins(16, 8, 16, 8)
        tx.setFixedHeight(44)
        tx_row = QHBoxLayout()
        tx_icon = label("")
        tx_icon.setPixmap(action_icon("radio").pixmap(20,20))
        tx_row.addWidget(tx_icon)
        tx_row.addWidget(label("TX"))
        tx_row.addSpacing(12)
        self.tx_label = label("Выключен", "muted")
        tx_row.addWidget(self.tx_label)
        tx_row.addStretch()
        self.tx_dot = ActivityDot(compact=True)
        tx_row.addWidget(self.tx_dot)
        tx_box.addLayout(tx_row)
        rail.addWidget(tx)
        camera, camera_box = panel()
        camera.setObjectName("cameraInspector")
        camera_box.setContentsMargins(16, 4, 16, 6)
        camera_box.setSpacing(4)
        camera_heading = QHBoxLayout()
        camera_heading.addWidget(label("ПЕРЕДАТЧИК", "eyebrow"))
        self.quick_camera_name = label("Нет связи", "muted")
        self.quick_camera_name.setStyleSheet("font-size:11px;")
        camera_heading.addStretch()
        camera_heading.addWidget(self.quick_camera_name)
        camera_box.addLayout(camera_heading)
        self.camera_choice = ChoicePicker('Камера')
        self.camera_choice.setFixedHeight(56)
        self.camera_choice.setToolTip('Автовыбор ищет сохранённые камеры по радио. Если включены несколько, предложит выбор. Для новой камеры сначала выполните сопряжение по LAN.')
        self.camera_choice.addItem('Автовыбор', None)
        self.camera_choice.currentIndexChanged.connect(self._camera_choice_changed)
        camera_box.addWidget(self.camera_choice)
        self.radio_editor = RadioSettings(compact=True)
        self.radio_editor.refreshRequested.connect(self._refresh_radio)
        self.radio_editor.restartRequested.connect(self._restart_radio)
        self.radio_editor.settingsRequested.connect(lambda changes: self._restart_radio(**changes))
        camera_box.addWidget(self.radio_editor)
        camera_box.addStretch()
        rail.addWidget(camera, 1)
        self.live_rail_scroll = QScrollArea()
        self.live_rail_scroll.setWidgetResizable(True)
        self.live_rail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.live_rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.live_rail_scroll.setWidget(self.live_rail)

        stage_row = QHBoxLayout()
        stage_row.setSpacing(10)
        stage = QWidget()
        stage.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        stage.setMinimumWidth(480)
        video_column = QVBoxLayout(stage)
        video_column.setContentsMargins(0,0,0,0)
        video_column.setSpacing(2)
        self.video = VideoCanvas()
        video_column.addWidget(self.video,1)
        self.stream_label = label("")
        self.stream_label.hide()
        self.frame_label = label("")
        self.frame_label.hide()
        self.telemetry = QFrame()
        self.telemetry.setObjectName("telemetryStrip")
        metrics = QHBoxLayout(self.telemetry)
        metrics.setContentsMargins(4,2,4,2)
        metrics.setSpacing(0)
        for key, caption, hint in (("mbps","Поток","Мбит/с"), ("megabytes","Приём","МБ/с"),
                                   ("fps","Экран","FPS"), ("codec","Кодек",""), ("size","Разрешение","")):
            metric = MetricChip(caption,"—",hint)
            metric.setMinimumWidth(92)
            self.metrics[key] = metric
            metrics.addWidget(metric,1)
        video_column.addWidget(self.telemetry)
        video_column.addWidget(self.live_toolbar_widget)
        stage_row.addWidget(stage,1)
        stage_row.addWidget(self.live_rail_scroll)
        root.addLayout(stage_row,1)
        self.dock = QFrame()
        self.dock.setObjectName("mediaDock")
        bottom = QHBoxLayout(self.dock)
        bottom.setContentsMargins(10,5,10,5)
        bottom.setSpacing(0)
        self.start_button = dock_button("play","Начать приём",self._start,"primary")
        self.stop_button = dock_button("stop","Стоп",self.session.stop,"primary")
        self.stop_button.hide()
        start_slot = QWidget()
        start_layout = QHBoxLayout(start_slot)
        start_layout.setContentsMargins(0,0,0,0)
        start_layout.addWidget(self.start_button)
        start_layout.addWidget(self.stop_button)
        self.record_button = dock_button("record","Запись",self._record)
        self.record_button.setProperty("recordAction",True)
        self.recordings_button = dock_button("folder", "Записи", self._open_recordings)
        self.stream_action = dock_button("stream","Трансляция",lambda: self.show_page("network"))
        self.dock_actions = [self.start_button,self.stop_button,self.record_button,self.recordings_button,self.stream_action]
        fullscreen = dock_button("expand","Полный экран",self._focus)
        camera_action = dock_button("settings","Настройки камеры",lambda:self.show_page("camera"))
        self.dock_actions.extend((fullscreen,camera_action))
        for index, control in enumerate((start_slot,self.record_button,self.recordings_button,self.stream_action,fullscreen,camera_action)):
            if index:
                separator = QFrame()
                separator.setObjectName("controlSeparator")
                separator.setFixedSize(1,40)
                bottom.addWidget(separator)
            bottom.addWidget(control,1)
        self.live_rail_mode = None
        root.addWidget(self.dock)
        return page

    def _camera_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        card, box = panel()
        row = QHBoxLayout()
        text = QVBoxLayout()
        self.camera_name = label("Подключите камеру", "section")
        self.camera_address = label(self.camera.host, "muted")
        text.addWidget(self.camera_name)
        text.addWidget(self.camera_address)
        row.addLayout(text)
        row.addStretch()
        self.camera_status = StatusBadge("ПОИСК", "offline")
        row.addWidget(self.camera_status)
        box.addLayout(row)
        self.camera_command_status = label('Команды не отправлялись', 'muted')
        self.camera_command_status.setWordWrap(True)
        self.camera_command_status.setTextFormat(Qt.TextFormat.PlainText)
        box.addWidget(self.camera_command_status)
        root.addWidget(card)
        tabs = QTabWidget()
        self.camera_tabs = tabs
        self.camera_editor = CameraSettings()
        self.camera_editor.applyRequested.connect(self._apply_camera_settings)
        self.camera_editor.refreshRequested.connect(self._refresh_camera_settings)
        self.camera_editor.restoreRequested.connect(self._restore_camera_settings)
        tabs.addTab(self.camera_editor, action_icon("settings"), "Настройки")
        self.camera_values = {}
        connection = QWidget()
        connection_box = QVBoxLayout(connection)
        connection_box.setContentsMargins(20, 20, 20, 20)
        connection_box.setSpacing(16)
        devices_card, devices_box = panel()
        devices_box.addWidget(label('Камеры в сети', 'section'))
        self.lan_devices = ChoicePicker('Найденные устройства')
        self.lan_devices.setEnabled(False)
        self.lan_device_data = []
        self.lan_announced = set()
        self.lan_steps = label('Подключите камеру к общей сети · выберите найденное устройство', 'muted')
        self.lan_steps.setWordWrap(True)
        devices_box.addWidget(self.lan_steps)
        devices_box.addWidget(self.lan_devices)
        actions = QHBoxLayout()
        actions.addWidget(button('Найти камеры', self._find_lan_cameras))
        self.lan_setup = button('Подключить и настроить', self._onboard_lan_device, 'primary')
        self.lan_setup.setEnabled(False)
        actions.addWidget(self.lan_setup, 1)
        devices_box.addLayout(actions)
        connection_box.addWidget(devices_card)
        transport_card, transport_box = panel()
        transport_box.addWidget(label("Подключение", "section"))
        transport_row = QWidget()
        transport_layout = QHBoxLayout(transport_row)
        transport_layout.setContentsMargins(0, 0, 0, 0)
        self.camera_transport_buttons = {}
        for title, value in (('Кабель LAN', 'lan'), ('Радиоканал', 'radio')):
            item = MotionButton(title, transport_row)
            item.setCheckable(True)
            item.setAutoExclusive(True)
            item.setProperty('transportChoice', True)
            item.setChecked(value == self.camera.transport)
            item.toggled.connect(lambda checked, mode=value: self._control_transport_changed(mode) if checked else None)
            self.camera_transport_buttons[value] = item
            transport_layout.addWidget(item)
        transport_box.addWidget(transport_row)
        host_row = QHBoxLayout()
        self.camera_host = QLineEdit(self.camera.host)
        self.camera_host.setPlaceholderText("Адрес камеры")
        self.camera_host.setAccessibleName("Адрес камеры")
        host_row.addWidget(self.camera_host, 1)
        host_row.addWidget(button("Найти", self._set_camera_host))
        host_row.addWidget(button('Войти', lambda: self._camera_login(manual=True)))
        transport_box.addLayout(host_row)
        self.camera_tx_status = label('Обратный канал выключен', 'muted')
        transport_box.addWidget(self.camera_tx_status)
        self.auto_login = QCheckBox('Автоматический вход')
        self.auto_login.setChecked(self.preferences.get('auto_login', True))
        self.auto_login.setToolTip('Сначала сохранённый пароль. Если камера его отклонит, появится форма входа.')
        self.auto_login.toggled.connect(self._save_preferences)
        transport_box.addWidget(self.auto_login)
        self.camera_settings_button = button('Веб-панель по LAN', self._open_camera_panel)
        self.camera_settings_button.setIcon(action_icon('expand'))
        self.camera_settings_button.setToolTip('Дополнительные функции прошивки. Параметры съёмки доступны во вкладке «Настройки».')
        self.camera_settings_button.setEnabled(False)
        transport_box.addWidget(self.camera_settings_button)
        connection_box.addWidget(transport_card)
        pairing, pairing_layout = panel()
        self.pairing_status = label('Первое сопряжение — по LAN', 'section')
        self.pairing_status.setWordWrap(True)
        pairing_layout.addWidget(self.pairing_status)
        self.saved_camera = label('Нет сохранённых камер', 'muted')
        self.saved_camera.setWordWrap(True)
        pairing_layout.addWidget(self.saved_camera)
        manage = button('Сохранённые камеры', self._manage_saved_cameras)
        manage.setIcon(action_icon('camera'))
        pairing_layout.addWidget(manage)
        self.auto_pair = QCheckBox('Привязывать новые камеры после входа по LAN')
        self.auto_pair.setChecked(self.preferences.get('auto_pair_lan', True))
        self.auto_pair.toggled.connect(self._save_preferences)
        pairing_layout.addWidget(self.auto_pair)
        self.pairing_button = button('Связать камеру', lambda: self._pair_keys(False), 'primary')
        self.pairing_button.setIcon(action_icon('key'))
        self.pairing_button.setToolTip('Первое сопряжение по LAN. Далее выберите знакомую камеру рядом с видео.')
        pairing_layout.addWidget(self.pairing_button)
        self.renew_pair_button = button('Обновить ключи', lambda: self._pair_keys(True))
        self.renew_pair_button.setIcon(action_icon('key'))
        pairing_layout.addWidget(self.renew_pair_button)
        access = QWidget()
        access_box = QVBoxLayout(access)
        access_box.setContentsMargins(16, 16, 16, 16)
        access_box.addWidget(pairing)
        security, security_box = panel()
        security_box.addWidget(label('Защита камеры', 'section'))
        self.security_status = label('Выполните вход для проверки защиты камеры', 'muted')
        self.security_status.setWordWrap(True)
        security_box.addWidget(self.security_status)
        self.protect_button = button('Защитить вход', self._protect_camera)
        self.protect_button.setIcon(action_icon('key'))
        self.protect_button.setToolTip('По LAN: новый случайный пароль, проверка входа и откат при сбое. Радиоключи меняются отдельно.')
        security_box.addWidget(self.protect_button)
        self.auto_protect = QCheckBox('Защищать камеры при подключении по LAN')
        self.auto_protect.setChecked(False)
        self.preferences['auto_protect_lan'] = False
        self.auto_protect.toggled.connect(self._save_preferences)
        self.auto_protect.hide()
        security_box.addWidget(button('Пароль и вход', lambda: self._camera_login(manual=True)))
        access_box.addWidget(security)
        access_box.addStretch()
        connection_box.addStretch()
        connection_scroll = QScrollArea()
        connection_scroll.setWidgetResizable(True)
        connection_scroll.setWidget(connection)
        tabs.addTab(connection_scroll, action_icon('key'), 'Подключение')
        info = QWidget()
        info_form = QFormLayout(info)
        info_form.setContentsMargins(20, 20, 20, 20)
        info_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for caption, rows in (
            ('Совместимость', (("compatibility", "Работа с FIT-LAB"), ("transmitter", "Передатчик"),
                              ("radio_bands", "Диапазоны драйвера"), ("working_band", "Рабочий диапазон"), ("active_frequency", "Рабочая частота"))),
            ('Устройство', (("hostname", "Имя"), ("platform", "Платформа"), ("soc", "Процессор"),
                           ("sensor", "Сенсор"), ("firmware", "Прошивка"), ("ethernet_mac", "MAC"))),
            ('Видео', (("codec", "Кодек"), ("size", "Разрешение"), ("fps", "Частота кадров"), ("bitrate", "Битрейт"), ("gop", "Ключевой кадр"))),
            ('OSD', (("osd_engine", "Тип"), ("osd_enabled", "OSD камеры"), ("osd_template", "Текст"))),
            ('Радиослужбы', (("radio_service", "Служба радио"), ("radio_driver", "Драйвер"), ("radio_tunnel", "IP-туннель"), ("adaptive_link", "Adaptive Link"))),
        ):
            info_form.addRow(label(caption, 'section'))
            for key, title in rows:
                value = label("—")
                value.setWordWrap(True)
                value.setTextFormat(Qt.TextFormat.PlainText)
                self.camera_values[key] = value
                info_form.addRow(label(title, "muted"), value)
        info_scroll = QScrollArea()
        info_scroll.setWidgetResizable(True)
        info_scroll.setWidget(info)
        tabs.addTab(info_scroll, action_icon('camera'), 'О камере')
        access_scroll = QScrollArea()
        access_scroll.setWidgetResizable(True)
        access_scroll.setWidget(access)
        tabs.addTab(access_scroll, action_icon('key'), 'Привязка и защита')
        self._refresh_saved_cameras()
        self.pairing_timer = QTimer(self)
        self.pairing_timer.setInterval(300)
        self.pairing_timer.timeout.connect(self._pairing_progress)
        self.pairing_timer.start()
        root.addWidget(tabs, 1)
        return page

    def _pairing_progress(self):
        from shared.pairing_store import PairingStore
        try:
            pending = PairingStore(self.config.data_root).pending()
        except (OSError, ValueError):
            return
        if pending:
            self.pairing_status.setText({'prepared': 'Подготовка ключей', 'launching': 'Настройка камеры',
                'activating': 'Настройка приёмника', 'verifying': 'Проверка видео и команд',
                'committing': 'Сохранение привязки'}.get(pending['stage'], 'Восстановление привязки'))
        elif not self.pairing_requested:
            fingerprint = (self.camera_profile or {}).get('fingerprint')
            bound = fingerprint and fingerprint in getattr(self, 'radio_camera_fingerprints', set())
            self.pairing_status.setText('Эта камера привязана к радио' if bound else
                                       'Камера ещё не привязана к радио' if fingerprint else 'Подключите камеру по LAN')

    def _refresh_saved_cameras(self):
        from shared.pairing_store import PairingStore
        store = PairingStore(self.config.data_root)
        choice = self.camera_choice.currentData()
        self.camera_choice.blockSignals(True)
        self.camera_choice.clear()
        self.camera_choice.addItem('Автовыбор', None)
        self.camera_labels = {}
        self.radio_camera_fingerprints = set()
        for profile in store.profiles():
            self.radio_camera_fingerprints.add(profile.get('ssh_fingerprint'))
            name = profile.get('camera_label', 'Камера · ' + profile['identity'][-6:])
            self.camera_labels[profile['identity']] = name
            self.camera_choice.addItem(name, profile['identity'])
        self.camera_choice.setCurrentIndex(max(0, self.camera_choice.findData(choice)))
        self.camera_choice.blockSignals(False)
        self.saved_camera.setText('Сохранены: ' + ', '.join(self.camera_labels.values()) if self.camera_labels else 'Нет сохранённых камер')

    def _camera_availability(self, identities):
        for identity, name in self.camera_labels.items():
            index = self.camera_choice.findData(identity)
            self.camera_choice.setItemText(index, name + (' · В эфире' if identity in identities else ' · Сохранена'))
        active = self.session.state.get('selected_camera')
        if self.session.running and active in identities:
            automatic = 'Автовыбор · ' + self.camera_labels.get(active, 'Камера')
        elif len(identities) == 1:
            automatic = 'Автовыбор · ' + self.camera_labels.get(identities[0], 'Камера найдена')
        elif len(identities) > 1:
            automatic = 'Автовыбор · несколько камер'
        else:
            automatic = 'Автовыбор · поиск камеры'
        self.camera_choice.setItemText(0, automatic)
        new = set(identities) - self.announced_cameras
        if new:
            self.announced_cameras.update(new)
            self.notify('Камера найдена' if len(identities) == 1 else 'Найдено несколько камер · выберите камеру')

    def _manage_saved_cameras(self):
        from shared.pairing_store import PairingStore
        store = PairingStore(self.config.data_root)
        dialog = QDialog(self)
        dialog.setWindowTitle('Сохранённые камеры')
        dialog.resize(480, 360)
        layout = QVBoxLayout(dialog)
        picker = ChoicePicker('Камера')
        layout.addWidget(picker)
        hint = label('Удалённую камеру можно восстановить здесь.', 'muted')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        action = button('Удалить из списка', lambda: change())
        layout.addWidget(action)
        revoke_action = button('Камера потеряна · отозвать доверие', lambda: change(revoke=True))
        layout.addWidget(revoke_action)
        layout.addStretch()
        layout.addWidget(button('Готово', dialog.accept))
        profiles = {}

        def refresh():
            picker.blockSignals(True)
            picker.clear()
            profiles.clear()
            for profile in store.profiles(include_archived=True):
                identity = profile['identity']
                profiles[identity] = profile
                name = profile.get('camera_label', 'Камера · ' + identity[-6:])
                from master.camera_protection import protection_status
                protection = protection_status(self.config.data_root, profile.get('ssh_fingerprint', ''), store.profiles(include_archived=True))
                picker.addItem(name + (' · Доверие отозвано' if profile.get('revoked') else ' · Удалена' if profile.get('archived') else ' · ' + protection['text']), identity)
            picker.blockSignals(False)
            selected()

        def selected(*_):
            profile = profiles.get(picker.currentData())
            action.setEnabled(bool(profile) and not profile.get('revoked'))
            revoke_action.setEnabled(bool(profile) and not profile.get('revoked'))
            action.setText('Восстановить' if profile and profile.get('archived') else 'Удалить из списка')
            hint.setText('Доверие отозвано на этой станции. Для возврата нужны LAN и новые ключи.' if profile and profile.get('revoked') else 'Удалённую камеру можно восстановить здесь.')

        def change(revoke=False):
            if self.session.running or self.camera.busy or self.radio_switch or self.pairing_requested:
                hint.setText('Перед изменением списка остановите приём и дождитесь завершения операций.')
                return
            profile = profiles.get(picker.currentData())
            if not profile:
                return
            archived = True if revoke else not profile.get('archived', False)
            if archived:
                name = profile.get('camera_label', 'Камера · ' + profile['identity'][-6:])
                answer = QMessageBox.question(dialog, 'Отозвать доверие' if revoke else 'Удалить камеру',
                    (f'Запретить подключение «{name}» на этой станции?\nКлючи на потерянной камере не стираются. Для возврата потребуется привязка с новыми ключами по LAN.' if revoke else f'Убрать «{name}» из сохранённых?\nОна перестанет участвовать в автопоиске.'),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
            try:
                store.set_archived(profile['identity'], archived, revoke=revoke)
                self._refresh_saved_cameras()
                active = store.read(store.active_path) or {}
                if archived and active.get('identity') != profile['identity']:
                    self.preferences.update(active.get('receiver_config', {}))
                    self.codec.setCurrentText(self.preferences.get('codec', 'H.265'))
                    self._save_preferences()
                self.announced_cameras.discard(profile['identity'])
                if archived and self.camera_profile and self.camera_profile.get('identity') == profile['identity']:
                    self.camera._invalidate('Камера удалена из списка')
                    self.camera.credentials = self.camera.bound_host = self.camera.settings = self.camera.radio_settings = None
                    self.camera_auth = self.camera_profile = None
                    self.camera_editor.load({})
                    self.radio_editor.load({})
                    self._show_camera_info()
                self.notify('Доверие к камере отозвано' if revoke else 'Камера удалена из списка' if archived else 'Камера восстановлена')
                from master.diagnostics import append_event
                append_event(self.config.data_root, {'operation': 'camera_revoke' if revoke else 'camera_archive', 'identity': profile['identity'], 'archived': archived, 'result': 'saved'})
                refresh()
            except (OSError, ValueError) as exc:
                self._refresh_saved_cameras()
                hint.setText(str(exc))

        picker.currentIndexChanged.connect(selected)
        refresh()
        self.touch.attach(dialog)
        dialog.exec()

    def _camera_choice_changed(self, *_):
        identity = self.camera_choice.currentData()
        if not self.session.running:
            return
        if identity is None:
            self.session.selection_pinned = False
            return
        self._select_saved_camera(identity)

    def _choose_camera_for_start(self):
        self.camera_choice.choose()
        if self.camera_choice.currentData() and not self.session.running:
            self._start()

    def _select_saved_camera(self, identity):
        if not identity:
            self.notify('Сначала свяжите камеру по LAN')
            return
        if self.camera.busy or self.radio_switch or self.pairing_requested:
            self.notify('Дождитесь завершения текущей операции')
            return
        if self.session.running:
            from shared.pairing_store import PairingStore
            profile = next((p for p in PairingStore(self.config.data_root).profiles() if p['identity'] == identity), None)
            if not profile or not self.session.select_camera(profile):
                self.notify('Завершите текущую операцию, запись или трансляцию')
            return
        from shared.pairing_store import PairingStore
        try:
            profile = PairingStore(self.config.data_root).select_known(identity)
            self.preferences.update(profile['receiver_config'])
            self.camera._invalidate('Выбрана другая камера')
            self.camera.credentials = self.camera.bound_host = self.camera.settings = self.camera.radio_settings = None
            self.camera.host = profile['host']
            self.codec.setCurrentText(profile['receiver_config']['codec'])
            self._save_preferences()
            self._refresh_saved_cameras()
            self.notify('Камера выбрана · нажмите «Запуск»')
        except (OSError, ValueError) as exc:
            self.notify(str(exc))

    def _radio_camera_selected(self, profile):
        if (getattr(self.camera, 'transport', None) == 'lan'
                and getattr(self.camera, '_lan_available', False)
                and self.camera.credentials and self.camera.bound_host == self.camera.host):
            return  # RF auto-selection must not replace the camera being configured by LAN.
        same_camera = bool(self.camera_profile and self.camera.credentials
                           and self.camera_profile.get('fingerprint') == profile.get('ssh_fingerprint')
                           and self.camera.bound_host == profile['host'])
        if not same_camera:
            self.camera._invalidate('Выбрана другая камера по радио')
            self.camera.credentials = self.camera.bound_host = self.camera.settings = self.camera.radio_settings = None
            self.camera_auth = self.camera_profile = None
            self.camera_editor.load({})
            self.radio_editor.load({})
            self._show_camera_info()
        self.camera.host = profile['host']
        self.camera_host.setText(profile['host'])
        self.camera_name.setText(profile.get('camera_label', 'Знакомая камера'))
        self.camera_status.set_status('ready', 'СОПРЯЖЕНА')
        self.preferences.update(profile['receiver_config'])
        self.codec.setCurrentText(profile['receiver_config'].get('codec', 'H.265'))
        self.camera.transport = 'radio'
        self.camera_transport_buttons['radio'].setChecked(True)
        self._save_preferences()
        self._refresh_saved_cameras()
        self.notify('Камера подключается')

    def _remember_camera_tuning(self, data, attempt=0, fingerprint=None):
        if not self.camera_profile:
            return
        current = self.camera_profile.get('fingerprint')
        if fingerprint is not None and current != fingerprint:
            return
        values = {}
        radio = data.get('radio_settings', {}).get('live', {})
        if 'channel' in radio and 'width' in radio:
            values.update(radio_channel=radio['channel'], radio_width=radio['width'])
        codec = data.get('settings', {}).get('config', {}).get('video0', {}).get('codec')
        if codec in ('h264', 'h265'):
            values['codec'] = 'H.264' if codec == 'h264' else 'H.265'
        if values:
            from shared.pairing_store import PairingStore
            try:
                PairingStore(self.config.data_root).remember_tuning(self.camera_profile.get('fingerprint'), **values)
            except BlockingIOError:
                if attempt < 4:
                    QTimer.singleShot(500, lambda: self._remember_camera_tuning(data, attempt + 1, current))
                else:
                    self.notify('Сохранение профиля занято · повторите чтение настроек')
            except (OSError, ValueError):
                self.notify('Не удалось сохранить профиль радиопоиска')

    def _pair_keys(self, renew=False):
        if self.pairing_requested or self.radio_switch or self.camera.busy:
            self.notify('Дождитесь завершения текущей операции')
            return
        if self.camera.transport != 'lan':
            self.camera_transport_buttons['lan'].setChecked(True)
        if not self.camera.credentials:
            self.pairing_after_login = True
            self._camera_login()
            return
        if self.session.state.get('recording') in ('starting', 'recording', 'finishing') or self.session.state.get('streaming') in ('starting', 'streaming'):
            self.notify('Перед привязкой остановите запись и трансляцию')
            return
        self.pairing_requested, self.pairing_resume = True, self.session.running
        self.session.stop()
        self.pairing_button.setEnabled(False)
        self.renew_pair_button.setEnabled(False)
        self.camera_editor.set_busy(True)
        self.radio_editor.set_busy(True)
        for item in self.camera_transport_buttons.values():
            item.setEnabled(False)
        deadline = time.monotonic() + 15
        def start_when_stopped():
            if any(p.state() != QProcess.ProcessState.NotRunning for p in (self.session.radio, self.session.media, self.session.scanner)):
                if time.monotonic() < deadline:
                    QTimer.singleShot(100, start_when_stopped)
                    return
                self._finish_pairing({'state': 'error', 'error': 'Приёмник ещё останавливается · повторите привязку'})
                return
            if not self.camera.pair_keys(renew):
                self._finish_pairing({'state': 'error', 'error': 'Не удалось начать привязку'})
        QTimer.singleShot(0, start_when_stopped)

    def _protect_camera(self):
        if self.camera.busy or self.pairing_requested or self.radio_switch:
            self.notify('Дождитесь завершения текущей операции')
            return
        if self.camera.transport != 'lan' or not self.camera.credentials or not self.camera_profile:
            self.notify('Выберите камеру по LAN и выполните вход')
            return
        identity = self.camera_profile.get('fingerprint')
        if not identity:
            return
        if self.camera.protect(identity):
            self.protect_button.setEnabled(False)
            self.security_status.setText('Проверяем защиту и сохраняем доступ…')

    def _protection(self):
        from master.camera_protection import protection_status
        from shared.pairing_store import PairingStore
        return protection_status(self.config.data_root, (self.camera_profile or {}).get('fingerprint', ''),
                                 PairingStore(self.config.data_root).profiles(include_archived=True))

    def _continue_lan_setup(self):
        if self.camera.transport != 'lan' or not self.camera.credentials or not self.camera_profile:
            return
        status = self._protection()
        self.security_status.setText(status['text'])
        identity = self.camera_profile.get('fingerprint')
        known = identity in getattr(self, 'radio_camera_fingerprints', set())
        explicit = self.pairing_after_login
        self.pairing_after_login = False
        if explicit or (self.auto_pair.isChecked() and not known):
            self._pair_keys(False)
        else:
            # Reading a known camera must not stop video or re-run enrollment.
            if hasattr(self, 'module_initializer'):
                self.module_initializer.next_try = 0
            self._refresh_radio()

    def _lan_camera_found(self, data):
        candidate = data.get('candidate_fingerprint')
        if not candidate or candidate == self.lan_candidate_fingerprint:
            return
        if data.get('host') == self.camera.host:
            self.lan_candidate_fingerprint = candidate
        self._lan_devices_changed([d for d in self.lan_device_data if d['host'] != data['host']] + [data])

    def _lan_scan_changed(self, scanning):
        if self.camera.user_busy or self.auto_login_pending or self.login_dialog_open:
            return
        if self.lan_device_data:
            self.lan_steps.setText('Выберите камеру · для новой камеры потребуется пароль')
        else:
            self.lan_steps.setText('Поиск камер в локальной сети…' if scanning else
                                   'Камеры OpenIPC не найдены · проверьте питание и подключение')

    def _lan_devices_changed(self, devices):
        selected = self.lan_devices.currentData()
        from master.camera_lan import camera_devices
        devices = camera_devices(devices, self.known_camera_fingerprints)
        for device in devices:
            if selected in device['addresses']:
                device['host'] = selected
        devices = sorted(devices, key=lambda d: (
            d.get('candidate_fingerprint') not in self.known_camera_fingerprints,
            not d.get('video_service_available'), d['host']))
        if devices == self.lan_device_data:
            return
        self.lan_device_data = devices
        self.lan_devices.clear()
        for device in devices:
            known = device.get('candidate_fingerprint') in self.known_camera_fingerprints
            title = 'Знакомая камера' if known else device.get('family', 'Устройство')
            self.lan_devices.addItem(f"{title} · {device['host']}", device['host'])
            identity = device.get('candidate_fingerprint') or device['host']
            if identity not in self.lan_announced and (known or device.get('video_service_available')):
                self.lan_announced.add(identity)
                self.notify('Устройство найдено по LAN · Камера → Подключение')
        index = self.lan_devices.findData(selected)
        previous = next((d for d in devices if d['host'] == selected), {})
        if index >= 0 and (previous.get('video_service_available') or
                           previous.get('candidate_fingerprint') in self.known_camera_fingerprints):
            self.lan_devices.setCurrentIndex(index)
        self.lan_devices.setEnabled(bool(devices))
        self.lan_setup.setEnabled(bool(devices))
        if not devices:
            self.lan_steps.setText('Поиск камер в общей сети · Ethernet и Wi-Fi')
        elif not self.camera.credentials:
            self.lan_steps.setText('Выберите камеру · для новой камеры потребуется пароль')

    def _onboard_lan_device(self):
        if self.camera.user_busy or self.pairing_requested or self.radio_switch:
            self.notify('Дождитесь завершения текущей операции')
            return
        device = next((d for d in self.lan_device_data if d['host'] == self.lan_devices.currentData()), None)
        if not device:
            return
        identity = device.get('candidate_fingerprint')
        if (self.camera.host != device['host'] or
                not identity or identity != (self.camera_profile or {}).get('fingerprint')):
            self.camera._invalidate('Выбрана камера по LAN')
            self.camera.credentials = self.camera.bound_host = self.camera.settings = self.camera.radio_settings = None
            self.camera_auth = self.camera_profile = None
            self.camera_editor.load({})
            self.radio_editor.load({})
            self._show_camera_info()
        self.camera.host = device['host']
        self.camera_host.setText(device['host'])
        self.camera.transport = 'lan'
        self.camera_transport_buttons['lan'].setChecked(True)
        self.lan_candidate_fingerprint = identity
        self.lan_setup_host = device['host']
        if self.camera.transport == 'lan' and self._is_rtsp_camera():
            self._open_rtsp_camera()
            return
        self.lan_steps.setText('Проверяем вход и возможности устройства…')
        self.auto_login_attempts.clear()
        if not self._attempt_saved_login(force=True):
            self._camera_login(manual=True)

    def _finish_pairing(self, data):
        self.pairing_requested = False
        self.pairing_button.setEnabled(True)
        self.renew_pair_button.setEnabled(True)
        self.camera_editor.set_busy(False)
        self.radio_editor.set_busy(False)
        for item in self.camera_transport_buttons.values():
            item.setEnabled(True)
        success = data.get('state') == 'paired'
        if success and hasattr(self, 'module_initializer'):
            self.module_initializer.next_try = 0
        if success:
            self.pairing_status.setText('Привязка готова')
            self.notify('Камера и приёмник привязаны')
            radio = data.get('radio_settings', {}).get('live', {})
            if radio:
                self.preferences.update(radio_channel=radio['channel'], radio_width=radio['width'])
            if data.get('codec'):
                self.codec.setCurrentText('H.265' if data['codec'] == 'h265' else 'H.264')
            self._save_preferences()
            self._refresh_saved_cameras()
            self.security_status.setText(self._protection()['text'])
        else:
            self.pairing_status.setText(data.get('error', 'Привязка не завершена'))
            self.notify(data.get('error', 'Привязка не завершена'))
        resume, self.pairing_resume = self.pairing_resume, False
        if resume and success:
            QTimer.singleShot(0, self._start)
        elif success:
            QTimer.singleShot(0, self.session.discover_cameras)

    def _sync_camera_settings(self):
        if (getattr(self, '_shutdown_complete', False) or self.camera.busy
                or self.radio_switch or not self.camera.credentials
                or time.monotonic() < getattr(self.camera, 'sync_retry_after', 0)
                or self.camera.bound_host != self.camera.host):
            return
        try:
            if self.camera_editor.changes() or self.radio_editor.changes():
                return
        except (ValueError, TypeError):
            return
        self._sync_radio_next = not getattr(self, '_sync_radio_next', False)
        if self._sync_radio_next:
            self.camera.read_radio(background=True)
        else:
            self.camera.refresh_settings(background=True)

    def _refresh_camera_settings(self):
        if self.camera.refresh_settings():
            self.camera_editor.set_busy(True)

    def _apply_camera_settings(self, changes):
        if any(key.startswith('video0.') for key in changes) and (
                self.session.state.get('recording') in ('starting', 'recording', 'finishing')
                or self.session.state.get('streaming') in ('starting', 'streaming')):
            self.notify('Перед изменением формата видео остановите запись и трансляцию')
            return
        # Keep RF and its authenticated return channel alive. The confirmed
        # result retunes only the decoder; stopping RX here would disable the
        # very transport needed to change the camera codec.
        if self.camera.apply_settings(changes):
            self.camera_editor.set_busy(True)
            self.notify("Применение настроек камеры")

    def _open_camera_panel(self):
        if self.camera.transport != 'lan':
            self.notify('Веб-панель доступна при подключении камеры по LAN')
            return
        from master.ui.camera_panel import open_camera_panel
        open_camera_panel(self.camera.host, self.config.data_root, self)

    def _network_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        streaming, box = panel()
        box.addWidget(label("Трансляция", "section"))
        self.stream_interface = ChoicePicker('Сеть трансляции')
        self._refresh_interfaces()
        self.stream_mode = ChoicePicker('Формат трансляции')
        self.stream_mode.addItem("Телефон или браузер", "web")
        self.stream_mode.addItem("Внешний плеер", "rtsp")
        self.stream_mode.setToolTip('Браузер: отдельный поток H.264 до 30 FPS. Внешний плеер: исходный поток RTSP/TCP без перекодирования.')
        box.addWidget(self.stream_mode)
        self.rtsp_button = button("Начать трансляцию", self._rtsp_toggle, "primary")
        self.rtsp_button.setIcon(action_icon("stream"))
        rtsp_row = QHBoxLayout()
        rtsp_row.addWidget(self.stream_interface, 1)
        rtsp_row.addWidget(self.rtsp_button)
        box.addLayout(rtsp_row)
        self.stream_url = QLineEdit()
        self.stream_url.setReadOnly(True)
        self.stream_url.setPlaceholderText("Ссылка появится после запуска")
        url_row = QHBoxLayout()
        url_row.addWidget(self.stream_url, 1)
        self.copy_stream_url = button("Копировать", lambda: QApplication.clipboard().setText(self.stream_url.text()))
        self.copy_stream_url.setEnabled(False)
        url_row.addWidget(self.copy_stream_url)
        self.open_stream = icon_button("expand", "Открыть трансляцию", self._open_stream)
        self.open_stream.setEnabled(False)
        url_row.addWidget(self.open_stream)
        box.addLayout(url_row)
        box.addWidget(label("Просмотр в одной локальной сети", "muted"))
        self.stream_clients = label("Трансляция выключена", "muted")
        box.addWidget(self.stream_clients)
        root.addWidget(streaming)
        wifi, wifi_box = panel()
        wifi_box.addWidget(label('Wi-Fi для зрителей', 'section'))
        self.wifi_hint = label('', 'muted')
        self.wifi_hint.setWordWrap(True)
        wifi_box.addWidget(self.wifi_hint)
        wifi_button = button('Подключить телефон' if sys.platform == 'linux' else 'Настроить Wi-Fi', self._configure_viewer_wifi)
        wifi_button.setIcon(action_icon('stream'))
        wifi_button.setToolTip('Название сети и пароль для зрителей' if sys.platform == 'linux' else 'Открыть настройки раздачи Wi-Fi')
        wifi_box.addWidget(wifi_button)
        root.addWidget(wifi)
        root.addStretch()
        self.network_timer = QTimer(self)
        self.network_timer.timeout.connect(self._refresh_interfaces)
        self.network_timer.start(3000)
        self._refresh_interfaces()
        return page

    def _configure_viewer_wifi(self):
        import sys
        if sys.platform == 'darwin':
            QDesktopServices.openUrl(QUrl('x-apple.systempreferences:com.apple.Sharing-Settings.extension'))
        elif sys.platform == 'linux':
            try:
                settings = json.loads((self.config.data_root/'config/viewer-wifi.json').read_text())
                ssid, password = settings['ssid'], settings['password']
            except (OSError, ValueError, KeyError):
                self.notify('Сеть для зрителей ещё не настроена')
                return
            dialog = QDialog(self)
            dialog.setWindowTitle('Wi-Fi для зрителей')
            dialog.setMinimumWidth(360)
            layout = QVBoxLayout(dialog)
            layout.addWidget(label(ssid, 'section'))
            secret = QLineEdit(password)
            secret.setReadOnly(True)
            secret.setEchoMode(QLineEdit.EchoMode.Password)
            secret.setAccessibleName('Пароль Wi-Fi')
            layout.addWidget(secret)
            reveal = QCheckBox('Показать пароль')
            reveal.toggled.connect(lambda checked: secret.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
            layout.addWidget(reveal)
            hint = label('Выберите «Wi-Fi · FIT-LAB WFB» и включите трансляцию. Затем подключите телефон к этой сети и откройте ссылку из приложения.', 'muted')
            hint.setWordWrap(True)
            layout.addWidget(hint)
            layout.addWidget(button('Готово', dialog.accept))
            dialog.exec()
            secret.clear()
        else:
            self.notify('Точка доступа настраивается сетевым модулем станции')

    def _modules_page(self):
        self.modules_page = ModulesPage()
        return self.modules_page

    def _open_stream(self):
        url = self.stream_url.text()
        if url.startswith("http://"):
            QDesktopServices.openUrl(QUrl(url))

    def _system_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        self.system_tabs = QTabWidget()
        root.addWidget(self.system_tabs)

        def section(title, symbol):
            content = QWidget()
            column = QVBoxLayout(content)
            column.setContentsMargins(20, 20, 20, 20)
            card, box = panel()
            column.addWidget(card)
            column.addStretch()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(content)
            self.system_tabs.addTab(scroll, action_icon(symbol), title)
            return box

        box = section('Просмотр', 'video')
        box.addWidget(label('Просмотр на приёмнике' if self.embedded_receiver else 'Просмотр на станции', 'section'))
        self.playback_hint = label('Настройки декодера и восстановления изображения', 'muted')
        self.playback_hint.setWordWrap(True)
        box.addWidget(self.playback_hint)
        form = QFormLayout()
        self.codec = ChoicePicker('Кодек приёмника')
        self.codec.addItems(["H.265", "H.264"])
        self.codec.setCurrentText(self.preferences.get("codec", "H.265"))
        self.codec.currentTextChanged.connect(self._save_preferences)
        self.latency = QSpinBox()
        self.latency.setRange(0, 200)
        self.latency.setSuffix(" мс")
        self.latency.setValue(int(self.preferences.get("latency", 40)))
        self.latency.valueChanged.connect(self._save_preferences)
        self.latency.setToolTip("Буфер приёмника. Это не полная задержка от камеры до экрана.")
        self.recovery_mode = ChoicePicker('После потерь')
        self.recovery_mode.addItem("Минимальная задержка", "realtime")
        self.recovery_mode.addItem("Чистый кадр после потерь", "keyframe")
        self.recovery_mode.setCurrentIndex(max(0, self.recovery_mode.findData(self.preferences.get("recovery_mode", "keyframe"))))
        self.recovery_mode.setToolTip("Чистый кадр пропускает повреждённый участок до ключевого кадра без накопления очереди. Непрерывное декодирование может показывать серые артефакты после потерь.")
        self.recovery_mode.currentIndexChanged.connect(self._save_preferences)
        form.addRow("Кодек приёмника", self.codec)
        form.addRow("Буфер", self.latency)
        form.addRow("После потерь", self.recovery_mode)
        self.decoder_mode = ChoicePicker('Декодирование')
        self.decoder_mode.addItem('Программное' if sys.platform == 'linux' else 'Быстрый отклик', 'lowlatency')
        self.decoder_mode.addItem('Аппаратное' if sys.platform == 'linux' else 'VideoToolbox', 'hardware')
        default_decoder = 'hardware' if self.embedded_receiver else 'lowlatency'
        self.decoder_mode.setCurrentIndex(max(0, self.decoder_mode.findData(self.preferences.get('decoder_mode', default_decoder))))
        self.decoder_mode.setToolTip('Аппаратное декодирование разгружает процессор. Программное — резервный режим.' if sys.platform == 'linux' else 'Быстрый отклик снижает очередь H.265. VideoToolbox снижает нагрузку, но добавляет задержку.')
        self.decoder_mode.currentIndexChanged.connect(self._save_preferences)
        form.addRow('Декодирование', self.decoder_mode)
        box.addLayout(form)
        box = section('Запись', 'record')
        box.addWidget(label('Сохранение видео', 'section'))
        storage_button = button("Папка записи", self._choose_record_directory)
        storage_button.setIcon(action_icon("folder"))
        box.addWidget(storage_button)
        self.record_location = label(self.record_directory.name, "muted")
        self.record_location.setToolTip(str(self.record_directory))
        box.addWidget(self.record_location)
        box.addWidget(label('Запись включается кнопкой под видео', 'muted'))
        box = section('Звуковое сопровождение', 'bell')
        self.sound_enabled = QCheckBox('Звуки событий')
        self.sound_enabled.setChecked(self.preferences.get('event_sounds', True))
        self.sound_enabled.setToolTip('Короткий тихий сигнал запуска, первого видео и начала записи. Потеря сигнала озвучивается один раз после паузы.')
        self.sound_enabled.toggled.connect(self._save_preferences)
        box.addWidget(self.sound_enabled)
        self.voice_enabled = QCheckBox('Голосовые подсказки')
        self.voice_enabled.setChecked(self.preferences.get('event_voice', False))
        self.voice_enabled.setToolTip('Голосовые уведомления о связи, записи и ошибках. Работают без интернета.')
        self.voice_enabled.toggled.connect(self._save_preferences)
        box.addWidget(self.voice_enabled)
        self.event_volume = ChoicePicker('Громкость уведомлений')
        for caption, level in (('Тихо', 8), ('Умеренно', 16), ('Громче', 28), ('Громко', 50)):
            self.event_volume.addItem(caption, level)
        self.event_volume.setCurrentIndex(max(0, self.event_volume.findData(self.preferences.get('event_volume', 16 if self.embedded_receiver else 8))))
        self.event_volume.currentIndexChanged.connect(self._save_preferences)
        box.addWidget(self.event_volume)
        self.voice_volume = ChoicePicker('Громкость голоса')
        for caption, level in (('Голос · 50%', 50), ('Голос · 70%', 70), ('Голос · 100%', 100)):
            self.voice_volume.addItem(caption, level)
        self.voice_volume.setCurrentIndex(max(0, self.voice_volume.findData(self.preferences.get('voice_volume', 100))))
        self.voice_volume.currentIndexChanged.connect(self._save_preferences)
        box.addWidget(self.voice_volume)
        self.sound_event_checks = {}
        for key, caption in (('hello', 'Приветствие'), ('connected', 'Камера подключена'), ('lost', 'Сигнал потерян'), ('record', 'Запись начата'), ('saved', 'Запись сохранена'), ('warning', 'Ошибка записи'), ('restored', 'Сигнал восстановлен'), ('receiver_lost', 'Приёмник отключён'), ('record_stopped', 'Запись остановлена'), ('storage_full', 'Недостаточно места'), ('settings_error', 'Ошибка настроек'), ('storage_lost', 'Накопитель отключён'), ('master_lost', 'Мастер отключён'), ('master_restored', 'Связь с приложением мастера восстановлена'), ('bye', 'Прощание')):
            row = QHBoxLayout()
            check = QCheckBox(caption)
            check.setChecked(self.preferences.get('sound_events', {}).get(key, True))
            self.sound_event_checks[key] = check
            check.toggled.connect(self._save_preferences)
            row.addWidget(check, 1)
            preview = icon_button('audio', 'Прослушать: ' + caption, lambda checked=False, key=key: self._preview_sound(key))
            preview.setAccessibleName('Прослушать: ' + caption)
            preview.setFixedWidth(56)
            row.addWidget(preview)
            box.addLayout(row)
        hint = label('Звук камеры настраивается отдельно — коснитесь видео.', 'muted')
        hint.setWordWrap(True)
        box.addWidget(hint)
        box = section('FIT-LAB Assistant', 'settings')
        self.assistant_summary = label('Проверка устройств…', 'muted')
        self.assistant_summary.setWordWrap(True)
        box.addWidget(self.assistant_summary)
        box.addWidget(label('Состояние системы', 'section'))
        self.checks = label('Проверка…')
        self.checks.setWordWrap(True)
        box.addWidget(self.checks)
        box.addWidget(button('Проверить', self._health))
        journal_button = button("Журнал событий", lambda: self.show_page("journal"))
        journal_button.setIcon(action_icon("folder"))
        box.addWidget(journal_button)
        export_button = button('Сохранить отчёт', self._export_diagnostics)
        export_button.setIcon(action_icon('folder'))
        box.addWidget(export_button)
        box = section('Экран', 'expand')
        box.addWidget(label('Экран и сенсор', 'section'))
        self.display_info = label('Определение экрана…')
        self.touch_device_label = label('Поиск сенсора…', 'muted')
        self.touch_device_label.setWordWrap(True)
        box.addWidget(self.display_info)
        box.addWidget(self.touch_device_label)
        self.layout_density = ChoicePicker('Размер элементов')
        for caption, value in (('Автоматически', 'auto'), ('Компактно', 'compact'), ('Крупнее', 'comfortable')):
            self.layout_density.addItem(caption, value)
        self.layout_density.setCurrentIndex(max(0, self.layout_density.findData(self.preferences.get('layout_density', 'auto'))))
        self.layout_density.setToolTip('Подстраивается под размер окна. Крупный режим ограничивается доступным местом.')
        self.layout_density.currentIndexChanged.connect(self._display_density_changed)
        box.addWidget(self.layout_density)
        gestures = label('Настройки: прокрутка пальцем. Нижняя панель: свайп между разделами. Видео: касание показывает громкость, двойное касание открывает полный экран.', 'muted')
        gestures.setWordWrap(True)
        box.addWidget(gestures)
        return page

    def _radio_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        radio, box = panel()
        box.addWidget(label("Радиолиния", "section"))
        self.frequency_label = label("— MHz", "heroValue")
        self.channel_label = label("", "muted")
        self.chart = TrafficChart()
        self.packet_label = label("RTP —", "muted")
        for item in (self.frequency_label, self.channel_label, self.chart, self.packet_label):
            box.addWidget(item)
        box.addWidget(label("Источник приёма", "muted"))
        box.addWidget(self.source)
        self.control_enabled = QCheckBox('Обратный канал')
        self.control_enabled.setChecked(bool(self.preferences.get('control_enabled', False)))
        self.control_enabled.setToolTip('Один доступный приёмник отправляет команды. При его отключении TX переходит на второй.')
        if self.embedded_receiver and not (self.config.data_root.parent/'tools/wfb-radio-ssh').is_file():
            self.control_enabled.setChecked(False)
            self.control_enabled.setEnabled(False)
            self.control_enabled.setToolTip('Управление камерой с этого устройства ещё не подключено. Сейчас команды отправляет мастер по LAN.')
        self.control_enabled.toggled.connect(self._save_preferences)
        box.addWidget(self.control_enabled)
        details = QScrollArea()
        details.setWidgetResizable(True)
        details.setMinimumHeight(32)
        details.setWidget(radio)
        root.addWidget(details, 1)
        return page

    def _refresh_radio(self):
        if self.radio_switch:
            if self.radio_switch.get('phase') == 'recovery':
                self.radio_switch.update(deadline=time.monotonic() + 25, fallbacks=0, next_probe=0)
                self.radio_editor.set_busy(True)
                self.radio_switch_timer.start()
                self.notify('Повторная проверка радиоканалов')
            return
        if self.camera.busy:
            return
        if self.camera.read_radio():
            self.radio_editor.set_busy(True)

    def _control_transport_changed(self, transport):
        if self.radio_switch:
            return
        self.camera.transport = transport
        self.camera_settings_button.setEnabled(False)
        self._save_preferences()
        if not self.camera_profile or self.last_camera_state == 'offline':
            self.camera_name.setText('Ожидание камеры по радио' if transport == 'radio' else 'Подключите камеру по LAN')
        self.camera.scan()

    def _restart_radio(self, channel=None, power=None):
        if self.radio_switch:
            self.notify('Дождитесь подтверждения переключения')
            return
        if self.camera.transport == 'radio' and (not self.session.running or not self.camera.radio_connected):
            self.notify('Для управления по радио включите приём и TX')
            return
        if self.session.state.get("recording") in ("starting", "recording", "finishing") or self.session.state.get("streaming") in ("starting", "streaming"):
            self.notify("Перед изменением радиолинии остановите запись и трансляцию")
            return
        self.resume_after_radio = self.session.running and self.session.mode in ("local", "lan")
        if self.camera.read_radio(restart=True, channel=channel, power=power):
            self.radio_editor.set_busy(True)
            self.notify("Применение мощности" if power is not None and channel is None else
                        "Применение радионастроек · видео временно прервётся")

    def _retune_switch(self, tuning):
        self.radio_switch['listening'] = dict(tuning)
        current = self.session.state.get('radio_tuning', {})
        if any(current.get(key) != tuning[key] for key in ('channel', 'width')):
            self.session.stop()
            QTimer.singleShot(250, self._resume_radio)

    def _tick_radio_switch(self):
        switch = self.radio_switch
        if not switch or self.camera.closed or not self.session.running or not self.camera.credentials:
            return
        now = time.monotonic()
        if now >= switch['deadline']:
            attempts = switch.get('fallbacks', 0)
            if attempts >= 2:
                self._wait_radio_recovery('Связь не восстановлена')
                return
            switch['fallbacks'] = attempts + 1
            switch['deadline'] = now + 25
            self._retune_switch(switch['old'] if attempts == 0 else switch['target'])
            self.notify('Проверка резервного канала')
        if (not self.camera.radio_connected or self.camera.job is not None
                or not self.camera.credentials or now < switch.get('next_probe', 0)):
            return
        switch['next_probe'] = now + 3
        if switch.get('phase') == 'prepared':
            self.camera.switch_action(switch['ticket'], 'arm')
            return
        current = self.session.state.get('radio_tuning', {})
        on_target = current.get('channel') == switch['target']['channel']
        action = 'commit' if on_target and self.session.state.get('phase') == 'video' else 'query'
        self.camera.switch_action(switch['ticket'], action, switch['target'])

    def _wait_radio_recovery(self, message):
        # Keep read-only reconciliation alive on the current channel. Let the
        # user retry the bounded channel scan or authenticate after a restart.
        self.radio_switch.update(phase='recovery', deadline=float('inf'), next_probe=time.monotonic() + 3)
        self.radio_editor.status.setText(message + ' · нажмите «Обновить» для проверки каналов')
        self.radio_editor.refresh.setEnabled(True)
        self.notify(message + ' · оба канала сохранены')

    def _finish_radio_switch(self, data, rolled_back=False, error=None):
        from shared.radio_settings import receiver_settings
        live = data['radio_settings'].get('live', {})
        try:
            receiver_settings(live.get('channel'), live.get('width'))
        except (ValueError, TypeError):
            self._wait_radio_recovery(error or 'Камера не подтвердила рабочий канал')
            return
        self.radio_switch_timer.stop()
        if self.radio_switch:
            self._retune_switch(live)
        self.preferences.update(radio_channel=live['channel'], radio_width=live['width'])
        self._save_preferences()
        self.radio_switch_path.unlink(missing_ok=True)
        self.radio_switch = None
        self._remember_camera_tuning(data)
        self.camera.coordinated_ticket = None
        self.resume_after_radio = False
        self.radio_editor.load(data['radio_settings'])
        self.camera_editor.set_busy(False)
        for item in self.camera_transport_buttons.values():
            item.setEnabled(True)
        self.notify(error if error else 'Камера и приёмники вернулись на прежний канал' if rolled_back else
                    'Частота и мощность подтверждены по радио')

    def _resume_radio(self, attempt=0):
        if self.session.radio.state() != QProcess.ProcessState.NotRunning or self.session.media.state() != QProcess.ProcessState.NotRunning:
            if attempt < 40:
                QTimer.singleShot(250, lambda: self._resume_radio(attempt+1))
            else:
                self.notify("Приёмник завершает работу · запустите приём кнопкой")
            return
        self._start()

    def _journal_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        self.journal = QPlainTextEdit()
        self.journal.setReadOnly(True)
        self.journal.setMaximumBlockCount(300)
        root.addWidget(self.journal)
        root.addWidget(button("Открыть журналы", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config.data_root / "logs")))))
        return page

    def _refresh_interfaces(self):
        from master.viewer_network import local_viewer_networks, local_hotspot_issue
        networks = local_viewer_networks()
        if hasattr(self, 'viewer_service'):
            self.viewer_service.update([item.address for item in networks])
        hotspot = next((item for item in networks if item.kind == 'hotspot'), None)
        if hasattr(self, 'wifi_hint'):
            issue = local_hotspot_issue(networks)
            self.wifi_hint.setText(issue or ('Раздача включена · подключитесь к Wi-Fi станции и откройте ссылку.' if hotspot else
                                   'Wi-Fi для зрителей включается только на время трансляции.' if __import__('sys').platform == 'linux' else 'Раздача выключена. Настройте Wi-Fi для зрителей.'))
        if self.session.state.get("streaming") in ("starting", "streaming", "stopping"):
            host = self.session.state.get('stream_host')
            if host and host not in {item.address for item in networks} and self.session.stream_wanted:
                self.session.stop_streaming()
                self.notify('Сеть трансляции отключена · выберите доступную сеть')
            return
        selected = self.stream_interface.currentData()
        previous_hotspot = getattr(self, '_viewer_hotspot', None)
        self._viewer_hotspot = hotspot.address if hotspot else None
        choices = [(item.label, item.address) for item in networks]
        import sys
        if sys.platform == 'linux':
            choices.insert(0, ('Wi-Fi · FIT-LAB WFB', 'fitlab-hotspot'))
        if choices == self.stream_interface.items:
            return
        self.stream_interface.clear()
        for text, address in choices:
            self.stream_interface.addItem(text, address)
        if hotspot and hotspot.address != previous_hotspot:
            selected = hotspot.address
        index = self.stream_interface.findData(selected)
        if index >= 0:
            self.stream_interface.setCurrentIndex(index)

    def show_page(self, key):
        if key == "network":
            self._refresh_interfaces()
        target = "camera" if key == "osd" else key
        self.pages.setCurrentIndex(self.page_keys[target])
        self.pages.currentWidget().raise_()
        self.pages.currentWidget().update()
        if key in ("camera", "osd"):
            self.camera_tabs.setCurrentIndex(0 if self.camera_editor.controls or key == 'osd' else 1)
            if key == "osd" and self.camera_editor.controls:
                for i in range(self.camera_editor.group.count()):
                    if "OSD" in self.camera_editor.group.itemText(i):
                        self.camera_tabs.setCurrentIndex(0)
                        self.camera_editor.group.setCurrentIndex(i)
                        break
        self.page_title.setText({"live": "", "camera": "Камера", "network": "Трансляция", "journal": "Журнал"}.get(key, self.nav[key].text() if key in self.nav else ""))
        self.page_title.setVisible(bool(self.page_title.text()))
        for page, nav in self.nav.items():
            nav.setProperty("selected", page == key or (key == "journal" and page == "system"))
            repolish(nav)
        self._fit_live_layout()

    def notify(self, text):
        text = str(text)[:500]
        now = time.monotonic()
        if not self.notification_queue.push(text, now):
            return
        self._append_journal(text)
        self.notification_timer.start()
        self._deliver_notification()

    def _deliver_notification(self):
        text = self.notification_queue.take(time.monotonic())
        if not self.notification_queue.pending:
            self.notification_timer.stop()
        if text is None:
            return
        self.toast.setText('Запись сохранена' if text.startswith('Запись сохранена: ') else text)
        self.toast.setToolTip(text)
        self.toast.setVisible(not self.native_focus)
        self.toast_animation.stop()
        self.toast_animation.setStartValue(0.0)
        self.toast_animation.setEndValue(1.0)
        self.toast_animation.start()
        self.toast_timer.start(3600)
        self.sounds.notify_event(text)

    def _append_journal(self, text):
        entry = time.strftime("%H:%M:%S") + "  " + text
        if hasattr(self, "journal"):
            self.journal.appendPlainText(entry)
        with (self.config.data_root / "logs" / "station-events.log").open("a") as stream:
            stream.write(entry + "\n")

    def _fade_notification(self):
        self.toast_animation.stop()
        self.toast_animation.setStartValue(1.0)
        self.toast_animation.setEndValue(0.0)
        self.toast_animation.start()

    def _usb_changed(self, devices):
        self.usb_devices = devices
        if not self.session.running:
            self._session_changed(self.session.state)

    def _start(self):
        if self.pairing_requested:
            self.notify('Идёт проверка новой привязки')
            return
        mode = "local" if self.source.currentIndex() == 0 else "lan"
        if self.radio_switch is None and self.radio_switch_path.exists():
            try:
                from master.radio_switch import valid_ticket
                saved = json.loads(self.radio_switch_path.read_text())
                valid_ticket(saved['ticket'])
                if saved.get('host') == self.camera.host:
                    self.radio_switch = {**saved, 'phase': 'recovery', 'listening': saved['old'],
                                         'deadline': time.monotonic() + 55, 'next_probe': 0}
                    self.camera.coordinated_ticket = saved['ticket']
                    self.radio_switch_timer.start()
            except (OSError, ValueError, KeyError):
                self.notify('Не удалось прочитать сохранённое переключение радиоканала')
        tuning = self.radio_switch.get('listening', {}) if self.radio_switch else {}
        identity = self.camera_choice.currentData() if mode == 'local' and not self.radio_switch else None
        self.session.start(mode, 0, self.latency.value(),
                           codec=self.codec.currentText().lower().replace(".", ""),
                           channel=int(tuning.get('channel', self.preferences.get("radio_channel", 161))),
                           width=int(tuning.get('width', self.preferences.get("radio_width", 20))),
                           recovery=self.recovery_mode.currentData(), control=self.control_enabled.isChecked(),
                           decoder_mode=self.decoder_mode.currentData(), profile_identity=identity,
                           auto_select=mode == 'local' and not self.radio_switch and identity is None,
                           pin_selection=identity is not None, retune=bool(tuning))

    def _session_changed(self, state):
        signal_was_lost = self.sounds.signal_alert.announced
        self.sounds.observe_signal(state, self.session.running, bool(self.radio_switch or self.pairing_requested))
        signal_is_lost = self.sounds.signal_alert.announced
        if signal_is_lost and not signal_was_lost:
            self.notify('Видеосигнал потерян')
        elif signal_was_lost and not signal_is_lost and self.session.running and state.get('phase') == 'video':
            self.notify('Видеосигнал восстановлен')
        if not self.session.running:
            self.video_announced = False
        self.session.search_blocked = bool(self.radio_switch or self.pairing_requested or self.camera.busy)
        phase = state.get("phase", "idle")
        phases = {"idle": ("ГОТОВ", "ready", "Готов к приёму"),
                  "starting": ("ЗАПУСК", "warning", "Запуск приёмника"),
                  "searching": ("ПОИСК", "warning", "Поиск камеры"),
                  "waiting": ("ОЖИДАНИЕ", "offline", "Ожидание сигнала"),
                  "decoding": ("ПОТОК", "warning", "Ожидание ключевого кадра"),
                  "recovering": ("ВОССТАНОВЛЕНИЕ", "warning", "Ожидание целого кадра"),
                  "video": ("ВИДЕО", "ready", ""),
                  "stopped": ("ОСТАНОВЛЕН", "offline", "Приём остановлен"),
                  "error": ("ОШИБКА", "error", "Не удалось запустить приём")}
        text, kind, title = phases.get(phase, phases["idle"])
        self.status.set_status(kind, text)
        self.video.title = title
        self.video.subtitle = "RTP · LAN" if self.session.mode == "lan" else "WFB · USB"
        self.video.stale = phase not in ("video", "recovering")
        if self.video.native_surface is not None:
            self.video.set_native_active(state.get('frame_transport') == 'native_overlay' and self.session.running)
        self.video.update()
        if self.fullscreen_video is not None:
            canvas = self.fullscreen_video.video
            canvas.stale, canvas.title, canvas.subtitle = self.video.stale, self.video.title, self.video.subtitle
            if canvas.native_surface is not None:
                canvas.set_native_active(state.get('frame_transport') == 'native_overlay' and self.session.running)
            canvas.update()
        if phase != self.previous_phase:
            if phase == "video" and not getattr(self, 'video_announced', False):
                self.notify("Тестовое изображение" if state.get("synthetic") else "Видео получено")
                self.video_announced = True
            self.previous_phase = phase
        receiving = self.session.running or self.session.handover is not None or self.session.pending_start is not None
        self.start_button.setEnabled(not receiving)
        self.start_button.setVisible(not receiving)
        self.stop_button.setEnabled(receiving)
        self.stop_button.setVisible(receiving)
        self._camera_availability(state.get('available_cameras', []))
        self.source.setEnabled(not self.session.running)
        self.control_enabled.setEnabled(not self.session.running)
        control = state.get('control', {}) if self.session.running else {}
        tx_active = control.get('state') == 'connected' and time.monotonic()-control.get('last_reply_monotonic', 0) < 3
        self.camera.radio_connected = tx_active
        tx_text = (f"{control.get('rtt_ms', 0):.0f} мс" if tx_active else
                   'Нет ответа' if control.get('state') in ('connected', 'waiting') else
                   'Другая станция' if control.get('state') == 'busy' else
                   'Повтор…' if control.get('state') == 'retrying' else
                   'Ошибка' if control.get('state') == 'error' else
                   'Запуск…' if control.get('state') == 'starting' else 'Выключен')
        self.tx_label.setText(tx_text)
        self.tx_dot.set_signal('receiving' if tx_active else 'offline')
        self.camera_tx_status.setText(f"Радио · {tx_text}" if control else 'Обратный канал выключен')
        tx_owner = control.get('tx_receiver')
        self.tx_label.setToolTip((f"Через RX{tx_owner} · " if tx_owner else '') +
                                f"Подтверждено ответов камеры: {control.get('replies', 0)} · отправлено: {control.get('sent', 0)}"
                                "\nTX выбирается отдельно; видео принимают оба RX.")
        self.codec.setEnabled(not self.session.running)
        self.decoder_mode.setEnabled(not self.session.running)
        self.latency.setEnabled(not self.session.running)
        self.recovery_mode.setEnabled(not self.session.running)
        self.playback_hint.setText('Для изменения декодера остановите приём' if self.session.running else
                                   'Настройки декодера и восстановления изображения')
        radio = state.get("radio", {})
        interval, totals = radio.get("interval", {}), radio.get("totals", {})
        fresh = bool(radio.get("antenna_fresh")) and phase in ("video", "decoding", "waiting") and self.session.running
        self.metrics["mbps"].set_value(f"{state.get('mbps', 0):.2f}" if self.session.running else "—")
        self.metrics["megabytes"].set_value(f"{state.get('mbps', 0) / 8:.2f}" if self.session.running else "—")
        canvas = self.fullscreen_video.video if self.fullscreen_video is not None else self.video
        if state.get('frame_transport') == 'native_overlay':
            self.metrics['fps'].set_value(str(state.get('presented_fps', '—')) if phase == 'video' else '—')
            self.metrics['fps'].setToolTip('Кадры, выведенные аппаратным видеоплеером')
        elif canvas.isVisible():
            display = canvas.performance()
            self.session.state.update(display)
            self.metrics['fps'].set_value(str(display['presented_fps']) if phase == 'video' else '—')
            self.metrics['fps'].setToolTip(f"Отрисовано в окне · декодер {state.get('decoded_fps', '—')} FPS")
        else:
            self.session.state.pop('presented_fps', None)
            self.session.state.pop('paint_max_ms', None)
        self.metrics["fec"].set_value(str(totals.get("fec_recovered", "—")))
        loss_percent = state.get('health', {}).get('loss_percent')
        loss_text = f'{loss_percent:.2f}%' if loss_percent is not None else '—'
        self.metrics["loss"].set_value(loss_text)
        self.metrics['loss'].setToolTip(f"Последние измерения · за сеанс потеряно {totals.get('lost_packets', 0)} пакетов")
        integrity = state.get("rtp_integrity", {})
        self.packet_label.setText((f"RTP  {state.get('rtp_packets', 0):,}\n"
                                  f"Пропуски RTP  {integrity.get('sequence_gaps', 0)} · Дубликаты  {integrity.get('duplicates', 0)}\n"
                                  f"Перестановки  {integrity.get('reordered', 0)} · Неверные пакеты  {integrity.get('invalid', 0)}").replace(",", " "))
        self.packet_label.setToolTip("Пропуски номеров RTP учитываются отдельно от потерь WFB/FEC")
        active_codec = getattr(self.session, 'selected_codec', None)
        codec = {'h264': 'H.264', 'h265': 'H.265'}.get(active_codec, self.codec.currentText())
        self.metrics["codec"].set_value(codec)
        self.metrics["size"].set_value(f"{state['width']}×{state['height']}" if state.get("width") and phase == "video" else "—")
        if state.get("width") and phase == "video":
            self.stream_label.setText(f"{codec}  ·  {state['width']} × {state['height']}")
        else:
            self.stream_label.setText(f"{codec} · ожидание")
        self.frame_label.setText("ТЕСТ" if state.get("synthetic") or state.get("test_phase") else "LIVE" if phase == "video" else "")
        receivers = state.get("receivers", [])
        for index, tile in enumerate(self.rx_tiles):
            receiver = next((r for r in receivers if r.get("index") == index), None)
            if index >= 2:
                tile.setVisible(receiver is not None or index < len(self.usb_devices))
            active = bool(receiver and self.session.running and time.monotonic() - receiver.get("last_frame_monotonic", 0) < 2)
            signal_mode = "receiving" if active else receiver.get("connection", "offline") if receiver and self.session.running else "ready" if index < len(self.usb_devices) else "offline"
            tile.set_signal(signal_mode, receiver.get("rssi_dbm") if active else None,
                            receiver.get("snr_db") if active else None)
        snrs = [r.get("snr_db") for r in receivers if self.session.running and time.monotonic()-r.get("last_frame_monotonic",0)<2 and isinstance(r.get("snr_db"),(int,float))]
        snr_text = f"{max(snrs):g}" if snrs else "—"
        self.snr_metric.set_value(snr_text)
        self.snr_metric.setToolTip("SNR из статистики драйвера; нулевое значение может означать отсутствие измерения шума")
        self.compact_quality.set_values(snr_text, str(totals.get('fec_recovered', '—')), loss_text)
        self.compact_quality.fields['loss'].setToolTip(self.metrics['loss'].toolTip())
        local = bool(receivers) and self.session.mode in ("local", "lan")
        tuning = state.get("radio_tuning", {})
        self.frequency_label.setText(f"{tuning['frequency_mhz']} MHz" if local and tuning.get("frequency_mhz") else "— MHz")
        self.live_frequency.setText(self.frequency_label.text())
        self.channel_label.setText(f"Канал {tuning['channel']}  /  {tuning['width']} MHz" if local and tuning.get("channel") else "")
        if time.monotonic() - self.last_chart >= 1:
            self.chart.append(state.get("mbps", 0))
            self.last_chart = time.monotonic()
        recording = state.get("recording")
        self.record_button.setText("Стоп записи" if recording in ("starting", "recording") else "Сохранение…" if recording == "finishing" else "Запись")
        self.record_button.setAccessibleName(self.record_button.text())
        self.record_button.setToolTip(self.record_button.text())
        self.record_button.setEnabled(recording in ("starting", "recording") or
                                      (phase == "video" and recording != "finishing"))
        for item, active in ((self.record_button, recording == "recording"),
                             (self.stream_action, state.get("streaming") == "streaming"),
                             (self.nav["live"], phase == "video"),
                             (self.nav["radio"], any(r.get("last_frame_monotonic", 0) > time.monotonic() - 2 for r in receivers) and self.session.running)):
            if item.property("active") != active:
                item.setProperty("active", active)
                repolish(item)
        stream_state = state.get("streaming", "stopped")
        self.rtsp_button.setText("Остановить трансляцию" if stream_state in ("starting", "streaming") else "Завершение…" if stream_state == "stopping" else "Начать трансляцию")
        self.rtsp_button.setEnabled(stream_state in ("starting", "streaming") or (phase == "video" and stream_state != "stopping" and self.stream_interface.count() > 0))
        self.copy_stream_url.setEnabled(stream_state == "streaming")
        self.open_stream.setEnabled(stream_state == "streaming" and state.get("stream_mode") == "web")
        self.stream_mode.setEnabled(stream_state not in ("starting", "streaming", "stopping"))
        self.stream_clients.setText((f"Подключений: {state.get('stream_clients', 0)}" if state.get('stream_signal', True) else 'Ожидание видеосигнала') if stream_state == "streaming" else "Запуск…" if stream_state == "starting" else "Трансляция выключена")
        self.stream_interface.setEnabled(state.get("streaming") not in ("starting", "streaming"))
        if state.get("streaming") == "streaming":
            self.stream_url.setText(state.get("stream_url") or "")
        elif state.get("streaming") in ("stopped", "error"):
            self.stream_url.clear()

    def _rtsp_toggle(self):
        if self.session.state.get("streaming") in ("starting", "streaming"):
            self.session.stop_streaming()
            self.notify("Трансляция выключена")
        else:
            try:
                self.session.start_streaming(self.stream_interface.currentData(), self.stream_mode.currentData())
            except ValueError as exc:
                self.notify(str(exc))

    def _choose_record_directory(self):
        if self.session.state.get('recording') in ('starting', 'recording', 'finishing'):
            self.notify('Сначала остановите запись')
            return
        from master.ui.recording_storage import RecordingStorageDialog
        dialog = RecordingStorageDialog(self)
        self.touch.attach(dialog)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.record_directory = dialog.directory
            self.record_location.setText(self.record_directory.parent.parent.name + ' · Записи')
            self.record_location.setToolTip(str(self.record_directory))
            self.preferences['record_directory'] = str(self.record_directory)
            self._save_preferences()
            self.notify('Накопитель выбран')
        dialog.deleteLater()

    def _open_recordings(self):
        from master.ui.recordings import RecordingsDialog
        active = self.session.record_path if self.session.state.get('recording') in ('starting', 'recording', 'finishing') else None
        dialog = RecordingsDialog(self.record_directory, active, self)
        dialog.exec()
        dialog.deleteLater()

    def _record(self):
        if self.session.state.get("recording") in ("starting", "recording"):
            self.session.stop_recording()
        else:
            try:
                self.session.start_recording(self.record_directory)
            except (ValueError, OSError) as exc:
                self.notify(str(exc))

    def _preview_sound(self, key):
        existing = getattr(self, 'sound_preview', None)
        if existing is not None:
            existing.cancel()
            existing.deleteLater()
        for effect in [*self.sounds.effects.values(), *self.sounds.voices.values()]:
            effect.stop()
        if key in ('hello', 'bye'):
            from master.lifecycle_audio import LifecycleAudio
            self.sound_preview = LifecycleAudio(self)
            if not self.sound_preview.start(key, self.voice_volume.currentData()):
                self.notify('Запись недоступна')
        else:
            effect = self.sounds.voices.get(key) if self.sounds.voice_enabled else None
            (effect or self.sounds.effects[key]).play()

    def _display_density_changed(self, *_):
        self.preferences['layout_density'] = self.layout_density.currentData()
        self._save_preferences()
        if hasattr(self, 'sidebar'):
            self._apply_navigation_size()
            self._fit_live_layout()

    def _save_preferences(self, *_):
        if hasattr(self, 'source'):
            self.preferences['receiver_source'] = 'lan' if self.source.currentIndex() == 1 else 'local'
        if hasattr(self, 'auto_login'):
            self.preferences['auto_login'] = self.auto_login.isChecked()
        if hasattr(self, 'sound_enabled'):
            self.preferences['event_sounds'] = self.sound_enabled.isChecked()
            self.sounds.enabled = self.sound_enabled.isChecked()
        if hasattr(self, 'sound_event_checks'):
            self.preferences['sound_events'] = {key: check.isChecked() for key, check in self.sound_event_checks.items()}
            self.sounds.event_enabled = dict(self.preferences['sound_events'])
        if hasattr(self, 'voice_enabled'):
            self.preferences['event_voice'] = self.voice_enabled.isChecked()
            self.sounds.voice_enabled = self.voice_enabled.isChecked()
        if hasattr(self, 'voice_volume'):
            self.preferences['voice_volume'] = self.voice_volume.currentData()
            self.sounds.set_voice_volume(self.voice_volume.currentData())
        if hasattr(self, 'event_volume'):
            self.preferences['event_volume'] = self.event_volume.currentData()
            self.sounds.set_volume(self.event_volume.currentData())
        if hasattr(self, 'auto_pair'):
            self.preferences['auto_pair_lan'] = self.auto_pair.isChecked()
        if hasattr(self, 'auto_protect'):
            self.preferences['auto_protect_lan'] = self.auto_protect.isChecked()
        if hasattr(self, 'control_enabled'):
            self.preferences['control_enabled'] = self.control_enabled.isChecked()
        if not all(hasattr(self, attr) for attr in ("codec", "latency")):
            return
        self.preferences.pop("auto_lan", None)
        self.preferences.update(codec=self.codec.currentText(),
                                latency=self.latency.value(), camera_host=self.camera.host,
                                camera_transport=self.camera.transport)
        if hasattr(self, "recovery_mode"):
            self.preferences["recovery_mode"] = self.recovery_mode.currentData()
        if hasattr(self, 'decoder_mode'):
            self.preferences['decoder_mode'] = self.decoder_mode.currentData()
        temporary = self.preferences_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.preferences, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(self.preferences_path)

    def _restore_camera_settings(self):
        if self.camera.user_busy or self.radio_switch or not self.camera_profile:
            self.notify('Дождитесь подключения камеры и завершения операции')
            return
        from master.camera_restore import CameraRestoreStore
        try:
            store = CameraRestoreStore(self.config.data_root, self.camera_profile.get('fingerprint'))
            saved = store.read()
            dialog = QDialog(self)
            dialog.setWindowTitle('Восстановление настроек')
            box = QVBoxLayout(dialog)
            box.addWidget(label('Параметры этой камеры · связь и ключи сохраняются', 'muted'))
            selection = ChoicePicker('Сохранённые параметры')
            for key, title in (('previous', 'До последнего изменения'), ('initial', 'При первом подключении')):
                if key in saved:
                    selection.addItem(title, key)
            if not selection.items:
                self.notify('Для этой камеры ещё нет сохранённых параметров')
                return
            box.addWidget(selection)
            proceed = button('Посмотреть изменения', dialog.accept, 'primary')
            box.addWidget(proceed)
            box.addWidget(button('Отмена', dialog.reject))
            self.touch.attach(dialog)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                changes = store.patch(selection.currentData(), self.camera.settings or {})
                if changes:
                    self.camera_editor.review_changes(changes, 'Восстановить настройки камеры')
                else:
                    self.notify('Эти параметры уже установлены')
        except (OSError, ValueError) as exc:
            self.notify(str(exc))

    def _find_lan_cameras(self):
        if self.camera.transport == 'radio':
            self.camera.scan()
        self.lan_discovery.scan_now()
        self.camera_tabs.setCurrentIndex(1)

    def _set_camera_host(self):
        if self.radio_switch:
            self.notify('Дождитесь завершения переключения радиоканала')
            return
        if not self.camera_host.text().strip():
            self.camera.transport = 'lan'
            self.camera_transport_buttons['lan'].setChecked(True)
            self.lan_discovery.scan_now()
            self.camera_tabs.setCurrentIndex(1)
            self.notify('Поиск камер в локальной сети')
            return
        try:
            self.camera.host = valid_host(self.camera_host.text())
            self._save_preferences()
            self.camera.scan()
        except ValueError as exc:
            self.notify(str(exc))

    def _is_rtsp_camera(self):
        candidate = next((d for d in self.lan_device_data if d['host'] == self.camera.host), {})
        if not candidate:
            candidate = getattr(self, 'last_discovered_camera', {})
        return (self.camera.transport == 'lan' and candidate.get('host') == self.camera.host
                and candidate.get('video_service_available')
                and not candidate.get('candidate_fingerprint')
                and 'OpenIPC' not in candidate.get('family', ''))

    def _open_rtsp_camera(self):
        process = getattr(self, 'rtsp_window', None)
        if process is not None and process.state() != QProcess.ProcessState.NotRunning:
            self.notify('Окно IP-камеры уже открыто')
            return
        self.rtsp_window = QProcess(self)
        # Multimedia backend diagnostics may include authenticated URLs.
        # Keep this isolated viewer's stdout/stderr out of application logs.
        self.rtsp_window.setStandardErrorFile(os.devnull)
        self.rtsp_window.setStandardOutputFile(os.devnull)
        self.rtsp_window.start(sys.executable, ['-m', 'master.rtsp_viewer', '--host', self.camera.host])

    def _attempt_saved_login(self, force=False):
        if self.camera.transport == 'lan' and self._is_rtsp_camera():
            return False
        if (not self.auto_login.isChecked() or self.auto_login_pending or self.login_dialog_open or
                self.camera.user_busy or self.camera.closed or self.pairing_requested or
                (self.camera.transport == 'radio' and not self.camera.radio_connected)):
            return False
        if not force and time.monotonic() < self.auto_login_retry_at:
            return False
        if not force and self.camera.credentials and self.camera.bound_host == self.camera.host:
            return False
        identity = self.lan_candidate_fingerprint if self.camera.transport == 'lan' else None
        if self.camera.transport == 'radio':
            from shared.pairing_store import PairingStore
            store = PairingStore(self.config.data_root)
            identity = (store.read(store.active_path) or {}).get('ssh_fingerprint')
        context = (self.camera.host, self.camera.transport, identity)
        if not force and identity:
            from shared.pairing_store import PairingStore
            if any(p.get('archived') and p.get('ssh_fingerprint') == identity
                   for p in PairingStore(self.config.data_root).profiles(include_archived=True)):
                return False
        if not force and context in self.auto_login_attempts:
            return False
        self.auto_login_attempts.add(context)
        self.auto_login_context = context
        self.auto_login_pending = True
        approved = identity if self.camera.transport == 'lan' and identity in getattr(self, 'known_camera_fingerprints', set()) else None
        if self.camera.bind_saved(identity, approved=approved):
            self.camera_status.set_status('warning', 'ПОДКЛЮЧЕНИЕ')
            return True
        self.auto_login_pending = False
        return False

    def _camera_login(self, approved=None, manual=False):
        if self.camera.transport == 'lan' and self._is_rtsp_camera():
            self._open_rtsp_camera()
            return
        if self.login_dialog_open or self.auto_login_pending:
            return
        if self.radio_switch and self.radio_switch.get('phase') != 'recovery':
            self.notify('Дождитесь завершения переключения радиоканала')
            return
        if self.camera.transport == 'radio' and not self.camera.radio_connected:
            self.notify('Ожидается ответ камеры по радио')
            return
        if self.camera.user_busy:
            self.notify('Дождитесь завершения текущей операции')
            return
        if not manual and self._attempt_saved_login(force=True):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Подключить камеру")
        dialog.setMinimumWidth(360)
        form = QFormLayout(dialog)
        form.setContentsMargins(24, 24, 24, 24)
        host = QLineEdit(self.camera.host)
        host.setReadOnly(bool(self.radio_switch))
        username = QLineEdit("root")
        password = QLineEdit()
        password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Адрес", host)
        form.addRow("Пользователь", username)
        form.addRow("Пароль", password)
        identity = (self.camera_profile or {}).get('fingerprint')
        if not identity:
            for path in (self.config.data_root / 'config/cameras').glob('*.json'):
                try:
                    profile = json.loads(path.read_text())
                    if profile.get('host') == self.camera.host:
                        identity = profile.get('fingerprint')
                        break
                except (OSError, ValueError):
                    continue
        if identity:
            try:
                saved = self.camera.credentials_store.load(identity)
                if saved:
                    username.setText(saved[0])
                    password.setText(saved[1])
            except (OSError, ValueError):
                pass
        reveal = QCheckBox('Показать пароль')
        reveal.toggled.connect(lambda checked: password.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        form.addRow(reveal)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        actions.button(QDialogButtonBox.StandardButton.Ok).setText("Подключить")
        actions.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        form.addRow(actions)
        self.touch.attach(dialog)
        self.login_dialog_open = True
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        self.login_dialog_open = False
        if accepted:
            try:
                self.camera.host = valid_host(host.text())
                self.camera_auth = (username.text(), password.text())
                self.camera.bind(*self.camera_auth)
                self.camera_status.set_status("warning", "ПОДКЛЮЧЕНИЕ")
            except ValueError as exc:
                self.notify(str(exc))
        password.clear()

    def _show_camera_info(self, settings=None):
        from master.camera_summary import camera_summary
        values = camera_summary(self.camera_profile, settings)
        for key, label in self.camera_values.items():
            label.setText(values.get(key, '—'))

    def _camera_changed(self, data):
        state = data.get("state")
        if state in ('security_saved', 'security_rolled_back'):
            self.protect_button.setEnabled(True)
            message = 'Индивидуальный пароль установлен · вход проверен' if state == 'security_saved' else 'Изменение отменено · прежний доступ восстановлен'
            self.security_status.setText(message)
            self.notify(message)
            pending = getattr(self, '_security_onboarding', None)
            self._security_onboarding = None
            if state == 'security_saved' and pending == (self.camera_profile or {}).get('fingerprint'):
                QTimer.singleShot(200, self._continue_lan_setup)
            return
        if state == 'error' and hasattr(self, 'protect_button'):
            self.protect_button.setEnabled(True)
            self._security_onboarding = None
        automatic = self.auto_login_pending
        if state in ('bound', 'auth_required', 'trust_required', 'unsupported', 'error'):
            self.auto_login_pending = False
        if automatic and state == 'error' and self.auto_login_context:
            context = self.auto_login_context
            failures = self.auto_login_failures.get(context, 0) + 1
            self.auto_login_failures[context] = failures
            if failures < 3:
                self.auto_login_attempts.discard(context)
                self.auto_login_retry_at = time.monotonic() + 5 * failures
                QTimer.singleShot(5000 * failures + 100, self._attempt_saved_login)
        if state == 'auth_required':
            self.camera_status.set_status('warning', 'НУЖЕН ВХОД')
        if state == 'auth_required' and automatic:
            if data.get('reason') == 'no_saved_credentials' and getattr(self, 'lan_setup_host', None) != self.camera.host:
                self.notify('Для настроек камеры нужен вход · раздел «Камера»')
            else:
                self.lan_setup_host = None
                QTimer.singleShot(0, lambda: self._camera_login(manual=True))
        if state == 'trust_required' and not self.camera_auth and self.camera.active_request:
            self.camera_auth = self.camera.active_request.credentials
        if state in ('radio_settings', 'radio_restarted', 'settings', 'settings_saved') and not self.radio_switch:
            self._remember_camera_tuning(data)
        if state in ('paired', 'pairing_rolled_back') or (state == 'error' and self.pairing_requested):
            self._finish_pairing(data)
            return
        if self.radio_switch and state in ('found', 'offline'):
            return  # A planned channel gap must not unlock controls or queue discovery writes.
        if state == 'radio_prepared':
            saved = {**data['switch'], 'host': self.camera.host}
            self.radio_switch = {**saved, 'phase': 'prepared',
                                 'deadline': time.monotonic() + 65, 'next_probe': 0}
            self.radio_switch_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2))
            self.camera_editor.set_busy(True)
            self.radio_editor.set_busy(True)
            for item in self.camera_transport_buttons.values():
                item.setEnabled(False)
            self.radio_switch_timer.start()
            self.notify('Камера готова · согласование нового канала')
            return
        if state == 'radio_armed' and self.radio_switch:
            self.radio_switch.update(phase='armed', next_probe=time.monotonic() + 4,
                                     deadline=time.monotonic() + 55)
            self._retune_switch(self.radio_switch['target'])
            return
        if state == 'radio_pending':
            return
        if state in ('radio_switch_confirmed', 'radio_rolled_back', 'radio_switch_failed'):
            self._finish_radio_switch(data, state == 'radio_rolled_back', data.get('error'))
            return
        if self.radio_switch and state == 'error':
            self.radio_editor.status.setText('Восстановление связи · ожидается подтверждение')
            return
        if state == "trust_required" and self.camera_auth:
            answer = QMessageBox.question(self, "Привязать камеру", f"{data['host']}\n{data['fingerprint']}\n\nЭто ваша камера?")
            if answer == QMessageBox.StandardButton.Yes:
                auth = self.camera_auth
                QTimer.singleShot(100, lambda: self.camera.bind(*auth, approved=data["fingerprint"]))
            else:
                self.camera_auth = None
            return
        if state == "bound":
            self.lan_setup_host = None
            self.camera_host.setText(data['host'])
            if hasattr(self, "module_initializer"):
                self.module_initializer.next_try = 0
            self.auto_login_attempts.clear()
            self.auto_login_failures.clear()
            self.auto_login_retry_at = 0
            self.camera_auth = None
            self.camera_profile = data
            self.lan_steps.setText('Камера распознана · доступны настройки, привязка радио и защита входа')
            from master.camera_credentials import security_receipt_path
            try:
                protected = json.loads(security_receipt_path(self.config.data_root, data['fingerprint']).read_text()).get('stage') == 'protected'
            except (OSError, ValueError):
                protected = False
            self.security_status.setText('Индивидуальный пароль · вход проверен' if protected else 'Настройте индивидуальный пароль кнопкой «Защитить вход»')
            self.known_camera_fingerprints.add(data.get('fingerprint'))
            self.camera_name.setText(data["family"])
            self.camera_address.setText(data["host"])
            self.camera_status.set_status("ready", "ПОДКЛЮЧЕНА")
            self.camera_editor.load(data.get("settings", {}))
            # A saved pairing profile can predate a camera codec change.
            # Use the authenticated camera readback on reconnection as well.
            codec = data.get("settings", {}).get("config", {}).get("video0", {}).get("codec")
            if codec in ("h264", "h265"):
                self.codec.setCurrentText("H.264" if codec == "h264" else "H.265")
                if self.session.running and codec != getattr(self.session, 'selected_codec', codec):
                    self.session.restart_decoder(codec)
            self.radio_editor.load(data.get('radio_settings', {}))
            self._show_camera_info()
            self._save_preferences()
            camera_notice_id = data.get('fingerprint') or data.get('host')
            if camera_notice_id and camera_notice_id != getattr(self, '_last_bound_notice', None):
                self._last_bound_notice = camera_notice_id
                self.notify("Камера подключена · параметры получены")
            if data.get('credential_storage') == 'session_only':
                self.notify('Вход сохранён до закрытия приложения')
            if self.radio_switch:
                self.camera_editor.set_busy(True)
                self.radio_editor.set_busy(True)
                self.radio_switch_timer.start()
            elif self.camera.transport == 'lan':
                # Wait for the authentication request to leave the dispatcher.
                QTimer.singleShot(200, self._continue_lan_setup)
            else:
                QTimer.singleShot(0, self._refresh_radio)
        elif state in ("radio_settings", "radio_restarted"):
            preserve_radio_edits = False
            if data.get("background"):
                try:
                    preserve_radio_edits = bool(self.radio_editor.changes())
                except (ValueError, TypeError):
                    preserve_radio_edits = True
            if not preserve_radio_edits:
                self.radio_editor.load(data["radio_settings"])
            if state == "radio_restarted":
                from shared.radio_settings import receiver_settings
                live = data["radio_settings"]["live"]
                try:
                    receiver_settings(live["channel"], live["width"])
                except (ValueError, KeyError):
                    self.notify("Радиослужба запущена, параметры приёмника требуют проверки")
                    self.resume_after_radio = False
                    return
                self.preferences.update(radio_channel=live["channel"], radio_width=live["width"])
                self._save_preferences()
                previous = self.session.state.get('radio_tuning', {})
                tuning_changed = any(previous.get(key) != live[key] for key in ('channel', 'width'))
                if self.resume_after_radio and tuning_changed:
                    self.session.stop()
                    QTimer.singleShot(250, self._resume_radio)
                self.resume_after_radio = False
                self.notify("Частота и мощность подтверждены камерой")
        elif state in ("settings", "settings_saved"):
            before_video = self.camera_editor.config.get("video0", {})
            after_video = data["settings"]["config"].get("video0", {})
            timing_changed = any(before_video.get(key) != after_video.get(key) for key in ("fps", "size", "codec", "profile", "gopSize"))
            preserve_edits = False
            if data.get('background'):
                try:
                    preserve_edits = bool(self.camera_editor.changes())
                except (ValueError, TypeError):
                    preserve_edits = True
            if not preserve_edits:
                self.camera_editor.load(data["settings"])
            self._show_camera_info(data['settings'])
            codec = data["settings"]["config"].get("video0", {}).get("codec")
            if codec in ("h264", "h265"):
                self.codec.setCurrentText("H.264" if codec == "h264" else "H.265")
                codec_changed = codec != getattr(self.session, 'selected_codec', codec)
                if self.session.running and (codec_changed or (state == "settings_saved" and timing_changed)):
                    self.session.restart_decoder(codec)
            if state == "settings_saved":
                self.notify("Настройки применены · чтение с камеры подтверждено")
        elif state == "found":
            previous_host = getattr(self, 'last_discovered_camera', {}).get('host')
            self.last_discovered_camera = dict(data)
            self.camera_settings_button.setEnabled(self.camera.transport == 'lan' and bool(data.get("web_url")))
            identity = self.camera_profile if self.camera_profile and self.camera_profile.get("host") == data["host"] else data
            self.camera_name.setText(identity["family"])
            self.camera_address.setText(data["host"])
            self.camera_status.set_status("ready", "ПОДКЛЮЧЕНА" if identity is self.camera_profile and self.camera.credentials and self.camera.bound_host == data["host"] else "В СЕТИ")
            self.camera_editor.set_busy(self.camera.busy)
            self.radio_editor.set_busy(self.camera.busy)
            if self.last_camera_state == "offline" and self.camera.bound_host == data["host"]:
                self.camera_editor.set_busy(self.camera.busy)
                self.radio_editor.set_busy(self.camera.busy)
                if not self.camera.busy:
                    QTimer.singleShot(0, self._refresh_radio)
            if previous_host != data['host']:
                self.notify("Камера найдена")
            QTimer.singleShot(0, self._attempt_saved_login)
        elif state == "offline":
            self.camera_editor.set_busy(True)
            self.radio_editor.set_busy(True)
            self.camera_settings_button.setEnabled(False)
            self.camera_status.set_status("offline", "НЕТ СВЯЗИ")
            if self.last_camera_state in ("found", "bound"):
                self.notify("Камера не отвечает по радио" if self.camera.transport == 'radio' else "Камера отключена от LAN")
        elif state in ("auth_required", "unsupported", "error"):
            from master.camera_errors import connection_message
            self.camera_editor.set_busy(False)
            self.radio_editor.set_busy(False)
            self.resume_after_radio = False
            self.camera_auth = None
            self.camera_status.set_status("warning", "НУЖЕН ВХОД" if state == "auth_required" else "ПРОВЕРЬТЕ")
            self.notify(connection_message(data.get("error", "Камера недоступна")))
        self.last_camera_state = state
        self.quick_camera_name.setText("Нет связи" if state == "offline" else "Подключена" if self.camera_editor.controls else "Нужен вход")

    def _camera_command_changed(self, data):
        from master.camera_errors import connection_message
        data = {**data, 'message': connection_message(data['message'])}
        state = data['command_state']
        if state != 'queued':
            route = 'LAN' if data['transport'] == 'lan' else 'радио'
            elapsed = f" · {data['elapsed_ms'] / 1000:.1f} с" if state != 'running' and 'elapsed_ms' in data else ''
            self._append_journal(f"{data['label']} · {route} · {data['message']}{elapsed}")
        if data['label'] == 'Подключение камеры' and state == 'cancelled':
            self.auto_login_pending = False
            self.auto_login_attempts.discard(self.auto_login_context)
            self.auto_login_retry_at = 0
        self.camera_command_status.setText(f"{data['label']} · {data['message']}")
        self.camera_command_status.setToolTip(f"Операция {data['operation_id']} · {data['transport'].upper()}")
        color = '#33d49b' if state == 'confirmed' else '#ffc16f' if state in ('queued', 'running') else '#ff827d'
        self.camera_command_status.setStyleSheet(f'color: {color};')
        if data['label'] == 'Радионастройки':
            self.radio_editor.status.setText(data['message'])
        if state in ('unconfirmed', 'failed') and data['label'] in ('Радионастройки', 'Настройки камеры'):
            self.sounds.play('settings_error')
        if state in ('cancelled', 'unconfirmed', 'failed'):
            if self.radio_switch or self.camera.busy:
                return
            self.camera_editor.set_busy(False)
            self.radio_editor.set_busy(False)
            self.resume_after_radio = False
            if state in ('cancelled', 'unconfirmed'):
                self.notify(data['message'])

    def _health(self):
        screen = self.screen()
        if screen is not None:
            size = screen.geometry().size()
            self.display_info.setText(f'{size.width()} × {size.height()} · {screen.refreshRate():.0f} Гц · размер окна автоматически')
        if not (getattr(self, '_shutdown_complete', False) or getattr(self, 'closing_camera', False)
                or self.pairing_requested or self.radio_switch or self.camera.busy):
            self.session.discover_cameras()
        storage = probe_storage(self.record_directory)
        from shared.recording_storage import validate_recording_directory
        try:
            volume = validate_recording_directory(self.record_directory)
            self.record_location.setText(f'{volume.name} · свободно {storage.free_gib:.1f} ГБ')
        except (ValueError, OSError):
            self.record_location.setText('Выберите накопитель для записи')
        radio = self.config.data_root.parent / "experiments/wfb-link/target/release/wfb-radio-diag"
        if self.embedded_receiver:
            radio = Path('/usr/local/libexec/fit-lab/wfb_rx')
        decoder = self.session.state.get("version", "ожидание запуска")
        report = self._assistant_report(storage.writable)
        self.assistant_summary.setText(' · '.join(item['message'] for item in report['issues']) or 'Замечаний по текущим данным нет')
        self.assistant_summary.setToolTip('\n'.join(item['action'] for item in report['issues']) or 'Локальная диагностика без изменения настроек.')
        if hasattr(self, "checks"):
            from master.module_status import local_receiver_status
            live = local_receiver_status(self.usb_devices, self.session.state, self.session.running, self.session.mode)
            self.checks.setText(f"Запись  {'доступна' if storage.writable else 'накопитель недоступен'}\n"
                               f"USB  {live.usb_count} подключено · {live.receiving_count} принимают\n"
                               f"Приёмник  {live.title if radio.is_file() else 'не установлен'}\n"
                               f"TX  {live.tx}\nДекодер  {decoder}")

    def _assistant_report(self, writable=None):
        from master.assistant import assess
        screens = [{'name': s.name(), 'width': s.geometry().width(), 'height': s.geometry().height(),
                    'refresh_hz': round(s.refreshRate()), 'pixel_ratio': s.devicePixelRatio()}
                   for s in QApplication.screens()]
        touch = getattr(getattr(self, 'touch', None), 'status', 'Не проверен')
        if writable is None:
            writable = probe_storage(self.record_directory).writable
        return assess(self.session.state, self.session.running, screens, touch, writable)

    def _export_diagnostics(self):
        from master.diagnostics import station_snapshot
        report = station_snapshot(self.session.state, self.session.running, len(self.usb_devices))
        report['assistant'] = self._assistant_report()
        target = self.config.data_root / 'exports' / f'FIT-LAB-check-{time.strftime("%Y%m%d-%H%M%S")}-{time.time_ns() % 1000000:06d}.json'
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        except (OSError, ValueError):
            self.notify('Не удалось сохранить отчёт')
            return
        self.notify('Отчёт сохранён')
        self.toast.setToolTip(str(target))
        self._append_journal('Отчёт: ' + str(target))

    def _update_modules(self):
        if not self.embedded_receiver:
            if not hasattr(self, 'application_presence'):
                from master.lan_presence import LanPresence
                self.application_presence = LanPresence(
                    self.config.data_root.parent,
                    os.environ.get('FIT_LAB_RECEIVER_HOST', '192.168.2.36'))
            import queue
            from master.module_initialization import ModuleInitialization
            if not hasattr(self, 'module_initializer'):
                self.module_initializer = ModuleInitialization(
                    self.config.data_root.parent,
                    os.environ.get('FIT_LAB_RECEIVER_HOST', '192.168.2.36'),
                    self.camera.credentials_store)
            self.module_initializer.tick()
            try:
                while True:
                    self.notify(self.module_initializer.messages.get_nowait())
            except queue.Empty:
                pass
        self.station.check_stale_modules()
        modules = self.station.registry.all()
        if self.embedded_receiver:
            modules = []
        count, tone, active = self.modules_page.update_inventory(
            self.usb_devices, self.session.state, self.session.running, self.session.mode,
            modules, self.discovery_ready)
        self.module_summary.set_status(tone, f"RX · {len(self.usb_devices)}" if self.embedded_receiver else f"МОДУЛИ · {count}")
        self.nav['modules'].setProperty('active', active)
        for module in modules:
            previous = self.module_states.get(module.module_id)
            if previous != module.state:
                action = 'Модуль найден' if previous is None else 'Связь с модулем потеряна' if module.state.value == 'unreachable' else 'Модуль снова в сети'
                self.notify(f'{action}: {module.public_label()}')
        self.module_states = {m.module_id: m.state for m in modules}
        if self.embedded_receiver:
            from shared.master_presence import connected_masters, PresenceNotice
            if not hasattr(self, 'master_presence_notice'):
                self.master_presence_notice = PresenceNotice()
            masters = connected_masters()
            self.modules_page.set_master_connected(bool(masters))
            change = self.master_presence_notice.update(bool(masters))
            if change == 'lost':
                message = 'Связь с приложением мастера потеряна' + (' · локальный приём продолжается' if self.session.running else '')
                self.recent_notifications.pop(message, None)
                self.notify(message)
            elif change == 'restored':
                self.recent_notifications.pop('Связь с приложением мастера восстановлена', None)
                self.notify('Связь с приложением мастера восстановлена')

    def _discover_modules(self):
        if self.discovery_socket.state() != QAbstractSocket.SocketState.BoundState:
            return
        for _ in range(64):
            if not self.discovery_socket.hasPendingDatagrams():
                break
            packet = self.discovery_socket.receiveDatagram(65535)
            self.discovery.process_datagram(bytes(packet.data()), (packet.senderAddress().toString(), packet.senderPort()))

    def _focus(self):
        if self.session.video_window_handle:
            self._native_fullscreen()
            return
        if self.fullscreen_video is not None:
            self.fullscreen_video.close()
            return
        dialog = self.cached_fullscreen_video
        if dialog is None:
            dialog = FullscreenVideo(self.video, self)
            self.session.frame.connect(dialog.video.set_frame)
            dialog.video.audio_controls.changed.connect(self._set_camera_audio)
            dialog.finished.connect(self._fullscreen_finished)
            self.touch.attach(dialog)
            if self.session.video_window_handle:
                # Keep the X11 target alive while the worker switches back.
                # Destroying it on close races the decoder's drawing thread.
                dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
                self.cached_fullscreen_video = dialog
                dialog.video.nativeResized.connect(lambda width, height: self.session.set_video_window(dialog.video.native_handle(), width, height) if self.fullscreen_video is dialog else None)
        self.fullscreen_video = dialog
        dialog.video.audio_controls.set_values(self.session.audio_volume, self.session.audio_muted)
        dialog.showFullScreen()
        if self.session.video_window_handle:
            self.session.set_video_window(dialog.video.native_handle(), dialog.video.width(), dialog.video.height())

    def _set_camera_audio(self, volume, muted):
        self.session.set_audio(volume, muted)
        self.preferences.update(camera_audio_volume=volume, camera_audio_muted=muted)
        self.video.audio_controls.set_values(volume, muted)
        if self.fullscreen_video is not None:
            self.fullscreen_video.video.audio_controls.set_values(volume, muted)
        self._save_preferences()

    def _fullscreen_finished(self, _):
        self.fullscreen_video = None
        if self.session.video_window_handle:
            self.session.set_video_window(self.video.native_handle(), self.video.width(), self.video.height())
        self.video.performance()

    def _exit_focus(self):
        if self.native_focus:
            self._native_fullscreen()
            return
        if self.fullscreen_video is not None:
            self.fullscreen_video.close()

    def _native_fullscreen(self):
        self.video.settle_native()
        self.setUpdatesEnabled(False)
        try:
            self._change_native_fullscreen()
            self.centralWidget().layout().activate()
            self.content_column.activate()
        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def _change_native_fullscreen(self):
        if not self.native_focus:
            self.show_page('live')
            widgets = [self.sidebar, self.live_rail_scroll, self.telemetry, self.live_toolbar_widget, self.dock]
            widgets += [self.header_row.itemAt(i).widget() for i in range(self.header_row.count()) if self.header_row.itemAt(i).widget()]
            self.focus_widgets = [(item, item.isVisible()) for item in widgets]
            self.native_focus = True
            for item, visible in self.focus_widgets:
                item.hide()
            self.content_column.setContentsMargins(0, 0, 0, 0)
            self.content_column.setSpacing(0)
            self.native_leave.show()
            self.native_leave.raise_()
        else:
            self.native_focus = False
            self.native_leave.hide()
            for item, visible in self.focus_widgets:
                item.setVisible(visible)
            self.content_column.setContentsMargins(12, 4, 12, 8)
            self.content_column.setSpacing(6)
            QTimer.singleShot(0, self._fit_video_aspect)
        QTimer.singleShot(0, lambda: self.native_leave.move(max(0, self.video.width()-76), 16))

    def _desktop_panel(self, visible):
        if not getattr(self, 'embedded_receiver', False) or QApplication.platformName() != 'xcb':
            return
        # XFCE panel remains running; restore its task buttons while minimized.
        QProcess.startDetached('xfconf-query', ['-c', 'xfce4-panel', '-p',
                              '/panels/panel-1/autohide-behavior', '-s', '0' if visible else '2'])

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, 'video'):
            self.video.settle_native()
            self._desktop_panel(self.isMinimized())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'farewell_screen'):
            self.farewell_screen.setGeometry(self.rect())
        if not hasattr(self, "sidebar"):
            return
        self._apply_navigation_size()
        self._fit_live_layout()

    def _apply_navigation_size(self):
        from master.ui.display import compact_navigation
        compact = compact_navigation(self.width(), self.height(), self.preferences.get('layout_density', 'auto'))
        for item in self.nav.values():
            item.setFixedHeight(58 if compact else 78)
            item.setToolTip(item.text())
            item.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.sidebar.setFixedHeight(68 if compact else 88)
        if hasattr(self, 'camera_address'):
            self.camera_address.setVisible(not compact)
            self.camera_command_status.setVisible(not compact)
        if hasattr(self, "record_button"):
            self.record_button.setMinimumWidth(56 if compact else 110)

    def _fit_live_layout(self):
        if not hasattr(self, "live_rail_mode"):
            return
        wide = self.width() >= 1180 and self.height() >= 820
        self.live_rail_scroll.setFixedWidth(max(280, round(self.width()*.278)))
        QTimer.singleShot(0, self._fit_video_aspect)
        for metric in self.metrics.values():
            if isinstance(metric, MetricChip):
                metric.symbol.setVisible(wide)
        self.product_label.setVisible(self.width() >= 1050)
        for control in self.dock_actions:
            control.setFixedHeight(82 if wide else 62)
        if wide == self.live_rail_mode:
            return
        self.live_rail_mode = wide
        for metric in self.metrics.values():
            if isinstance(metric, MetricChip):
                metric.layout().setContentsMargins(12 if wide else 5, 5, 12 if wide else 5, 5)
                metric.value_label.setStyleSheet('font-size: 19px;' if wide else 'font-size: 14px;')
        self.live_toolbar_widget.setVisible(not wide)
        for tile in self.rx_tiles:
            self.live_toolbar.removeWidget(tile)
            self.rx_rail_layout.removeWidget(tile)
            (self.rx_rail_layout if wide else self.live_toolbar).addWidget(tile)
            tile.set_wide(wide)
            tile.setVisible(self.rx_tiles.index(tile) < 2 or any(r.get("index") == 2 for r in self.session.state.get("receivers", [])) or len(self.usb_devices) >= 3)
        self.live_toolbar_column.addWidget(self.compact_quality)
        self.compact_quality.setVisible(not wide)
        self.live_radio_summary.setVisible(wide)

    def _fit_video_aspect(self):
        if self.native_focus or self.live_rail_mode or not self.video.isVisible():
            return
        # On the short touch display, give unused horizontal space to the
        # inspector instead of surrounding a small 16:9 picture with side bars.
        stage = self.video.parentWidget()
        target = max(stage.minimumWidth(), round(self.video.height() * 16 / 9))
        if target >= stage.minimumWidth():
            available = stage.width() + self.live_rail_scroll.width()
            rail = max(280, min(self.width() // 2, available - target))
            if abs(rail - self.live_rail_scroll.width()) > 1:
                self.live_rail_scroll.setFixedWidth(rail)

    def _power_menu(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('FIT-LAB')
        dialog.setObjectName('powerMenu')
        dialog.setMinimumWidth(min(390, self.screen().availableGeometry().width()-32))
        dialog.setStyleSheet('#powerMenu { background: #171e20; border: 1px solid #827055; border-radius: 12px; }')
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 22, 22, 20)
        layout.setSpacing(14)
        heading = label('FIT-LAB', 'section')
        heading.setStyleSheet('font-size: 21px; color: #ffd29a; font-weight: 600; letter-spacing: 2px;')
        layout.addWidget(heading)
        layout.addWidget(label('Управление приложением', 'muted'))
        layout.addSpacing(6)
        for caption, symbol, restart in [('Перезапустить', 'restart', True), ('Завершить работу', 'power', False)]:
            item = button(caption, lambda checked=False, restart=restart: finish(restart))
            item.setIcon(action_icon(symbol))
            item.setIconSize(QSize(30, 30))
            item.setProperty('role', 'primary' if restart else 'ghost')
            item.setMinimumHeight(66)
            item.setAccessibleName('Перезапустить приложение' if restart else 'Закрыть приложение')
            layout.addWidget(item)
        def finish(restart):
            self.restart_requested = restart
            dialog.accept()
            self.close()
        layout.addWidget(button('Отмена', dialog.reject))
        self.touch.attach(dialog)
        dialog.exec()

    def _finish_farewell(self):
        self._farewell_done = True
        self.close()

    def closeEvent(self, event):
        if self.camera.job is not None and self.camera.job.isRunning():
            # Finish an in-flight write before destroying its QThread. Keep
            # Qt responsive; a synchronous wait here can freeze or crash exit.
            event.ignore()
            if not getattr(self, "closing_camera", False):
                self.closing_camera = True
                self.camera.closed = True
                self.camera._cancel_pending('Приложение закрывается')
                self.camera.timer.stop()
                self.camera.job.finished.connect(self.close)
                self.session.stop()
                self.notify("Завершение операции камеры…")
            return
        if not getattr(self, '_farewell_done', False):
            event.ignore()
            if getattr(self, '_farewell_started', False):
                return
            self._farewell_started = True
            self.closing_camera = True
            self.health_timer.stop()
            self.modules_timer.stop()
            self.camera.timer.stop()
            self.camera.closed = True
            self.sounds.enabled = False
            if getattr(self, 'sound_preview', None) is not None:
                self.sound_preview.cancel()
            for effect in [*self.sounds.effects.values(), *self.sounds.voices.values()]:
                effect.stop()
            self.centralWidget().setEnabled(False)
            from master.ui.farewell import FarewellScreen
            self.video.hide()
            self.farewell_screen = FarewellScreen(self)
            if self.session.recorder.state() != QProcess.ProcessState.NotRunning:
                self.farewell_screen.set_caption('Сохраняем запись')
            self.toast.setText('Завершение работы…')
            self.session.stop_recording()
            self.session.stop()
            def farewell():
                self.farewell_screen.set_caption('Перезапускаем FIT-LAB' if getattr(self, 'restart_requested', False) else 'До следующего полёта')
                from master.lifecycle_audio import LifecycleAudio
                self.farewell_audio = LifecycleAudio(self)
                self.farewell_audio.finished.connect(self._finish_farewell)
                if not self.preferences.get('event_sounds', True) or not self.preferences.get('sound_events', {}).get('bye', True) or not self.farewell_audio.start('bye', int(self.preferences.get('voice_volume', 100))):
                    QTimer.singleShot(0, self._finish_farewell)
            if self.session.recorder.state() != QProcess.ProcessState.NotRunning:
                self.session.recorder.finished.connect(lambda *_: farewell())
            else:
                farewell()
            return
        self.shutdown()
        event.accept()

    def shutdown(self):
        if getattr(self, '_shutdown_complete', False):
            return
        self._shutdown_complete = True
        if hasattr(self, 'application_presence'):
            self.application_presence.close()
        if self.system_volume is not None:
            self.system_volume.close()
        self.session.stop()
        if self.camera_browser is not None:
            self.camera_browser.terminate()
            if not self.camera_browser.waitForFinished(3000):
                self.camera_browser.kill()
                self.camera_browser.waitForFinished(1000)
        for cleanup in (self.viewer_service.close, self.lan_discovery.close, self.touch.close, self.usb_monitor.close, self.camera.close,
                        self.session.close, self.discovery_socket.close):
            try:
                cleanup()
            except Exception as exc:
                from master.diagnostics import append_event
                append_event(self.config.data_root, {'time': time.time(), 'operation': 'shutdown',
                             'component': cleanup.__qualname__, 'error': type(exc).__name__})
