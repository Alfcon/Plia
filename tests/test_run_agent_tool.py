"""Tests for the list_agents and run_agent sub-agent orchestration tools."""

import types
import core.agent_runtime as ar
from core.agent_state import AgentState
from core.executors.run_result import RunResult
from core.function_executor import executor


def _fresh_runtime(monkeypatch, tmp_path):
    """Build a sandbox runtime with a controlled store + scripted runner."""
    ar._runtime = None
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    rt = ar.get_runtime()
    return rt


def _add_agent(rt, role_id, display_name, runner_result):
    """Insert an agent and stub its instance + runner so run_agent succeeds."""
    state = AgentState(
        role_id=role_id, instance_id=f"i-{role_id}", display_name=display_name,
        icon="🤖", executor="tool_loop", trigger="on_demand",
        persistence="session", notify="chat", status="active",
        created_at="2026-05-16T00:00:00",
    )
    rt.store.upsert(state)

    fake_instance = types.SimpleNamespace(
        id=f"inst-{role_id}",
        agent=types.SimpleNamespace(role=types.SimpleNamespace(id=role_id)),
        current_task=None,
    )
    # Pretend the multi_agent_system has this instance registered.
    orig_get_instance = rt._get_instance
    def patched(role_id_arg, _orig=orig_get_instance, _inst=fake_instance, _rid=role_id):
        if role_id_arg == _rid:
            return _inst
        return _orig(role_id_arg)
    rt._get_instance = patched

    orig_build_runner = rt._build_runner
    def patched_runner(state_arg, _orig=orig_build_runner, _result=runner_result, _rid=role_id):
        if state_arg.role_id == _rid:
            return lambda **kw: _result
        return _orig(state_arg)
    rt._build_runner = patched_runner

    return state


def test_list_agents_returns_registered_agents(monkeypatch, tmp_path):
    rt = _fresh_runtime(monkeypatch, tmp_path)
    _add_agent(rt, "searcher", "Searcher",
               RunResult(True, "s", "d"))
    _add_agent(rt, "formatter", "Formatter",
               RunResult(True, "f", "d"))

    out = executor.execute("list_agents", {})
    assert out["success"] is True
    names = sorted(a["name"] for a in out["data"]["agents"])
    assert names == ["Formatter", "Searcher"]


def test_run_agent_invokes_sub_agent_by_role_id(monkeypatch, tmp_path):
    rt = _fresh_runtime(monkeypatch, tmp_path)
    _add_agent(rt, "searcher", "Searcher",
               RunResult(True, "found 3 repos", "details",
                         items_found=3, items=[{"title": "a"}]))

    out = executor.execute("run_agent", {"agent": "searcher", "task": "go"})
    assert out["success"] is True
    assert out["data"]["agent"] == "Searcher"
    assert out["data"]["items_found"] == 3
    assert out["data"]["items"][0]["title"] == "a"


def test_run_agent_matches_by_display_name(monkeypatch, tmp_path):
    rt = _fresh_runtime(monkeypatch, tmp_path)
    _add_agent(rt, "fmt-1", "Formatter",
               RunResult(True, "formatted", "d"))

    out = executor.execute("run_agent", {"name": "formatter"})  # case-insensitive
    assert out["success"] is True
    assert out["data"]["role_id"] == "fmt-1"


def test_run_agent_rejects_unknown_agent(monkeypatch, tmp_path):
    _fresh_runtime(monkeypatch, tmp_path)
    out = executor.execute("run_agent", {"agent": "nope"})
    assert out["success"] is False
    assert "no live agent" in out["message"].lower()


def test_run_agent_refuses_terminated_agent(monkeypatch, tmp_path):
    rt = _fresh_runtime(monkeypatch, tmp_path)
    state = _add_agent(rt, "dead", "Dead",
                       RunResult(True, "x", "y"))
    state.status = "terminated"
    rt.store.upsert(state)

    out = executor.execute("run_agent", {"agent": "dead"})
    assert out["success"] is False
    assert "terminated" in out["message"].lower()


def test_run_agent_recursion_guard(monkeypatch, tmp_path):
    """If an agent's runner itself calls run_agent (and so on), recursion is
    capped at 3 levels."""
    rt = _fresh_runtime(monkeypatch, tmp_path)

    # Build an agent whose runner calls run_agent on itself — a guaranteed cycle.
    state = AgentState(
        role_id="loop", instance_id="i", display_name="Loop",
        icon="🤖", executor="tool_loop", trigger="on_demand",
        persistence="session", notify="chat", status="active",
        created_at="2026-05-16T00:00:00",
    )
    rt.store.upsert(state)
    rt._get_instance = lambda rid: types.SimpleNamespace(
        id="i", agent=types.SimpleNamespace(role=types.SimpleNamespace(id=rid)),
        current_task=None,
    )

    def recursive_runner(**kw):
        # Each invocation calls run_agent on itself, deepening the stack.
        sub = executor.execute("run_agent", {"agent": "loop"})
        if not sub["success"]:
            return RunResult(False, "blocked", "x", error="recursion")
        return RunResult(True, "ok", "")

    rt._build_runner = lambda s: recursive_runner

    out = executor.execute("run_agent", {"agent": "loop"})
    # The top-level call still succeeds; we want to see the recursion guard
    # kicking in somewhere down the stack.
    assert out["success"] is True
    # The inner failure surfaces in details / error somewhere — the run finished
    # because the recursion guard returned, not because it actually completed.
    assert out["data"]["error"] in (None, "recursion")
