from __future__ import annotations

import socket
import threading
import time
import uuid
from collections.abc import Callable

from master.core import StationCore
from master.discovery import DiscoveryServer
from receiver.beacon import (
    build_receiver_announcement,
    build_receiver_heartbeat,
    send_announcement,
    send_heartbeat,
)


def exchange(
    server: DiscoveryServer,
    sock: socket.socket,
    sender: Callable[[], None],
):
    result_box = []

    def receive() -> None:
        result_box.append(server.receive_once(sock))

    thread = threading.Thread(target=receive, daemon=True)
    thread.start()
    sender()
    thread.join(timeout=2.0)

    if not result_box:
        raise RuntimeError("Ответ от сетевого обработчика не получен")
    return result_box[0]


def main() -> None:
    station = StationCore()
    server = DiscoveryServer(station)
    module_id = str(uuid.uuid4())

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        host, port = sock.getsockname()

        hello = build_receiver_announcement(module_id=module_id)
        hello_result = exchange(
            server,
            sock,
            lambda: send_announcement(host, port, hello),
        )

        heartbeat = build_receiver_heartbeat(module_id=module_id)
        exchange(
            server,
            sock,
            lambda: send_heartbeat(host, port, heartbeat),
        )

        time.sleep(0.08)
        station.check_stale_modules(timeout_seconds=0.02)

        heartbeat_result = exchange(
            server,
            sock,
            lambda: send_heartbeat(host, port, heartbeat),
        )

    print("FIT-LAB Network Lifecycle Demo")
    print(f"Модуль обнаружен: {'да' if hello_result.accepted else 'нет'}")
    print(f"Heartbeat принят: {'да' if heartbeat_result.accepted else 'нет'}")
    print(f"ID: {module_id}")

    for event in station.journal.snapshot():
        print(f"[{event.severity}] {event.message}")


if __name__ == "__main__":
    main()
