"""Bounded shutdown: one stuck child must not retain the other USB devices."""
import subprocess
import time


def stop_children(children, grace=3, kill_grace=1):
    children = list(dict.fromkeys(child for child in children if child is not None))
    for child in children:
        try:
            if child.poll() is None:
                child.terminate()
        except OSError:
            pass
    deadline = time.monotonic() + grace
    for child in children:
        try:
            child.wait(timeout=max(0, deadline - time.monotonic()))
        except (subprocess.TimeoutExpired, OSError):
            pass
    # Kill every remaining child before waiting on any one of them. A macOS
    # process delayed in kernel teardown may outlive even SIGKILL briefly.
    for child in children:
        try:
            if child.poll() is None:
                child.kill()
        except OSError:
            pass
    deadline = time.monotonic() + kill_grace
    pending = []
    for child in children:
        try:
            child.wait(timeout=max(0, deadline - time.monotonic()))
        except (subprocess.TimeoutExpired, OSError):
            pending.append(child.pid)
    return pending
