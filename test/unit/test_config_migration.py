import json
from pathlib import Path

from src.core.config_manager import ConfigManager
from src.core.runtime_paths import get_config_path


def test_default_config_migrates_legacy_working_directory_config(tmp_path, monkeypatch):
    app_data = tmp_path / "app-data"
    legacy_dir = tmp_path / "legacy-workdir"
    legacy_dir.mkdir()
    legacy_config = {"window_geometry": {"x": 10, "width": 123}, "legacy": True}
    (legacy_dir / "config.json").write_text(
        json.dumps(legacy_config), encoding="utf-8"
    )
    monkeypatch.setenv("MOZIKIT_APP_DATA_DIR", str(app_data))
    monkeypatch.chdir(legacy_dir)

    manager = ConfigManager()

    assert manager.config_file == get_config_path()
    assert manager.config_file.is_absolute()
    assert manager.config == legacy_config
    assert json.loads(manager.config_file.read_text(encoding="utf-8")) == legacy_config


def test_default_config_does_not_overwrite_existing_app_data_config(tmp_path, monkeypatch):
    app_data = tmp_path / "app-data"
    legacy_dir = tmp_path / "legacy-workdir"
    legacy_dir.mkdir()
    existing_config = {"window_geometry": {"x": 99}, "source": "new"}
    legacy_config = {"window_geometry": {"x": 1}, "source": "legacy"}
    target = app_data / "config.json"
    app_data.mkdir()
    target.write_text(json.dumps(existing_config), encoding="utf-8")
    (legacy_dir / "config.json").write_text(
        json.dumps(legacy_config), encoding="utf-8"
    )
    monkeypatch.setenv("MOZIKIT_APP_DATA_DIR", str(app_data))
    monkeypatch.chdir(legacy_dir)

    manager = ConfigManager()

    assert manager.config == existing_config
    assert json.loads(target.read_text(encoding="utf-8")) == existing_config
