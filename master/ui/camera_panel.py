"""Supervise camera WebEngine separately so a web crash cannot stop the radio."""
import sys
from pathlib import Path
from PySide6.QtCore import QProcess, QProcessEnvironment
from master.camera import valid_host


def open_camera_panel(host, data_root, parent):
    host = valid_host(host)
    if parent.camera_browser is not None and parent.camera_browser.state() != QProcess.ProcessState.NotRunning:
        parent.notify("Настройки камеры уже открыты")
        return
    process = QProcess(parent)
    parent.camera_browser = process
    env = QProcessEnvironment.systemEnvironment()
    env.insert("PYTHONPYCACHEPREFIX", str(data_root / "cache/python"))
    env.insert("XDG_CACHE_HOME", str(data_root / "cache"))
    env.insert("TMPDIR", str(data_root / "temp"))
    process.setProcessEnvironment(env)
    process.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
    process.setStandardErrorFile(str(data_root / "logs/camera-browser.log"), QProcess.OpenModeFlag.Append)
    process.finished.connect(lambda code, status: parent.notify("Окно настроек камеры завершилось с ошибкой; приём продолжается") if code else None)
    process.errorOccurred.connect(lambda _: parent.notify("Не удалось открыть настройки камеры"))
    process.start(sys.executable, ["-m", "master.camera_browser", "--host", host, "--data-root", str(data_root)])
