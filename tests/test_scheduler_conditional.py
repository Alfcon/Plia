"""AgentScheduler integration with WatchManager for conditional triggers."""

from datetime import datetime

from core.agent_scheduler import AgentScheduler
from core.agent_state import AgentState, AgentStateStore


class _FakeWatchManager:
    """Stands in for the real WatchManager — records register/unregister
    calls; we drive ``triggered`` manually by calling the captured callback
    on the scheduler."""

    def __init__(self):
        self.registered = {}    # role_id -> condition
        self.unregistered = []  # role_ids

    def register(self, role_id, condition):
        self.registered[role_id] = condition
        return True

    def unregister(self, role_id):
        self.unregistered.append(role_id)
        self.registered.pop(role_id, None)


class _FakeTaskManager:
    def __init__(self):
        self.launched = []

    def launch(self, **kw):
        self.launched.append(kw)
        return "task-123"


def _build_sched(tmp_path, watch_manager):
    store = AgentStateStore(path=tmp_path / "state.json")
    task_manager = _FakeTaskManager()
    sched = AgentScheduler(
        state_store=store,
        task_manager=task_manager,
        runner_builder=lambda state: (lambda **kw: None),
        instance_provider=lambda role_id: object(),
        now_provider=lambda: datetime(2026, 5, 16, 12, 0, 0),
        timer_factory=lambda rid, cb: _NoopTimer(),
        watch_manager=watch_manager,
    )
    return sched, store, task_manager


class _NoopTimer:
    def start(self, _ms): pass
    def stop(self): pass


def _conditional_state(role_id="watcher-1"):
    return AgentState(
        role_id=role_id,
        instance_id=f"i-{role_id}",
        display_name="Watcher",
        icon="🛎️",
        executor="tool_loop",
        trigger="conditional",
        persistence="persistent",
        notify="comm_log",
        status="active",
        created_at="2026-05-16T12:00:00",
        condition={"type": "file_watch", "path": "/tmp/x"},
    )


def test_arm_conditional_registers_with_watch_manager(tmp_path):
    wm = _FakeWatchManager()
    sched, store, _ = _build_sched(tmp_path, wm)

    state = _conditional_state()
    store.upsert(state)
    sched.arm(state)

    assert "watcher-1" in wm.registered
    assert wm.registered["watcher-1"] == {"type": "file_watch", "path": "/tmp/x"}
    refreshed = store.get("watcher-1")
    assert refreshed.next_fire_at is None  # not a time-based agent


def test_disarm_conditional_unregisters(tmp_path):
    wm = _FakeWatchManager()
    sched, store, _ = _build_sched(tmp_path, wm)

    state = _conditional_state()
    store.upsert(state)
    sched.arm(state)
    sched.disarm("watcher-1")

    assert "watcher-1" in wm.unregistered
    assert "watcher-1" not in wm.registered


def test_arm_conditional_skips_when_no_watch_manager(tmp_path):
    """If no WatchManager is wired in, arming a conditional agent is a no-op
    (it doesn't start a QTimer or crash)."""
    sched, store, _ = _build_sched(tmp_path, watch_manager=None)
    state = _conditional_state()
    store.upsert(state)
    sched.arm(state)  # must not raise
    refreshed = store.get("watcher-1")
    assert refreshed.next_fire_at is None


def test_fire_now_drives_conditional_agent(tmp_path):
    """When the WatchManager would fire `triggered(role_id)`, that
    dispatches through `scheduler.fire_now`. We simulate that path
    directly to confirm a launch happens."""
    wm = _FakeWatchManager()
    sched, store, task_manager = _build_sched(tmp_path, wm)

    state = _conditional_state()
    store.upsert(state)
    sched.arm(state)

    # Simulate the watcher trigger.
    sched.fire_now("watcher-1")

    assert len(task_manager.launched) == 1
    # The launch payload should target our conditional agent.
    payload = task_manager.launched[0]
    assert payload["task"]  # something non-empty (display_name or current_task)
