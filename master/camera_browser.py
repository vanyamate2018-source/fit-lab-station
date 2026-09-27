"""Isolated native window for the camera's own supported configuration UI."""
import argparse
import json
import signal
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QDialog, QFormLayout, QLineEdit, QDialogButtonBox
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from master.camera import valid_host
from master.ui.theme import APP_STYLESHEET
from master.ui.brand import icon
from master.ui.display import DisplayLayout
from master.ui.touch import TouchSupport


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    args=parser.parse_args()
    host=valid_host(args.host)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app=QApplication([])
    app.setApplicationName('FIT-LAB · Камера')
    app.setStyleSheet(APP_STYLESHEET)
    app.setWindowIcon(icon())
    profile=QWebEngineProfile('FIT-LAB-Camera', app)
    cache=args.data_root/'cache/camera-browser'
    cache.mkdir(parents=True, exist_ok=True)
    profile.setCachePath(str(cache/'cache'))
    profile.setPersistentStoragePath(str(cache/'storage'))
    profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
    profile.downloadRequested.connect(lambda request: request.cancel())

    class CameraPage(QWebEnginePage):
        def acceptNavigationRequest(self, url, kind, main_frame):
            return url.scheme() in ('http','https') and url.host()==host
        def createWindow(self, _):
            return None

    window=QMainWindow()
    window.setWindowTitle(f'FIT-LAB · Настройки камеры · {host}')
    window.resize(1024,600)
    window.setMinimumSize(640,400)
    root=QWidget()
    window.setCentralWidget(root)
    layout=QVBoxLayout(root)
    layout.setContentsMargins(8,8,8,8)
    row=QHBoxLayout()
    back=QPushButton('Назад')
    refresh=QPushButton('Обновить')
    status=QLabel('Подключение к камере…')
    close=QPushButton('Готово')
    row.addWidget(back);row.addWidget(refresh);row.addWidget(status,1);row.addWidget(close)
    layout.addLayout(row)
    view=QWebEngineView()
    page=CameraPage(profile,view)
    view.setPage(page)
    layout.addWidget(view,1)
    back.clicked.connect(view.back)
    refresh.clicked.connect(view.reload)
    close.clicked.connect(window.close)
    def loaded(ok):
        status.setText(host if ok else 'Камера недоступна · повторите подключение')
        (args.data_root/'logs/camera-browser-state.json').write_text(json.dumps({'host':host, 'loaded':ok}))
    view.loadFinished.connect(loaded)
    view.renderProcessTerminated.connect(lambda *_: status.setText('Панель остановлена · нажмите «Обновить»'))
    touch=TouchSupport(window,args.data_root,status_file="camera-touch-status.json")
    def authenticate(url, authenticator):
        if url.host()!=host:
            return
        dialog=QDialog(window)
        dialog.setWindowTitle('Вход в камеру')
        form=QFormLayout(dialog)
        form.setContentsMargins(24,24,24,24)
        user=QLineEdit('root')
        password=QLineEdit()
        password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow('Пользователь',user)
        form.addRow('Пароль',password)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Войти')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Отмена')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        touch.attach(dialog)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            authenticator.setUser(user.text())
            authenticator.setPassword(password.text())
        password.clear()
        dialog.deleteLater()
    page.authenticationRequired.connect(authenticate)
    display=DisplayLayout(window)
    window.show(); display.fit()
    window.raise_(); window.activateWindow()
    view.setUrl(QUrl(f'http://{host}/'))
    app.aboutToQuit.connect(touch.close)
    signal.signal(signal.SIGTERM,lambda *_:window.close())
    wake=QTimer();wake.start(250);wake.timeout.connect(lambda:None)
    return app.exec()


if __name__=='__main__':
    raise SystemExit(main())
