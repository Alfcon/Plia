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


from PySide6.QtCore import QObject, QTimer, Signal


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

    Signals:
      run_started(role_id)   — emitted just before an agent's runner is invoked
      run_finished(role_id)  — emitted when the run callback fires (any outcome)
    """

    run_started = Signal(str)
    run_finished = Signal(str)

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
        self.run_started.emit(state.role_id)

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
        self._handle_completion(role_id, record)
        self.run_finished.emit(role_id)

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

    def fire_now(self, role_id: str, task: Optional[str] = None) -> Optional[str]:
        """Run an agent immediately, regardless of trigger mode.

        Args:
          role_id: which agent to fire.
          task:    optional one-off prompt for this run. If None, falls back
                   to the agent's `current_task` then to its display name.
                   Lets callers (e.g. the "Run with prompt..." dialog) drive
                   an agent with a fresh prompt without editing its
                   stored task description.

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
        self.run_started.emit(role_id)

        if task and task.strip():
            final_task = task.strip()
        else:
            final_task = str(
                getattr(instance, "current_task", None) or state.display_name
            )

        return self._task_manager.launch(
            agent=instance,
            task=final_task,
            context=context,
            runner=runner,
            on_complete=lambda record, rid=role_id: self._on_run_complete(rid, record),
        )

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


def build_default_runner(state, *, role_tools, ollama_url: str, model: str):
    """Construct the executor runner for an AgentState.

    state.executor == "script"      -> subprocess runner over state.script_path
    state.executor == "tool_loop"   -> Ollama tool-call loop over role_tools
    state.executor == "direct_tool" -> Invoke one named tool with fixed args
                                       (no LLM in the loop). Reads
                                       state.direct_tool_id / direct_tool_args.
    """
    from core.executors.script_executor import make_script_runner
    from core.executors.tool_loop_executor import make_tool_loop_runner
    from core.executors.direct_tool_executor import make_direct_tool_runner
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

    if state.executor == "direct_tool":
        return make_direct_tool_runner(
            tool_id=state.direct_tool_id or "",
            arguments=state.direct_tool_args or {},
        )

    return make_tool_loop_runner(
        allowed_tools=list(role_tools or []),
        ollama_url=ollama_url,
        model=model,
    )
