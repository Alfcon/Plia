"""Tests for WakeDetector (mic-owning openWakeWord wrapper)."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core import wake_detector


@pytest.fixture
def fake_oww_model():
    """A MagicMock standing in for openwakeword.model.Model.

    `.predict(chunk)` returns whatever was last set in `scores`.
    """
    fake = MagicMock()
    fake.scores = {"plia": 0.0, "hey_jarvis": 0.0}
    fake.predict = lambda chunk: dict(fake.scores)
    return fake


@pytest.fixture
def settings_two_models():
    return [
        {"id": "plia", "display": "Plia", "path": "bundled/plia.onnx",
         "enabled": True, "sensitivity": 0.5, "builtin": True},
        {"id": "hey_jarvis", "display": "Hey Jarvis", "path": "bundled/hey_jarvis.onnx",
         "enabled": True, "sensitivity": 0.6, "builtin": True},
    ]


def test_load_models_passes_only_enabled_paths(tmp_path, settings_two_models):
    """Disabled models must not be passed to openwakeword.Model."""
    settings_two_models[1]["enabled"] = False
    captured = {}

    def fake_model_ctor(wakeword_models, inference_framework):
        captured["paths"] = wakeword_models
        m = MagicMock()
        m.prediction_buffer = {"plia": []}
        return m

    with patch.object(wake_detector, "_oww_model_class", fake_model_ctor):
        d = wake_detector.WakeDetector(
            wake_models=settings_two_models,
            models_base=tmp_path,
            recorder=None,
        )
        d._load_models()

    assert any(p.endswith("plia.onnx") for p in captured["paths"])
    assert all(not p.endswith("hey_jarvis.onnx") for p in captured["paths"])


def test_thresholds_populated_from_settings(tmp_path, settings_two_models):
    with patch.object(wake_detector, "_oww_model_class") as mock_ctor:
        mock_ctor.return_value = MagicMock(prediction_buffer={"plia": [], "hey_jarvis": []})
        d = wake_detector.WakeDetector(
            wake_models=settings_two_models,
            models_base=tmp_path,
            recorder=None,
        )
        d._load_models()
    assert d.thresholds == {"plia": 0.5, "hey_jarvis": 0.6}


def test_load_models_skips_broken_onnx_and_keeps_others(tmp_path, settings_two_models):
    """If one .onnx fails to load, the other still works and a warning is emitted."""

    def fake_model_ctor(wakeword_models, inference_framework):
        # First call: raise. Second call (single model): succeed.
        if len(wakeword_models) > 1:
            raise RuntimeError("bad .onnx")
        m = MagicMock()
        m.prediction_buffer = {"plia": []}
        return m

    with patch.object(wake_detector, "_oww_model_class", fake_model_ctor):
        d = wake_detector.WakeDetector(
            wake_models=settings_two_models,
            models_base=tmp_path,
            recorder=None,
        )
        errors = []
        d.error.connect(errors.append)
        d._load_models()

    # With this fake, both singles validate but every combined load raises,
    # so exactly one survivor is kept — the LAST one tried (hey_jarvis).
    assert d.thresholds == {"hey_jarvis": 0.6}
    assert any("could not load" in e.lower() or "skipped" in e.lower() for e in errors)


def test_combined_fail_with_three_singles_aligns_kept_id_and_model(tmp_path):
    """Regression: when 3+ models validate singly but combine fails, the kept
    id in thresholds must match the kept Model instance."""
    settings = [
        {"id": "plia", "display": "Plia", "path": "bundled/plia.onnx",
         "enabled": True, "sensitivity": 0.5, "builtin": True},
        {"id": "hey_jarvis", "display": "Hey Jarvis", "path": "bundled/hey_jarvis.onnx",
         "enabled": True, "sensitivity": 0.6, "builtin": True},
        {"id": "alexa", "display": "Alexa", "path": "bundled/alexa.onnx",
         "enabled": True, "sensitivity": 0.7, "builtin": True},
    ]

    instances_by_path = {}

    def fake_model_ctor(wakeword_models, inference_framework):
        # Any combined load (>1 paths) raises. Singles succeed and return
        # a unique sentinel MagicMock per path.
        if len(wakeword_models) > 1:
            raise RuntimeError("bad combined")
        path = wakeword_models[0]
        if path not in instances_by_path:
            inst = MagicMock(name=f"Model<{path}>")
            inst.prediction_buffer = {Path(path).stem: []}
            instances_by_path[path] = inst
        return instances_by_path[path]

    with patch.object(wake_detector, "_oww_model_class", fake_model_ctor):
        d = wake_detector.WakeDetector(
            wake_models=settings,
            models_base=tmp_path,
            recorder=None,
        )
        d._load_models()

    # Exactly one survivor — the LAST one tried (alexa).
    assert d.thresholds == {"alexa": 0.7}
    # The Model instance must be the one created for alexa, not plia.
    expected_inst = instances_by_path[str(tmp_path / "bundled/alexa.onnx")]
    assert d._oww is expected_inst
