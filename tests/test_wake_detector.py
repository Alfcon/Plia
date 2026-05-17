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


@pytest.fixture
def detector_with_fake_models(tmp_path, settings_two_models):
    with patch.object(wake_detector, "_oww_model_class") as mock_ctor:
        oww = MagicMock()
        oww.prediction_buffer = {"plia": [], "hey_jarvis": []}
        oww.scores = {"plia": 0.0, "hey_jarvis": 0.0}
        oww.predict = lambda chunk: dict(oww.scores)
        mock_ctor.return_value = oww
        d = wake_detector.WakeDetector(
            wake_models=settings_two_models,
            models_base=tmp_path,
            recorder=None,
        )
        d._load_models()
    return d, oww


def test_predict_above_threshold_emits_signal(detector_with_fake_models):
    d, oww = detector_with_fake_models
    emitted = []
    d.wake_word_detected.connect(emitted.append)

    oww.scores = {"plia": 0.9, "hey_jarvis": 0.0}
    chunk = np.zeros(wake_detector.CHUNK_SAMPLES, dtype=np.int16)
    d._process_chunk(chunk)

    assert emitted == ["plia"]


def test_predict_below_threshold_does_not_emit(detector_with_fake_models):
    d, oww = detector_with_fake_models
    emitted = []
    d.wake_word_detected.connect(emitted.append)

    oww.scores = {"plia": 0.4, "hey_jarvis": 0.5}  # both below their thresholds
    chunk = np.zeros(wake_detector.CHUNK_SAMPLES, dtype=np.int16)
    d._process_chunk(chunk)

    assert emitted == []


def test_cooldown_suppresses_second_trigger(detector_with_fake_models):
    d, oww = detector_with_fake_models
    emitted = []
    d.wake_word_detected.connect(emitted.append)

    oww.scores = {"plia": 0.9}
    chunk = np.zeros(wake_detector.CHUNK_SAMPLES, dtype=np.int16)
    d._process_chunk(chunk)
    d._process_chunk(chunk)
    assert emitted == ["plia"]   # only the first


def test_cooldown_expires(detector_with_fake_models, monkeypatch):
    d, oww = detector_with_fake_models
    fake_time = [1000.0]
    monkeypatch.setattr(wake_detector.time, "monotonic", lambda: fake_time[0])
    emitted = []
    d.wake_word_detected.connect(emitted.append)

    oww.scores = {"plia": 0.9}
    chunk = np.zeros(wake_detector.CHUNK_SAMPLES, dtype=np.int16)
    d._process_chunk(chunk)
    fake_time[0] += wake_detector.COOLDOWN_SEC + 0.1
    d._process_chunk(chunk)
    assert emitted == ["plia", "plia"]


def test_chunk_fed_to_recorder_when_listening(detector_with_fake_models):
    d, oww = detector_with_fake_models
    recorder = MagicMock()
    recorder.is_listening = True
    d._recorder = recorder

    oww.scores = {"plia": 0.9}  # would otherwise fire
    chunk = np.zeros(wake_detector.CHUNK_SAMPLES, dtype=np.int16)
    d._process_chunk(chunk)

    recorder.feed_audio.assert_called_once()
    # predict() must NOT be consulted while listening — emit nothing
    emitted = []
    d.wake_word_detected.connect(emitted.append)
    assert emitted == []
