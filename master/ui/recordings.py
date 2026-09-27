"""Touch-friendly local recordings library, without a system file browser."""
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, QSize
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QLabel, QPushButton, QSlider, QMessageBox, QStyle
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

class RecordingsDialog(QDialog):
    def __init__(self, directory, active_path=None, parent=None):
        super().__init__(parent)
        self.directory = Path(directory).resolve()
        self.active_path = Path(active_path).resolve() if active_path else None
        self.setWindowTitle('Записи')
        self.resize(min(940, parent.width()), min(580, parent.height()))
        root = QVBoxLayout(self)
        self.status = QLabel('Записи')
        header = QHBoxLayout()
        header.addWidget(self.status, 1)
        self.clear_button = QPushButton('Очистить видео')
        self.clear_button.setMinimumHeight(48)
        self.clear_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self.clear_button.clicked.connect(self.clear_videos)
        header.addWidget(self.clear_button)
        root.addLayout(header)
        self.files = QListWidget()
        root.addWidget(self.files, 1)
        self.video = QVideoWidget()
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video.hide()
        root.addWidget(self.video, 2)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(.5)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.errorOccurred.connect(lambda *_: self.status.setText('Не удалось воспроизвести запись'))
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setMinimumHeight(32)
        self.seek.setAccessibleName('Позиция записи')
        self.seek.setEnabled(False)
        self.player.durationChanged.connect(lambda duration: self.seek.setRange(0, duration))
        self.player.seekableChanged.connect(self.seek.setEnabled)
        self.player.positionChanged.connect(lambda position: self.seek.setValue(position) if not self.seek.isSliderDown() else None)
        self.seek.sliderReleased.connect(lambda: self.player.setPosition(self.seek.value()))
        root.addWidget(self.seek)
        actions = QHBoxLayout()
        for title, callback in [('Смотреть', self.play), ('Пауза', self.player.pause), ('К списку', self.back), ('Закрыть', self.accept)]:
            control = QPushButton(title)
            control.setMinimumHeight(48)
            control.clicked.connect(callback)
            actions.addWidget(control)
        root.addLayout(actions)
        self.files.itemDoubleClicked.connect(lambda *_: self.play())
        self.reload()
        self.finished.connect(lambda *_: self.player.stop())

    def reload(self):
        self.files.clear()
        self.clear_button.setEnabled(False)
        try:
            videos = sorted((p for p in self.directory.iterdir()
                             if p.is_file() and not p.is_symlink()
                             and p.suffix.lower() in ('.mkv', '.mp4', '.mov', '.webm')
                             and p.resolve() != self.active_path),
                            key=lambda p: p.stat().st_mtime, reverse=True)
            for path in videos:
                item = QListWidgetItem(f'{path.stem}   ·   {path.stat().st_size / 1048576:.1f} МБ')
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                item.setSizeHint(QSize(0, 54))
                self.files.addItem(item)
            self.clear_button.setEnabled(bool(videos))
            self.status.setText(f'Записи · {len(videos)}' if videos else 'Записей пока нет')
            if videos:
                self.files.setCurrentRow(0)
        except OSError:
            self.status.setText('Накопитель недоступен')

    def clear_videos(self):
        paths = [Path(self.files.item(i).data(Qt.ItemDataRole.UserRole))
                 for i in range(self.files.count())]
        if not paths:
            return
        question = QMessageBox(self)
        question.setWindowTitle('Очистить видео')
        question.setText(f'Удалить записей: {len(paths)}?')
        question.setInformativeText('Удаление без восстановления. Текущая запись останется.')
        remove = question.addButton('Удалить', QMessageBox.ButtonRole.DestructiveRole)
        cancel = question.addButton('Отмена', QMessageBox.ButtonRole.RejectRole)
        question.setDefaultButton(cancel)
        for button in (remove, cancel):
            button.setMinimumHeight(48)
        question.exec()
        if question.clickedButton() != remove:
            return
        self.back()
        self.player.setSource(QUrl())
        failed = 0
        for path in paths:
            try:
                if (path.parent != self.directory or path.is_symlink()
                        or path.resolve() == self.active_path
                        or path.suffix.lower() not in ('.mkv', '.mp4', '.mov', '.webm')):
                    continue
                path.unlink(missing_ok=True)
            except OSError:
                failed += 1
        self.reload()
        if failed:
            self.status.setText(f'Не удалось удалить: {failed}')

    def play(self):
        item = self.files.currentItem()
        if item is None:
            return
        self.files.hide()
        self.video.show()
        source = QUrl.fromLocalFile(item.data(Qt.ItemDataRole.UserRole))
        if self.player.source() != source:
            self.player.setSource(source)
        self.player.play()

    def back(self):
        self.player.stop()
        self.video.hide()
        self.files.show()
