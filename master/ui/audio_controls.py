"""Touch-sized playback controls which fade away above the video."""
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSlider, QToolButton, QLabel, QGraphicsOpacityEffect, QStyle, QStyleOptionSlider
from master.ui.brand import ui_icon


class VolumeSlider(QSlider):
    def _set_at(self, position):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, option,
                                             QStyle.SubControl.SC_SliderHandle, self)
        span = max(1, self.width() - handle.width())
        value = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
            round(position.x() - handle.width()/2), span, option.upsideDown)
        self.setValue(value)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self._set_at(event.position())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self._set_at(event.position())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self._set_at(event.position())
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class AudioControls(QFrame):
    changed = Signal(int, bool)

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('cameraAudioOverlay')
        self.setStyleSheet('''QFrame#cameraAudioOverlay { background: rgba(16,19,22,240); border: 1px solid #806444; border-radius: 16px; }
            QToolButton { background: transparent; border: 0; color: #ffd08b; }
            QSlider::groove:horizontal { height: 6px; background: #555551; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #ffc16c; border-radius: 2px; }
            QSlider::handle:horizontal { width: 24px; margin: -9px 0; background: #ffce88; border-radius: 12px; }
            QLabel { color: #f7e6cc; background: transparent; border: 0; }''')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 12, 4)
        self.mute = QToolButton(self)
        self.mute.setCheckable(True)
        self.mute.setFixedSize(44, 44)
        self.slider = VolumeSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, 100)
        self.slider.setValue(35)
        self.slider.setMinimumWidth(100)
        self.slider.setFixedHeight(48)
        self.slider.setAccessibleName('Громкость камеры')
        self.value = QLabel('35%', self)
        self.value.setFixedWidth(48)
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.mute)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.value)
        self.resize(320, 60)
        self.setFixedHeight(60)
        self.opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity)
        self.fade = QPropertyAnimation(self.opacity, b'opacity', self)
        self.fade.setDuration(280)
        self.fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.fade.finished.connect(self._faded)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._dismiss)
        self.mute.toggled.connect(self._changed)
        self.slider.valueChanged.connect(self._changed)
        self.slider.sliderPressed.connect(self.reveal)
        self.slider.sliderReleased.connect(self.reveal)
        self.set_values(35, False)
        self.hide()

    def set_values(self, volume, muted):
        self.slider.blockSignals(True)
        self.mute.blockSignals(True)
        self.slider.setValue(volume)
        self.mute.setChecked(muted)
        self.slider.blockSignals(False)
        self.mute.blockSignals(False)
        self.value.setText(f'{volume}%')
        self.mute.setIcon(ui_icon('volume-off' if muted else 'volume'))
        text = 'Включить звук камеры' if muted else 'Выключить звук камеры'
        self.mute.setAccessibleName(text)
        self.mute.setToolTip(text)

    def _changed(self, *_):
        volume, muted = self.slider.value(), self.mute.isChecked()
        self.set_values(volume, muted)
        self.reveal()
        self.changed.emit(volume, muted)

    def reveal(self):
        self.fade.stop()
        self.opacity.setOpacity(1)
        self.show()
        self.raise_()
        self.timer.start(3200)

    def _dismiss(self):
        if self.slider.isSliderDown():
            self.timer.start(1000)
            return
        self.fade.setStartValue(1.)
        self.fade.setEndValue(0.)
        self.fade.start()

    def _faded(self):
        if self.opacity.opacity() < .01:
            self.hide()

    def enterEvent(self, event):
        self.reveal()
        super().enterEvent(event)
