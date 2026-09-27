"""Keep the application's GStreamer registry and plugin selection on its data disk."""
import os
import sys
from pathlib import Path


def media_environment(data_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    cache = data_root / "cache" / "gstreamer"
    cache.mkdir(parents=True, exist_ok=True)
    env["GST_REGISTRY"] = str(cache / "registry.bin")
    env["PYTHONPYCACHEPREFIX"] = str(data_root / "cache" / "python")
    if sys.platform == "darwin":
        # Only load the media plugins this application uses. Loading unrelated
        # GTK/Python plugins can conflict with Qt or hang a first registry scan.
        source = Path("/opt/homebrew/lib/gstreamer-1.0")
        plugins = cache / "plugins"
        plugins.mkdir(exist_ok=True)
        for name in ("coreelements", "app", "udp", "rtp", "rtpmanager", "videoparsersbad",
                     "applemedia", "videoconvertscale", "libav", "typefindfunctions",
                     "videotestsrc", "videorate", "matroska", "x264", "rtspclientsink", "rtsp", "tcp",
                     "audioconvert", "audioresample", "opus", "audioparsers", "osxaudio", "level", "volume", "alaw", "mulaw"):
            target = source / f"libgst{name}.dylib"
            link = plugins / target.name
            if target.is_file() and not link.exists():
                link.symlink_to(target)
        env["GST_PLUGIN_SYSTEM_PATH"] = str(plugins)
        env["GST_PLUGIN_PATH"] = ""
        env["DYLD_FALLBACK_LIBRARY_PATH"] = "/opt/homebrew/lib:/usr/lib"
        gi_path = f"/opt/homebrew/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (env.get("PYTHONPATH"), gi_path)))
    if sys.platform == 'linux':
        libraries = data_root.parent / 'gst-runtime/usr/lib/aarch64-linux-gnu'
        if libraries.is_dir():
            env['GST_PLUGIN_PATH'] = str(libraries / 'gstreamer-1.0')
            env['LD_LIBRARY_PATH'] = str(libraries) + os.pathsep + env.get('LD_LIBRARY_PATH', '')
    return env
