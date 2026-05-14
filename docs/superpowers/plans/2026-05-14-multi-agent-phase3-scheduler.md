# Multi-Agent System — Phase 3: Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the cron-like scheduler that arms, fires, pauses, resumes, and stops live agents — delegating each run to `AgentTaskManager` with the right executor runner.

**Architecture:** A new `core/agent_scheduler.py` provides a pure cadence parser, a pure `compute_next_fire` function, and an `AgentScheduler` QObject. The scheduler holds one timer per agent, uses an injected clock (`now_provider`) and timer factory for testability, and on each tick delegates to `AgentTaskManager.launch(...)` with a runner built from the agent's `executor` field. `AgentTaskManager.launch` gains an optional `on_complete` callback so the scheduler is notified when a run finishes.

**Tech Stack:** Python 3, PySide6 `QObject`/`QTimer`, `datetime`, dependency injection for clock + timers, `pytest`.

**Spec:** `docs/superpowers/specs/2026-05-14-multi-agent-system-design.md` (Scheduler section).

**Depends on:** Phase 1 (`core/agent_state.py`), Phase 2 (`core/executors/`). Uses `core/multi_agent.py` `AgentTaskManager` / `multi_agent_system`.

---

## File Structure

| Path | Responsibility |
|---|---|
| `core/multi_agent.py` (modify) | Add optional `on_complete` callback to `AgentTaskManager.launch` |
| `core/agent_scheduler.py` (create) | `parse_cadence`, `compute_next_fire`, `AgentScheduler` (arm/disarm/pause/resume/fire_now/load_and_arm) |
| `tests/test_cadence_parser.py` (create) | Pure-function tests for `parse_cadence` + `compute_next_fire` |
| `tests/test_agent_scheduler.py` (create) | `AgentScheduler` tests with injected clock + fake timers |
| `tests/test_task_manager_callback.py` (create) | `AgentTaskManager.launch` `on_complete` callback test |

---

## Task 1: Add `on_complete` callback to `AgentTaskManager.launch`

**Files:**
- Modify: `core/multi_agent.py` (`AgentTaskManager.launch`, around lines 302-332)
- Create: `tests/test_task_manager_callback.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_task_manager_callback.py`:

```python
import time

from core.multi_agent import AgentTaskManager


class _FakeAgent:
    id = "agent-1"

    class _Role:
        name = "Fake"
    class _Inner:
        role = _Role()
    agent = _Inner()


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_task_manager_callback.py -v`
Expected: FAIL — `launch()` does not accept an `on_complete` keyword argument (`TypeError`).

- [ ] **Step 3: Modify `AgentTaskManager.launch`**

In `core/multi_agent.py`, the current method is:

```python
    def launch(self, *, agent: AgentInstance, task: str, context: str, runner: Callable[..., Dict[str, Any]]) -> str:
        task_id = _uuid()
        record = {
            "id": task_id,
            "agentId": agent.id,
            "agentName": agent.agent.role.name,
            "task": task,
            "context": context,
            "status": "running",
            "startedAt": _now_ms(),
            "completedAt": None,
            "result": None,
        }
        with self._lock:
            self._tasks[task_id] = record

        def _run():
            try:
                result = runner(agent=agent, task=task, context=context)
                with self._lock:
                    record["status"] = "completed"
                    record["completedAt"] = _now_ms()
                    record["result"] = result
            except Exception as exc:
                with self._lock:
                    record["status"] = "failed"
                    record["completedAt"] = _now_ms()
                    record["result"] = {"success": False, "response": str(exc)}

        threading.Thread(target=_run, daemon=True).start()
        return task_id
```

Replace it with this version (adds the optional `on_complete` parameter and calls it after the record is finalised, inside `_run`, outside the lock):

```python
    def launch(self, *, agent: AgentInstance, task: str, context: str,
               runner: Callable[..., Dict[str, Any]],
               on_complete: Optional[Callable[[Dict[str, Any]], None]] = None) -> str:
        task_id = _uuid()
        record = {
            "id": task_id,
            "agentId": agent.id,
            "agentName": agent.agent.role.name,
            "task": task,
            "context": context,
            "status": "running",
            "startedAt": _now_ms(),
            "completedAt": None,
            "result": None,
        }
        with self._lock:
            self._tasks[task_id] = record

        def _run():
            try:
                result = runner(agent=agent, task=task, context=context)
                with self._lock:
                    record["status"] = "completed"
                    record["completedAt"] = _now_ms()
                    record["result"] = result
            except Exception as exc:
                with self._lock:
                    record["status"] = "failed"
                    record["completedAt"] = _now_ms()
                    record["result"] = {"success": False, "response": str(exc)}
            if on_complete is not None:
                try:
                    on_complete(dict(record))
                except Exception as cb_exc:
                    print(f"[AgentTaskManager] on_complete callback error: {cb_exc}")

        threading.Thread(target=_run, daemon=True).start()
        return task_id
```

`Optional` is already imported at the top of `core/multi_agent.py` (`from typing import ... Optional`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_task_manager_callback.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add core/multi_agent.py tests/test_task_manager_callback.py
git commit -m "feat: add on_complete callback to AgentTaskManager.launch"
```

---

## Task 2: Build the cadence parser

**Files:**
- Create: `core/agent_scheduler.py`
- Create: `tests/test_cadence_parser.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cadence_parser.py`:

```python
from core.agent_scheduler import parse_cadence


def test_parse_hourly():
    assert parse_cadence("every hour")["interval_sec"] == 3600
    assert parse_cadence("hourly")["interval_sec"] == 3600


def test_parse_every_n_minutes():
    assert parse_cadence("every 30 minutes")["interval_sec"] == 1800
    assert parse_cadence("every 5 mins")["interval_sec"] == 300


def test_parse_every_n_hours():
    assert parse_cadence("every 6 hours")["interval_sec"] == 21600


def test_parse_twice_a_day():
    assert parse_cadence("twice a day")["interval_sec"] == 43200


def test_parse_daily():
    assert parse_cadence("daily")["interval_sec"] == 86400
    assert parse_cadence("every day")["interval_sec"] == 86400


def test_parse_daily_with_time_sets_anchor_hour():
    cad = parse_cadence("every day at 8am")
    assert cad["interval_sec"] == 86400
    assert cad["anchor_iso"] is not None
    # anchor hour should be 08:00
    from datetime import datetime
    assert datetime.fromisoformat(cad["anchor_iso"]).hour == 8


def test_parse_weekly():
    cad = parse_cadence("every Monday morning")
    assert cad["interval_sec"] == 604800
    assert cad["anchor_iso"] is not None


def test_parse_garbage_returns_none():
    assert parse_cadence("blarg flooble") is None
    assert parse_cadence("") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cadence_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.agent_scheduler'`

- [ ] **Step 3: Write minimal implementation**

Create `core/agent_scheduler.py`:

```python
"""
agent_scheduler.py — Cron-like scheduler for Plia live agents.

Two pure functions:
  parse_cadence(text)     -> {"interval_sec": int, "anchor_iso": str | None} | None
  compute_next_fire(cad)  -> datetime

Plus AgentScheduler (added in a later task), which holds one timer per agent
and fires AgentTaskManager.launch on each tick.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Dict, Optional

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _next_weekday(from_dt: datetime, weekday: int, hour: int) -> datetime:
    days_ahead = (weekday - from_dt.weekday()) % 7
    candidate = from_dt.replace(hour=hour, minute=0, second=0, microsecond=0) \
        + timedelta(days=days_ahead)
    if candidate <= from_dt:
        candidate += timedelta(days=7)
    return candidate


def parse_cadence(text: str, now: Optional[datetime] = None) -> Optional[Dict]:
    """Parse a natural cadence phrase into {interval_sec, anchor_iso}.

    Returns None if the phrase is not understood.
    """
    if not text:
        return None
    now = now or datetime.now()
    t = text.strip().lower()

    # weekly — "every monday", "every monday morning"
    for name, wd in _WEEKDAYS.items():
        if name in t:
            anchor = _next_weekday(now, wd, hour=8)
            return {"interval_sec": 604800, "anchor_iso": anchor.isoformat(timespec="seconds")}

    # "every N minutes" / "every N mins"
    m = re.search(r"every\s+(\d+)\s*min", t)
    if m:
        return {"interval_sec": int(m.group(1)) * 60, "anchor_iso": None}

    # "every N hours"
    m = re.search(r"every\s+(\d+)\s*hour", t)
    if m:
        return {"interval_sec": int(m.group(1)) * 3600, "anchor_iso": None}

    # "every hour" / "hourly"
    if "hourly" in t or re.search(r"every\s+hour", t):
        return {"interval_sec": 3600, "anchor_iso": None}

    # "twice a day"
    if "twice a day" in t or "twice daily" in t:
        return {"interval_sec": 43200, "anchor_iso": None}

    # daily with a time — "every day at 8am", "daily at 8 am"
    m = re.search(r"at\s+(\d{1,2})\s*(am|pm)?", t)
    if ("daily" in t or "every day" in t) and m:
        hour = int(m.group(1))
        if m.group(2) == "pm" and hour < 12:
            hour += 12
        if m.group(2) == "am" and hour == 12:
            hour = 0
        anchor = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if anchor <= now:
            anchor += timedelta(days=1)
        return {"interval_sec": 86400, "anchor_iso": anchor.isoformat(timespec="seconds")}

    # plain daily
    if "daily" in t or "every day" in t:
        return {"interval_sec": 86400, "anchor_iso": None}

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cadence_parser.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add core/agent_scheduler.py tests/test_cadence_parser.py
git commit -m "feat: add natural-language cadence parser"
```

---

## Task 3: Add `compute_next_fire`

**Files:**
- Modify: `core/agent_scheduler.py`
- Create: `tests/test_compute_next_fire.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_compute_next_fire.py`:

```python
from datetime import datetime

from core.agent_scheduler import compute_next_fire


def test_no_anchor_adds_interval_to_now():
    now = datetime(2026, 5, 14, 14, 0, 0)
    cad = {"interval_sec": 3600, "anchor_iso": None}
    assert compute_next_fire(cad, now) == datetime(2026, 5, 14, 15, 0, 0)


def test_future_anchor_is_used_directly():
    now = datetime(2026, 5, 14, 14, 0, 0)
    cad = {"interval_sec": 86400, "anchor_iso": "2026-05-14T20:00:00"}
    assert compute_next_fire(cad, now) == datetime(2026, 5, 14, 20, 0, 0)


def test_past_anchor_advances_by_whole_intervals():
    now = datetime(2026, 5, 14, 14, 0, 0)
    # anchor was 08:00 today, interval 6h -> next tick after 14:00 is 20:00
    cad = {"interval_sec": 21600, "anchor_iso": "2026-05-14T08:00:00"}
    assert compute_next_fire(cad, now) == datetime(2026, 5, 14, 20, 0, 0)


def test_past_anchor_exactly_on_interval_boundary_moves_forward():
    now = datetime(2026, 5, 14, 14, 0, 0)
    # anchor 08:00, interval 6h -> 14:00 is a boundary; next must be strictly after
    cad = {"interval_sec": 21600, "anchor_iso": "2026-05-14T08:00:00"}
    result = compute_next_fire(cad, now)
    assert result > now
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_compute_next_fire.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_next_fire'`

- [ ] **Step 3: Write minimal implementation**

Append to `core/agent_scheduler.py`:

```python
def compute_next_fire(cadence: Dict, from_dt: datetime) -> datetime:
    """Given a cadence dict and a reference time, return the next fire time.

    - No anchor: from_dt + interval.
    - Future anchor: the anchor itself.
    - Past anchor: advance by whole intervals until strictly after from_dt.
    """
    interval = int(cadence["interval_sec"])
    anchor_iso = cadence.get("anchor_iso")
    if not anchor_iso:
        return from_dt + timedelta(seconds=interval)

    anchor = datetime.fromisoformat(anchor_iso)
    if anchor > from_dt:
        return anchor

    elapsed = (from_dt - anchor).total_seconds()
    steps = int(elapsed // interval) + 1
    return anchor + timedelta(seconds=steps * interval)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_compute_next_fire.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add core/agent_scheduler.py tests/test_compute_next_fire.py
git commit -m "feat: add compute_next_fire schedule arithmetic"
```

---

## Task 4: Build the `AgentScheduler` skeleton with `arm` and `disarm`

**Files:**
- Modify: `core/agent_scheduler.py`
- Create: `tests/test_agent_scheduler.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_scheduler.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_scheduler.py -v`
Expected: FAIL with `ImportError: cannot import name 'AgentScheduler'`

- [ ] **Step 3: Write minimal implementation**

Append to `core/agent_scheduler.py`:

```python
from PySide6.QtCore import QObject, QTimer


def _default_timer_factory(role_id: str, callback):
    """Create a real single-shot QTimer wired to `callback`."""
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(callback)

    class _Wrapped:
        def start(self, ms): timer.start(ms)
        def stop(self): timer.stop()

    return _Wrapped()


# quota agents poll on a fixed short interval (seconds)
QUOTA_INTERVAL_SEC = 600


class AgentScheduler(QObject):
    """Holds one timer per live agent; fires AgentTaskManager.launch on tick.

    Dependency-injected for testability:
      state_store       — AgentStateStore (Phase 1)
      task_manager      — AgentTaskManager (core/multi_agent.py)
      runner_builder    — callable(AgentState) -> runner callable
      instance_provider — callable(role_id) -> AgentInstance
      now_provider      — callable() -> datetime          (defaults to datetime.now)
      timer_factory     — callable(role_id, callback) -> timer-like object
    """

    def __init__(self, *, state_store, task_manager, runner_builder,
                 instance_provider, now_provider=None, timer_factory=None,
                 parent=None):
        super().__init__(parent)
        self._store = state_store
        self._task_manager = task_manager
        self._runner_builder = runner_builder
        self._instance_provider = instance_provider
        self._now = now_provider or datetime.now
        self._timer_factory = timer_factory or _default_timer_factory
        self._timers: Dict[str, object] = {}
        self._in_flight: set = set()

    # ── arming ────────────────────────────────────────────────────────────
    def arm(self, state) -> None:
        """Compute next_fire_at and start a timer if the agent is scheduled
        or quota-driven. on_demand agents are never armed."""
        if state.status != "active":
            return
        if state.trigger == "on_demand":
            return

        now = self._now()
        if state.trigger == "scheduled":
            cadence = state.cadence or {"interval_sec": 3600, "anchor_iso": None}
        else:  # quota
            cadence = {"interval_sec": QUOTA_INTERVAL_SEC, "anchor_iso": None}

        next_dt = compute_next_fire(cadence, now)
        delay_ms = max(0, int((next_dt - now).total_seconds() * 1000))

        state.next_fire_at = next_dt.isoformat(timespec="seconds")
        self._store.upsert(state)

        self.disarm(state.role_id)  # clear any existing timer
        timer = self._timer_factory(state.role_id,
                                    lambda rid=state.role_id: self._on_tick(rid))
        self._timers[state.role_id] = timer
        timer.start(delay_ms)

    def disarm(self, role_id: str) -> None:
        timer = self._timers.pop(role_id, None)
        if timer is not None:
            timer.stop()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_scheduler.py -v`
Expected: FAIL — `_on_tick` is referenced but not yet defined. This is expected; it's added in Task 5. For now, confirm the error is specifically `AttributeError: 'AgentScheduler' object has no attribute '_on_tick'` and **not** an import error.

Actually, `_on_tick` is only *called* lazily inside the lambda, so `arm`/`disarm` tests should pass. Run again and confirm:

Run: `pytest tests/test_agent_scheduler.py -v`
Expected: PASS (3 passed) — the lambda referencing `_on_tick` is not invoked during arm/disarm.

- [ ] **Step 5: Commit**

```bash
git add core/agent_scheduler.py tests/test_agent_scheduler.py
git commit -m "feat: add AgentScheduler arm/disarm with injected timers"
```

---

## Task 5: Implement `_on_tick` — fire a run

**Files:**
- Modify: `core/agent_scheduler.py`
- Modify: `tests/test_agent_scheduler.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_scheduler.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_scheduler.py::test_on_tick_launches_run_and_reschedules -v`
Expected: FAIL with `AttributeError: 'AgentScheduler' object has no attribute '_on_tick'`

- [ ] **Step 3: Write minimal implementation**

Append to `core/agent_scheduler.py`:

```python
    # ── firing ────────────────────────────────────────────────────────────
    def _on_tick(self, role_id: str) -> None:
        state = self._store.get(role_id)
        if state is None or state.status != "active":
            return

        # skip overlapping runs — one run per agent at a time
        if role_id in self._in_flight:
            self._reschedule(state)
            return

        self._launch_run(state)
        self._reschedule(state)

    def _launch_run(self, state) -> None:
        instance = self._instance_provider(state.role_id)
        if instance is None:
            return
        runner = self._runner_builder(state)
        context = ""
        if state.history:
            context = str(state.history[-1].get("summary", ""))

        self._in_flight.add(state.role_id)
        now = self._now()
        state.last_fire_at = now.isoformat(timespec="seconds")
        state.runs += 1
        self._store.upsert(state)

        self._task_manager.launch(
            agent=instance,
            task=str(getattr(instance, "current_task", None) or state.display_name),
            context=context,
            runner=runner,
            on_complete=lambda record, rid=state.role_id: self._on_run_complete(rid, record),
        )

    def _reschedule(self, state) -> None:
        """Arm the next tick for a scheduled/quota agent."""
        if state.trigger == "on_demand":
            return
        if state.status != "active":
            return
        now = self._now()
        if state.trigger == "scheduled":
            cadence = state.cadence or {"interval_sec": 3600, "anchor_iso": None}
        else:
            cadence = {"interval_sec": QUOTA_INTERVAL_SEC, "anchor_iso": None}
        next_dt = compute_next_fire(cadence, now)
        delay_ms = max(0, int((next_dt - now).total_seconds() * 1000))
        state.next_fire_at = next_dt.isoformat(timespec="seconds")
        self._store.upsert(state)

        self.disarm(state.role_id)
        timer = self._timer_factory(state.role_id,
                                    lambda rid=state.role_id: self._on_tick(rid))
        self._timers[state.role_id] = timer
        timer.start(delay_ms)

    def _on_run_complete(self, role_id: str, record: Dict) -> None:
        """Called (from a worker thread) when AgentTaskManager finishes a run."""
        self._in_flight.discard(role_id)
        # Reporting + quota handling are added in Task 6.
        self._handle_completion(role_id, record)
```

- [ ] **Step 4: Run test to verify it fails on missing `_handle_completion`**

Run: `pytest tests/test_agent_scheduler.py::test_on_tick_launches_run_and_reschedules -v`
Expected: PASS — `_on_run_complete` is only called via `on_complete`, which the `FakeTaskManager` never invokes, so `_handle_completion` is not reached in this test.

Run: `pytest tests/test_agent_scheduler.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add core/agent_scheduler.py tests/test_agent_scheduler.py
git commit -m "feat: add AgentScheduler tick + run launch + reschedule"
```

---

## Task 6: Handle run completion — quota progress, termination, reporting hook

**Files:**
- Modify: `core/agent_scheduler.py`
- Modify: `tests/test_agent_scheduler.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_scheduler.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_scheduler.py::test_completion_appends_history_and_invokes_reporter -v`
Expected: FAIL — `AgentScheduler.__init__` does not accept a `reporter` keyword argument (`TypeError`).

- [ ] **Step 3: Update `__init__` to accept `reporter`**

In `core/agent_scheduler.py`, change the `AgentScheduler.__init__` signature and body. The current signature is:

```python
    def __init__(self, *, state_store, task_manager, runner_builder,
                 instance_provider, now_provider=None, timer_factory=None,
                 parent=None):
        super().__init__(parent)
        self._store = state_store
        self._task_manager = task_manager
        self._runner_builder = runner_builder
        self._instance_provider = instance_provider
        self._now = now_provider or datetime.now
        self._timer_factory = timer_factory or _default_timer_factory
        self._timers: Dict[str, object] = {}
        self._in_flight: set = set()
```

Replace it with:

```python
    def __init__(self, *, state_store, task_manager, runner_builder,
                 instance_provider, now_provider=None, timer_factory=None,
                 reporter=None, parent=None):
        super().__init__(parent)
        self._store = state_store
        self._task_manager = task_manager
        self._runner_builder = runner_builder
        self._instance_provider = instance_provider
        self._now = now_provider or datetime.now
        self._timer_factory = timer_factory or _default_timer_factory
        self._reporter = reporter or (lambda state, result: None)
        self._timers: Dict[str, object] = {}
        self._in_flight: set = set()
```

- [ ] **Step 4: Implement `_handle_completion`**

Append to `core/agent_scheduler.py`:

```python
    HISTORY_CAP = 50

    def _handle_completion(self, role_id: str, record: Dict) -> None:
        from core.executors.run_result import RunResult

        state = self._store.get(role_id)
        if state is None:
            return

        result = RunResult.from_runner_output(record.get("result"))

        # always: append to history (FIFO cap)
        state.history.append({
            "ran_at": self._now().isoformat(timespec="seconds"),
            "success": result.success,
            "summary": result.summary,
            "details": result.details,
            "items_found": result.items_found,
            "items": result.items,
            "error": result.error,
        })
        if len(state.history) > self.HISTORY_CAP:
            state.history = state.history[-self.HISTORY_CAP:]

        # quota accounting
        if state.trigger == "quota" and state.quota is not None and result.success:
            state.quota["progress"] = int(state.quota.get("progress", 0)) + result.items_found
            if state.quota["progress"] >= int(state.quota.get("limit", 0)):
                state.status = "terminated"
                self.disarm(role_id)

        self._store.upsert(state)

        # hand off to the reporter (Phase 5 wires the real ResultDispatcher here)
        try:
            self._reporter(state, result)
        except Exception as exc:
            print(f"[AgentScheduler] reporter error: {exc}")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_agent_scheduler.py -v`
Expected: PASS (8 passed)

- [ ] **Step 6: Commit**

```bash
git add core/agent_scheduler.py tests/test_agent_scheduler.py
git commit -m "feat: add run-completion handling, quota termination, reporter hook"
```

---

## Task 7: Add `pause`, `resume`, `fire_now`

**Files:**
- Modify: `core/agent_scheduler.py`
- Modify: `tests/test_agent_scheduler.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_scheduler.py`:

```python
def test_pause_stops_timer_and_sets_status(tmp_path):
    now = datetime(2026, 5, 14, 14, 0, 0)
    factory, created = make_timer_factory()
    sched, store = build_scheduler(tmp_path, now, factory)
    state = scheduled_state(role_id="p1")
    store.upsert(state)
    sched.arm(state)

    sched.pause("p1")
    assert created["p1"].cancelled is True
    assert store.get("p1").status == "paused"


def test_resume_rearms_and_sets_active(tmp_path):
    now = datetime(2026, 5, 14, 14, 0, 0)
    factory, created = make_timer_factory()
    sched, store = build_scheduler(tmp_path, now, factory)
    state = scheduled_state(role_id="p2")
    store.upsert(state)
    sched.arm(state)
    sched.pause("p2")

    sched.resume("p2")
    assert store.get("p2").status == "active"
    assert created["p2"].armed_ms == 3600 * 1000


def test_fire_now_launches_immediately(tmp_path):
    now = datetime(2026, 5, 14, 14, 0, 0)
    factory, _ = make_timer_factory()
    store = AgentStateStore(path=tmp_path / "state.json")
    launched = []

    class FakeTaskManager:
        def launch(self, *, agent, task, context, runner, on_complete=None):
            launched.append(task)
            return "task-now"

    sched = AgentScheduler(
        state_store=store, task_manager=FakeTaskManager(),
        runner_builder=lambda s: (lambda **kw: None),
        instance_provider=lambda rid: f"inst-{rid}",
        now_provider=fixed_clock(now), timer_factory=factory,
        reporter=lambda s, r: None,
    )
    state = scheduled_state(role_id="on_demand_a", trigger="on_demand", cadence=None)
    store.upsert(state)

    task_id = sched.fire_now("on_demand_a")
    assert task_id == "task-now"
    assert len(launched) == 1
    assert store.get("on_demand_a").runs == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_scheduler.py::test_pause_stops_timer_and_sets_status -v`
Expected: FAIL with `AttributeError: 'AgentScheduler' object has no attribute 'pause'`

- [ ] **Step 3: Write minimal implementation**

Append to `core/agent_scheduler.py`:

```python
    # ── lifecycle controls ────────────────────────────────────────────────
    def pause(self, role_id: str) -> None:
        state = self._store.get(role_id)
        if state is None:
            return
        self.disarm(role_id)
        state.status = "paused"
        self._store.upsert(state)

    def resume(self, role_id: str) -> None:
        state = self._store.get(role_id)
        if state is None or state.status == "terminated":
            return
        state.status = "active"
        self._store.upsert(state)
        self.arm(state)

    def fire_now(self, role_id: str) -> Optional[str]:
        """Run an agent immediately, regardless of trigger mode.

        Returns the AgentTaskManager task id, or None if the agent could not
        be run (missing, terminated, or already in flight).
        """
        state = self._store.get(role_id)
        if state is None or state.status == "terminated":
            return None
        if role_id in self._in_flight:
            return None

        instance = self._instance_provider(role_id)
        if instance is None:
            return None
        runner = self._runner_builder(state)
        context = ""
        if state.history:
            context = str(state.history[-1].get("summary", ""))

        self._in_flight.add(role_id)
        now = self._now()
        state.last_fire_at = now.isoformat(timespec="seconds")
        state.runs += 1
        self._store.upsert(state)

        return self._task_manager.launch(
            agent=instance,
            task=str(getattr(instance, "current_task", None) or state.display_name),
            context=context,
            runner=runner,
            on_complete=lambda record, rid=role_id: self._on_run_complete(rid, record),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_scheduler.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add core/agent_scheduler.py tests/test_agent_scheduler.py
git commit -m "feat: add pause, resume, fire_now to AgentScheduler"
```

---

## Task 8: Add `load_and_arm` with catch-up

**Files:**
- Modify: `core/agent_scheduler.py`
- Modify: `tests/test_agent_scheduler.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_scheduler.py`:

```python
def test_load_and_arm_arms_active_scheduled_agents(tmp_path):
    now = datetime(2026, 5, 14, 14, 0, 0)
    factory, created = make_timer_factory()
    store = AgentStateStore(path=tmp_path / "state.json")
    store.upsert(scheduled_state(role_id="active_one"))
    store.upsert(scheduled_state(role_id="paused_one", status="paused"))

    fresh = AgentStateStore(path=tmp_path / "state.json")
    fresh.load()
    sched = AgentScheduler(
        state_store=fresh, task_manager=None,
        runner_builder=lambda s: (lambda **kw: None),
        instance_provider=lambda rid: object(),
        now_provider=fixed_clock(now), timer_factory=factory,
        reporter=lambda s, r: None,
    )
    sched.load_and_arm()

    assert "active_one" in created
    assert "paused_one" not in created


def test_load_and_arm_catch_up_fires_missed_scheduled_agent(tmp_path):
    now = datetime(2026, 5, 14, 14, 0, 0)
    factory, created = make_timer_factory()
    store = AgentStateStore(path=tmp_path / "state.json")
    # last fired at 09:00, interval 1h -> many ticks missed by 14:00
    missed = scheduled_state(role_id="missed")
    missed.last_fire_at = "2026-05-14T09:00:00"
    store.upsert(missed)

    fresh = AgentStateStore(path=tmp_path / "state.json")
    fresh.load()
    launched = []

    class FakeTaskManager:
        def launch(self, *, agent, task, context, runner, on_complete=None):
            launched.append(task)
            return "catchup-task"

    sched = AgentScheduler(
        state_store=fresh, task_manager=FakeTaskManager(),
        runner_builder=lambda s: (lambda **kw: None),
        instance_provider=lambda rid: object(),
        now_provider=fixed_clock(now), timer_factory=factory,
        reporter=lambda s, r: None,
    )
    sched.load_and_arm()

    assert len(launched) == 1  # caught up once
    assert "missed" in created  # and re-armed for the future


def test_load_and_arm_no_catch_up_when_recently_fired(tmp_path):
    now = datetime(2026, 5, 14, 14, 0, 0)
    factory, created = make_timer_factory()
    store = AgentStateStore(path=tmp_path / "state.json")
    recent = scheduled_state(role_id="recent")
    recent.last_fire_at = "2026-05-14T13:45:00"  # 15 min ago, interval 1h
    store.upsert(recent)

    fresh = AgentStateStore(path=tmp_path / "state.json")
    fresh.load()
    launched = []

    class FakeTaskManager:
        def launch(self, *, agent, task, context, runner, on_complete=None):
            launched.append(task)
            return "x"

    sched = AgentScheduler(
        state_store=fresh, task_manager=FakeTaskManager(),
        runner_builder=lambda s: (lambda **kw: None),
        instance_provider=lambda rid: object(),
        now_provider=fixed_clock(now), timer_factory=factory,
        reporter=lambda s, r: None,
    )
    sched.load_and_arm()

    assert launched == []  # not overdue -> no catch-up
    assert "recent" in created
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_scheduler.py::test_load_and_arm_arms_active_scheduled_agents -v`
Expected: FAIL with `AttributeError: 'AgentScheduler' object has no attribute 'load_and_arm'`

- [ ] **Step 3: Write minimal implementation**

Append to `core/agent_scheduler.py`:

```python
    # ── startup ───────────────────────────────────────────────────────────
    def load_and_arm(self) -> None:
        """Called on Plia startup. Arms every active scheduled/quota agent.

        Catch-up: if a scheduled agent's last fire is older than one full
        interval, fire it once immediately, then arm the next tick.
        """
        now = self._now()
        for state in self._store.all():
            if state.status != "active":
                continue
            if state.trigger == "on_demand":
                continue

            if state.trigger == "scheduled" and self._is_overdue(state, now):
                if state.role_id not in self._in_flight:
                    self._launch_run(state)

            self.arm(state)

    def _is_overdue(self, state, now: datetime) -> bool:
        if not state.last_fire_at:
            return False
        cadence = state.cadence or {"interval_sec": 3600, "anchor_iso": None}
        try:
            last = datetime.fromisoformat(state.last_fire_at)
        except ValueError:
            return False
        return (now - last).total_seconds() > int(cadence["interval_sec"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_scheduler.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Commit**

```bash
git add core/agent_scheduler.py tests/test_agent_scheduler.py
git commit -m "feat: add load_and_arm with missed-tick catch-up"
```

---

## Task 9: Add the default runner builder

**Files:**
- Modify: `core/agent_scheduler.py`
- Create: `tests/test_runner_builder.py`

This connects the scheduler to the Phase 2 executor factories. It is kept as a standalone function so tests can inject a fake instead.

- [ ] **Step 1: Write the failing test**

Create `tests/test_runner_builder.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_runner_builder.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_default_runner'`

- [ ] **Step 3: Write minimal implementation**

Append to `core/agent_scheduler.py`:

```python
def build_default_runner(state, *, role_tools, ollama_url: str, model: str):
    """Construct the executor runner for an AgentState.

    state.executor == "script"    -> subprocess runner over state.script_path
    state.executor == "tool_loop" -> Ollama tool-call loop over role_tools
    """
    from core.executors.script_executor import make_script_runner
    from core.executors.tool_loop_executor import make_tool_loop_runner
    from core.executors.run_result import RunResult

    if state.executor == "script":
        if not state.script_path:
            def _missing(*, agent, task, context):
                return RunResult(
                    success=False,
                    summary="Agent has no script path.",
                    details="state.executor is 'script' but script_path is unset.",
                    error="script_not_found",
                )
            return _missing
        return make_script_runner(state.script_path)

    return make_tool_loop_runner(
        allowed_tools=list(role_tools or []),
        ollama_url=ollama_url,
        model=model,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_runner_builder.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add core/agent_scheduler.py tests/test_runner_builder.py
git commit -m "feat: add build_default_runner connecting scheduler to executors"
```

---

## Task 10: Phase 3 integration check

**Files:** none — verification only.

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v`
Expected: PASS — 29 from Phases 1-2 plus Phase 3:
`test_task_manager_callback.py` (2), `test_cadence_parser.py` (8), `test_compute_next_fire.py` (4), `test_agent_scheduler.py` (14), `test_runner_builder.py` (3) = 31 new → 60 passed total.

- [ ] **Step 2: Verify scheduler imports cleanly**

Run: `python -c "from core.agent_scheduler import AgentScheduler, parse_cadence, compute_next_fire, build_default_runner; print('scheduler OK')"`
Expected: prints `scheduler OK`.

- [ ] **Step 3: Commit (if any fixes were needed)**

If steps 1-2 required fixes, commit them:

```bash
git add -A
git commit -m "fix: Phase 3 integration adjustments"
```

If no fixes were needed, skip this step.

---

## Phase 3 Complete

**Deliverables:**
- `AgentTaskManager.launch` now supports an `on_complete` callback.
- `parse_cadence` — natural-language → `{interval_sec, anchor_iso}`.
- `compute_next_fire` — schedule arithmetic with future/past anchors.
- `AgentScheduler` — arm, disarm, tick, reschedule, run-completion handling (history + quota termination + reporter hook), pause, resume, fire_now, load_and_arm with catch-up.
- `build_default_runner` — connects scheduler to Phase 2 executor factories.
- 60 passing tests total.

**Verification before moving to Phase 4:** `pytest tests/ -v` green, `core.agent_scheduler` imports cleanly.

**Next:** Phase 4 (Creation pipeline) builds the wizard that produces `AgentState` entries + role YAML and feeds them into the scheduler.
