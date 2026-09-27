"""Read-only module inventory with real local and LAN discovery state."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget, QCheckBox

from master.module_status import discovered_status, local_receiver_status
from master.status import MODULE_TITLES
from master.ui.brand import ui_icon
from master.ui.video import ActivityDot
from master.ui.widgets import StatusBadge
from shared.models import ModuleState


def text(value='', prop=None):
    label = QLabel(value)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if prop:
        label.setProperty(prop, True)
    return label


class ModuleTile(QFrame):
    def __init__(self, title, symbol):
        super().__init__()
        self.setProperty('card', True)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(20, 16, 20, 16)
        self.box.setSpacing(12)
        heading = QHBoxLayout()
        picture = QLabel()
        picture.setPixmap(ui_icon(symbol).pixmap(28, 28))
        heading.addWidget(picture)
        self.title = text(title, 'section')
        heading.addWidget(self.title, 1)
        self.dot = ActivityDot(compact=True)
        heading.addWidget(self.dot)
        self.box.addLayout(heading)
        self.subtitle = text('', 'muted')
        self.box.addWidget(self.subtitle)
        self.status = StatusBadge('ОЖИДАНИЕ', 'warning')
        self.status.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.box.addWidget(self.status)

    def update_status(self, caption, tone, mode):
        self.status.set_status(tone, caption)
        self.dot.set_signal(mode)


class ModulesPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        self.local = ModuleTile('Видеомодуль WFB', 'radio')
        self.local.subtitle.setText('Встроенный приёмник')
        self.checks = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        for i, (key, caption) in enumerate((('usb', 'ОБНАРУЖЕНИЕ'), ('rx', 'РАДИОПРИЁМ'), ('video', 'ВИДЕО'), ('tx', 'ОБРАТНЫЙ КАНАЛ'))):
            column = QVBoxLayout()
            column.addWidget(text(caption, 'eyebrow'))
            value = text('Ожидание')
            column.addWidget(value)
            grid.addLayout(column, i // 2, i % 2)
            self.checks[key] = value
        self.local.box.addLayout(grid)
        root.addWidget(self.local)
        import os
        self.embedded = os.environ.get('FIT_LAB_EMBEDDED_RECEIVER') == '1'
        if self.embedded:
            from shared.receiver_outputs import read, update
            self.master_output = QCheckBox('Передавать видео мастеру по LAN')
            self.master_output.setChecked(read()['master_enabled'])
            self.master_output.setMinimumHeight(48)
            self.master_output.toggled.connect(lambda enabled: update(master_enabled=enabled))
            self.local.box.addWidget(self.master_output)
            self.master_state = text('Автономная работа', 'muted')
            self.local.box.addWidget(self.master_state)
            self.local.box.addWidget(text('Кнопки под видео управляют просмотром на этом устройстве.', 'muted'))
        heading = QHBoxLayout()
        self.network_heading = text('По кабелю · LAN', 'section')
        heading.addWidget(self.network_heading, 1)
        self.discovery = StatusBadge('ПОИСК', 'warning')
        heading.addWidget(self.discovery)
        root.addLayout(heading)
        self.empty = text('Подключите приёмный модуль по Ethernet', 'muted')
        root.addWidget(self.empty)
        if self.embedded:
            self.empty.setText('Локальный приём работает независимо от подключения мастера')
            self.network_heading.hide()
            self.discovery.hide()
        self.network = QVBoxLayout()
        self.network.setSpacing(12)
        root.addLayout(self.network)
        root.addStretch()
        self.tiles = {}

    def update_inventory(self, devices, state, running, mode, modules, discovery_ready):
        if self.embedded:
            modules = []
        local = local_receiver_status(devices, state, running, 'local' if self.embedded else mode)
        self.local.subtitle.setText('На этом устройстве · ' + (f'подключено RX: {local.usb_count}' if local.usb_count else 'USB-приёмники не обнаружены'))
        self.local.update_status(local.title, local.tone, local.mode)
        for key, value in {'usb': f'USB · {local.usb_count} из 2', 'rx': f'RX · {local.receiving_count} из 2', 'video': local.video, 'tx': local.tx}.items():
            self.checks[key].setText(value)
        self.discovery.set_status('ready' if discovery_ready else 'offline', 'ПОИСК АКТИВЕН' if discovery_ready else 'ПОИСК НЕДОСТУПЕН')
        self.empty.setVisible(not modules)
        ids = {m.module_id for m in modules}
        for module_id in self.tiles.keys() - ids:
            tile = self.tiles.pop(module_id)
            self.network.removeWidget(tile)
            tile.deleteLater()
        for module in modules:
            tile = self.tiles.get(module.module_id)
            if tile is None:
                tile = self.tiles[module.module_id] = ModuleTile('', 'modules')
                self.network.addWidget(tile)
            is_wfb = 'radio.forward.encrypted' in module.capabilities
            tile.title.setText('Видеомодуль WFB' if is_wfb else module.public_label())
            tile.subtitle.setText(f"{MODULE_TITLES.get(module.kind, 'Модуль')} · {module.address or 'LAN'}")
            import os
            selected = module.address == os.environ.get('FIT_LAB_RECEIVER_HOST', '192.168.2.36')
            streaming = not self.embedded and selected and running and mode == 'lan' and (state.get('mbps') or 0) > .01
            tile.update_status(*(('Видеопоток поступает', 'ready', 'receiving') if streaming else discovered_status(module)))
        present = sum(m.state is not ModuleState.UNREACHABLE for m in modules)
        count = int(bool(local.usb_count)) + present
        tone = 'warning' if present or local.tone == 'warning' else 'ready' if local.receiving_count else 'offline'
        return count, tone, bool(local.receiving_count)

    def set_master_connected(self, connected):
        if self.embedded:
            self.master_state.setText('Приложение мастера · защищённое соединение' if connected else 'Автономная работа')
