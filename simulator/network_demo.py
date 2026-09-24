from __future__ import annotations

import socket
import threading
import uuid

from master.core import StationCore
from master.discovery import DiscoveryServer
from receiver.beacon import build_receiver_announcement, send_announcement


def main() -> None:
    station = StationCore()
    server = DiscoveryServer(station)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        host, port = sock.getsockname()

        result_box: list[object] = []

        def receive() -> None:
            result_box.append(server.receive_once(sock))

        thread = threading.Thread(target=receive, daemon=True)
        thread.start()

        announcement = build_receiver_announcement(
            module_id=str(uuid.uuid4()),
        )
        send_announcement(host, port, announcement)

        thread.join(timeout=2.0)

    if not result_box:
        raise SystemExit("Модуль не обнаружен")

    result = result_box[0]
    print("FIT-LAB Network Demo")
    print(f"Модуль обнаружен: {'да' if result.accepted else 'нет'}")
    print(f"ID: {result.module_id or '-'}")

    for event in station.journal.snapshot():
        print(f"[{event.severity}] {event.message}")


if __name__ == "__main__":
    main()
