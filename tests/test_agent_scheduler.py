from datetime import datetime

from core.agent_scheduler import AgentScheduler
from core.agent_state import AgentState, AgentStateStore


class FakeTimer:
    """Records arm/cancel calls instead of using a real Qt event loop."""
    def __init__(self):
        self.armed_ms = None
        self.cancelled = False
        self._cb = None

    def start(self, ms):
        self.armed_ms = ms
        self.cancelled = False

    def stop(self):
        self.cancelled = True

    def set_callback(self, cb):
        self._cb = cb

    def trigger(self):
        if self._cb:
            self._cb()


def make_timer_factory():
    created = {}

    def factory(role_id, callback):
        t = FakeTimer()
        t.set_callback(callback)
        created[role_id] = t
        return t

    return factory, created


def fixed_clock(dt):
    return lambda: dt


def scheduled_state(role_id="a", **overrides):
    base = dict(
        role_id=role_id, instance_id=f"i-{role_id}", display_name=role_id.title(),
        icon="🤖", executor="tool_loop", trigger="scheduled", persistence="persistent",
        notify="comm_log", status="active", created_at="2026-05-14T10:00:00",
        cadence={"interval_sec": 3600, "anchor_iso": None},
    )
    base.update(overrides)
    return AgentState(**base)


def build_scheduler(tmp_path, now, timer_factory):
    store = AgentStateStore(path=tmp_path / "state.json")
    sched = AgentScheduler(
        state_store=store,
        task_manager=None,
        runner_builder=lambda state: (lambda **kw: None),
        instance_provider=lambda role_id: object(),
        now_provider=fixed_clock(now),
        timer_factory=timer_factory,
    )
    return sched, store


def test_arm_scheduled_sets_next_fire_and_starts_timer(tmp_path):
    now = datetime(2026, 5, 14, 14, 0, 0)
    factory, created = make_timer_factory()
    sched, store = build_scheduler(tmp_path, now, factory)

    state = scheduled_state()
    store.upsert(state)
    sched.arm(state)

    assert created["a"].armed_ms == 3600 * 1000
    refreshed = store.get("a")
    assert refreshed.next_fire_at == datetime(2026, 5, 14, 15, 0, 0).isoformat(timespec="seconds")


def test_arm_on_demand_does_not_start_timer(tmp_path):
    now = datetime(2026, 5, 14, 14, 0, 0)
    factory, created = make_timer_factory()
    sched, store = build_scheduler(tmp_path, now, factory)

    state = scheduled_state(role_id="b", trigger="on_demand", cadence=None)
    store.upsert(state)
    sched.arm(state)

    assert "b" not in created


def test_disarm_stops_timer(tmp_path):
    now = datetime(2026, 5, 14, 14, 0, 0)
    factory, created = make_timer_factory()
    sched, store = build_scheduler(tmp_path, now, factory)

    state = scheduled_state(role_id="c")
    store.upsert(state)
    sched.arm(state)
    sched.disarm("c")

    assert created["c"].cancelled is True


def test_on_tick_launches_run_and_reschedules(tmp_path):
    now = datetime(2026, 5, 14, 14, 0, 0)
    factory, created = make_timer_factory()
    store = AgentStateStore(path=tmp_path / "state.json")

    launched = []

    class FakeTaskManager:
        def launch(self, *, agent, task, context, runner, on_complete=None):
            launched.append({"agent": agent, "task": task})
            return "task-1"

    sched = AgentScheduler(
        state_store=store,
        task_manager=FakeTaskManager(),
        runner_builder=lambda state: (lambda **kw: None),
        instance_provider=lambda role_id: f"instance-{role_id}",
        now_provider=fixed_clock(now),
        timer_factory=factory,
    )

    state = scheduled_state(role_id="t1")
    store.upsert(state)
    sched.arm(state)

    created["t1"].trigger()  # simulate the timer firing

    assert len(launched) == 1
    assert launched[0]["agent"] == "instance-t1"
    refreshed = store.get("t1")
    assert refreshed.runs == 1
    assert refreshed.last_fire_at == now.isoformat(timespec="seconds")
    # a new timer was armed for the next tick
    assert created["t1"].armed_ms == 3600 * 1000


def test_on_tick_skips_when_run_in_flight(tmp_path):
    now = datetime(2026, 5, 14, 14, 0, 0)
    factory, created = make_timer_factory()
    store = AgentStateStore(path=tmp_path / "state.json")

    launched = []

    class FakeTaskManager:
        def launch(self, *, agent, task, context, runner, on_complete=None):
            launched.append(1)
            return "task-x"  # never calls on_complete -> stays "in flight"

    sched = AgentScheduler(
        state_store=store, task_manager=FakeTaskManager(),
        runner_builder=lambda state: (lambda **kw: None),
        instance_provider=lambda role_id: object(),
        now_provider=fixed_clock(now), timer_factory=factory,
    )
    state = scheduled_state(role_id="t2")
    store.upsert(state)
    sched.arm(state)

    created["t2"].trigger()  # first tick -> launches
    created["t2"].trigger()  # second tick while first still in flight -> skipped

    assert len(launched) == 1


from core.executors.run_result import RunResult


def quota_state(role_id="q", limit=3, progress=0):
    return AgentState(
        role_id=role_id, instance_id=f"i-{role_id}", display_name="Quota Agent",
        icon="🎯", executor="tool_loop", trigger="quota", persistence="persistent",
        notify="comm_log", status="active", created_at="2026-05-14T10:00:00",
        quota={"limit": limit, "criterion": "any", "progress": progress},
    )


def _completion_record(run_result):
    return {"id": "task-1", "status": "completed", "result": run_result}


def test_completion_appends_history_and_invokes_reporter(tmp_path):
    now = datetime(2026, 5, 14, 14, 0, 0)
    factory, _ = make_timer_factory()
    store = AgentStateStore(path=tmp_path / "state.json")
    reported = []

    sched = AgentScheduler(
        state_store=store, task_manager=None,
        runner_builder=lambda s: (lambda **kw: None),
        instance_provider=lambda rid: object(),
        now_provider=fixed_clock(now), timer_factory=factory,
        reporter=lambda state, result: reported.append((state.role_id, result)),
    )
    state = scheduled_state(role_id="h1")
    store.upsert(state)

    rr = RunResult(success=True, summary="found 2", details="d", items_found=2)
    sched._on_run_complete("h1", _completion_record(rr))

    refreshed = store.get("h1")
    assert len(refreshed.history) == 1
    assert refreshed.history[0]["summary"] == "found 2"
    assert reported == [("h1", rr)]


def test_quota_progress_accumulates_and_terminates(tmp_path):
    now = datetime(2026, 5, 14, 14, 0, 0)
    factory, created = make_timer_factory()
    store = AgentStateStore(path=tmp_path / "state.json")

    sched = AgentScheduler(
        state_store=store, task_manager=None,
        runner_builder=lambda s: (lambda **kw: None),
        instance_provider=lambda rid: object(),
        now_provider=fixed_clock(now), timer_factory=factory,
        reporter=lambda state, result: None,
    )
    state = quota_state(role_id="q1", limit=3, progress=0)
    store.upsert(state)
    sched.arm(state)

    rr = RunResult(success=True, summary="found 2", details="d", items_found=2)
    sched._on_run_complete("q1", _completion_record(rr))
    assert store.get("q1").quota["progress"] == 2
    assert store.get("q1").status == "active"

    rr2 = RunResult(success=True, summary="found 1 more", details="d", items_found=1)
    sched._on_run_complete("q1", _completion_record(rr2))
    refreshed = store.get("q1")
    assert refreshed.quota["progress"] == 3
    assert refreshed.status == "terminated"
    assert created["q1"].cancelled is True


def test_completion_with_dict_result_is_normalised(tmp_path):
    now = datetime(2026, 5, 14, 14, 0, 0)
    factory, _ = make_timer_factory()
    store = AgentStateStore(path=tmp_path / "state.json")
    reported = []

    sched = AgentScheduler(
        state_store=store, task_manager=None,
        runner_builder=lambda s: (lambda **kw: None),
        instance_provider=lambda rid: object(),
        now_provider=fixed_clock(now), timer_factory=factory,
        reporter=lambda state, result: reported.append(result),
    )
    state = scheduled_state(role_id="d1")
    store.upsert(state)

    # AgentTaskManager stores a dict when the runner raised
    record = {"id": "t", "status": "failed",
              "result": {"success": False, "response": "boom"}}
    sched._on_run_complete("d1", record)

    assert reported[0].success is False
    assert reported[0].error == "runner_returned_dict"
    assert store.get("d1").history[0]["success"] is False
