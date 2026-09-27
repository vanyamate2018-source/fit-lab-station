import json
import subprocess
import sys
import threading
from unittest.mock import patch
import pytest
from master import camera_worker as worker


def test_reuses_one_child_and_restarts_after_exit(tmp_path):
    worker.stop_worker()
    spawn = subprocess.Popen
    program = "import sys,json,os\nfor line in sys.stdin:\n r=json.loads(line);print(json.dumps({'pid':os.getpid(),'state':'ok'}),flush=True)"
    def child(*args, **kwargs):
        return spawn([sys.executable, '-u', '-c', program], **kwargs)
    try:
        with patch.object(worker.subprocess, 'Popen', side_effect=child):
            a=worker.call('radio','host','user','password',tmp_path,transport='radio')
            b=worker.call('radio','host','user','password',tmp_path,transport='radio')
            assert a['pid']==b['pid']
            worker._worker.kill();worker._worker.wait()
            c=worker.call('radio','host','user','password',tmp_path,transport='radio')
            assert c['pid']!=a['pid']
    finally:worker.stop_worker()


def test_cancel_before_send_does_not_spawn(tmp_path):
    worker.stop_worker()
    cancel=threading.Event();cancel.set()
    with patch.object(worker.subprocess,'Popen') as spawn, pytest.raises(ValueError):
        worker.call('radio','host','user','password',tmp_path,transport='radio',cancel=cancel)
    spawn.assert_not_called()
