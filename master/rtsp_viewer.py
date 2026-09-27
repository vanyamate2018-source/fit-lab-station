"""Isolated RTSP login/player. Credentials remain in process memory only."""
import argparse
from PySide6.QtCore import QUrl, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QFormLayout, QLineEdit, QLabel, QPushButton, QHBoxLayout
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from master.camera import valid_host
from master.ui.theme import apply_theme
from master.ui.brand import icon

class RtspDialog(QDialog):
    def __init__(self, host):
        super().__init__()
        self.setWindowTitle('FIT-LAB · IP-камера')
        self.resize(720, 520)
        self.setWindowIcon(icon())
        root=QVBoxLayout(self)
        self.status=QLabel('Вход в видеопоток камеры')
        root.addWidget(self.status)
        form=QFormLayout()
        self.host=QLineEdit(valid_host(host))
        self.path=QLineEdit('/stream1')
        self.user=QLineEdit()
        self.password=QLineEdit();self.password.setEchoMode(QLineEdit.EchoMode.Password)
        for title,field in [('Адрес камеры',self.host),('Путь потока',self.path),('Пользователь',self.user),('Пароль',self.password)]:
            field.setAccessibleName(title);field.setMinimumHeight(40);form.addRow(title,field)
        root.addLayout(form)
        self.video=QVideoWidget();self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video.hide();root.addWidget(self.video,1)
        self.player=QMediaPlayer(self);self.audio=QAudioOutput(self);self.audio.setVolume(.35)
        self.player.setAudioOutput(self.audio);self.player.setVideoOutput(self.video)
        self.player.errorOccurred.connect(self.failed)
        self.video.videoSink().videoFrameChanged.connect(self.frame)
        self.timeout=QTimer(self);self.timeout.setSingleShot(True);self.timeout.timeout.connect(self.failed)
        buttons=QHBoxLayout()
        for title,callback in [('Подключить',self.connect_camera),('Остановить',self.stop),('Закрыть',self.close)]:
            b=QPushButton(title);b.setMinimumHeight(48);b.clicked.connect(callback);buttons.addWidget(b)
        root.addLayout(buttons)
        self.password.returnPressed.connect(self.connect_camera)

    def connect_camera(self):
        try: host=valid_host(self.host.text())
        except ValueError:
            self.status.setText('Проверьте адрес камеры');return
        path=self.path.text().strip()
        if not path.startswith('/') or any(c in path for c in ('\r','\n')):
            self.status.setText('Путь потока должен начинаться с /');return
        self.stop()
        url=QUrl();url.setScheme('rtsp');url.setHost(host);url.setPort(554);url.setPath(path)
        url.setUserName(self.user.text());url.setPassword(self.password.text())
        self.password.clear()
        self.status.setText('Подключение…');self.video.show()
        self.player.setSource(url);self.player.play();self.timeout.start(15000)

    def frame(self, frame):
        if frame.isValid():
            self.timeout.stop();self.status.setText('Видео подключено')

    def stop(self):
        self.timeout.stop();self.player.stop();self.player.setSource(QUrl())
        self.status.setText('Приём остановлен')

    def failed(self,*_):
        self.stop();self.status.setText('Нет видео: проверьте подключение, путь потока, логин и пароль')

    def closeEvent(self,event):
        self.stop();self.password.clear();super().closeEvent(event)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--host',required=True);args=parser.parse_args()
    app=QApplication([]);app.setApplicationName('FIT-LAB · IP-камера');apply_theme(app)
    window=RtspDialog(args.host);window.show();return app.exec()

if __name__=='__main__':raise SystemExit(main())
