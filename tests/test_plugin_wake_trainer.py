"""Plugin tool sanity tests — no real training, just contract."""

from pathlib import Path

import pytest

from config import WAKE_TRAINER_ENABLED


def _load_plugin():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "plugins_wake_trainer",
        Path(__file__).parent.parent / "plugins" / "wake_trainer.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(
    not WAKE_TRAINER_ENABLED,
    reason="in-app trainer paused — see config.WAKE_TRAINER_ENABLED",
)
def test_tool_train_wake_word_validates_word():
    mod = _load_plugin()
    result = mod.tool_train_wake_word({"word": ""})
    assert result["success"] is False
    assert "word is required" in result["message"].lower()


@pytest.mark.skipif(
    not WAKE_TRAINER_ENABLED,
    reason="in-app trainer paused — see config.WAKE_TRAINER_ENABLED",
)
def test_tool_train_wake_word_delegates_to_core(monkeypatch):
    mod = _load_plugin()

    captured = {}

    def fake_train(word, **kwargs):
        captured["word"] = word
        captured["variants"] = kwargs.get("variants")
        return Path("/tmp/fake.onnx")

    monkeypatch.setattr(mod, "train_wake_word", fake_train)
    result = mod.tool_train_wake_word({"word": "plia", "variants": 1000})
    assert result["success"] is True
    assert captured["word"] == "plia"
    assert captured["variants"] == 1000
    assert result["data"]["path"].endswith("fake.onnx")


@pytest.mark.skipif(
    WAKE_TRAINER_ENABLED,
    reason="paused-behaviour guard; only runs while WAKE_TRAINER_ENABLED is False",
)
def test_tool_train_wake_word_returns_paused_message_when_disabled(monkeypatch):
    mod = _load_plugin()

    def boom(*a, **kw):
        raise AssertionError("train_wake_word must not be called while paused")
    monkeypatch.setattr(mod, "train_wake_word", boom)

    result = mod.tool_train_wake_word({"word": "plia"})
    assert result["success"] is False
    assert "paused" in result["message"].lower()
    assert "colab" in result["message"].lower()
