"""LiveAgentEditorDialog must refresh its tool whitelist live when the
plugin registry reloads, instead of going stale until the dialog is
re-opened. Regression guard for the dangling ``plugins_changed`` signal
the 2026-05-19 audit found.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def stub_role(monkeypatch):
    """Inject a minimal role into multi_agent_system so the editor builds."""
    from core import multi_agent

    class _FakeRole:
        tools = set()
        responsibilities = ["test responsibility"]

    monkeypatch.setattr(
        multi_agent.multi_agent_system, "roles", {"r1": _FakeRole()},
    )
    return _FakeRole


@pytest.fixture
def empty_registry(monkeypatch):
    """Start the plugin registry from a known-empty state for each test."""
    from core.plugins import registry
    original_tools = dict(registry._tools)
    monkeypatch.setattr(registry, "_tools", {})
    yield registry
    # monkeypatch handles restoration of the attribute; nothing else to do.


def _state():
    from core.agent_state import AgentState
    return AgentState(
        role_id="r1", instance_id="i1", display_name="Test",
        icon="🤖", executor="tool_loop", trigger="on_demand",
        persistence="session", notify="chat", status="active",
        created_at="2026-05-19T00:00:00",
    )


def test_editor_refreshes_tool_list_when_plugins_changed_fires(
    qapp, stub_role, empty_registry,
):
    from gui.tabs.agent_editor import LiveAgentEditorDialog

    dlg = LiveAgentEditorDialog(_state())
    try:
        # No plugin tools initially.
        assert not any(":" in t for t in dlg._tool_checks), (
            f"unexpected plugin tools at startup: "
            f"{[t for t in dlg._tool_checks if ':' in t]}"
        )
        # A built-in tool is present so we know construction worked.
        assert "web_search" in dlg._tool_checks

        # Inject a plugin tool + fire the signal.
        empty_registry._tools["my_plugin:do_thing"] = (
            lambda p: {}, "my_plugin", "stub doc",
        )
        empty_registry.plugins_changed.emit()
        qapp.processEvents()

        assert "my_plugin:do_thing" in dlg._tool_checks, (
            "tool whitelist did not refresh on plugins_changed; got: "
            f"{sorted(dlg._tool_checks.keys())}"
        )
    finally:
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()


def test_editor_preserves_user_checks_across_refresh(
    qapp, stub_role, empty_registry,
):
    """If the user has ticked a tool, a refresh must not silently un-tick it."""
    from gui.tabs.agent_editor import LiveAgentEditorDialog

    dlg = LiveAgentEditorDialog(_state())
    try:
        dlg._tool_checks["web_search"].setChecked(True)

        empty_registry._tools["my_plugin:do_thing"] = (
            lambda p: {}, "my_plugin", "",
        )
        empty_registry.plugins_changed.emit()
        qapp.processEvents()

        assert dlg._tool_checks["web_search"].isChecked(), (
            "user's existing tool selection was lost during refresh"
        )
    finally:
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()
