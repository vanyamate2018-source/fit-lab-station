"""Isolate camera transport from Qt. Credentials travel only through stdin."""
import json
import atexit
import os
import selectors
import threading
import subprocess
import sys
import time
from pathlib import Path


def _call_once(operation, host, username, password, root, cancel=None, **parameters):
    if cancel is not None and cancel.is_set():
        raise ValueError('Запрос отменён до отправки')
    request = {"operation": operation, "host": host, "username": username,
               "password": password, "root": str(root), **parameters}
    process = subprocess.Popen([sys.executable, "-m", "master.camera_worker"],
                               cwd=Path(__file__).resolve().parents[1],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        payload = json.dumps(request).encode()
        deadline = time.monotonic() + 120
        while True:
            if cancel is not None and cancel.is_set():
                raise ValueError('Связь изменилась. Операция могла выполниться — обновите параметры.')
            if time.monotonic() >= deadline:
                raise ValueError("Камера не ответила вовремя. Операция могла выполниться — обновите параметры перед повторной записью.")
            try:
                output, _ = process.communicate(payload, timeout=.1)
                break
            except subprocess.TimeoutExpired:
                payload = None  # communicate resumes the same request; never retransmit it.
    finally:
        request.clear()
        if process.poll() is None:
            process.kill()
            process.communicate()
    if process.returncode or len(output) > 3 * 1024 * 1024:
        raise ValueError("Служба настройки камеры завершилась без подтверждения. Обновите параметры.")
    return json.loads(output)


def dispatch(request):
    try:
        operation = request.pop("operation")
        root = Path(request.pop("root"))
        if operation == "settings":
            from master.camera_api import settings_operation
            result = settings_operation(root=root, **request)
        elif operation == "radio":
            from master.camera_radio import radio_operation
            result = radio_operation(root=root, **request)
        elif operation == 'switch':
            from master.radio_switch import switch_operation
            result = switch_operation(root=root, **request)
        elif operation == 'pair':
            from master.pairing import pair_operation
            result = pair_operation(root=root, **request)
        elif operation == 'protect':
            from master.camera_security import protect_operation
            result = protect_operation(root=root, **request)
        else:
            raise ValueError("Неизвестная операция камеры")
    except Exception as exc:
        result = {"state": "error", "error": str(exc)}
    finally:
        request.clear()
    return result


_worker_lock = threading.Lock()
_worker = None


def stop_worker():
    global _worker
    process, _worker = _worker, None
    if process is not None:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()


atexit.register(stop_worker)


def call(operation, host, username, password, root, cancel=None, **parameters):
    global _worker
    if sys.platform == 'win32' or parameters.get('transport') != 'radio' or operation not in ('radio', 'settings', 'switch'):
        return _call_once(operation, host, username, password, root, cancel=cancel, **parameters)
    deadline = time.monotonic() + 120
    def check():
        if (cancel is not None and cancel.is_set()) or time.monotonic() >= deadline:
            raise ValueError('Запрос прерван. Операция могла выполниться — обновите параметры.')
    while not _worker_lock.acquire(timeout=.1):
        check()
    try:
        check()
        if _worker is None or _worker.poll() is not None:
            stop_worker()
            _worker = subprocess.Popen([sys.executable, '-m', 'master.camera_worker', '--persistent'],
                cwd=Path(__file__).resolve().parents[1], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        payload = json.dumps(dict(operation=operation, host=host, username=username,
            password=password, root=str(root), **parameters)).encode() + b'\n'
        if len(payload) > 3 * 1024 * 1024:
            raise ValueError('Слишком большой запрос')
        # One request per exclusive worker lease. No retry of an uncertain write.
        with selectors.DefaultSelector() as selector:
            os.set_blocking(_worker.stdin.fileno(), False)
            selector.register(_worker.stdin, selectors.EVENT_WRITE)
            view = memoryview(payload)
            while view:
                check()
                if selector.select(.1):
                    view = view[os.write(_worker.stdin.fileno(), view):]
            selector.unregister(_worker.stdin)
            selector.register(_worker.stdout, selectors.EVENT_READ)
            output = bytearray()
            while True:
                check()
                if not selector.select(.1):
                    continue
                chunk = os.read(_worker.stdout.fileno(), 65536)
                if not chunk:
                    raise ValueError('Служба камеры завершилась без подтверждения')
                output.extend(chunk)
                if len(output) > 3 * 1024 * 1024:
                    raise ValueError('Слишком большой ответ камеры')
                if b'\n' in output:
                    return json.loads(output)
    except Exception:
        stop_worker()
        raise
    finally:
        _worker_lock.release()


def main():
    if '--persistent' in sys.argv:
        while True:
            line = sys.stdin.buffer.readline(3 * 1024 * 1024 + 1)
            if not line:
                return
            if len(line) > 3 * 1024 * 1024 or not line.endswith(b'\n'):
                return
            print(json.dumps(dispatch(json.loads(line)), ensure_ascii=False), flush=True)
    else:
        print(json.dumps(dispatch(json.loads(sys.stdin.buffer.read(3 * 1024 * 1024))), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
