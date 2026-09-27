"""Native WFB service panel, populated from the authenticated camera."""
from PySide6.QtCore import Signal, QSize
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
                              QDialog, QScrollArea, QGridLayout)
from master.ui.widgets import MotionButton
from master.ui.brand import ui_icon
from shared.radio_settings import frequency, runcam_power_reference
from master.ui.camera_settings import NumberEdit


from master.ui.choices import ChoicePicker


class FrequencyPicker(ChoicePicker):
    def __init__(self):
        super().__init__('Частота передатчика')


class RadioSettings(QWidget):
    refreshRequested = Signal()
    restartRequested = Signal()
    settingsRequested = Signal(dict)

    def __init__(self, compact=False):
        super().__init__()
        self.compact = compact
        self.snapshot = None
        self.busy = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        if compact:
            root.setSpacing(4)
        self.status = QLabel("Подключите камеру для управления")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        form = QFormLayout()
        if compact:
            form.setVerticalSpacing(4)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows if compact else QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.channel = FrequencyPicker()
        self.channel.setMinimumWidth(220)
        if compact:
            self.channel.setFixedHeight(44)
        self.channel.currentIndexChanged.connect(self.update_buttons)
        self.power = ChoicePicker('Мощность передатчика')
        self.power.setMinimumHeight(48)
        self.power.currentIndexChanged.connect(self.update_buttons)
        self.current = QLabel("—")
        self.current.setWordWrap(True)
        self.saved_power = QLabel('—')
        if compact:
            self.current.setStyleSheet('color: #ffd08a; font-size: 13px; padding: 4px 0;')
            root.addWidget(self.current)
            self.current.hide()
        else:
            form.addRow("Фактически", self.current)
        form.addRow("Частота", self.channel)
        form.addRow("Мощность", self.power)
        if not compact:
            form.addRow("Сохранено в камере", self.saved_power)
        root.addLayout(form)
        row = QHBoxLayout()
        self.refresh = MotionButton("Обновить")
        self.refresh.setIcon(ui_icon('refresh'))
        self.refresh.clicked.connect(self.refreshRequested)
        self.restart = MotionButton("Перезапустить радиослужбу")
        self.restart.setIcon(ui_icon("radio"))
        self.restart.clicked.connect(self.restartRequested)
        self.apply = MotionButton("Применить")
        self.apply.setProperty("role", "primary")
        self.apply.clicked.connect(lambda: self.settingsRequested.emit(self.changes()))
        if compact:
            for widget in (self.refresh, self.restart):
                widget.setAccessibleName(widget.text())
                widget.setToolTip(widget.text())
                widget.setText('')
                widget.setProperty('iconOnly', True)
                widget.setFixedSize(48, 48)
                widget.setIconSize(QSize(22, 22))
        for widget in (self.refresh, self.restart, self.apply):
            row.addWidget(widget)
        root.addLayout(row)
        self.update_buttons()

    def load(self, data):
        self.snapshot = data
        self.busy = False
        self.channel.blockSignals(True)
        self.channel.clear()
        configured = data.get("config", {})
        for channel in data.get("channels", []):
            self.channel.addItem(f"{frequency(channel)} МГц · канал {channel}", channel)
        self.channel.setCurrentIndex(self.channel.findData(configured.get("channel")))
        self.channel.blockSignals(False)
        live = data.get("live", {})
        actual = f"{live['frequency_mhz']} МГц · {live['width']} МГц" if live.get("frequency_mhz") else "Нет подтверждения драйвера"
        if "driver_dbm" in live:
            actual += f" · драйвер {live['driver_dbm']:g} dBm"
        if data and not data.get('transmitter_running'):
            actual = 'Передатчик остановлен · ' + actual
        self.current.setText(actual if data else '—')
        if self.compact:
            self.current.setVisible(bool(data))
        scale = data.get("power_scale")
        self.saved_power.setText(f"{configured['power'] * scale:g} dBm" if scale and 'power' in configured else '—')
        self.populate_power(reset=True)
        self.status.setText("Подключите камеру для управления" if not data else
                            " · ".join(data.get("notices", [])) or ("Передатчик работает" if data.get("transmitter_running") else "Передатчик остановлен"))
        if self.compact:
            # The actual-value row already reports transmitter state. Keep
            # warnings visible, without repeating the normal state above it.
            self.status.setVisible(not data or bool(data.get('notices')))
        self.update_buttons()

    def populate_power(self, reset=False):
        from shared.radio_settings import power_choices
        snapshot = self.snapshot or {}
        channel = self.channel.currentData()
        items = power_choices(snapshot, channel)
        selected = (snapshot.get('config', {}).get('power', 0) * (snapshot.get('power_scale') or 0)
                    if reset else self.power.currentData())
        if not reset and self.power.items == items:
            return
        self.power.blockSignals(True)
        self.power.clear()
        for title, value in items:
            self.power.addItem(title, value)
        self.power.setCurrentIndex(self.power.findData(selected))
        self.power.blockSignals(False)

    def changes(self):
        snapshot = self.snapshot or {}
        config = snapshot.get("config", {})
        changes = {}
        channel = self.channel.currentData()
        if channel is not None and channel != config.get("channel"):
            changes["channel"] = channel
        if snapshot.get("power_scale") and self.power.currentData() is not None:
            value = self.power.currentData()
            if value != config.get("power", 0) * snapshot["power_scale"]:
                from shared.radio_settings import power_value
                power_value(value, snapshot, channel)
                changes["power"] = value
        return changes

    def set_busy(self, busy):
        self.busy = busy
        self.update_buttons()

    def update_buttons(self, *_):
        snapshot = self.snapshot or {}
        self.refresh.setEnabled(not self.busy)
        ready = bool(snapshot.get("restart_ready")) and not self.busy
        self.restart.setEnabled(ready)
        self.channel.setEnabled(ready and not snapshot.get("adaptive"))
        channel = self.channel.currentData()
        maximum = snapshot.get("power_limits", {}).get(channel, snapshot.get("power_limits", {}).get(str(channel)))
        self.populate_power()
        self.power.setEnabled(ready and not snapshot.get("adaptive") and snapshot.get("power_scale") == .5 and maximum is not None)
        try:
            self.apply.setEnabled(ready and not snapshot.get("adaptive") and bool(self.changes()))
        except (ValueError, TypeError):
            self.apply.setEnabled(False)
