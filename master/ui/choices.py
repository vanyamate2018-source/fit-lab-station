"""Accessible, large choices shared by radio and camera controls."""
from PySide6.QtCore import Signal, QTimer, Qt, QSize, QObject, QEvent
from PySide6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QListWidgetItem, QAbstractItemView
from master.ui.widgets import MotionButton


class ChoiceDrag(QObject):
    """Pointer-compatible touch panels: drag rows without activating them."""
    def __init__(self, view):
        super().__init__(view)
        self.view, self.origin, self.dragged = view, None, False
        view.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position()
            self.start = self.view.verticalScrollBar().value()
            self.dragged = False
        elif kind == QEvent.Type.MouseMove and self.origin is not None:
            delta = event.position().y() - self.origin.y()
            self.dragged = self.dragged or abs(delta) >= 8
            if self.dragged:
                self.view.verticalScrollBar().setValue(self.start - round(delta))
                return True
        elif kind == QEvent.Type.MouseButtonRelease and self.origin is not None:
            self.origin = None
            if self.dragged:
                self.dragged = False
                return True
        return False


class ChoicePicker(MotionButton):
    currentIndexChanged = Signal(int)
    currentTextChanged = Signal(str)

    def __init__(self, title='Выбрать значение'):
        super().__init__(title + ' ▾')
        self.title = title
        self.items, self.index = [], -1
        self.clicked.connect(self.choose)

    def clear(self):
        self.items, self.index = [], -1
        self.setText(self.title + ' ▾')

    def addItem(self, text, value=None):
        self.items.append((text, value))
        if self.index < 0:
            self.setCurrentIndex(0)

    def addItems(self, items):
        for text in items:
            self.addItem(text)

    def count(self):
        return len(self.items)

    def setItemText(self, index, text):
        self.items[index] = (text, self.items[index][1])
        if self.index == index:
            self.setText(text + ' ▾')
            self.setAccessibleName(self.title + ' · ' + text)

    def currentIndex(self):
        return self.index

    def currentText(self):
        return self.items[self.index][0] if 0 <= self.index < len(self.items) else ''

    def findText(self, text):
        return next((i for i, (label, _) in enumerate(self.items) if label == text), -1)

    def setCurrentText(self, text):
        index = self.findText(text)
        if index >= 0:
            self.setCurrentIndex(index)

    def findData(self, value):
        return next((i for i, (_, data) in enumerate(self.items) if data == value), -1)

    def currentData(self):
        return self.items[self.index][1] if 0 <= self.index < len(self.items) else None

    def setCurrentIndex(self, index):
        if index == self.index:
            return
        self.index = index
        text = self.items[index][0] if 0 <= index < len(self.items) else self.title
        self.setText(text + ' ▾')
        self.setAccessibleName(self.title + ' · ' + text)
        self.currentIndexChanged.emit(index)
        self.currentTextChanged.emit(self.currentText())

    def choose(self):
        if not self.items:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.title)
        area = self.screen().availableGeometry()
        compact = area.width() <= 1100 or area.height() <= 700
        dialog.resize(min(460 if compact else 600, area.width()-24), min(460, area.height()-48))
        layout = QVBoxLayout(dialog)
        scroll = QListWidget(dialog)
        scroll.setAccessibleName(self.title)
        scroll.setUniformItemSizes(True)
        scroll.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("""
            QListWidget { background: #171b1f; color: #f5eee4; border: 1px solid #68563d; border-radius: 10px; outline: none; }
            QListWidget::item { padding: 8px 16px; border-bottom: 1px solid #303437; }
            QListWidget::item:selected { background: #59442a; color: #ffca7b; }
            QListWidget::item:hover { background: #35302a; }
            QScrollBar:vertical { width: 14px; background: #171b1f; }
            QScrollBar::handle:vertical { background: #a98350; min-height: 40px; border-radius: 6px; }
        """)
        for text, _ in self.items:
            item = QListWidgetItem(text)
            item.setSizeHint(QSize(0, 56))
            scroll.addItem(item)
        if 0 <= self.index < scroll.count():
            scroll.setCurrentRow(self.index)
            QTimer.singleShot(0, lambda: scroll.scrollToItem(scroll.currentItem(), QAbstractItemView.ScrollHint.PositionAtCenter))
        def select(item):
            self.setCurrentIndex(scroll.row(item))
            dialog.accept()
        scroll.itemClicked.connect(select)
        scroll.drag_handler = ChoiceDrag(scroll)
        layout.addWidget(scroll)
        cancel = MotionButton('Отмена')
        cancel.clicked.connect(dialog.reject)
        layout.addWidget(cancel)
        station = self.window()
        if hasattr(station, 'touch'):
            station.touch.attach(dialog)
        dialog.exec()
