"""Tests for the direct_tool executor — deterministic single-tool runs."""

from core.executors.direct_tool_executor import make_direct_tool_runner
from core.executors.run_result import RunResult


def test_direct_tool_runner_calls_named_tool(monkeypatch):
    captured = {}

    def fake_execute(name, params):
        captured["name"] = name
        captured["params"] = params
        return {
            "success": True,
            "message": "ok",
            "data": {"results": [
                {"title": "a", "url": "u1"},
                {"title": "b", "url": "u2"},
            ]},
        }

    import core.executors.direct_tool_executor as mod
    monkeypatch.setattr(mod.function_executor, "execute", fake_execute)

    runner = make_direct_tool_runner(
        tool_id="web_search",
        arguments={"query": "JARVIS projects"},
    )
    result = runner(agent=object(), task="ignored", context="")
    assert isinstance(result, RunResult)
    assert result.success is True
    assert result.summary == "ok"
    assert result.items_found == 2
    assert result.items[0]["title"] == "a"
    assert captured["name"] == "web_search"
    assert captured["params"] == {"query": "JARVIS projects"}


def test_direct_tool_runner_handles_tool_failure(monkeypatch):
    import core.executors.direct_tool_executor as mod
    monkeypatch.setattr(
        mod.function_executor,
        "execute",
        lambda n, p: {"success": False, "message": "boom", "data": None,
                       "error": "kaboom"},
    )
    runner = make_direct_tool_runner(tool_id="anything", arguments={})
    result = runner(agent=None, task="", context="")
    assert result.success is False
    assert result.summary == "boom"
    assert result.error == "kaboom"
    assert result.items_found == 0


def test_direct_tool_runner_missing_tool_id_fails_cleanly():
    runner = make_direct_tool_runner(tool_id="", arguments={})
    result = runner(agent=None, task="", context="")
    assert result.success is False
    assert result.error == "missing_tool_id"


def test_direct_tool_runner_handles_crash(monkeypatch):
    import core.executors.direct_tool_executor as mod
    def boom(name, params):
        raise RuntimeError("network down")
    monkeypatch.setattr(mod.function_executor, "execute", boom)
    runner = make_direct_tool_runner(tool_id="x", arguments={})
    result = runner(agent=None, task="", context="")
    assert result.success is False
    assert result.error == "executor_internal"
    assert "network down" in result.details


def test_direct_tool_runner_wraps_non_dict_response(monkeypatch):
    import core.executors.direct_tool_executor as mod
    monkeypatch.setattr(mod.function_executor, "execute", lambda n, p: "just a string")
    runner = make_direct_tool_runner(tool_id="x", arguments={})
    result = runner(agent=None, task="", context="")
    assert result.success is False
    assert result.error == "non_dict_result"


def test_direct_tool_runner_extracts_items_from_list_payload(monkeypatch):
    """If `data` is itself a list of dicts, treat each as an item."""
    import core.executors.direct_tool_executor as mod
    monkeypatch.setattr(mod.function_executor, "execute", lambda n, p: {
        "success": True, "message": "ok",
        "data": [{"name": "x"}, {"name": "y"}, "not-a-dict"],
    })
    runner = make_direct_tool_runner(tool_id="x", arguments={})
    result = runner(agent=None, task="", context="")
    assert result.items_found == 2
    assert [i["name"] for i in result.items] == ["x", "y"]


def test_scheduler_routes_direct_tool_state_to_direct_runner(monkeypatch):
    """build_default_runner picks make_direct_tool_runner for executor=direct_tool."""
    from core.agent_scheduler import build_default_runner
    from core.agent_state import AgentState

    state = AgentState(
        role_id="t", instance_id="i", display_name="T",
        icon="⏱", executor="direct_tool", trigger="scheduled",
        persistence="persistent", notify="comm_log", status="active",
        created_at="2026-05-16T10:00:00",
        direct_tool_id="example:say_hello",
        direct_tool_args={"name": "test"},
    )
    # Stub function_executor so we don't need plugins loaded.
    import core.executors.direct_tool_executor as mod
    monkeypatch.setattr(mod.function_executor, "execute",
                        lambda n, p: {"success": True, "message": f"called {n}",
                                       "data": None})
    runner = build_default_runner(state, role_tools=[],
                                  ollama_url="http://x/api", model="m")
    result = runner(agent=None, task="", context="")
    assert result.summary == "called example:say_hello"
