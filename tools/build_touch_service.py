"""Build the optional macOS-wide MPI7009 bridge on the SSD."""
import plistlib
import subprocess
from pathlib import Path

root = Path('/Volumes/FIT-LAB')
project = root / 'project'
bundle = root / 'FIT-LAB Touch.app/Contents'
(bundle / 'MacOS').mkdir(parents=True, exist_ok=True)
(bundle / 'Resources').mkdir(exist_ok=True)
executable = bundle / 'MacOS/FIT-LAB Touch'
subprocess.run(['xcrun','clang++','-std=c++17','-fobjc-arc','-Wall','-O2',
    '-framework','AppKit','-framework','ApplicationServices','-framework','IOKit',
    '-framework','ServiceManagement',str(project/'tools/native/touch_service.mm'),'-o',str(executable)], check=True)
(bundle / 'Info.plist').write_bytes(plistlib.dumps({
    'CFBundleName':'FIT-LAB Touch','CFBundleDisplayName':'FIT-LAB Touch',
    'CFBundleIdentifier':'lab.fit.touch','CFBundleVersion':'1','CFBundleShortVersionString':'0.1',
    'CFBundleExecutable':'FIT-LAB Touch','CFBundlePackageType':'APPL','LSUIElement':True,
    'LSMinimumSystemVersion':'13.0','NSHighResolutionCapable':True,
}))
subprocess.run(['codesign','--force','--sign','-','--identifier','lab.fit.touch',str(bundle.parent)],check=True)
print(bundle.parent)
