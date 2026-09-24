from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class MetricChip(QFrame):
    def __init__(self, label: str, value: str = "—", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        caption = QLabel(label)
        caption.setProperty("muted", True)

        self.value_label = QLabel(value)
        self.value_label.setProperty("metricValue", True)

        layout.addWidget(caption)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class ModuleCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        top = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setProperty("section", True)

        self.state_label = QLabel("Не подключен")
        self.state_label.setProperty("muted", True)

        top.addWidget(title_label)
        top.addStretch(1)
        top.addWidget(self.state_label)

        self.id_label = QLabel("ID: —")
        self.id_label.setProperty("muted", True)
        self.id_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        actions = QHBoxLayout()
        self.service_button = QPushButton("Перезапустить службу")
        self.reboot_button = QPushButton("Перезагрузить")
        self.shutdown_button = QPushButton("Выключить")

        for button in (self.service_button, self.reboot_button, self.shutdown_button):
            button.setEnabled(False)
            actions.addWidget(button)

        actions.addStretch(1)

        root.addLayout(top)
        root.addWidget(self.id_label)
        root.addLayout(actions)

    def update_state(self, state: str, module_id: str | None) -> None:
        self.state_label.setText(state.capitalize())
        self.id_label.setText(f"ID: {module_id or '—'}")

        connected = module_id is not None and state not in {"не подключен", "нет связи"}
        for button in (self.service_button, self.reboot_button, self.shutdown_button):
            button.setEnabled(connected)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setProperty("title", True)
        layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setProperty("muted", True)
            subtitle_label.setWordWrap(True)
            layout.addWidget(subtitle_label)
