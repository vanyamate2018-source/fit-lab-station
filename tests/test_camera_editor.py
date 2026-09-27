"""Exercise the actual editor and its review dialog without camera transport."""
import pytest
import os
import subprocess
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit
from master.ui.camera_settings import CameraSettings


def exercise_editor(case):
    app = QApplication([])
    panel = CameraSettings()
    panel.load({'schema': {'properties': {'video0': {'properties': {
        'size': {'type': 'string'}, 'fps': {'type': 'integer', 'minimum': 1, 'maximum': 120, 'default': 30}}}}},
        'config': {'video0': {'size': '1280x720', 'fps': 60}}})
    if case == 'load':
        assert panel.presets.currentText() == '720p · 60 FPS'
        assert panel.changes() == {}
        assert not panel.apply.isEnabled()
        return
    received, preview = [], []
    panel.applyRequested.connect(received.append)
    if case == 'review':
        panel.controls['video0.fps'][0].input.setText('30')
    def accept_review():
        for item in app.topLevelWidgets():
            if isinstance(item, QDialog) and item.windowTitle() in ('Применить настройки камеры', 'Сброс параметров раздела'):
                preview.append(item.findChild(QPlainTextEdit).toPlainText())
                item.accept()
    QTimer.singleShot(50, accept_review)
    (panel.apply if case == 'review' else panel.defaults).click()
    assert preview == ['Основное видео · Частота кадров: 60 → 30']
    assert received == [{'video0.fps': 30}]


@pytest.mark.parametrize('case', ['load', 'review', 'defaults'])
def test_editor(case):
    # Other transport tests own a QCoreApplication. Qt cannot promote that
    # singleton to QApplication; use a separate process for widget tests.
    result = subprocess.run([sys.executable, '-m', 'tests.test_camera_editor', case],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


if __name__ == '__main__':
    exercise_editor(sys.argv[1])
