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


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class StatusBadge(QLabel):
    def __init__(
        self,
        text: str,
        status: str = "offline",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status(status)

    def set_status(self, status: str, text: str | None = None) -> None:
        if text is not None:
            self.setText(text)
        self.setProperty("status", status)
        repolish(self)


class MetricChip(QFrame):
    def __init__(
        self,
        label: str,
        value: str = "—",
        hint: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setMinimumWidth(118)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(3)

        caption = QLabel(label.upper())
        caption.setProperty("metricCaption", True)

        self.value_label = QLabel(value)
        self.value_label.setProperty("metricValue", True)

        layout.addWidget(caption)
        layout.addWidget(self.value_label)

        if hint:
            hint_label = QLabel(hint)
            hint_label.setProperty("muted", True)
            hint_label.setStyleSheet("font-size: 11px;")
            layout.addWidget(hint_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class ModuleCard(QFrame):
    def __init__(
        self,
        title: str,
        description: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(11)

        top = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(3)

        title_label = QLabel(title)
        title_label.setProperty("section", True)

        description_label = QLabel(description)
        description_label.setProperty("muted", True)

        title_box.addWidget(title_label)
        title_box.addWidget(description_label)

        self.state_label = StatusBadge("НЕ ПОДКЛЮЧЕН", "offline")

        top.addLayout(title_box)
        top.addStretch(1)
        top.addWidget(self.state_label)

        detail_row = QHBoxLayout()
        detail_row.setSpacing(10)

        self.id_label = QLabel("ID: —")
        self.id_label.setProperty("muted", True)
        self.id_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.trust_label = QLabel("Доверие: не установлено")
        self.trust_label.setProperty("muted", True)

        detail_row.addWidget(self.id_label)
        detail_row.addWidget(self.trust_label)
        detail_row.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self.service_button = QPushButton("Перезапустить службу")
        self.service_button.setProperty("role", "ghost")
        self.service_button.setToolTip("Станет доступно после доверенной привязки модуля.")

        self.reboot_button = QPushButton("Перезагрузить модуль")
        self.reboot_button.setProperty("role", "ghost")
        self.reboot_button.setToolTip("Станет доступно после доверенной привязки модуля.")

        self.shutdown_button = QPushButton("Выключить")
        self.shutdown_button.setProperty("role", "danger")
        self.shutdown_button.setToolTip("Станет доступно после доверенной привязки модуля.")

        for button in (self.service_button, self.reboot_button, self.shutdown_button):
            button.setEnabled(False)
            actions.addWidget(button)

        actions.addStretch(1)

        root.addLayout(top)
        root.addLayout(detail_row)
        root.addLayout(actions)

    def update_state(self, state: str, module_id: str | None) -> None:
        self.id_label.setText(f"ID: {module_id or '—'}")

        status_kind = self._status_kind(state)
        self.state_label.set_status(status_kind, state.upper())

        # Destructive controls remain disabled until authenticated pairing exists.
        for button in (self.service_button, self.reboot_button, self.shutdown_button):
            button.setEnabled(False)

    @staticmethod
    def _status_kind(state: str) -> str:
        if state in {"готов", "активен"}:
            return "ready"
        if state in {"предупреждение", "загрузка", "проверка", "переподключение"}:
            return "warning"
        if state in {"ошибка", "несовместим"}:
            return "error"
        return "offline"


class PageHeader(QWidget):
    def __init__(
        self,
        title: str,
        subtitle: str = "",
        eyebrow: str = "FIT-LAB STATION",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        eyebrow_label = QLabel(eyebrow)
        eyebrow_label.setProperty("eyebrow", True)
        layout.addWidget(eyebrow_label)

        title_label = QLabel(title)
        title_label.setProperty("title", True)
        layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setProperty("muted", True)
            subtitle_label.setWordWrap(True)
            layout.addWidget(subtitle_label)
