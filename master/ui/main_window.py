from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from master.core import StationCore
from master.status import MasterStatus, build_master_status
from master.ui.widgets import MetricChip, ModuleCard, PageHeader, StatusBadge, repolish
from shared.config import StationConfig
from shared.models import ModuleKind
from shared.storage import ensure_directories, probe_storage


class MainWindow(QMainWindow):
    NAV_ITEMS = (
        ("video", "Видеоприём", "В"),
        ("modules", "Модули", "М"),
        ("cameras", "Камеры", "К"),
        ("radio", "Радиосвязь", "Р"),
        ("recording", "Запись", "З"),
        ("streaming", "Трансляция", "Т"),
        ("guidance", "Наведение", "Н"),
        ("diagnostics", "Диагностика", "Д"),
        ("settings", "Настройки", "П"),
        ("service", "Сервис", "С"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FIT-LAB Station")
        self.resize(1440, 900)
        self.setMinimumSize(920, 620)

        self.config = StationConfig.load()
        ensure_directories(self.config.data_root, self.config.required_directories())
        self.station = StationCore()

        self._sidebar_expanded = True
        self._sidebar_user_choice = False
        self._nav_buttons: dict[str, QPushButton] = {}
        self._page_indexes: dict[str, int] = {}
        self._module_cards: dict[ModuleKind, ModuleCard] = {}

        root = QWidget()
        self.setCentralWidget(root)

        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = self._build_sidebar()
        layout.addWidget(self.sidebar)

        content = QVBoxLayout()
        content.setContentsMargins(20, 15, 20, 18)
        content.setSpacing(14)

        content.addWidget(self._build_topbar())

        self.pages = QStackedWidget()
        content.addWidget(self.pages, 1)

        content_container = QWidget()
        content_container.setLayout(content)
        layout.addWidget(content_container, 1)

        self._add_pages()
        self.show_page("video")
        self.refresh_status()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(2000)
        self.refresh_timer.timeout.connect(self.refresh_status)
        self.refresh_timer.start()

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(5)

        header = QHBoxLayout()
        header.setSpacing(7)

        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)

        self.brand_label = QLabel("FIT-LAB")
        self.brand_label.setObjectName("brand")

        self.brand_caption = QLabel("GROUND STATION")
        self.brand_caption.setObjectName("brandCaption")

        brand_box.addWidget(self.brand_label)
        brand_box.addWidget(self.brand_caption)

        self.collapse_button = QPushButton("‹")
        self.collapse_button.setObjectName("collapseButton")
        self.collapse_button.setToolTip("Свернуть боковую панель")
        self.collapse_button.clicked.connect(self.toggle_sidebar)

        header.addLayout(brand_box)
        header.addStretch(1)
        header.addWidget(self.collapse_button)

        layout.addLayout(header)
        layout.addSpacing(13)

        nav_caption = QLabel("РАЗДЕЛЫ")
        nav_caption.setProperty("eyebrow", True)
        self.nav_caption = nav_caption
        layout.addWidget(nav_caption)
        layout.addSpacing(2)

        for key, title, short_title in self.NAV_ITEMS:
            button = QPushButton(title)
            button.setProperty("nav", True)
            button.setToolTip(title)
            button.setMinimumWidth(46)
            button.clicked.connect(lambda checked=False, page=key: self.show_page(page))
            button.setProperty("shortTitle", short_title)
            self._nav_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        self.sidebar_status = StatusBadge("СТАНЦИЯ ГОТОВА", "ready")
        layout.addWidget(self.sidebar_status)

        self.sidebar_storage = QLabel("Хранилище: проверка…")
        self.sidebar_storage.setProperty("muted", True)
        self.sidebar_storage.setWordWrap(True)
        layout.addWidget(self.sidebar_storage)

        return sidebar

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topbar")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(9, 8, 10, 8)
        layout.setSpacing(8)

        selector = QFrame()
        selector.setProperty("modeSelector", True)
        selector_layout = QHBoxLayout(selector)
        selector_layout.setContentsMargins(3, 3, 3, 3)
        selector_layout.setSpacing(2)

        self.broadcast_button = QPushButton("Broadcast")
        self.broadcast_button.setProperty("mode", True)
        self.broadcast_button.clicked.connect(lambda: self.show_page("video"))

        self.sdr_button = QPushButton("SDR")
        self.sdr_button.setProperty("mode", True)
        self.sdr_button.clicked.connect(lambda: self.show_page("sdr"))

        selector_layout.addWidget(self.broadcast_button)
        selector_layout.addWidget(self.sdr_button)

        self.modules_info = QLabel("Модули: 0")
        self.modules_info.setProperty("topInfo", True)

        self.storage_info = QLabel("SSD: проверка…")
        self.storage_info.setProperty("topInfo", True)

        self.overall_label = StatusBadge("ПРОВЕРКА", "offline")

        layout.addWidget(selector)
        layout.addStretch(1)
        layout.addWidget(self.modules_info)
        layout.addWidget(self.storage_info)
        layout.addWidget(self.overall_label)

        return bar

    def _add_page(self, key: str, widget: QWidget) -> None:
        self._page_indexes[key] = self.pages.addWidget(widget)

    def _add_pages(self) -> None:
        self._add_page("video", self._video_page())
        self._add_page("modules", self._modules_page())
        self._add_page(
            "cameras",
            self._placeholder_page(
                "Камеры",
                "Определение модели, резервное копирование и только поддерживаемые настройки камеры.",
                "КАМЕРЫ И ПЕРЕДАТЧИКИ",
            ),
        )
        self._add_page(
            "radio",
            self._placeholder_page(
                "Радиосвязь",
                "Broadcast, RX1/RX2 и согласованные параметры радиолинии.",
                "РАДИОЛИНИЯ",
            ),
        )
        self._add_page(
            "recording",
            self._placeholder_page(
                "Запись",
                "Исходный видеопоток, сегменты, состояние накопителя и архив.",
                "МЕДИА",
            ),
        )
        self._add_page(
            "streaming",
            self._placeholder_page(
                "Трансляция",
                "Локальная трансляция для телефона, планшета или другого клиента.",
                "КЛИЕНТЫ",
            ),
        )
        self._add_page(
            "guidance",
            self._placeholder_page(
                "Наведение",
                "PAN/TILT, центр, пределы, скорость и пресеты после подключения Модуля управления.",
                "УПРАВЛЕНИЕ",
            ),
        )
        self._add_page(
            "diagnostics",
            self._placeholder_page(
                "Диагностика",
                "Состояние модулей, радио, декодера, температур, накопителя и ресурсов.",
                "СОСТОЯНИЕ СИСТЕМЫ",
            ),
        )
        self._add_page(
            "settings",
            self._placeholder_page(
                "Настройки",
                "Профили станции, интерфейс, хранение и безопасные пользовательские параметры.",
                "КОНФИГУРАЦИЯ",
            ),
        )
        self._add_page(
            "service",
            self._placeholder_page(
                "Сервис",
                "Технический журнал, версии, обслуживание модулей и расширенная диагностика.",
                "ТЕХНИЧЕСКИЙ РЕЖИМ",
            ),
        )
        self._add_page(
            "sdr",
            self._placeholder_page(
                "SDR",
                "Спектр, сканирование, аналоговое видео и запись IQ. Сейчас подготовлен каркас.",
                "ОТДЕЛЬНЫЙ РЕЖИМ",
            ),
        )

    def _video_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(13)

        root.addWidget(
            PageHeader(
                "Видеоприём",
                "Основной рабочий экран Broadcast. Камерный OSD остаётся частью исходного изображения.",
                "BROADCAST",
            )
        )

        source_bar = QFrame()
        source_bar.setProperty("toolbar", True)
        source_layout = QHBoxLayout(source_bar)
        source_layout.setContentsMargins(12, 7, 8, 7)
        source_layout.setSpacing(8)

        source_caption = QLabel("Источник")
        source_caption.setProperty("muted", True)

        self.video_source_label = QLabel("Модуль видеоприёма не подключен")
        self.video_source_label.setStyleSheet("font-weight: 700;")

        modules_button = QPushButton("Открыть модули")
        modules_button.setProperty("role", "ghost")
        modules_button.clicked.connect(lambda: self.show_page("modules"))

        fullscreen_button = QPushButton("Во весь экран")
        fullscreen_button.setProperty("role", "ghost")
        fullscreen_button.setEnabled(False)
        fullscreen_button.setToolTip("Станет доступно после подключения видеопотока.")

        source_layout.addWidget(source_caption)
        source_layout.addWidget(self.video_source_label)
        source_layout.addStretch(1)
        source_layout.addWidget(modules_button)
        source_layout.addWidget(fullscreen_button)

        root.addWidget(source_bar)

        video = QFrame()
        video.setProperty("video", True)
        video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        video_layout = QVBoxLayout(video)
        video_layout.setContentsMargins(24, 24, 24, 24)
        video_layout.addStretch(1)

        video_title = QLabel("Видеосигнал не подключен")
        video_title.setObjectName("videoTitle")
        video_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        video_hint = QLabel(
            "Подключённый Модуль видеоприёма появится здесь автоматически."
        )
        video_hint.setObjectName("videoHint")
        video_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        connect_button = QPushButton("Перейти к модулям")
        connect_button.setProperty("role", "primary")
        connect_button.setFixedWidth(190)
        connect_button.clicked.connect(lambda: self.show_page("modules"))

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(connect_button)
        button_row.addStretch(1)

        video_layout.addWidget(video_title)
        video_layout.addWidget(video_hint)
        video_layout.addSpacing(8)
        video_layout.addLayout(button_row)
        video_layout.addStretch(1)

        root.addWidget(video, 1)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(9)
        metrics.setVerticalSpacing(9)

        metric_items = (
            ("RX1", "—", "приёмник 1"),
            ("RX2", "—", "приёмник 2"),
            ("FEC", "—", "коррекция"),
            ("Потери", "—", "пакеты"),
            ("REC", "Остановлена", "запись"),
            ("Видеолинк", "Нет данных", "поток"),
        )

        for index, (label, value, hint) in enumerate(metric_items):
            metrics.addWidget(MetricChip(label, value, hint), index // 3, index % 3)

        root.addLayout(metrics)

        quick = QHBoxLayout()
        quick.setSpacing(9)

        for title, target in (
            ("Запись  →", "recording"),
            ("Трансляция  →", "streaming"),
            ("Диагностика  →", "diagnostics"),
        ):
            button = QPushButton(title)
            button.setProperty("quick", True)
            button.clicked.connect(lambda checked=False, page=target: self.show_page(page))
            quick.addWidget(button)

        root.addLayout(quick)
        return page

    def _modules_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(13)

        root.addWidget(
            PageHeader(
                "Модули",
                "Независимые узлы станции. Обнаружение идёт автоматически; управление будет доступно только после доверенной привязки.",
                "СЕТЬ И ОБОРУДОВАНИЕ",
            )
        )

        notice = QFrame()
        notice.setProperty("toolbar", True)
        notice_layout = QHBoxLayout(notice)
        notice_layout.setContentsMargins(13, 8, 13, 8)

        notice_text = QLabel("Поиск модулей в локальной сети")
        notice_text.setStyleSheet("font-weight: 700;")

        notice_state = StatusBadge("ОЖИДАНИЕ", "offline")

        notice_layout.addWidget(notice_text)
        notice_layout.addStretch(1)
        notice_layout.addWidget(notice_state)

        root.addWidget(notice)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        content = QWidget()
        cards = QVBoxLayout(content)
        cards.setContentsMargins(0, 0, 4, 4)
        cards.setSpacing(11)

        module_specs = (
            (
                ModuleKind.RECEIVER,
                "Модуль видеоприёма",
                "WFB-ng • RX1 / RX2 • видеопоток • состояние",
            ),
            (
                ModuleKind.CONTROL,
                "Модуль управления",
                "PAN/TILT • CRSF • INA219 • IMU • аппаратные входы/выходы",
            ),
            (
                ModuleKind.SDR,
                "SDR-модуль",
                "Спектр • сканирование • аналоговое видео • запись IQ",
            ),
        )

        for kind, title, description in module_specs:
            card = ModuleCard(title, description)
            self._module_cards[kind] = card
            cards.addWidget(card)

        cards.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        return page

    def _placeholder_page(
        self,
        title: str,
        subtitle: str,
        eyebrow: str,
    ) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(13)

        root.addWidget(PageHeader(title, subtitle, eyebrow))

        card = QFrame()
        card.setProperty("card", True)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(7)

        state = StatusBadge("ПОДГОТОВЛЕНО", "offline")
        state.setFixedWidth(130)

        headline = QLabel("Раздел готов к подключению функционального слоя")
        headline.setProperty("section", True)

        label = QLabel(
            "Интерфейс уже зарезервирован. Реальные элементы управления появятся "
            "вместе с соответствующим сервисом и только после проверки доступных возможностей."
        )
        label.setProperty("muted", True)
        label.setWordWrap(True)

        card_layout.addWidget(state, 0, Qt.AlignmentFlag.AlignLeft)
        card_layout.addSpacing(5)
        card_layout.addWidget(headline)
        card_layout.addWidget(label)
        card_layout.addStretch(1)

        root.addWidget(card, 1)
        return page

    def toggle_sidebar(self) -> None:
        self._sidebar_user_choice = True
        self._set_sidebar_expanded(not self._sidebar_expanded)

    def _set_sidebar_expanded(self, expanded: bool) -> None:
        self._sidebar_expanded = expanded
        self.sidebar.setFixedWidth(224 if expanded else 70)
        self.brand_label.setText("FIT-LAB" if expanded else "FL")
        self.brand_caption.setVisible(expanded)
        self.nav_caption.setVisible(expanded)
        self.sidebar_storage.setVisible(expanded)
        self.sidebar_status.setVisible(expanded)
        self.collapse_button.setText("‹" if expanded else "›")
        self.collapse_button.setToolTip(
            "Свернуть боковую панель" if expanded else "Развернуть боковую панель"
        )

        for key, title, short_title in self.NAV_ITEMS:
            self._nav_buttons[key].setText(title if expanded else short_title)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "sidebar"):
            return
        if self.width() < 1080 and self._sidebar_expanded and not self._sidebar_user_choice:
            self._set_sidebar_expanded(False)

    def show_page(self, key: str) -> None:
        index = self._page_indexes[key]
        self.pages.setCurrentIndex(index)

        for page_key, button in self._nav_buttons.items():
            selected = page_key == key
            button.setProperty("selected", selected)
            repolish(button)

        sdr_selected = key == "sdr"
        self._set_selected(self.sdr_button, sdr_selected)
        self._set_selected(self.broadcast_button, not sdr_selected)

    def _set_selected(self, button: QPushButton, selected: bool) -> None:
        button.setProperty("selected", selected)
        repolish(button)

    def refresh_status(self) -> None:
        storage = probe_storage(self.config.data_root)
        status = build_master_status(storage, self.station.registry.all())
        self._apply_status(status)

    def _apply_status(self, status: MasterStatus) -> None:
        ready = status.overall == "ГОТОВ"
        overall_kind = "ready" if ready else "warning"

        self.overall_label.set_status(overall_kind, status.overall)
        self.sidebar_status.set_status(
            overall_kind,
            "СТАНЦИЯ ГОТОВА" if ready else "ОГРАНИЧЕННЫЙ РЕЖИМ",
        )

        self.modules_info.setText(f"Модули: {status.connected_modules}")
        self.storage_info.setText(
            f"SSD: {status.storage_free_gib:.1f} GiB"
            if status.storage_ready
            else "SSD: недоступен"
        )

        self.sidebar_storage.setText(
            f"Хранилище\n{status.storage_free_gib:.1f} GiB свободно"
            if status.storage_ready
            else "Хранилище\nнедоступно"
        )

        rows = {row.kind: row for row in status.modules}
        for kind, card in self._module_cards.items():
            row = rows[kind]
            card.update_state(row.state, row.module_id)

        receiver = rows[ModuleKind.RECEIVER]
        if receiver.module_id is None:
            self.video_source_label.setText("Модуль видеоприёма не подключен")
        else:
            self.video_source_label.setText(
                f"{receiver.title} • {receiver.state}"
            )
