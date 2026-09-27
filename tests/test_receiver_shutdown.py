"""Repeated Stop/Quit must still release the receiver's child processes."""
import os
import signal
import subprocess
import sys
from unittest.mock import Mock

from receiver.process_cleanup import stop_children


def test_stuck_control_child_cannot_skip_usb_shutdown():
    order = []
    stuck = Mock(pid=123)
    stuck.poll.return_value = None
    stuck.wait.side_effect = subprocess.TimeoutExpired('control', 0)
    usb = Mock(pid=456)
    usb.poll.return_value = None
    for label, child in [('control', stuck), ('usb', usb)]:
        child.terminate.side_effect = lambda label=label: order.append('term-' + label)
        child.kill.side_effect = lambda label=label: order.append('kill-' + label)
    assert stop_children([stuck, usb], grace=0, kill_grace=0) == [123]
    assert order == ['term-control', 'term-usb', 'kill-control', 'kill-usb']
    assert usb.wait.call_count == 2


def test_second_stop_does_not_interrupt_child_cleanup():
    script = '''
import signal, subprocess, sys, time
from receiver.dual_radio import stop_once
signal.signal(signal.SIGTERM, stop_once)
signal.signal(signal.SIGINT, stop_once)
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
try:
    print('ready', flush=True)
    while True: time.sleep(.1)
except KeyboardInterrupt:
    pass
finally:
    print('cleaning', flush=True)
    time.sleep(.15)
    child.terminate()
    child.wait(timeout=2)
    print('released', flush=True)
'''
    process = subprocess.Popen([sys.executable, '-u', '-c', script], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'ready'
        process.send_signal(signal.SIGTERM)
        assert process.stdout.readline().strip() == 'cleaning'
        process.send_signal(signal.SIGTERM)
        process.send_signal(signal.SIGINT)
        output, errors = process.communicate(timeout=5)
        assert process.returncode == 0 and output.strip() == 'released', errors
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
