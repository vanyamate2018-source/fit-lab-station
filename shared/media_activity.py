"""A scoped native macOS activity for real-time reception, never global settings."""
import ctypes
import sys
from pathlib import Path


class MediaActivity:
    def __init__(self, root: Path):
        self.library = None
        self.token = None
        if sys.platform == "darwin":
            try:
                self.library = ctypes.CDLL(str(root / "cache/native/media-activity.dylib"))
                self.library.fitlab_media_begin.argtypes = []
                self.library.fitlab_media_begin.restype = ctypes.c_void_p
                self.library.fitlab_media_end.argtypes = [ctypes.c_void_p]
                self.library.fitlab_media_end.restype = None
            except OSError:
                self.library = None

    def start(self):
        if self.library is not None and not self.token:
            self.token = self.library.fitlab_media_begin()
        return bool(self.token)

    def close(self):
        if self.token:
            self.library.fitlab_media_end(self.token)
            self.token = None
