"""Recording destinations are mounted data disks, never system volumes."""
from dataclasses import dataclass
from pathlib import Path
import os
import re
import sys

@dataclass(frozen=True)
class RecordingVolume:
    root: Path
    name: str
    free: int
    device: bytes


def disk_identity(device):
    name = os.fsdecode(device)
    if sys.platform == 'darwin':
        match = re.match(r'(/dev/disk\d+)', name)
        return match.group(1) if match else name
    if sys.platform == 'linux':
        node = Path('/sys/class/block') / Path(name).name
        if (node / 'partition').exists():
            return str(node.resolve().parent)
        if node.exists(): return str(node.resolve())
    return name


def recording_volumes():
    from PySide6.QtCore import QStorageInfo
    system_paths = [Path('/'), Path.home()]
    if sys.platform == 'darwin':system_paths.append(Path('/System/Volumes/Data'))
    if sys.platform == 'linux':system_paths += [Path('/boot'), Path('/boot/efi')]
    if sys.platform == 'win32':system_paths=[Path(os.environ.get('SystemDrive','C:') + '\\')]
    protected = {disk_identity(bytes(QStorageInfo(str(p)).device())) for p in system_paths if p.exists()}
    volumes=[]
    for storage in QStorageInfo.mountedVolumes():
        device=bytes(storage.device()); root=Path(storage.rootPath()).resolve()
        if not storage.isValid() or not storage.isReady() or storage.isReadOnly() or storage.isRoot():continue
        if disk_identity(device) in protected or storage.bytesTotal() <= 0:continue
        if sys.platform != 'win32' and not os.fsdecode(device).startswith('/dev/'):continue
        if not os.access(root, os.W_OK):continue
        volumes.append(RecordingVolume(root, storage.name() or root.name, storage.bytesAvailable(), device))
    return sorted(volumes,key=lambda v:str(v.root))


def validate_recording_directory(directory, volumes=None):
    directory=Path(directory).resolve()
    for volume in recording_volumes() if volumes is None else volumes:
        try:directory.relative_to(volume.root.resolve())
        except ValueError:continue
        if not volume.root.is_mount():continue
        return volume
    raise ValueError('Выберите накопитель для записи. Системный диск недоступен.')


def prepare_recording_directory(volume):
    # Re-read mounted volumes to reject unplugged or replaced destinations.
    current=next((v for v in recording_volumes() if v.root==volume.root and v.device==volume.device),None)
    if current is None:raise ValueError('Накопитель отключён. Обновите список.')
    directory=current.root/'FIT-LAB'/'Записи'
    validate_recording_directory(directory,[current])
    directory.mkdir(parents=True,exist_ok=True)
    validate_recording_directory(directory,[current])
    return directory
