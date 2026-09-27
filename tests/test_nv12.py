import ctypes.util
import pytest
from master.nv12 import NV12Converter

pytestmark=pytest.mark.skipif(not ctypes.util.find_library('swscale'),reason='libswscale unavailable')


def test_padded_camera_surface_preserves_visible_pixels():
    convert=NV12Converter(4,2)
    try:
        raw=bytes([16]*4+[99]*4+[235]*4+[99]*4+[128]*4+[99]*4)
        output=bytearray(4*2*4)
        convert.convert(raw,[8,8],[0,16],output)
        assert all(v <= 2 for v in output[:3])
        assert all(v >= 250 for v in output[16:19])
        assert output[3]==output[19]==255
        with pytest.raises(ValueError): convert.convert(raw,[8,8],[0,23],output)
    finally: convert.close()
