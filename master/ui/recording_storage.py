"""FIT-LAB storage selection; no OS directory picker."""
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QListWidget,QListWidgetItem,QPushButton
from shared.recording_storage import recording_volumes,prepare_recording_directory

class RecordingStorageDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Накопитель для записи');self.resize(560,400)
        self.directory=None
        layout=QVBoxLayout(self)
        title=QLabel('Где сохранять видео?');title.setProperty('section',True);layout.addWidget(title)
        self.list=QListWidget();layout.addWidget(self.list,1)
        self.note=QLabel('Папка FIT-LAB / Записи будет создана на выбранном накопителе.')
        self.note.setWordWrap(True);layout.addWidget(self.note)
        buttons=QHBoxLayout()
        for text,callback in [('Обновить',self.refresh),('Выбрать',self.choose),('Отмена',self.reject)]:
            button=QPushButton(text);button.setMinimumHeight(48);button.clicked.connect(callback);buttons.addWidget(button)
        layout.addLayout(buttons);self.refresh()
        self.refresh_timer=QTimer(self)
        self.refresh_timer.setInterval(2000)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start()
        self.finished.connect(self.refresh_timer.stop)

    def refresh(self):
        previous=self.list.currentItem()
        selected=previous.data(Qt.ItemDataRole.UserRole) if previous else None
        self.list.clear()
        for volume in recording_volumes():
            item=QListWidgetItem(f'{volume.name}\nСвободно {volume.free/1024**3:.1f} ГБ')
            item.setData(Qt.ItemDataRole.UserRole,volume);item.setSizeHint(QSize(0,70));self.list.addItem(item)
        if self.list.count():
            index=next((i for i in range(self.list.count()) if selected and self.list.item(i).data(Qt.ItemDataRole.UserRole).root==selected.root and self.list.item(i).data(Qt.ItemDataRole.UserRole).device==selected.device),0)
            self.list.setCurrentRow(index)
            self.note.setText('Папка FIT-LAB / Записи будет создана на выбранном накопителе.')
        else:self.note.setText('Подключите SSD, флешку или SD-карту. Системный диск исключён.')

    def choose(self):
        item=self.list.currentItem()
        if item is None:return
        try:self.directory=prepare_recording_directory(item.data(Qt.ItemDataRole.UserRole))
        except (OSError,ValueError) as exc:self.note.setText(str(exc));return
        self.accept()
