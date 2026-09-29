"""FIT-LAB Control UI concept demo.

Safe animated prototype: no sockets, GPIO, serial ports, CRSF or RF are opened.
Run:
    FIT_LAB_THEME=amber python -m simulator.control_ui_demo
    FIT_LAB_THEME=cyan  python -m simulator.control_ui_demo
"""
from __future__ import annotations

import math
import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMainWindow, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from master.ui.theme import apply_theme, selected_theme


class Stick(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setProperty("card", True)
        self.title = QLabel(title)
        self.value = QLabel("X 1500   Y 1500")
        self.value.setProperty("inlineValue", True)
        lay = QVBoxLayout(self)
        lay.addWidget(self.title)
        lay.addStretch()
        lay.addWidget(self.value, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addStretch()

    def set_xy(self, x: int, y: int):
        self.value.setText(f"X {x:4d}   Y {y:4d}")


class Demo(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FIT-LAB Control · animated concept")
        self.resize(1380, 850)
        self.started = time.monotonic()
        self.phase = 0

        root = QWidget()
        root.setObjectName("stationRoot")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(12)

        head = QHBoxLayout()
        brand = QLabel("FIT-LAB")
        brand.setObjectName("brandWordmark")
        head.addWidget(brand)
        product = QLabel("TECHNOLOGIES · CONTROL CONCEPT")
        product.setProperty("eyebrow", True)
        head.addWidget(product)
        head.addStretch()
        self.theme = QComboBox()
        self.theme.addItems(["Amber", "Cyan"])
        self.theme.setCurrentText("Amber" if selected_theme() == "amber" else "Cyan")
        self.theme.currentTextChanged.connect(self.change_theme)
        head.addWidget(QLabel("Тема"))
        head.addWidget(self.theme)
        outer.addLayout(head)

        body = QGridLayout()
        body.setSpacing(12)
        outer.addLayout(body, 1)

        video = QFrame()
        video.setProperty("card", True)
        vl = QVBoxLayout(video)
        title = QLabel("ВИДЕО · WFB-ng")
        title.setProperty("section", True)
        vl.addWidget(title)
        self.video_status = QLabel("● LIVE   1280×720 · 60 FPS · H.265")
        self.video_status.setProperty("inlineValue", True)
        vl.addWidget(self.video_status)
        placeholder = QLabel("ЖИВОЕ ВИДЕО\n\nВ реальной Station здесь остаётся существующий видеопоток.\nЭтот экран — безопасная анимационная демонстрация управления.")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("font-size: 22px; border: 1px solid #4b5251; border-radius: 8px;")
        vl.addWidget(placeholder, 1)
        body.addWidget(video, 0, 0, 1, 2)

        link = QFrame()
        link.setProperty("card", True)
        ll = QVBoxLayout(link)
        t = QLabel("КОНТУР УПРАВЛЕНИЯ")
        t.setProperty("section", True)
        ll.addWidget(t)
        self.nodes = {}
        for name in ("Mac / HID", "Orange Pi", "RP2040 / FreeRTOS", "FIT-LAB TX", "FIT-LAB RX", "Flight Controller"):
            row = QHBoxLayout()
            row.addWidget(QLabel(name))
            state = QLabel("ОЖИДАНИЕ")
            state.setProperty("status", "warning")
            row.addStretch()
            row.addWidget(state)
            ll.addLayout(row)
            self.nodes[name] = state
        self.power = QLabel("TX POWER BOARD · питание выключено")
        self.power.setProperty("status", "warning")
        ll.addWidget(self.power)
        body.addWidget(link, 0, 2)

        control = QFrame()
        control.setProperty("card", True)
        cl = QVBoxLayout(control)
        title = QLabel("УПРАВЛЕНИЕ")
        title.setProperty("section", True)
        cl.addWidget(title)
        status_row = QHBoxLayout()
        self.control_state = QLabel("СИМУЛЯЦИЯ")
        self.control_state.setProperty("status", "ready")
        status_row.addWidget(self.control_state)
        status_row.addStretch()
        self.latency = QLabel("LAN 0 ms")
        self.latency.setProperty("inlineValue", True)
        status_row.addWidget(self.latency)
        cl.addLayout(status_row)

        sticks = QHBoxLayout()
        self.left = Stick("Левый стик · Throttle / Yaw")
        self.right = Stick("Правый стик · Pitch / Roll")
        sticks.addWidget(self.left)
        sticks.addWidget(self.right)
        cl.addLayout(sticks)

        self.channels = []
        grid = QGridLayout()
        for i in range(8):
            grid.addWidget(QLabel(f"CH{i+1}"), i, 0)
            bar = QProgressBar()
            bar.setRange(1000, 2000)
            bar.setValue(1500)
            bar.setTextVisible(True)
            grid.addWidget(bar, i, 1)
            self.channels.append(bar)
        cl.addLayout(grid)

        buttons = QHBoxLayout()
        arm = QPushButton("ARM · заблокирован в демо")
        arm.setEnabled(False)
        stop = QPushButton("АВАРИЙНАЯ ОСТАНОВКА · DEMO")
        stop.setProperty("role", "danger")
        stop.clicked.connect(self.reset_demo)
        buttons.addWidget(arm)
        buttons.addWidget(stop)
        cl.addLayout(buttons)
        body.addWidget(control, 1, 0, 1, 2)

        telemetry = QFrame()
        telemetry.setProperty("card", True)
        tl = QVBoxLayout(telemetry)
        title = QLabel("ТЕЛЕМЕТРИЯ / ДИАГНОСТИКА")
        title.setProperty("section", True)
        tl.addWidget(title)
        self.metrics = {}
        for key in ("LQ", "RSSI", "SNR", "TX", "Питание TX", "RP2040", "Пакеты", "Failsafe"):
            row = QHBoxLayout()
            row.addWidget(QLabel(key))
            val = QLabel("—")
            val.setProperty("metricValue", True)
            row.addStretch()
            row.addWidget(val)
            tl.addLayout(row)
            self.metrics[key] = val
        note = QLabel("SIMULATION ONLY · RF/CRSF/UART/GPIO НЕ ЗАПУСКАЮТСЯ")
        note.setProperty("eyebrow", True)
        note.setWordWrap(True)
        tl.addStretch()
        tl.addWidget(note)
        body.addWidget(telemetry, 1, 2)

        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def change_theme(self, text):
        apply_theme(QApplication.instance(), text.lower())

    def reset_demo(self):
        self.started = time.monotonic()
        self.phase = 0

    def tick(self):
        t = time.monotonic() - self.started
        order = list(self.nodes)
        ready_count = min(len(order), int(t / 0.65))
        for i, name in enumerate(order):
            state = self.nodes[name]
            if i < ready_count:
                state.setText("ГОТОВО")
                state.setProperty("status", "ready")
            else:
                state.setText("ОЖИДАНИЕ")
                state.setProperty("status", "warning")
            state.style().unpolish(state)
            state.style().polish(state)

        active = ready_count == len(order)
        self.power.setText("TX POWER BOARD · питание разрешено (симуляция)" if active else "TX POWER BOARD · питание выключено")
        self.power.setProperty("status", "ready" if active else "warning")
        self.power.style().unpolish(self.power)
        self.power.style().polish(self.power)

        wave = math.sin(t * 1.3)
        wave2 = math.cos(t * 1.05)
        x1 = int(1500 + 330 * wave)
        y1 = int(1500 + 260 * wave2)
        x2 = int(1500 + 300 * math.sin(t * 0.9 + 1.2))
        y2 = int(1500 + 300 * math.cos(t * 1.1 + 0.4))
        self.left.set_xy(x1, y1)
        self.right.set_xy(x2, y2)
        values = [y1, x1, y2, x2, 1000, 1500, 1500, 1500]
        for bar, value in zip(self.channels, values):
            bar.setValue(value)

        self.latency.setText(f"LAN {8 + int(abs(math.sin(t))*5)} ms")
        self.metrics["LQ"].setText(f"{98 + int(abs(math.sin(t))*2)} %")
        self.metrics["RSSI"].setText(f"{-58 - int(abs(math.sin(t*0.7))*7)} dBm")
        self.metrics["SNR"].setText(f"{15 + int(math.sin(t))} dB")
        self.metrics["TX"].setText("250 Hz · 100 mW" if active else "ОЖИДАНИЕ")
        self.metrics["Питание TX"].setText("12.1 V" if active else "0 V")
        self.metrics["RP2040"].setText("FreeRTOS · OK" if ready_count >= 3 else "BOOT")
        self.metrics["Пакеты"].setText(str(int(t * 250)) if active else "0")
        self.metrics["Failsafe"].setText("ГОТОВ" if active else "НЕ АКТИВЕН")


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    window = Demo()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
