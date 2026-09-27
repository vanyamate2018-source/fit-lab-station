"""Convert a copied MPP surface in cached RAM instead of rereading DMA pixels."""
import ctypes as C
import ctypes.util


class NV12Converter:
    def __init__(self, width, height):
        if not (0 < width <= 4096 and 0 < height <= 2160):
            raise ValueError('Invalid frame dimensions')
        self.width, self.height = width, height
        self.lib = C.CDLL(ctypes.util.find_library('swscale'))
        av = C.CDLL(ctypes.util.find_library('avutil'))
        av.av_get_pix_fmt.argtypes = [C.c_char_p]; av.av_get_pix_fmt.restype = C.c_int
        ptr = C.POINTER(C.c_uint8)
        self.lib.sws_getContext.argtypes = [C.c_int]*7 + [C.c_void_p]*3
        self.lib.sws_getContext.restype = C.c_void_p
        self.lib.sws_scale.argtypes = [C.c_void_p,C.POINTER(ptr),C.POINTER(C.c_int),C.c_int,C.c_int,C.POINTER(ptr),C.POINTER(C.c_int)]
        self.lib.sws_scale.restype = C.c_int
        self.lib.sws_freeContext.argtypes = [C.c_void_p]
        self.context = self.lib.sws_getContext(width,height,av.av_get_pix_fmt(b'nv12'),width,height,av.av_get_pix_fmt(b'rgba'),2,None,None,None)
        if not self.context: raise RuntimeError('Не удалось подготовить цветопреобразование')

    def convert(self, raw, strides, offsets, output):
        if len(output) < self.width*self.height*4:
            raise ValueError('Small output buffer')
        for plane, rows in ((0,self.height),(1,(self.height+1)//2)):
            if strides[plane] < self.width or offsets[plane] < 0 or offsets[plane]+(rows-1)*strides[plane]+self.width > len(raw):
                raise ValueError('Invalid NV12 surface layout')
        ptr = C.POINTER(C.c_uint8)
        source = C.c_char_p(raw)  # The bytes object stays alive throughout sws_scale.
        address = C.cast(source,C.c_void_p).value
        sources = (ptr*4)(C.cast(address+offsets[0],ptr), C.cast(address+offsets[1],ptr),ptr(),ptr())
        source_lines = (C.c_int*4)(strides[0],strides[1],0,0)
        destination = (C.c_uint8*len(output)).from_buffer(output)
        destinations = (ptr*4)(C.cast(destination,ptr),ptr(),ptr(),ptr())
        lines = (C.c_int*4)(self.width*4,0,0,0)
        if self.lib.sws_scale(self.context,sources,source_lines,0,self.height,destinations,lines) != self.height:
            raise RuntimeError('Неполное преобразование кадра')

    def close(self):
        if self.context:
            self.lib.sws_freeContext(self.context); self.context = None
