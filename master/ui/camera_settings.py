"""Native touch-friendly editor populated only by the connected camera's schema."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QLineEdit, QCheckBox, QPushButton, QFormLayout, QScrollArea, QStackedWidget,
    QDialog, QDialogButtonBox, QPlainTextEdit, QListWidget, QListWidgetItem)

from shared.camera_settings import GROUPS, field_label, fields, make_patch
from master.ui.widgets import MotionButton
from master.ui.brand import ui_icon
from master.ui.choices import ChoicePicker
from shared.camera_presets import resolution_choices, video_presets, link_video_profiles


class NumberEdit(QWidget):
    def __init__(self, value, spec):
        super().__init__()
        self.spec = spec
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.minus, self.plus = MotionButton("−"), MotionButton("+")
        self.input = QLineEdit("" if value is None else str(value))
        self.input.setPlaceholderText("Авто")
        self.input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.textChanged = self.input.textChanged
        for button in (self.minus, self.plus):
            button.setFixedSize(48, 48)
            button.setProperty("stepper", True)
        self.minus.setAccessibleName("Уменьшить значение")
        self.plus.setAccessibleName("Увеличить значение")
        self.minus.clicked.connect(lambda: self.step(-1))
        self.plus.clicked.connect(lambda: self.step(1))
        row.addWidget(self.minus)
        row.addWidget(self.input, 1)
        row.addWidget(self.plus)

    def text(self):
        return self.input.text()

    def step(self, direction):
        try:
            value = float(self.text())
        except ValueError:
            return
        delta = self.spec.get("multipleOf", 1 if self.spec["type"] == "integer" else .1)
        value += direction * delta
        value = max(self.spec.get("minimum", value), min(self.spec.get("maximum", value), value))
        self.input.setText(str(int(value)) if self.spec["type"] == "integer" else f"{value:g}")


class BitrateEdit(NumberEdit):
    """Camera-validated presets with an unchanged manual kbit/s input."""
    def __init__(self, value, spec):
        super().__init__(value, spec)
        from shared.camera_settings import validate
        self.presets = ChoicePicker("Битрейт")
        self.presets.setMinimumHeight(48)
        self.presets.addItem("Вручную", None)
        for rate in (1024, 2048, 3072, 4096, 6144, 8192, 12288, 16384):
            try:
                validate(spec, rate)
            except ValueError:
                continue
            self.presets.addItem(f"{rate / 1000:g} Мбит/с", rate)
        self.layout().insertWidget(0, self.presets, 1)
        self.presets.currentIndexChanged.connect(self.choose)
        self.textChanged.connect(self.sync)
        self.sync()

    def choose(self, *_):
        value = self.presets.currentData()
        if value is not None:
            self.input.setText(str(value))
        else:
            self.input.setFocus()

    def sync(self, *_):
        try:
            index = self.presets.findData(int(self.text()))
        except ValueError:
            index = -1
        self.presets.blockSignals(True)
        self.presets.setCurrentIndex(max(0, index))
        self.presets.blockSignals(False)


class CameraSettings(QWidget):
    applyRequested = Signal(dict)
    refreshRequested = Signal()
    restoreRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.schema, self.config, self.controls = {}, {}, {}
        self.busy = False
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        self.message = QLabel("Подключите камеру для загрузки настроек")
        self.message.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.message, 1)
        self.group = QComboBox()
        self.group.setMinimumWidth(160)
        row.addWidget(self.group, 1)
        self.refresh = MotionButton("")
        self.refresh.setProperty("iconOnly", True)
        self.refresh.setFixedSize(52, 48)
        self.refresh.setToolTip("Прочитать настройки камеры")
        self.refresh.setAccessibleName("Прочитать настройки камеры")
        self.refresh.setIcon(ui_icon("camera"))
        self.refresh.clicked.connect(self.refreshRequested)
        row.addWidget(self.refresh)
        root.addLayout(row)
        self.link_profiles = ChoicePicker('Профиль видео')
        self.link_profiles.setMinimumHeight(48)
        self.link_profiles.currentIndexChanged.connect(self.choose_link_profile)
        self.presets = ChoicePicker('Видеорежим')
        self.presets.setMinimumHeight(48)
        self.presets.currentIndexChanged.connect(self.choose_preset)
        body = QHBoxLayout()
        body.setSpacing(16)
        self.sections = QListWidget()
        self.sections.setObjectName("cameraSections")
        self.sections.setFixedWidth(180)
        self.sections.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sections.currentRowChanged.connect(self.group.setCurrentIndex)
        self.group.currentIndexChanged.connect(self.sections.setCurrentRow)
        body.addWidget(self.sections)
        self.stack = QStackedWidget()
        self.stack.setMinimumHeight(60)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)
        self.group.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.group.currentIndexChanged.connect(lambda _: self.presets.setVisible(
            bool(self.presets.items) and self.group.currentData() == 'video0'))
        bottom = QHBoxLayout()
        self.count = QLabel("")
        bottom.addWidget(self.count, 1)
        self.restore = MotionButton('Откат')
        self.restore.setToolTip('Восстановить сохранённые параметры этой камеры')
        self.restore.clicked.connect(self.restoreRequested)
        bottom.addWidget(self.restore)
        self.defaults = MotionButton('Сброс раздела')
        self.defaults.clicked.connect(self.review_defaults)
        bottom.addWidget(self.defaults)
        self.apply = MotionButton("Применить")
        self.apply.setProperty("role", "primary")
        self.apply.clicked.connect(self.review)
        bottom.addWidget(self.apply)
        root.addLayout(bottom)
        self.set_busy(False)

    def load(self, settings):
        if (self.controls and self.schema == settings.get('schema', {})
                and self.config == settings.get('config', {})):
            self.set_busy(False)
            return
        previous_group = self.group.currentText()
        positions = {self.group.itemData(i): self.stack.widget(i).verticalScrollBar().value()
                     for i in range(self.stack.count())}
        self.schema = settings.get("schema", {})
        self.config = settings.get("config", {})
        self.link_profiles.blockSignals(True)
        self.link_profiles.clear()
        for label, values in link_video_profiles(self.schema, self.config):
            self.link_profiles.addItem(label, values)
        self.link_profiles.blockSignals(False)
        self.presets.blockSignals(True)
        self.presets.clear()
        for label, values in video_presets(self.schema, self.config):
            self.presets.addItem(label, values)
        current_video = self.config.get('video0', {})
        self.presets.setCurrentIndex(self.presets.findData({
            'video0.size': current_video.get('size'), 'video0.fps': current_video.get('fps')}))
        self.presets.blockSignals(False)
        self.controls.clear()
        # Profiles belong to the scrollable video section, not fixed toolbars
        # that consume most of a 600-pixel touch display.
        self.link_profiles.setParent(self)
        self.presets.setParent(self)
        self.group.clear()
        self.sections.clear()
        while self.stack.count():
            old = self.stack.widget(0)
            self.stack.removeWidget(old)
            old.deleteLater()
        available = fields(self.schema, self.config)
        for group, name in GROUPS.items():
            subset = {p: s for p, s in available.items() if p.split(".")[0] == group}
            if not subset:
                continue
            content = QWidget()
            form = QFormLayout(content)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            form.setSpacing(12)
            if group == 'video0':
                form.addRow('Профиль', self.link_profiles)
                form.addRow('Видеорежим', self.presets)
            preferred = ("enabled", "codec", "size", "fps", "bitrate", "gopSize", "profile", "rcMode")
            for path, spec in sorted(subset.items(), key=lambda item: (preferred.index(item[0].split('.')[-1]) if item[0].split('.')[-1] in preferred else 99, item[0])):
                value = spec["value"]
                if spec["type"] == "boolean":
                    widget = QCheckBox()
                    widget.setMinimumHeight(46)
                    widget.setChecked(value is True)
                    getter = widget.isChecked
                    widget.toggled.connect(self.changed)
                elif spec.get("enum") or path in ('video0.size', 'video1.size'):
                    widget = ChoicePicker(field_label(path, spec))
                    choices = resolution_choices(spec) if path.endswith('.size') else [(str(item), item) for item in spec['enum']]
                    for label, item in choices:
                        if path.endswith('.codec'):
                            label = {'h264': 'H.264', 'h265': 'H.265'}.get(item, label)
                        widget.addItem(label, item)
                    widget.setCurrentIndex(widget.findData(value))
                    getter = widget.currentData
                    widget.currentIndexChanged.connect(self.changed)
                else:
                    number_editor = BitrateEdit if path in ('video0.bitrate', 'video1.bitrate') else NumberEdit
                    widget = number_editor(value, spec) if spec["type"] in ("integer", "number") else QLineEdit("" if value is None else str(value))
                    if spec["type"] == "integer":
                        getter = lambda w=widget: int(w.text())
                    elif spec["type"] == "number":
                        getter = lambda w=widget: float(w.text())
                    else:
                        getter = widget.text
                    widget.textChanged.connect(self.changed)
                caption = field_label(path, spec)
                widget.setAccessibleName(str(caption))
                details = [path]
                if "minimum" in spec or "maximum" in spec:
                    details.append(f"{spec.get('minimum', '…')} — {spec.get('maximum', '…')}")
                widget.setToolTip(" · ".join(details))
                widget.setEnabled(not spec.get("readOnly"))
                raw = widget.isChecked if isinstance(widget, QCheckBox) else widget.currentData if isinstance(widget, (QComboBox, ChoicePicker)) else widget.text
                # Firmware may report unset/default values outside its own
                # declared enum/range. Never transform these on load.
                self.controls[path] = (widget, getter, {**spec, "initial_display": raw(), "raw": raw})
                caption_box = QWidget()
                caption_layout = QVBoxLayout(caption_box)
                caption_layout.setContentsMargins(0, 3, 12, 3)
                caption_layout.setSpacing(4)
                caption_label = QLabel(str(caption))
                caption_label.setTextFormat(Qt.TextFormat.PlainText)
                caption_label.setWordWrap(True)
                caption_layout.addWidget(caption_label)
                if len(details) > 1:
                    hint = QLabel(details[1])
                    hint.setProperty("muted", True)
                    hint.setStyleSheet("font-size: 11px;")
                    caption_layout.addWidget(hint)
                form.addRow(caption_box, widget)
                if path in ("video0.fps", "video1.fps") and not spec.get("readOnly"):
                    from shared.camera_settings import validate
                    presets = QWidget()
                    options = QHBoxLayout(presets)
                    options.setContentsMargins(0, 0, 0, 0)
                    for rate in (30, 60, 120):
                        try:
                            validate(spec, rate)
                        except ValueError:
                            continue
                        choice = MotionButton(f"{rate} FPS")
                        choice.setMinimumHeight(48)
                        choice.setAccessibleName(f"Камера · {rate} FPS")
                        def choose(_=False, w=widget, fps=rate):
                            if isinstance(w, (QComboBox, ChoicePicker)):
                                w.setCurrentIndex(w.findData(fps))
                            else:
                                w.input.setText(str(fps))
                        choice.clicked.connect(choose)
                        options.addWidget(choice)
                    if options.count():
                        form.addRow("", presets)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(content)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.verticalScrollBar().setSingleStep(36)
            from master.ui.scrolling import configure_touch_scrolling
            configure_touch_scrolling(scroll, pointer_drag=True)
            self.stack.addWidget(scroll)
            if group in positions:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, lambda s=scroll, pos=positions[group]: s.verticalScrollBar().setValue(pos))
            symbol = {"video0": "video", "video1": "video", "isp": "lens", "image": "image",
                      "fpv": "radio", "osd": "osd", "audio": "audio", "jpeg": "image"}.get(group, "settings")
            self.group.addItem(ui_icon(symbol), name, group)
            self.sections.addItem(QListWidgetItem(ui_icon(symbol), name))
        self.message.setText(f"{len(available)} параметров · прочитано с камеры" if available else
                             "Подключите камеру, чтобы получить настройки" if not settings else
                             "Эта прошивка не предоставляет список настроек. Доступны сводка и веб-панель.")
        self.set_busy(False)
        if self.group.findText(previous_group) >= 0:
            self.group.setCurrentIndex(self.group.findText(previous_group))
        self._responsive()
        parent = self.window()
        if hasattr(parent, "touch"):
            parent.touch.attach(self)

    def changes(self):
        return make_patch(self.schema, self.config, {p: getter() for p, (_, getter, spec) in self.controls.items()
                                                    if not spec.get("readOnly") and spec["raw"]() != spec["initial_display"]})

    def choose_preset(self, *_):
        for path, value in (self.presets.currentData() or {}).items():
            widget = self.controls[path][0]
            if isinstance(widget, (ChoicePicker, QComboBox)):
                widget.setCurrentIndex(widget.findData(value))
            elif isinstance(widget, NumberEdit):
                widget.input.setText(str(value))
        self.group.setCurrentIndex(0)
        self.changed()

    def choose_link_profile(self, *_):
        for path, value in (self.link_profiles.currentData() or {}).items():
            widget = self.controls[path][0]
            if isinstance(widget, (ChoicePicker, QComboBox)):
                widget.setCurrentIndex(widget.findData(value))
            elif isinstance(widget, NumberEdit):
                widget.input.setText(str(value))
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value))
        self.group.setCurrentIndex(0)
        self.changed()

    def changed(self, *_):
        try:
            count = len(self.changes())
            self.count.setText(f"Изменений: {count}" if count else "")
            self.apply.setEnabled(count > 0 and not self.busy)
        except (ValueError, TypeError):
            self.count.setText("Проверьте значения")
            self.apply.setEnabled(False)

    def set_busy(self, busy):
        self.busy = busy
        self.link_profiles.setEnabled(not busy)
        self.link_profiles.setVisible(bool(self.link_profiles.items))
        self.stack.setEnabled(not busy)
        self.presets.setEnabled(not busy and bool(self.presets.items))
        self.presets.setVisible(bool(self.presets.items) and self.group.currentData() == 'video0')
        self.group.setEnabled(not busy and bool(self.controls))
        self.sections.setEnabled(not busy and bool(self.controls))
        self.refresh.setEnabled(not busy and bool(self.controls))
        self.stack.setVisible(bool(self.controls))
        self.group.setVisible(bool(self.controls))
        self.sections.setVisible(bool(self.controls))
        self.refresh.setVisible(bool(self.controls))
        self.apply.setVisible(bool(self.controls))
        self.restore.setVisible(bool(self.controls))
        self.restore.setEnabled(not busy and bool(self.controls))
        self.defaults.setVisible(bool(self.controls))
        self.defaults.setEnabled(not busy and bool(self.controls))
        self.changed()
        self._responsive()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "sections"):
            self._responsive()

    def _responsive(self):
        wide = self.width() >= 850
        self.message.setVisible(wide or not bool(self.controls))
        self.sections.setVisible(wide and bool(self.controls))
        self.group.setVisible(not wide and bool(self.controls))

    def review(self):
        changes = self.changes()
        self.review_changes(changes)

    def review_defaults(self):
        from master.camera_restore import default_patch
        try:
            changes = default_patch(self.schema, self.config, self.group.currentData())
        except (ValueError, TypeError):
            self.count.setText('Прошивка не указала допустимые значения сброса')
            return
        if not changes:
            self.count.setText('Нет доступных изменений по умолчанию')
            return
        self.review_changes(changes, 'Сброс параметров раздела')

    def review_changes(self, changes, title='Применить настройки камеры'):
        if not changes:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(500, 360)
        box = QVBoxLayout(dialog)
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText("\n".join(f"{GROUPS[path.split('.')[0]]} · {field_label(path)}: {self.controls[path][2]['value']} → {value}" for path, value in changes.items()))
        box.addWidget(preview)
        hint = QLabel("При изменении видеорежима изображение может временно пропасть.")
        hint.setWordWrap(True)
        box.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("Применить")
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(dialog.accept)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        parent = self.window()
        if hasattr(parent, "touch"):
            parent.touch.attach(dialog)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.applyRequested.emit(changes)
