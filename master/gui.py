from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from master.ui.main_window import MainWindow
from master.ui.theme import APP_STYLESHEET


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("FIT-LAB Station")
    app.setOrganizationName("FIT-LAB")
    app.setStyleSheet(APP_STYLESHEET)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
