from __future__ import annotations

import sys
import signal

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer, QElapsedTimer

from master.ui.theme import apply_theme
from master.ui.brand import icon, StartupSplash
from shared.config import StationConfig
from shared.storage import ensure_directories, probe_storage


def main() -> int:
    import os
    if os.environ.get('FIT_LAB_SERVICE_JOB') == 'receiver-sync':
        from master.binding_sync import sync_bindings
        from master.camera_credentials import CameraCredentialStore
        config = StationConfig.load()
        try:
            sync_bindings(config.data_root.parent, os.environ.get('FIT_LAB_RECEIVER_HOST', '192.168.2.36'),
                          CameraCredentialStore(config.data_root))
            print('Receiver profiles and credentials synchronized', flush=True)
            return 0
        except Exception:
            print('Secure receiver synchronization unavailable', flush=True)
            return 1
    if os.environ.get('FIT_LAB_SERVICE_JOB') == 'camera-security':
        from master.maintenance import camera_security_job
        return camera_security_job()
    app = QApplication(sys.argv)
    app.setApplicationName("FIT-LAB Station")
    app.setOrganizationName("FIT-LAB")
    from master.storage_monitor import StorageMonitor
    storage_monitor = StorageMonitor(app)
    app.aboutToQuit.connect(storage_monitor.stop)
    apply_theme(app)
    app.setWindowIcon(icon())
    independent_splash = app.platformName() == 'xcb'
    if independent_splash:
        from master.startup_screen import StartupScreen
        splash = StartupScreen(app)
        app.aboutToQuit.connect(splash.close)
    else:
        splash = StartupSplash()
    splash_time = QElapsedTimer()
    splash_time.start()
    from master.lifecycle_audio import LifecycleAudio
    greeting = LifecycleAudio(app)
    app.aboutToQuit.connect(greeting.cancel)
    window = None
    config = None
    def prepare_storage():
        nonlocal config
        config = StationConfig.load()
        ensure_directories(config.data_root, config.required_directories())
        if not probe_storage(config.data_root).writable:
            raise RuntimeError("Хранилище недоступно")
        splash.stage(30, "Хранилище готово")
        import json
        try:
            preferences = json.loads((config.data_root/'config/interface.json').read_text())
        except (OSError, ValueError):
            preferences = {}
        if preferences.get('event_sounds', True) and preferences.get('sound_events', {}).get('hello', True):
            greeting.start('hello', int(preferences.get('voice_volume', 100)))

    def prepare_video():
        from master.media_env import media_environment
        media_environment(config.data_root)
        splash.stage(60, "Видеомодули подготовлены")

    def prepare_window():
        nonlocal window
        from master.ui.main_window import MainWindow
        if os.environ.get('FIT_LAB_PROFILE_STARTUP') == '1':
            import cProfile
            profiler = cProfile.Profile()
            window = profiler.runcall(MainWindow)
            profiler.dump_stats(str(config.data_root/'logs/startup-profile.pstats'))
        else:
            window = MainWindow()
        # Native macOS Quit may bypass QWidget.closeEvent. Release USB and
        # child processes on both window close and application-level exit.
        app.aboutToQuit.connect(window.shutdown)
        splash.stage(100, "Видеомодуль WFB готов" if os.environ.get('FIT_LAB_EMBEDDED_RECEIVER') == '1' else "Станция готова")

    def reveal():
        if greeting.active:
            QTimer.singleShot(100, reveal)
            return
        remaining = 5000 - 240 - splash_time.elapsed()
        if remaining > 0:
            QTimer.singleShot(remaining, reveal)
            return
        screen = next((s for s in app.screens() if "MPI7009" not in s.name()), app.primaryScreen())
        if screen:
            area = screen.availableGeometry()
            window.resize(min(1380, area.width()), min(850, area.height()-28))
            window.move(area.topLeft())
        if os.environ.get("FIT_LAB_FULLSCREEN") == "1":
            window.showFullScreen()
        else:
            window.show()
            window.display_layout.fit()
        splash.finish_animated(window)
        # Owner greeting has already played during the splash.
        if '--start-reception' in sys.argv:
            QTimer.singleShot(300, window._start)

    steps = iter((prepare_storage, prepare_video, prepare_window, reveal))
    def next_step():
        try:
            step = next(steps)
        except StopIteration:
            return
        try:
            started = splash_time.elapsed()
            step()
            if config is not None:
                import json
                with (config.data_root / 'logs/startup.jsonl').open('a') as log:
                    log.write(json.dumps({'stage': step.__name__, 'duration_ms': splash_time.elapsed()-started,
                                          'elapsed_ms': splash_time.elapsed()})+'\n')
        except Exception as exc:
            import traceback
            traceback.print_exc()
            splash.close()
            QMessageBox.critical(None, "FIT-LAB Station", str(exc))
            app.exit(1)
            return
        QTimer.singleShot(150, next_step)
    if independent_splash:
        splash.ready.connect(lambda: QTimer.singleShot(50, next_step))
    else:
        QTimer.singleShot(50, next_step)
    splash.show()
    signal.signal(signal.SIGTERM, lambda *_: window.close() if window else app.quit())
    signal.signal(signal.SIGINT, lambda *_: window.close() if window else app.quit())

    result = app.exec()
    if window is not None and getattr(window, 'restart_requested', False):
        import subprocess
        from pathlib import Path
        native = config.data_root.parent / 'FIT-LAB Station.app/Contents/MacOS/FIT-LAB'
        # LaunchServices must register the new macOS app instance; executing the
        # Mach-O directly leaves window discovery and Dock activation unreliable.
        command = ['/usr/bin/open', '-n', '-a', str(native.parents[2])] if sys.platform == 'darwin' and native.is_file() else [sys.executable, '-m', 'master.gui']
        subprocess.Popen(command, cwd=str(Path(__file__).resolve().parents[1]), start_new_session=True)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
