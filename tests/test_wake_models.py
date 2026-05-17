"""Tests for wake-model discovery and reconciliation."""
from pathlib import Path

import pytest

from core import wake_models


def _make_models_dir(tmp_path: Path) -> Path:
    base = tmp_path / "models" / "wake"
    (base / "bundled").mkdir(parents=True)
    (base / "custom").mkdir(parents=True)
    return base


def test_discover_finds_bundled_and_custom_onnx(tmp_path):
    base = _make_models_dir(tmp_path)
    (base / "bundled" / "hey_jarvis.onnx").write_bytes(b"x")
    (base / "custom" / "myword.onnx").write_bytes(b"x")
    (base / "bundled" / "README.md").write_text("ignore me")

    found = wake_models.discover_wake_models(base)
    by_id = {m["id"]: m for m in found}

    assert "hey_jarvis" in by_id
    assert by_id["hey_jarvis"]["builtin"] is True
    assert by_id["hey_jarvis"]["path"] == "bundled/hey_jarvis.onnx"

    assert "myword" in by_id
    assert by_id["myword"]["builtin"] is False
    assert by_id["myword"]["path"] == "custom/myword.onnx"


def test_reconcile_adds_new_file_with_enabled_false(tmp_path):
    base = _make_models_dir(tmp_path)
    (base / "custom" / "new.onnx").write_bytes(b"x")

    existing = [
        {"id": "plia", "display": "Plia", "path": "bundled/plia.onnx",
         "enabled": True, "sensitivity": 0.5, "builtin": True},
    ]
    reconciled = wake_models.reconcile_with_settings(existing, base)
    by_id = {m["id"]: m for m in reconciled}

    assert "plia" in by_id
    assert by_id["plia"]["enabled"] is True  # untouched
    assert "new" in by_id
    assert by_id["new"]["enabled"] is False
    assert by_id["new"]["sensitivity"] == 0.5
    assert by_id["new"]["builtin"] is False


def test_reconcile_marks_missing_file_broken(tmp_path):
    base = _make_models_dir(tmp_path)
    # No files exist on disk.
    existing = [
        {"id": "plia", "display": "Plia", "path": "bundled/plia.onnx",
         "enabled": True, "sensitivity": 0.5, "builtin": True},
    ]
    reconciled = wake_models.reconcile_with_settings(existing, base)
    plia = next(m for m in reconciled if m["id"] == "plia")
    assert plia.get("broken") is True
    # Settings row is preserved, not removed.
    assert len(reconciled) == 1


def test_reconcile_clears_broken_flag_when_file_returns(tmp_path):
    base = _make_models_dir(tmp_path)
    (base / "bundled" / "plia.onnx").write_bytes(b"x")
    existing = [
        {"id": "plia", "display": "Plia", "path": "bundled/plia.onnx",
         "enabled": True, "sensitivity": 0.5, "builtin": True, "broken": True},
    ]
    reconciled = wake_models.reconcile_with_settings(existing, base)
    plia = next(m for m in reconciled if m["id"] == "plia")
    assert plia.get("broken", False) is False


def test_discover_collision_suffix(tmp_path):
    """A custom .onnx with the same stem as a bundled one gets a _1 suffix."""
    base = _make_models_dir(tmp_path)
    (base / "bundled" / "plia.onnx").write_bytes(b"x")
    (base / "custom" / "plia.onnx").write_bytes(b"x")

    found = wake_models.discover_wake_models(base)
    ids = sorted(m["id"] for m in found)
    assert "plia" in ids
    assert "plia_1" in ids


def test_reconcile_disambiguates_when_bundled_appears_after_custom(tmp_path):
    """Bundled file appearing after custom already in settings → no duplicate ids."""
    base = _make_models_dir(tmp_path)
    (base / "custom" / "plia.onnx").write_bytes(b"x")
    existing = [
        {"id": "plia", "display": "Plia", "path": "custom/plia.onnx",
         "enabled": True, "sensitivity": 0.5, "builtin": False},
    ]
    # Now bundled appears.
    (base / "bundled" / "plia.onnx").write_bytes(b"x")
    reconciled = wake_models.reconcile_with_settings(existing, base)

    ids = [m["id"] for m in reconciled]
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"
    # The settings-anchored entry keeps its id.
    saved = next(m for m in reconciled if m["path"] == "custom/plia.onnx")
    assert saved["id"] == "plia"
    # The newly-discovered bundled entry gets a unique id.
    new_entry = next(m for m in reconciled if m["path"] == "bundled/plia.onnx")
    assert new_entry["id"] != "plia"
    assert new_entry["builtin"] is True


def test_models_dir_resolves_under_project_root():
    p = wake_models.models_dir()
    assert p.name == "wake"
    assert p.parent.name == "models"
    assert p.is_absolute()
