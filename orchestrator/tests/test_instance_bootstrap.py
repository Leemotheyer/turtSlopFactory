import pytest

from app.services.instance_bootstrap import ensure_encryption_key


def test_ensure_encryption_key_persists(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.instance_bootstrap._KEY_FILE", tmp_path / ".factory" / "encryption.key")
    monkeypatch.setattr("app.config.settings.secrets_encryption_key", None)

    key1 = ensure_encryption_key()
    key2 = ensure_encryption_key()
    assert key1 == key2
    assert len(key1) == 44


def test_ensure_encryption_key_uses_env(monkeypatch):
    monkeypatch.setattr("app.config.settings.secrets_encryption_key", "test-env-key")
    assert ensure_encryption_key() == "test-env-key"
