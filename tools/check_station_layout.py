"""Render the real widgets offscreen with a labelled frame; no radio or touch IO."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QFont
from PySide6.QtWidgets import QApplication, QLabel
from master.ui.theme import apply_theme


class OfflineUSB(QObject):
    changed = Signal(list)
    scanningChanged = Signal(bool)
    def __init__(self, parent=None, data_root=None):
        super().__init__(parent)
    def close(self):
        pass


def main():
    app = QApplication([])
    apply_theme(app)
    from shared.config import default_data_root
    data_root = default_data_root()
    target = data_root / 'exports/module-layout-check'
    target.mkdir(exist_ok=True)
    image = QImage(1280, 720, QImage.Format.Format_RGB32)
    image.fill(QColor('#163a45'))
    painter = QPainter(image)
    painter.setPen(QColor('#608088'))
    for x in range(0, 1280, 80):
        painter.drawLine(x, 0, x, 720)
    for y in range(0, 720, 80):
        painter.drawLine(0, y, 1280, y)
    for x, y, color in ((8, 8, '#ff514b'), (1232, 8, '#65e5a3'), (8, 672, '#ffc570'), (1232, 672, '#70b5ff')):
        painter.fillRect(x, y, 40, 40, QColor(color))
    painter.setPen(QColor('#f0ede7'))
    painter.setFont(QFont('Arial', 28))
    painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, 'ТЕСТ КОМПОНОВКИ\n1280 × 720 · 16:9')
    painter.end()
    results = []
    text_overflow = []
    with tempfile.TemporaryDirectory(dir=data_root / 'temp', prefix='layout-check-') as root:
        with patch.dict(os.environ, {'FIT_LAB_DATA_ROOT': root}), \
             patch('master.ui.main_window.TouchSupport', return_value=SimpleNamespace(close=lambda: None, attach=lambda _: None, statusChanged=SimpleNamespace(connect=lambda _: None))), \
             patch('master.ui.main_window.UsbMonitor', OfflineUSB), \
             patch('master.camera_lan.LanDeviceDiscovery', OfflineUSB), \
             patch('master.viewer_server.ViewerService'), \
             patch('master.system_volume.SystemVolume'), \
             patch('master.camera.CameraManager.scan'), \
             patch('master.session.StationSession.discover_cameras'), \
             patch('master.ui.main_window.QUdpSocket.bind', return_value=False):
            from master.ui.main_window import MainWindow
            window = MainWindow()
            window.camera.timer.stop()
            window.modules_timer.stop()
            window.health_timer.stop()
            settings_file = data_root / 'logs/camera-settings-public.json'
            if settings_file.is_file():
                from shared.camera_settings import nested
                public = json.loads(settings_file.read_text())
                schema = {'properties': {}}
                for path, spec in public.items():
                    node = schema
                    parts = path.split('.')
                    for part in parts[:-1]:
                        node = node.setdefault('properties', {}).setdefault(part, {})
                    node.setdefault('properties', {})[parts[-1]] = {k: v for k, v in spec.items() if k != 'value'}
                window.camera_editor.load({'schema': schema, 'config': nested({p: s['value'] for p, s in public.items()})})
            window.video.set_frame(image)
            window.video.stale = False
            window.toast_timer.stop()
            window.toast_animation.stop()
            window.toast_opacity.setOpacity(1)
            window.toast.setText('Макет · без подключения к оборудованию')
            window.status.set_status('warning', 'МАКЕТ')
            window.show()
            for width, height in ((800, 480), (1024, 600), (1280, 720), (1380, 850)):
                for page in ('live', 'camera', 'camera-connection', 'camera-info', 'osd', 'network', 'radio', 'modules',
                             'system', 'system-recording', 'system-sounds', 'system-diagnostics', 'system-display'):
                    window.show_page('camera' if page.startswith('camera') else 'system' if page.startswith('system') else page)
                    if page == 'camera':
                        window.camera_tabs.setCurrentIndex(0)
                        editor = window.camera_editor
                        index = editor.group.findData('video0')
                        editor.group.setCurrentIndex(index)
                        editor.sections.setCurrentRow(index)
                        editor.stack.setCurrentIndex(index)
                    if page.startswith('camera-'):
                        window.camera_tabs.setCurrentIndex(1 if page.endswith('connection') else 2)
                    if page.startswith('system'):
                        window.system_tabs.setCurrentIndex({'system': 0, 'system-recording': 1, 'system-sounds': 2, 'system-diagnostics': 3, 'system-display': 4}[page])
                    window.resize(width, height)
                    app.processEvents()
                    canvas = window.video
                    canvas.set_frame(image)
                    canvas.stale = False
                    scaled = image.size().scaled(canvas.size(), Qt.AspectRatioMode.KeepAspectRatio)
                    result = {'requested': [width, height], 'actual': [window.width(), window.height()],
                              'page': page, 'canvas': [canvas.width(), canvas.height()],
                              'frame': [scaled.width(), scaled.height()]}
                    results.append(result)
                    window.grab().save(str(target / f'{page}-{width}x{height}.png'))
                    for item in window.findChildren(QLabel):
                        text = item.text()
                        if (item.isVisible() and not item.wordWrap() and text and '\n' not in text
                                and '<' not in text and not item.visibleRegion().isEmpty()
                                and item.fontMetrics().horizontalAdvance(text) > item.contentsRect().width()+2):
                            text_overflow.append(dict(page=page, size=[width,height], text=text,
                                                      width=item.contentsRect().width()))
                    assert window.width() == width and window.height() == height, result
                    if page == 'modules':
                        assert window.page_title.x() < width / 2, 'Section title moved into right-hand status area'
                    assert scaled.width() <= canvas.width() and scaled.height() <= canvas.height(), result
                    assert abs(scaled.width() / scaled.height() - 16 / 9) < .01, result
                    if page == 'live':
                        rendered = canvas.grab().toImage()
                        dpr = rendered.devicePixelRatio()
                        offset_x, offset_y = (canvas.width()-scaled.width())/2, (canvas.height()-scaled.height())/2
                        for x, y, color in ((28, 28, '#ff514b'), (1252, 28, '#65e5a3'), (28, 692, '#ffc570'), (1252, 692, '#70b5ff')):
                            sample = rendered.pixelColor(round((offset_x+x*scaled.width()/1280)*dpr), round((offset_y+y*scaled.height()/720)*dpr))
                            assert sample == QColor(color), (result, color, sample.name())
            window.close()
    (target/'geometry.json').write_text(json.dumps(results, indent=2))
    (target/'text-overflow.json').write_text(json.dumps(text_overflow, ensure_ascii=False, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
