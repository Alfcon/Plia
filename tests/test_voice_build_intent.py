"""Voice path must dispatch wake-trainer build intents to AgentBuilder.

Regression guard for the gap the audit found: README/plan promised
"Plia, train a wake word for plia" via voice would trigger the in-app
trainer, but the voice path only ran the router (which has no
wake-trainer tool) and the generic creation wizard (which only matches
"create an agent that ..."). The phrase silently fell through to qwen3:8b
text generation.

This test mirrors the chat path's Priority-0 dispatch at
gui/handlers.py:94, narrowly gated on intent.kind == "wake_trainer" so
established voice behaviour for generic "create an agent that ..."
phrases (which routes to the voice creation wizard) is preserved.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


def _build_va(monkeypatch):
    from core import voice_assistant as va_mod
    monkeypatch.setattr(va_mod.tts, "queue_sentence", lambda s: None)
    return va_mod.VoiceAssistant(), va_mod


def test_voice_train_wake_word_calls_build_agent(monkeypatch):
    va, va_mod = _build_va(monkeypatch)
    from core.agent_builder import BuildResult

    captured = {}

    def fake_build_agent(*, intent, ollama_url, model, on_status):
        captured["intent"] = intent
        on_status("stub status")
        return BuildResult(
            success=True,
            agent_name="wake_word_trainer_plia",
            display_name="Wake Word Trainer Plia",
            file_path="/tmp/wake_word_trainer_plia.py",
            message="ok",
        )

    monkeypatch.setattr("core.agent_builder.build_agent", fake_build_agent)

    va._process_query("train a wake word for plia")

    assert "intent" in captured, "build_agent was never called from voice path"
    assert captured["intent"].get("kind") == "wake_trainer"
    assert captured["intent"].get("word") == "plia"


def test_voice_generic_create_agent_does_not_short_circuit_to_build_agent(monkeypatch):
    """The wizard path must still win for generic 'create an agent that ...'
    phrases. Otherwise we'd silently break voice agent creation."""
    va, va_mod = _build_va(monkeypatch)

    build_calls = {"n": 0}

    def fake_build_agent(**kw):
        build_calls["n"] += 1
        raise AssertionError("build_agent must not be called for generic create-agent intents")

    monkeypatch.setattr("core.agent_builder.build_agent", fake_build_agent)

    wizard_calls = {"task": None}
    monkeypatch.setattr(va, "_start_agent_wizard",
                        lambda task: wizard_calls.__setitem__("task", task))

    va._process_query("create an agent that summarises my emails every morning")

    assert build_calls["n"] == 0
    assert wizard_calls["task"] is not None, "wizard should have been started"
