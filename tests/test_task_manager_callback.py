import time
import types

from core.multi_agent import AgentTaskManager


class _FakeAgent:
    id = "agent-1"
    agent = types.SimpleNamespace(role=types.SimpleNamespace(name="Fake"))


def test_launch_invokes_on_complete_with_record():
    tm = AgentTaskManager()
    received = []

    def runner(*, agent, task, context):
        return {"success": True, "response": "done"}

    tm.launch(agent=_FakeAgent(), task="t", context="c",
              runner=runner, on_complete=received.append)

    # launch runs the runner in a daemon thread; wait briefly for completion
    for _ in range(50):
        if received:
            break
        time.sleep(0.02)

    assert len(received) == 1
    assert received[0]["status"] == "completed"
    assert received[0]["result"] == {"success": True, "response": "done"}


def test_launch_still_works_without_on_complete():
    tm = AgentTaskManager()

    def runner(*, agent, task, context):
        return {"success": True}

    task_id = tm.launch(agent=_FakeAgent(), task="t", context="c", runner=runner)
    assert isinstance(task_id, str)
