"""Create the local SSD launcher and Finder icon; no system installation."""
import os
import plistlib
import subprocess
import sysconfig
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtCore import Qt


def main():
    root = Path(__file__).resolve().parents[2]
    project = root / "project"
    bundle = root / "FIT-LAB Station.app" / "Contents"
    for name in ("MacOS", "Resources"):
        (bundle / name).mkdir(parents=True, exist_ok=True)
    native = root / "data/cache/native"
    native.mkdir(parents=True, exist_ok=True)
    credential_build = native / 'camera-credentials-next.dylib'
    subprocess.run(['xcrun', 'clang', '-Wall', '-Wextra', '-O2', '-fobjc-arc', '-dynamiclib',
                    '-framework', 'Foundation', '-framework', 'Security', '-framework', 'LocalAuthentication',
                    str(project / 'tools/native/camera_credentials.m'), '-o', str(credential_build)], check=True)
    credential_build.replace(native / 'camera-credentials.dylib')
    native_build = native / "media-activity-next.dylib"
    subprocess.run(["xcrun", "clang", "-Wall", "-O2", "-dynamiclib", "-framework", "Foundation",
                    str(project / "tools/native/media_activity.m"), "-o", str(native_build)], check=True)
    native_build.replace(native / "media-activity.dylib")
    usb_build = native / 'usb-inventory-next.dylib'
    subprocess.run(['xcrun', 'clang', '-Wall', '-Wextra', '-O2', '-dynamiclib',
                    '-framework', 'CoreFoundation', '-framework', 'IOKit',
                    str(project / 'tools/native/usb_inventory.c'), '-o', str(usb_build)], check=True)
    usb_build.replace(native / 'usb-inventory.dylib')
    iconset = root / "data/cache/app-icon.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    image = QImage(str(project / "master/assets/app-icon.png"))
    if image.isNull():
        raise RuntimeError("Не найдена иконка Vector")
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            suffix = "@2x" if scale == 2 else ""
            image.scaled(size * scale, size * scale, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation).save(str(iconset / f"icon_{size}x{size}{suffix}.png"))
    subprocess.run(["/usr/bin/iconutil", "-c", "icns", "-o", str(bundle / "Resources/FIT-LAB-Vector.icns"), str(iconset)], check=True)
    (bundle / "Resources/FIT-LAB.icns").unlink(missing_ok=True)
    (bundle / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleName": "FIT-LAB Station", "CFBundleDisplayName": "FIT-LAB Station",
        "CFBundleIdentifier": "lab.fit.station", "CFBundleVersion": "0.3.1",
        "CFBundleShortVersionString": "0.3.1", "CFBundleExecutable": "FIT-LAB",
        "CFBundleIconFile": "FIT-LAB-Vector.icns", "CFBundlePackageType": "APPL",
        "NSHighResolutionCapable": True,
    }))
    executable = bundle / "MacOS/FIT-LAB"
    subprocess.run(["xcrun", "clang", "-Wall", "-O2", "-framework", "Foundation",
                    "-I" + sysconfig.get_config_var("INCLUDEPY"),
                    "-F" + sysconfig.get_config_var("PYTHONFRAMEWORKPREFIX"), "-framework", "Python",
                    str(project / "tools/native/station_launcher.m"), "-o", str(executable)], check=True)
    executable.chmod(0o755)
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(bundle.parent)], check=True)
    print(bundle.parent)


if __name__ == "__main__":
    main()
