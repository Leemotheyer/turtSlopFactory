import os

import pytest

from app.services.instance_bootstrap import ensure_encryption_key, load_local_env_overrides


def test_ensure_encryption_key_persists_in_config_dir(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    monkeypatch.setattr("app.services.instance_bootstrap._config_dir", lambda: config_dir)
    monkeypatch.setattr("app.config.settings.secrets_encryption_key", None)
    monkeypatch.setattr("app.config.settings.factory_config_dir", str(config_dir))

    key1 = ensure_encryption_key()
    key2 = ensure_encryption_key()
    assert key1 == key2
    assert (config_dir / "encryption.key").exists()


def test_load_local_env_overrides(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "local.env").write_text("PUBLIC_HOST=test.local\n")
    monkeypatch.setattr("app.services.instance_bootstrap._config_dir", lambda: config_dir)
    monkeypatch.delenv("PUBLIC_HOST", raising=False)

    load_local_env_overrides()
    assert os.environ.get("PUBLIC_HOST") == "test.local"


def test_load_local_env_does_not_override_existing(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "local.env").write_text("PUBLIC_HOST=from-file\n")
    monkeypatch.setattr("app.services.instance_bootstrap._config_dir", lambda: config_dir)
    monkeypatch.setenv("PUBLIC_HOST", "from-env")

    load_local_env_overrides()
    assert os.environ.get("PUBLIC_HOST") == "from-env"
