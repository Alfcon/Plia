from core.agent_scheduler import build_default_runner
from core.agent_state import AgentState


def _state(executor, **overrides):
    base = dict(
        role_id="r", instance_id="i", display_name="R", icon="🤖",
        executor=executor, trigger="on_demand", persistence="session",
        notify="tts", status="active", created_at="2026-05-14T10:00:00",
    )
    base.update(overrides)
    return AgentState(**base)


def test_build_default_runner_for_script_returns_callable():
    state = _state("script", script_path="/tmp/agent.py")
    runner = build_default_runner(state, role_tools=[], ollama_url="http://x/api", model="m")
    assert callable(runner)


def test_build_default_runner_for_tool_loop_returns_callable():
    state = _state("tool_loop")
    runner = build_default_runner(state, role_tools=["web_search"],
                                  ollama_url="http://x/api", model="m")
    assert callable(runner)


def test_build_default_runner_script_without_path_returns_failing_runner():
    state = _state("script", script_path=None)
    runner = build_default_runner(state, role_tools=[], ollama_url="http://x/api", model="m")
    result = runner(agent=object(), task="t", context="")
    assert result.success is False
    assert result.error == "script_not_found"
