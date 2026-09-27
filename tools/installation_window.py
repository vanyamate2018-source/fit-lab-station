"""Preview of the offline installer. Never mutates the working SSD installation."""
import sys
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QPushButton, QHeaderView
from master.install_plan import release_plan


def main():
    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle('FIT-LAB · Подготовка установки')
    window.resize(760, 480)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(28, 24, 28, 24)
    heading = QLabel('FIT-LAB Station')
    heading.setStyleSheet('font-size:28px;font-weight:600;color:#ffc16c')
    layout.addWidget(heading)
    layout.addWidget(QLabel('Полный комплект · установка без интернета'))
    plan = release_plan()
    table = QTableWidget(len(plan['components']), 2)
    table.setHorizontalHeaderLabels(['Компонент', 'Состояние'])
    table.verticalHeader().hide()
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    for row, item in enumerate(plan['components']):
        table.setItem(row, 0, QTableWidgetItem(item['name']))
        table.item(row, 0).setToolTip(item['description'])
        table.setItem(row, 1, QTableWidgetItem('Ожидает сборки'))
        table.setRowHeight(row, 44)
    layout.addWidget(table)
    status = QLabel('Предварительный состав. Автономные пакеты ещё не собраны.\nТестовая версия на SSD остаётся без изменений.')
    status.setWordWrap(True)
    layout.addWidget(status)
    button = QPushButton('Установка пока недоступна')
    button.setEnabled(False)
    button.setMinimumHeight(44)
    layout.addWidget(button)
    window.setStyleSheet('QWidget { background:#191d20;color:#eef0f2;font-size:14px; } QTableWidget {background:#22282b;gridline-color:#394145;} QHeaderView::section {background:#30373b;padding:10px;border:0;} QPushButton {background:#30373b;border-radius:8px;}')
    window.show()
    if '--check-layout' in sys.argv:
        app.processEvents()
        window.grab().save('/Volumes/FIT-LAB/data/exports/installation-window.png')
        return 0
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
