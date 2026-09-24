from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QFrame,
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
from master.ui.widgets import MetricChip, ModuleCard, PageHeader
from shared.config import StationConfig
from shared.models import ModuleKind
from shared.storage import ensure_directories, probe_storage


class MainWindow(QMainWindow):
    NAV_ITEMS = (
        ("video", "Видеоприём"),
        ("modules", "Модули"),
        ("cameras", "Камеры"),
        ("radio", "Радиосвязь"),
        ("recording", "Запись"),
        ("streaming", "Трансляция"),
        ("guidance", "Наведение"),
        ("diagnostics", "Диагностика"),
        ("settings", "Настройки"),
        ("service", "Сервис"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FIT-LAB Station")
        self.resize(1440, 900)
        self.setMinimumSize(960, 620)

        self.config = StationConfig.load()
        ensure_directories(self.config.data_root, self.config.required_directories())
        self.station = StationCore()

        self._sidebar_expanded = True
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
        content.setContentsMargins(22, 16, 22, 18)
        content.setSpacing(14)

        content.addLayout(self._build_topbar())

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
        sidebar.setFixedWidth(220)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self.brand_label = QLabel("FIT-LAB")
        self.brand_label.setObjectName("brand")

        collapse = QPushButton("☰")
        collapse.setFixedSize(38, 34)
        collapse.clicked.connect(self.toggle_sidebar)

        header.addWidget(self.brand_label)
        header.addStretch(1)
        header.addWidget(collapse)
        layout.addLayout(header)
        layout.addSpacing(8)

        for key, title in self.NAV_ITEMS:
            button = QPushButton(title)
            button.setProperty("nav", True)
            button.clicked.connect(lambda checked=False, page=key: self.show_page(page))
            self._nav_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        self.sidebar_storage = QLabel("Хранилище: проверка…")
        self.sidebar_storage.setProperty("muted", True)
        self.sidebar_storage.setWordWrap(True)
        layout.addWidget(self.sidebar_storage)

        return sidebar

    def _build_topbar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)

        self.broadcast_button = QPushButton("Broadcast")
        self.broadcast_button.setProperty("mode", True)
        self.broadcast_button.clicked.connect(lambda: self.show_page("video"))

        self.sdr_button = QPushButton("SDR")
        self.sdr_button.setProperty("mode", True)
        self.sdr_button.clicked.connect(lambda: self.show_page("sdr"))

        self.overall_label = QLabel("ПРОВЕРКА")
        self.overall_label.setProperty("pill", True)

        layout.addWidget(self.broadcast_button)
        layout.addWidget(self.sdr_button)
        layout.addStretch(1)
        layout.addWidget(self.overall_label)

        return layout

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
            ),
        )
        self._add_page(
            "radio",
            self._placeholder_page(
                "Радиосвязь",
                "Broadcast, RX1/RX2 и согласованные параметры радиолинии.",
            ),
        )
        self._add_page(
            "recording",
            self._placeholder_page(
                "Запись",
                "Исходный видеопоток, сегменты, состояние накопителя и архив.",
            ),
        )
        self._add_page(
            "streaming",
            self._placeholder_page(
                "Трансляция",
                "Локальная трансляция для телефона, планшета или другого клиента.",
            ),
        )
        self._add_page(
            "guidance",
            self._placeholder_page(
                "Наведение",
                "PAN/TILT, центр, пределы, скорость и пресеты после подключения Модуля управления.",
            ),
        )
        self._add_page(
            "diagnostics",
            self._placeholder_page(
                "Диагностика",
                "Состояние модулей, радио, декодера, температур, накопителя и ресурсов.",
            ),
        )
        self._add_page(
            "settings",
            self._placeholder_page(
                "Настройки",
                "Профили станции, интерфейс, хранение и безопасные пользовательские параметры.",
            ),
        )
        self._add_page(
            "service",
            self._placeholder_page(
                "Сервис",
                "Технический журнал, версии, обслуживание модулей и расширенная диагностика.",
            ),
        )
        self._add_page(
            "sdr",
            self._placeholder_page(
                "SDR",
                "Спектр, сканирование, аналоговое видео и запись IQ. Сейчас подготовлен каркас.",
            ),
        )

    def _video_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        root.addWidget(
            PageHeader(
                "Видеоприём",
                "Камерный OSD сохраняется без изменений. Данные станции размещаются отдельно от изображения.",
            )
        )

        video = QFrame()
        video.setProperty("video", True)
        video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        video_layout = QVBoxLayout(video)
        video_layout.setContentsMargins(24, 24, 24, 24)

        placeholder = QLabel("Видеосигнал не подключен")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setProperty("muted", True)
        placeholder.setStyleSheet("font-size: 18px;")
        video_layout.addWidget(placeholder)

        root.addWidget(video, 1)

        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        for label, value in (
            ("RX1", "—"),
            ("RX2", "—"),
            ("FEC", "—"),
            ("Потери", "—"),
            ("REC", "Остановлена"),
            ("Видеолинк", "Нет данных"),
        ):
            metrics.addWidget(MetricChip(label, value))

        root.addLayout(metrics)
        return page

    def _modules_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        root.addWidget(
            PageHeader(
                "Модули",
                "Независимые узлы станции. Перезапуск одного узла не должен останавливать остальные.",
            )
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        content = QWidget()
        cards = QVBoxLayout(content)
        cards.setContentsMargins(0, 0, 4, 4)
        cards.setSpacing(12)

        for kind, title in (
            (ModuleKind.RECEIVER, "Модуль видеоприёма"),
            (ModuleKind.CONTROL, "Модуль управления"),
            (ModuleKind.SDR, "SDR-модуль"),
        ):
            card = ModuleCard(title)
            self._module_cards[kind] = card
            cards.addWidget(card)

        cards.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        return page

    def _placeholder_page(self, title: str, subtitle: str) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        root.addWidget(PageHeader(title, subtitle))

        card = QFrame()
        card.setProperty("card", True)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 22, 22, 22)

        label = QLabel("Раздел подготовлен к подключению функционального модуля.")
        label.setProperty("muted", True)
        label.setWordWrap(True)

        card_layout.addWidget(label)
        card_layout.addStretch(1)
        root.addWidget(card, 1)

        return page

    def toggle_sidebar(self) -> None:
        self._sidebar_expanded = not self._sidebar_expanded
        self.sidebar.setFixedWidth(220 if self._sidebar_expanded else 72)
        self.brand_label.setText("FIT-LAB" if self._sidebar_expanded else "FL")

        for key, title in self.NAV_ITEMS:
            self._nav_buttons[key].setText(title if self._sidebar_expanded else "•")

        self.sidebar_storage.setVisible(self._sidebar_expanded)

    def show_page(self, key: str) -> None:
        index = self._page_indexes[key]
        self.pages.setCurrentIndex(index)

        for page_key, button in self._nav_buttons.items():
            selected = page_key == key
            button.setProperty("selected", selected)
            button.style().unpolish(button)
            button.style().polish(button)

        sdr_selected = key == "sdr"
        self._set_selected(self.sdr_button, sdr_selected)
        self._set_selected(self.broadcast_button, not sdr_selected)

    def _set_selected(self, button: QPushButton, selected: bool) -> None:
        button.setProperty("selected", selected)
        button.style().unpolish(button)
        button.style().polish(button)

    def refresh_status(self) -> None:
        storage = probe_storage(self.config.data_root)
        status = build_master_status(storage, self.station.registry.all())
        self._apply_status(status)

    def _apply_status(self, status: MasterStatus) -> None:
        self.overall_label.setText(status.overall)
        self.sidebar_storage.setText(
            f"Хранилище\n{status.storage_free_gib:.1f} GiB свободно"
            if status.storage_ready
            else "Хранилище недоступно"
        )

        rows = {row.kind: row for row in status.modules}
        for kind, card in self._module_cards.items():
            row = rows[kind]
            card.update_state(row.state, row.module_id)
