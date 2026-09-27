from types import SimpleNamespace
from PySide6.QtCore import QEvent, QPointF
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QScrollArea
from master.ui.swipe import SectionSwipe
from master.ui.scrolling import configure_touch_scrolling


def exercise_swipe():
    app = QApplication.instance() or QApplication([])
    bar = QWidget()
    button = QPushButton('Video', bar)
    clicked, navigated = [], []
    button.clicked.connect(lambda: clicked.append(True))
    gesture = SectionSwipe(bar, [button], navigated.append)
    def event(kind, x, y=0):
        return SimpleNamespace(type=lambda: kind, points=lambda: [SimpleNamespace(globalPosition=lambda: QPointF(x,y))], accept=lambda: None)
    def move(kind, x, y=0):
        gesture.eventFilter(button, event(kind,x,y))
    move(QEvent.Type.TouchBegin,100)
    move(QEvent.Type.TouchUpdate,130)
    move(QEvent.Type.TouchEnd,100)
    assert not clicked and not navigated
    move(QEvent.Type.TouchBegin,100)
    move(QEvent.Type.TouchEnd,102)
    assert len(clicked)==1
    move(QEvent.Type.TouchBegin,100)
    move(QEvent.Type.TouchEnd,20)
    assert navigated==[1] and len(clicked)==1
    move(QEvent.Type.TouchBegin,100)
    move(QEvent.Type.TouchCancel,20)
    assert navigated==[1] and not button.isDown()
    scroll=QScrollArea()
    configure_touch_scrolling(scroll)
    bar.close();scroll.close()


def test_swipe_does_not_click_after_drag_returns_to_origin():
    import subprocess, sys, os
    result = subprocess.run([sys.executable, '-m', 'tests.test_section_swipe'],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr

if __name__ == '__main__':
    exercise_swipe()
