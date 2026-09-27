import os,time,threading
import pytest
from master.lan_control import write_frame


def test_frame_written_exactly_once():
    r,w=os.pipe()
    try:
        os.set_blocking(w,False)
        with os.fdopen(w,'wb',buffering=0,closefd=False) as stream:
            write_frame(stream,b'abcdefgh',time.monotonic()+1,threading.Event())
        assert os.read(r,100)==b'\x00\x08abcdefgh'
    finally:os.close(r);os.close(w)


def test_full_pipe_does_not_hang_writer():
    r,w=os.pipe()
    try:
        os.set_blocking(w,False)
        while True:
            try:os.write(w,b'x'*4096)
            except BlockingIOError:break
        began=time.monotonic()
        with os.fdopen(w,'wb',buffering=0,closefd=False) as stream,pytest.raises(TimeoutError):
            write_frame(stream,b'abcdefgh',began+.1,threading.Event())
        assert time.monotonic()-began<1
    finally:os.close(r);os.close(w)


def test_cancelled_frame_is_not_sent():
    r,w=os.pipe()
    try:
        os.set_blocking(w,False);os.set_blocking(r,False)
        event=threading.Event();event.set()
        with os.fdopen(w,'wb',buffering=0,closefd=False) as stream,pytest.raises(TimeoutError):
            write_frame(stream,b'abcdefgh',time.monotonic()+1,event)
        with pytest.raises(BlockingIOError):os.read(r,100)
    finally:os.close(r);os.close(w)
