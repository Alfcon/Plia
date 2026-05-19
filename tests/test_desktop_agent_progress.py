"""Desktop agent's live action stream must surface to the UI.

DesktopAgent.run_task_sync already accepts a progress_callback parameter,
but nothing passes one — so users invoking "open notepad and type hello"
hear silence between the start and final result. The 2026-05-19 audit
pass 3 flagged this as a real UX gap.

Coverage:
  - VoiceAssistant exposes a desktop_task_progress Signal(str).
  - VoiceAssistant._handle_desktop_task forwards the callback so each
    agent step emits the signal.
  - FunctionExecutor.execute accepts a `_progress` kwarg and routes it
    into DesktopAgent.run_task_sync.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ── voice_assistant wiring ────────────────────────────────────────────────


def test_voice_assistant_exposes_desktop_progress_signal(qapp):
    from core.voice_assistant import VoiceAssistant
    from PySide6.QtCore import Signal
    assert isinstance(
        getattr(VoiceAssistant, "desktop_task_progress", None),
        type(Signal(str)),
    ) or hasattr(VoiceAssistant, "desktop_task_progress"), (
        "VoiceAssistant must expose desktop_task_progress signal"
    )


def test_voice_handle_desktop_task_emits_progress_for_each_step(qapp, monkeypatch):
    """When DesktopAgent's progress_callback fires, voice_assistant must
    re-emit the message via desktop_task_progress so the dashboard log
    picks it up."""
    from core import voice_assistant as va_mod
    from core import function_executor as fx_mod

    va = va_mod.VoiceAssistant()

    received: list[str] = []
    va.desktop_task_progress.connect(received.append)

    def fake_execute(name, params, *, _progress=None):
        # Simulate what _control_desktop will do once wired.
        assert name == "control_desktop"
        assert callable(_progress), (
            "execute must accept and pass _progress through to control_desktop"
        )
        _progress("Starting: open notepad")
        _progress("Action: screenshot")
        _progress("Task terminated: success")
        return {"success": True, "message": "ok", "data": {"log": []}}

    monkeypatch.setattr(va_mod.function_executor, "execute", fake_execute)
    # Silence the downstream "speak the result" call.
    monkeypatch.setattr(
        va, "_generate_response_with_context",
        lambda func_name, result, user_text: None,
    )

    va._handle_desktop_task("open notepad", "open notepad")

    qapp.processEvents()
    assert received == [
        "Starting: open notepad",
        "Action: screenshot",
        "Task terminated: success",
    ], received


# ── function_executor wiring ──────────────────────────────────────────────


def _install_fake_desktop_agent_module(monkeypatch, agent_cls):
    """Inject a stand-in core.agent.desktop_agent module so headless
    test runs (no X display) don't blow up on the real module's pyautogui
    → Xlib import chain. The real module is correctly try/except'd at
    every production call site."""
    import sys, types
    fake = types.ModuleType("core.agent.desktop_agent")
    fake.DesktopAgent = agent_cls
    monkeypatch.setitem(sys.modules, "core.agent.desktop_agent", fake)


def test_function_executor_routes_progress_into_control_desktop(monkeypatch):
    """execute(name='control_desktop', params, _progress=cb) must hand cb
    to DesktopAgent.run_task_sync."""
    from core import function_executor as fx_mod

    captured: dict = {}

    class _StubAgent:
        def __init__(self, *a, **kw): pass
        def run_task_sync(self, instruction, progress_callback=None, timeout_seconds=300):
            captured["instruction"] = instruction
            captured["cb"] = progress_callback
            if progress_callback:
                progress_callback("stub progress")
            return {"success": True, "message": "stub", "data": {"log": []}}

    _install_fake_desktop_agent_module(monkeypatch, _StubAgent)

    # Task must not match the fast-path _APP_MAP — otherwise _control_desktop
    # short-circuits via _try_direct_launch and never reaches DesktopAgent.
    seen: list[str] = []
    result = fx_mod.executor.execute(
        "control_desktop", {"task": "scroll down on the current page"},
        _progress=seen.append,
    )

    assert captured.get("instruction") == "scroll down on the current page"
    assert captured.get("cb") is not None, (
        "control_desktop must forward _progress to run_task_sync.progress_callback"
    )
    assert seen == ["stub progress"]
    assert result["success"] is True


def test_function_executor_execute_without_progress_still_works(monkeypatch):
    """Backwards compatibility: omitting _progress must work exactly as
    before (no crash, no required arg)."""
    from core import function_executor as fx_mod

    class _StubAgent:
        def __init__(self, *a, **kw): pass
        def run_task_sync(self, instruction, progress_callback=None, timeout_seconds=300):
            assert progress_callback is None
            return {"success": True, "message": "ok", "data": {"log": []}}

    _install_fake_desktop_agent_module(monkeypatch, _StubAgent)
    # Same fast-path-avoidance note as the previous test.
    result = fx_mod.executor.execute("control_desktop", {"task": "scroll down on the current page"})
    assert result["success"] is True
