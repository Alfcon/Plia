"""Tests for one-time migration from voice.wake_word → voice.wake_models."""
import json
from pathlib import Path

import pytest

from core import settings_store


def _seed_old_config(tmp_path: Path, wake_word: str = "jarvis", sensitivity: float = 0.4) -> Path:
    cfg_dir = tmp_path / ".plia"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "settings.json"
    cfg_file.write_text(json.dumps({
        "voice": {
            "wake_word": wake_word,
            "sensitivity": sensitivity,
            "enabled": True,
        }
    }))
    return cfg_file


def _load(monkeypatch, tmp_path):
    """Force the singleton to use a fresh tmp_path config."""
    monkeypatch.setattr(settings_store, "Path", Path)  # ensure Path is the real one
    store = settings_store.SettingsStore.__new__(settings_store.SettingsStore)
    # re-init the way __init__ does, but pointing at tmp
    import threading
    store._lock = threading.RLock()
    store._settings = {}
    store._settings_dir = tmp_path / ".plia"
    store._settings_file = tmp_path / ".plia" / "settings.json"
    # QObject.__init__ requires explicit call
    from PySide6.QtCore import QObject
    QObject.__init__(store)
    store._load()
    return store


def test_jarvis_migrates_to_hey_jarvis_plus_plia(tmp_path, monkeypatch):
    _seed_old_config(tmp_path, wake_word="jarvis")
    store = _load(monkeypatch, tmp_path)

    models = store.get("voice.wake_models")
    assert isinstance(models, list)
    ids = [m["id"] for m in models]
    assert "hey_jarvis" in ids
    assert "plia" in ids
    enabled_ids = {m["id"] for m in models if m["enabled"]}
    assert enabled_ids == {"hey_jarvis", "plia"}

    # Old keys removed
    assert store.get("voice.wake_word") is None
    assert store.get("voice.sensitivity") is None


def test_unknown_word_falls_back_with_toast_flag(tmp_path, monkeypatch):
    _seed_old_config(tmp_path, wake_word="americano")
    store = _load(monkeypatch, tmp_path)

    enabled_ids = {m["id"] for m in store.get("voice.wake_models") if m["enabled"]}
    assert enabled_ids == {"hey_jarvis", "plia"}
    assert store.get("voice._migration_toast_pending") is True


def test_migration_is_idempotent(tmp_path, monkeypatch):
    _seed_old_config(tmp_path, wake_word="jarvis")
    store1 = _load(monkeypatch, tmp_path)
    snap1 = store1.get("voice.wake_models")

    store2 = _load(monkeypatch, tmp_path)
    snap2 = store2.get("voice.wake_models")
    assert snap1 == snap2


def test_existing_new_schema_left_alone(tmp_path, monkeypatch):
    cfg_dir = tmp_path / ".plia"
    cfg_dir.mkdir()
    custom_models = [
        {"id": "plia", "display": "Plia", "path": "bundled/plia.onnx",
         "enabled": True, "sensitivity": 0.6, "builtin": True}
    ]
    (cfg_dir / "settings.json").write_text(json.dumps({
        "voice": {"wake_models": custom_models, "enabled": True}
    }))
    store = _load(monkeypatch, tmp_path)
    assert store.get("voice.wake_models") == custom_models
