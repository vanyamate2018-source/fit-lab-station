from pathlib import Path

from shared.config import StationConfig, save_local_config
from shared.storage import ensure_directories, probe_storage


def test_required_directories(tmp_path: Path) -> None:
    config = StationConfig(data_root=tmp_path / "fit-lab-data")
    ensure_directories(config.data_root, config.required_directories())

    assert config.data_root.is_dir()
    for path in config.required_directories():
        assert path.is_dir()


def test_probe_storage_is_writable(tmp_path: Path) -> None:
    status = probe_storage(tmp_path)

    assert status.exists is True
    assert status.writable is True
    assert status.total_bytes > 0
    assert status.free_bytes > 0


def test_local_config_round_trip(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "station.json"
    data_root = tmp_path / "data"

    monkeypatch.setenv("FIT_LAB_CONFIG", str(config_path))
    monkeypatch.delenv("FIT_LAB_DATA_ROOT", raising=False)

    saved = save_local_config(StationConfig(data_root=data_root))

    assert saved == config_path
    loaded = StationConfig.load()
    assert loaded.data_root == data_root
