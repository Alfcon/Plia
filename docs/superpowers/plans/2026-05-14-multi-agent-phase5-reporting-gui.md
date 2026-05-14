# Multi-Agent System — Phase 5: Reporting + GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the feature — `ResultDispatcher` fans run results to TTS / toast+card / comm-log; the Active Agents tab gains a Live Agents section with controls; an editor dialog edits live agents; a chat wizard dialog mirrors the voice wizard; and app-level wiring constructs the runtime, loads persisted agents on startup, and makes `commit()` real.

**Architecture:** A new `core/agent_reporting.py` holds `ResultDispatcher` (QObject, signal-based fan-out). A new `core/agent_runtime.py` constructs the process-wide singletons (`AgentStateStore`, `AgentScheduler`, `ResultDispatcher`) and exposes `get_runtime()` + `commit_answers()` so voice, chat, and the app share one runtime. GUI changes add a `LiveAgentsSection` to `AgentsTab`, a `LiveAgentEditorDialog` to `agent_editor.py`, an `add_agent_card` method to `DashboardView`, and a `CreationWizardDialog` for the chat path. `gui/app.py` starts the runtime, connects dispatcher signals, and the voice `_on_done` stub is replaced with a real `commit_answers()` call.

**Tech Stack:** Python 3, PySide6 + qfluentwidgets, `pytest` (for `ResultDispatcher` and `agent_runtime`), import-checks + a manual smoke checklist for the GUI widgets.

**Spec:** `docs/superpowers/specs/2026-05-14-multi-agent-system-design.md` (Reporting + Active Agents tab controls sections).

**Depends on:** Phases 1-4. Uses `core/agent_state.py`, `core/agent_scheduler.py`, `core/agent_creator.py`, `core/executors/`, `core/multi_agent.py`.

**Spec deviation (noted):** The spec described "extended `AgentEditorWindow`". The actual `gui/tabs/agent_editor.py` uses `AgentEditorWindow` as a role *browser* and `RoleEditorDialog` as the editor. To avoid restructuring working code, this plan adds a dedicated `LiveAgentEditorDialog` instead — consistent with the codebase's existing one-dialog-per-purpose pattern (`CreateAgentDialog`, `RunAgentDialog`, `RoleEditorDialog`).

---

## File Structure

| Path | Responsibility |
|---|---|
| `core/agent_reporting.py` (create) | `ResultDispatcher` — fan run results to history-refresh / TTS / toast+card / comm-log |
| `core/agent_runtime.py` (create) | Process-wide singletons + `get_runtime()` + `commit_answers()` + `start()` |
| `gui/tabs/dashboard.py` (modify) | `add_agent_card(payload)` method + a card-list region in the right panel |
| `gui/tabs/agents.py` (modify) | `LiveAgentRow` + `LiveAgentsSection` widgets; integrate into `AgentsTab` |
| `gui/tabs/agent_editor.py` (modify) | `LiveAgentEditorDialog` — schedule / tools / notify / advanced editing |
| `gui/tabs/creation_wizard.py` (create) | `CreationWizardDialog` — chat-channel multi-page wizard |
| `gui/app.py` (modify) | Start runtime, connect dispatcher signals |
| `gui/handlers.py` (modify) | `ChatHandlers` — connect `live_agent_wizard_signal`, open `CreationWizardDialog` |
| `core/voice_assistant.py` (modify) | Replace `_start_agent_wizard._on_done` stub with real `commit_answers()` |
| `tests/test_result_dispatcher.py` (create) | `ResultDispatcher` fan-out tests |
| `tests/test_agent_runtime.py` (create) | `agent_runtime` wiring tests |
| `tests/manual_smoke.md` (create) | Manual GUI/voice verification checklist |

---

## Task 1: Build `ResultDispatcher`

**Files:**
- Create: `core/agent_reporting.py`
- Create: `tests/test_result_dispatcher.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_result_dispatcher.py`:

```python
from core.agent_reporting import ResultDispatcher
from core.agent_state import AgentState
from core.executors.run_result import RunResult


def _state(notify, role_id="r1"):
    return AgentState(
        role_id=role_id, instance_id="i1", display_name="GitHub Watcher",
        icon="🔍", executor="tool_loop", trigger="scheduled",
        persistence="persistent", notify=notify, status="active",
        created_at="2026-05-14T10:00:00",
    )


def test_report_always_emits_history_appended():
    d = ResultDispatcher(speak=lambda s: None)
    appended = []
    d.agent_history_appended.connect(appended.append)
    d.report(_state("comm_log"), RunResult(True, "ok", "d", items_found=1))
    assert appended == ["r1"]


def test_report_tts_speaks_summary_on_success():
    spoken = []
    d = ResultDispatcher(speak=spoken.append)
    d.report(_state("tts"), RunResult(True, "found 3 repos", "d", items_found=3))
    assert len(spoken) == 1
    assert "found 3 repos" in spoken[0]


def test_report_tts_says_nothing_new_when_empty():
    spoken = []
    d = ResultDispatcher(speak=spoken.append)
    d.report(_state("tts"), RunResult(True, "ran", "d", items_found=0))
    assert "nothing new" in spoken[0].lower()


def test_report_tts_announces_failure():
    spoken = []
    d = ResultDispatcher(speak=spoken.append)
    d.report(_state("tts"), RunResult(False, "x", "d", error="timeout"))
    assert "failed" in spoken[0].lower()
    assert "timeout" in spoken[0].lower()


def test_report_toast_card_emits_both_signals():
    d = ResultDispatcher(speak=lambda s: None)
    toasts, cards = [], []
    d.show_toast.connect(lambda t, b, ok: toasts.append((t, b, ok)))
    d.dashboard_card_added.connect(cards.append)
    d.report(_state("toast_card"), RunResult(True, "found 2", "d", items_found=2,
                                             items=[{"title": "a"}, {"title": "b"}]))
    assert toasts[0][0] == "GitHub Watcher"
    assert toasts[0][2] is True
    assert cards[0]["role_id"] == "r1"
    assert cards[0]["items_found"] == 2


def test_report_comm_log_emits_with_item_bullets():
    d = ResultDispatcher(speak=lambda s: None)
    logs = []
    d.comm_log_append.connect(lambda rid, title, body: logs.append((rid, title, body)))
    d.report(_state("comm_log"), RunResult(True, "found 1", "d", items_found=1,
                                           items=[{"title": "acme/repo"}]))
    rid, title, body = logs[0]
    assert rid == "r1"
    assert "GitHub Watcher" in title
    assert "acme/repo" in body


def test_report_tts_channel_does_not_emit_toast():
    d = ResultDispatcher(speak=lambda s: None)
    toasts = []
    d.show_toast.connect(lambda *a: toasts.append(a))
    d.report(_state("tts"), RunResult(True, "x", "d"))
    assert toasts == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_result_dispatcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.agent_reporting'`

- [ ] **Step 3: Write minimal implementation**

Create `core/agent_reporting.py`:

```python
"""
agent_reporting.py — Fans an agent RunResult out to notification channels.

ResultDispatcher.report(state, result) is the callback the AgentScheduler
invokes (as its `reporter`) after a run completes. The scheduler has already
appended the run to AgentState.history and persisted it; the dispatcher's job
is purely notification:

  - always:           emit agent_history_appended(role_id)  -> AgentsTab refresh
  - notify == tts:        speak a short summary
  - notify == toast_card: emit show_toast + dashboard_card_added
  - notify == comm_log:   emit comm_log_append

All cross-thread delivery happens via Qt queued signal connections.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal


class ResultDispatcher(QObject):
    agent_history_appended = Signal(str)            # role_id
    show_toast = Signal(str, str, bool)             # title, body, success
    dashboard_card_added = Signal(dict)             # card payload
    comm_log_append = Signal(str, str, str)         # role_id, title, body

    def __init__(self, *, speak: Optional[Callable[[str], None]] = None, parent=None):
        super().__init__(parent)
        self._speak = speak

    def report(self, state, result) -> None:
        """state: AgentState, result: RunResult."""
        self.agent_history_appended.emit(state.role_id)
        if state.notify == "tts":
            self._report_tts(state, result)
        elif state.notify == "toast_card":
            self._report_toast_card(state, result)
        elif state.notify == "comm_log":
            self._report_comm_log(state, result)

    # ── channels ──────────────────────────────────────────────────────────
    def _speak_text(self, text: str) -> None:
        if self._speak is not None:
            self._speak(text)
            return
        try:
            from core.tts import tts
            tts.queue_sentence(text)
        except Exception as exc:
            print(f"[ResultDispatcher] TTS unavailable: {exc}")

    def _report_tts(self, state, result) -> None:
        if not result.success:
            msg = f"{state.display_name} failed. {result.error or 'unknown error'}."
        elif result.items_found == 0:
            msg = f"{state.display_name} ran. Nothing new."
        else:
            msg = f"{state.display_name}: {result.summary}"
        self._speak_text(msg)

    def _report_toast_card(self, state, result) -> None:
        title = state.display_name
        body = result.summary if result.success else f"Failed: {result.error}"
        self.show_toast.emit(title, body, bool(result.success))
        self.dashboard_card_added.emit({
            "role_id": state.role_id,
            "icon": state.icon,
            "title": state.display_name,
            "summary": result.summary,
            "items_found": result.items_found,
            "items": list(result.items[:5]),
            "success": bool(result.success),
        })

    def _report_comm_log(self, state, result) -> None:
        title = f"{state.icon} {state.display_name}"
        body = result.summary
        for item in (result.items or [])[:5]:
            body += f"\n  • {item.get('title', '?')}"
        self.comm_log_append.emit(state.role_id, title, body)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_result_dispatcher.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add core/agent_reporting.py tests/test_result_dispatcher.py
git commit -m "feat: add ResultDispatcher for agent run-result fan-out"
```

---

## Task 2: Build the `agent_runtime` wiring module

**Files:**
- Create: `core/agent_runtime.py`
- Create: `tests/test_agent_runtime.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_runtime.py`:

```python
import core.agent_runtime as ar


def test_get_runtime_is_singleton():
    ar._runtime = None  # reset
    r1 = ar.get_runtime()
    r2 = ar.get_runtime()
    assert r1 is r2


def test_runtime_exposes_store_scheduler_dispatcher():
    ar._runtime = None
    rt = ar.get_runtime()
    assert rt.store is not None
    assert rt.scheduler is not None
    assert rt.dispatcher is not None


def test_runtime_reporter_is_dispatcher_report():
    ar._runtime = None
    rt = ar.get_runtime()
    # the scheduler's reporter should be the dispatcher's report method
    assert rt.scheduler._reporter == rt.dispatcher.report
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_runtime.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.agent_runtime'`

- [ ] **Step 3: Write minimal implementation**

Create `core/agent_runtime.py`:

```python
"""
agent_runtime.py — Process-wide wiring for the live-agent system.

Constructs the single AgentStateStore + AgentScheduler + ResultDispatcher and
exposes them through get_runtime(). Voice, chat, and the app window all share
this one runtime so there is exactly one scheduler and one state store.

  get_runtime()                  -> the _Runtime singleton
  runtime.start()                -> load persisted agents + arm the scheduler
  runtime.commit_answers(answers) -> create a live agent from wizard answers
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.agent_state import AgentStateStore
from core.agent_scheduler import AgentScheduler, build_default_runner
from core.agent_reporting import ResultDispatcher
from core.agent_creator import commit
from core.multi_agent import multi_agent_system, AgentInstance
from config import OLLAMA_URL, RESPONDER_MODEL

_ROLES_DIR = Path.home() / ".plia_ai" / "roles"


class _Runtime:
    def __init__(self):
        self.store = AgentStateStore()
        self.dispatcher = ResultDispatcher()
        self.scheduler = AgentScheduler(
            state_store=self.store,
            task_manager=multi_agent_system.task_manager,
            runner_builder=self._build_runner,
            instance_provider=self._get_instance,
            reporter=self.dispatcher.report,
        )
        self._started = False

    # ── model helper ──────────────────────────────────────────────────────
    def _model(self) -> str:
        try:
            from core.settings_store import settings as app_settings
            return app_settings.get("models.chat", RESPONDER_MODEL)
        except Exception:
            return RESPONDER_MODEL

    # ── scheduler dependencies ────────────────────────────────────────────
    def _build_runner(self, state):
        role = multi_agent_system.roles.get(state.role_id)
        tools = list(role.tools) if role else []
        return build_default_runner(
            state, role_tools=tools, ollama_url=OLLAMA_URL, model=self._model())

    def _get_instance(self, role_id: str):
        for inst in multi_agent_system.hierarchy.get_all_agents():
            if inst.agent.role.id == role_id:
                return inst
        return None

    def _make_instance(self, role_id: str, display_name: str):
        multi_agent_system.reload_roles()
        role = multi_agent_system.roles.get(role_id)
        if role is None:
            print(f"[agent_runtime] role not found after reload: {role_id}")
            return None
        existing = self._get_instance(role_id)
        if existing is not None:
            return existing
        inst = AgentInstance(role)
        multi_agent_system.hierarchy.add_agent(inst)
        return inst

    # ── lifecycle ─────────────────────────────────────────────────────────
    def start(self) -> None:
        """Load persisted agents and arm the scheduler. Idempotent."""
        if self._started:
            return
        self.store.load()
        multi_agent_system.reload_roles()
        for state in self.store.all():
            if self._get_instance(state.role_id) is None:
                self._make_instance(state.role_id, state.display_name)
        self.scheduler.load_and_arm()
        self._started = True

    def commit_answers(self, answers: dict,
                       script_path: Optional[str] = None):
        """Create a live agent from wizard answers. Returns the AgentState."""
        return commit(
            answers,
            roles_dir=_ROLES_DIR,
            state_store=self.store,
            scheduler=self.scheduler,
            multi_agent_system=multi_agent_system,
            instance_factory=self._make_instance,
            script_path=script_path,
        )


_runtime: Optional[_Runtime] = None


def get_runtime() -> _Runtime:
    global _runtime
    if _runtime is None:
        _runtime = _Runtime()
    return _runtime
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_runtime.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add core/agent_runtime.py tests/test_agent_runtime.py
git commit -m "feat: add agent_runtime wiring module"
```

---

## Task 3: Add `add_agent_card` to `DashboardView`

**Files:**
- Modify: `gui/tabs/dashboard.py` (`DashboardView` class — `_build_right_panel` around line 752, add method near `add_system_message` at line 1050)

- [ ] **Step 1: Read the right-panel builder**

Run: `sed -n '752,800p' gui/tabs/dashboard.py`
Expected: shows `_build_right_panel` building a `QFrame` with a layout that contains the `COMMUNICATION LOG` label and the log widget. Note the layout variable name (e.g. `layout` or `right_layout`) and the panel variable returned.

- [ ] **Step 2: Add a card-list container in `_build_right_panel`**

In `gui/tabs/dashboard.py`, inside `_build_right_panel`, immediately before the line that adds the `COMMUNICATION LOG` label (`lbl = QLabel("COMMUNICATION LOG")` ... `layout.addWidget(lbl)`), insert a card container. Use the actual layout variable name observed in Step 1 (shown here as `layout`):

```python
        # ── Live-agent result cards ──────────────────────────────────────
        from PySide6.QtWidgets import QVBoxLayout as _QVBox
        self._agent_cards_box = QWidget()
        self._agent_cards_layout = _QVBox(self._agent_cards_box)
        self._agent_cards_layout.setContentsMargins(0, 0, 0, 0)
        self._agent_cards_layout.setSpacing(6)
        layout.addWidget(self._agent_cards_box)
```

`QWidget` is already imported in `dashboard.py`.

- [ ] **Step 3: Add the `add_agent_card` method**

In `gui/tabs/dashboard.py`, add this method to the `DashboardView` class, immediately after `add_system_message` (around line 1050):

```python
    def add_agent_card(self, payload: dict) -> None:
        """Add a live-agent result card to the right panel. Newest on top,
        capped at 5 visible cards."""
        from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel

        card = QFrame()
        card.setObjectName("agentResultCard")
        ok = payload.get("success", True)
        border = "#4caf50" if ok else "#ef5350"
        card.setStyleSheet(
            f"QFrame#agentResultCard {{ border: 1px solid {border};"
            f" border-radius: 6px; background: rgba(255,255,255,0.04); }}"
        )
        col = QVBoxLayout(card)
        col.setContentsMargins(8, 6, 8, 6)
        col.setSpacing(2)

        header = QLabel(f"{payload.get('icon', '🤖')}  {payload.get('title', 'Agent')}")
        header.setStyleSheet("font-weight: 600;")
        col.addWidget(header)

        summary = QLabel(payload.get("summary", ""))
        summary.setWordWrap(True)
        col.addWidget(summary)

        for item in payload.get("items", [])[:5]:
            row = QLabel(f"  • {item.get('title', '?')}")
            row.setStyleSheet("color: #9aa0aa;")
            col.addWidget(row)

        self._agent_cards_layout.insertWidget(0, card)

        # cap at 5 visible cards
        while self._agent_cards_layout.count() > 5:
            old = self._agent_cards_layout.takeAt(self._agent_cards_layout.count() - 1)
            w = old.widget()
            if w is not None:
                w.deleteLater()
```

- [ ] **Step 4: Verify the module imports**

Run: `python -c "import gui.tabs.dashboard; print('dashboard OK')"`
Expected: prints `dashboard OK` with no traceback.

- [ ] **Step 5: Commit**

```bash
git add gui/tabs/dashboard.py
git commit -m "feat: add live-agent result cards to dashboard"
```

---

## Task 4: Build the `LiveAgentsSection` and integrate into `AgentsTab`

**Files:**
- Modify: `gui/tabs/agents.py` (add `LiveAgentRow` + `LiveAgentsSection` classes; call from `AgentsTab._build_multi_agent_section` ~line 980 and `AgentsTab.refresh` ~line 1249)

- [ ] **Step 1: Read the integration points**

Run: `sed -n '876,1030p' gui/tabs/agents.py`
Expected: shows `AgentsTab.__init__`, `_build_multi_agent_section`, `_build_custom_section`. Note the layout variable used inside `_build_multi_agent_section` and how sections are added to the tab.

- [ ] **Step 2: Add the `LiveAgentRow` and `LiveAgentsSection` classes**

In `gui/tabs/agents.py`, add these two classes immediately before `class AgentsTab` (around line 876):

```python
class LiveAgentRow(QFrame):
    """One live agent: status line + Run/Pause/Resume/Stop/Edit/Delete + history."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self._state = state
        self.setObjectName("liveAgentRow")
        self._build()

    def _build(self):
        from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        s = self._state
        head = QLabel(f"{s.icon}  {s.display_name}   "
                      f"<span style='color:#9aa0aa'>● {s.status}</span>")
        outer.addWidget(head)

        sub_bits = [f"Trigger: {s.trigger}"]
        if s.trigger == "scheduled" and s.cadence:
            mins = s.cadence.get("interval_sec", 0) // 60
            sub_bits.append(f"every {mins} min")
        if s.trigger == "quota" and s.quota:
            sub_bits.append(f"quota {s.quota.get('progress', 0)}/{s.quota.get('limit', 0)}")
        sub_bits.append(f"runs: {s.runs}")
        if s.last_fire_at:
            sub_bits.append(f"last: {s.last_fire_at}")
        sub = QLabel(" · ".join(sub_bits))
        sub.setStyleSheet("color:#9aa0aa;")
        outer.addWidget(sub)

        btn_row = QHBoxLayout()
        from core.agent_runtime import get_runtime
        rt = get_runtime()

        def _refresh_parent():
            p = self.parent()
            while p is not None and not isinstance(p, LiveAgentsSection):
                p = p.parent()
            if p is not None:
                p.refresh()

        if s.status != "terminated":
            run_btn = PushButton("▶ Run now")
            run_btn.clicked.connect(
                lambda: (rt.scheduler.fire_now(s.role_id), _refresh_parent()))
            btn_row.addWidget(run_btn)

            if s.trigger != "on_demand":
                if s.status == "paused":
                    resume_btn = PushButton("▶ Resume")
                    resume_btn.clicked.connect(
                        lambda: (rt.scheduler.resume(s.role_id), _refresh_parent()))
                    btn_row.addWidget(resume_btn)
                else:
                    pause_btn = PushButton("⏸ Pause")
                    pause_btn.clicked.connect(
                        lambda: (rt.scheduler.pause(s.role_id), _refresh_parent()))
                    btn_row.addWidget(pause_btn)

            stop_btn = PushButton("⏹ Stop")
            stop_btn.clicked.connect(
                lambda: (rt.scheduler.disarm(s.role_id),
                         self._terminate(rt), _refresh_parent()))
            btn_row.addWidget(stop_btn)

            edit_btn = PushButton("⚙ Edit")
            edit_btn.clicked.connect(lambda: self._open_editor(_refresh_parent))
            btn_row.addWidget(edit_btn)

        del_btn = PushButton("🗑 Delete")
        del_btn.clicked.connect(lambda: self._delete(rt, _refresh_parent))
        btn_row.addWidget(del_btn)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        if s.history:
            hist = QLabel("\n".join(
                f"  {h.get('ran_at', '?')}  "
                f"{'✓' if h.get('success') else '✗'}  {h.get('summary', '')}"
                for h in s.history[-5:]))
            hist.setStyleSheet("color:#7d828c; font-size:11px;")
            outer.addWidget(hist)

    def _terminate(self, rt):
        from core.multi_agent import multi_agent_system
        st = rt.store.get(self._state.role_id)
        if st is None:
            return
        st.status = "terminated"
        rt.store.upsert(st)
        inst = rt._get_instance(self._state.role_id)
        if inst is not None:
            multi_agent_system.terminate_agent(inst.id)

    def _delete(self, rt, refresh_cb):
        from pathlib import Path
        rt.scheduler.disarm(self._state.role_id)
        rt.store.remove(self._state.role_id)
        role_file = Path.home() / ".plia_ai" / "roles" / f"{self._state.role_id}.yml"
        if role_file.exists():
            role_file.unlink()
        if self._state.script_path:
            sp = Path(self._state.script_path)
            if sp.exists():
                sp.unlink()
        refresh_cb()

    def _open_editor(self, refresh_cb):
        from gui.tabs.agent_editor import LiveAgentEditorDialog
        dlg = LiveAgentEditorDialog(self._state, parent=self)
        if dlg.exec():
            refresh_cb()


class LiveAgentsSection(QWidget):
    """Lists every live agent from the runtime's state store, with bulk
    controls (Pause all / Resume all) and a status filter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QComboBox

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)

        self._header = SubtitleLabel("Live Agents")
        self._layout.addWidget(self._header)

        # ── bulk controls row ────────────────────────────────────────────
        controls = QHBoxLayout()
        pause_all = PushButton("⏸ Pause all")
        pause_all.clicked.connect(self._pause_all)
        resume_all = PushButton("▶ Resume all")
        resume_all.clicked.connect(self._resume_all)
        controls.addWidget(pause_all)
        controls.addWidget(resume_all)
        self._filter = QComboBox()
        self._filter.addItems(["All", "Active", "Paused", "Terminated"])
        self._filter.currentTextChanged.connect(lambda _: self.refresh())
        controls.addWidget(self._filter)
        controls.addStretch(1)
        self._layout.addLayout(controls)

        self._rows_box = QWidget()
        from PySide6.QtWidgets import QVBoxLayout as _V
        self._rows_layout = _V(self._rows_box)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        self._layout.addWidget(self._rows_box)
        self.refresh()

    def _pause_all(self):
        from core.agent_runtime import get_runtime
        rt = get_runtime()
        for s in rt.store.all():
            if s.status == "active" and s.trigger != "on_demand":
                rt.scheduler.pause(s.role_id)
        self.refresh()

    def _resume_all(self):
        from core.agent_runtime import get_runtime
        rt = get_runtime()
        for s in rt.store.all():
            if s.status == "paused":
                rt.scheduler.resume(s.role_id)
        self.refresh()

    def refresh(self):
        # clear existing rows
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        from core.agent_runtime import get_runtime
        all_states = sorted(get_runtime().store.all(), key=lambda s: s.display_name)

        # apply the status filter
        chosen = self._filter.currentText()
        if chosen == "All":
            states = all_states
        else:
            states = [s for s in all_states if s.status == chosen.lower()]

        if not states:
            msg = ("No live agents yet. Say \"Create an agent that…\" "
                   "or use the chat to set one up.") if not all_states \
                else f"No {chosen.lower()} agents."
            empty = BodyLabel(msg)
            empty.setStyleSheet("color:#7d828c;")
            self._rows_layout.addWidget(empty)
        else:
            for state in states:
                self._rows_layout.addWidget(LiveAgentRow(state))

        # count strip always reflects ALL agents, not the filtered view
        active = sum(1 for s in all_states if s.status == "active")
        paused = sum(1 for s in all_states if s.status == "paused")
        term = sum(1 for s in all_states if s.status == "terminated")
        self._header.setText(
            f"Live Agents   ({active} active · {paused} paused · {term} terminated)")
```

- [ ] **Step 3: Instantiate `LiveAgentsSection` in `AgentsTab`**

In `gui/tabs/agents.py`, inside `AgentsTab._build_multi_agent_section` (around line 980), add the live-agents section. Using the layout variable observed in Step 1 (shown here as `section_layout` — replace with the real name), add near the end of the method, before it returns or finishes:

```python
        # ── Live Agents (scheduled / on-demand / quota workers) ──────────
        self._live_agents_section = LiveAgentsSection()
        section_layout.addWidget(self._live_agents_section)
```

- [ ] **Step 4: Refresh the section from `AgentsTab.refresh`**

In `gui/tabs/agents.py`, inside `AgentsTab.refresh` (around line 1249), add at the end of the method:

```python
        if getattr(self, "_live_agents_section", None) is not None:
            self._live_agents_section.refresh()
```

- [ ] **Step 5: Verify the module imports**

Run: `python -c "import gui.tabs.agents; print('agents OK')"`
Expected: prints `agents OK` with no traceback.

- [ ] **Step 6: Commit**

```bash
git add gui/tabs/agents.py
git commit -m "feat: add Live Agents section with controls to Active Agents tab"
```

---

## Task 5: Build `LiveAgentEditorDialog`

**Files:**
- Modify: `gui/tabs/agent_editor.py` (add `LiveAgentEditorDialog` class at the end of the file)

- [ ] **Step 1: Add the `LiveAgentEditorDialog` class**

In `gui/tabs/agent_editor.py`, append this class at the end of the file:

```python
class LiveAgentEditorDialog(QDialog):
    """Edit a live agent's schedule, tools, notification channel, and
    persistence. Executor type is read-only (changing it needs recreation)."""

    # confirmed tool names from core/function_executor.py
    ALL_TOOLS = [
        "web_search", "http_get", "read_emails", "get_system_info",
        "get_stock_price", "convert_currency", "translate_text",
        "manage_notes", "network_tools", "control_media",
        "send_email", "create_calendar_event", "add_task",
        "file_operations", "system_command", "control_desktop",
    ]
    DESTRUCTIVE = {"send_email", "create_calendar_event", "add_task",
                   "file_operations", "system_command", "control_desktop"}

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Live Agent — {state.display_name}")
        self._state = state
        self._build()

    def _build(self):
        from PySide6.QtWidgets import (
            QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
            QCheckBox, QPushButton, QScrollArea, QWidget,
        )

        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"<b>{self._state.icon}  {self._state.display_name}</b>"))
        root.addWidget(QLabel(f"Engine: {self._state.executor} (read-only)"))

        # ── Schedule ──────────────────────────────────────────────────────
        root.addWidget(QLabel("Trigger"))
        self._trigger = QComboBox()
        self._trigger.addItems(["scheduled", "on_demand", "quota"])
        self._trigger.setCurrentText(self._state.trigger)
        root.addWidget(self._trigger)

        root.addWidget(QLabel("Cadence (e.g. 'every 6 hours') — scheduled only"))
        self._cadence = QLineEdit()
        if self._state.cadence:
            mins = self._state.cadence.get("interval_sec", 0) // 60
            self._cadence.setText(f"every {mins} minutes")
        root.addWidget(self._cadence)

        root.addWidget(QLabel("Quota limit — quota only"))
        self._quota = QLineEdit()
        if self._state.quota:
            self._quota.setText(str(self._state.quota.get("limit", "")))
        root.addWidget(self._quota)

        # ── Notify ────────────────────────────────────────────────────────
        root.addWidget(QLabel("Notify channel"))
        self._notify = QComboBox()
        self._notify.addItems(["tts", "toast_card", "comm_log"])
        self._notify.setCurrentText(self._state.notify)
        root.addWidget(self._notify)

        # ── Persistence ───────────────────────────────────────────────────
        root.addWidget(QLabel("Persistence"))
        self._persistence = QComboBox()
        self._persistence.addItems(["persistent", "session"])
        self._persistence.setCurrentText(self._state.persistence)
        root.addWidget(self._persistence)

        # ── Tools ─────────────────────────────────────────────────────────
        root.addWidget(QLabel("Allowed tools (red = destructive, opt-in)"))
        tools_box = QWidget()
        tools_layout = QVBoxLayout(tools_box)
        from core.multi_agent import multi_agent_system
        role = multi_agent_system.roles.get(self._state.role_id)
        current_tools = set(role.tools) if role else set()
        self._tool_checks = {}
        for tool in self.ALL_TOOLS:
            cb = QCheckBox(tool)
            cb.setChecked(tool in current_tools)
            if tool in self.DESTRUCTIVE:
                cb.setStyleSheet("color:#ef5350;")
            tools_layout.addWidget(cb)
            self._tool_checks[tool] = cb
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(tools_box)
        scroll.setMinimumHeight(160)
        root.addWidget(scroll)

        # ── Buttons ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.clicked.connect(self._save)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel)
        btn_row.addWidget(save)
        root.addLayout(btn_row)

    def _save(self):
        from core.agent_runtime import get_runtime
        from core.agent_scheduler import parse_cadence
        from core.multi_agent import multi_agent_system
        import yaml
        from pathlib import Path

        rt = get_runtime()
        state = rt.store.get(self._state.role_id)
        if state is None:
            self.reject()
            return

        # disarm before mutating schedule
        rt.scheduler.disarm(state.role_id)

        state.trigger = self._trigger.currentText()
        state.notify = self._notify.currentText()
        state.persistence = self._persistence.currentText()

        if state.trigger == "scheduled":
            cad = parse_cadence(self._cadence.text())
            state.cadence = cad or {"interval_sec": 3600, "anchor_iso": None}
            state.quota = None
        elif state.trigger == "quota":
            try:
                limit = int(self._quota.text().strip())
            except ValueError:
                limit = 10
            state.quota = {"limit": limit, "criterion": "any", "progress": 0}
            state.cadence = None
        else:  # on_demand
            state.cadence = None
            state.quota = None

        # update tools in the role YAML
        selected = [t for t, cb in self._tool_checks.items() if cb.isChecked()]
        role_file = Path.home() / ".plia_ai" / "roles" / f"{state.role_id}.yml"
        if role_file.exists():
            raw = yaml.safe_load(role_file.read_text(encoding="utf-8")) or {}
            raw["tools"] = selected
            raw["autonomous_actions"] = selected
            role_file.write_text(
                yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
                encoding="utf-8")
            multi_agent_system.reload_roles()

        rt.store.upsert(state)
        if state.status == "active":
            rt.scheduler.arm(state)
        self.accept()
```

- [ ] **Step 2: Verify the module imports**

Run: `python -c "import gui.tabs.agent_editor; print('agent_editor OK')"`
Expected: prints `agent_editor OK` with no traceback.

- [ ] **Step 3: Commit**

```bash
git add gui/tabs/agent_editor.py
git commit -m "feat: add LiveAgentEditorDialog for editing live agents"
```

---

## Task 6: Build the chat `CreationWizardDialog`

**Files:**
- Create: `gui/tabs/creation_wizard.py`

This dialog drives the same `WizardController` the voice path uses — one question per page, advancing on button click.

- [ ] **Step 1: Write the dialog**

Create `gui/tabs/creation_wizard.py`:

```python
"""
creation_wizard.py — Chat-channel wizard for creating a live agent.

Drives the same WizardController as the voice path. Each wizard question is
shown as a single page (label + text input + Next button). On completion it
calls agent_runtime.commit_answers(...) and refreshes the Active Agents tab.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)

from core.agent_creator import WizardController, classify_executor
from core.agent_runtime import get_runtime
from config import OLLAMA_URL, RESPONDER_MODEL


class CreationWizardDialog(QDialog):
    def __init__(self, task: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create a Live Agent")
        self._task = task

        def _classify(t: str) -> str:
            try:
                from core.settings_store import settings as app_settings
                model = app_settings.get("models.chat", RESPONDER_MODEL)
            except Exception:
                model = RESPONDER_MODEL
            return classify_executor(t, OLLAMA_URL, model)

        self._wizard = WizardController(task, classify_fn=_classify)
        self._committed_state = None
        self._build()
        self._show_step(self._wizard.current_question())

    def _build(self):
        root = QVBoxLayout(self)
        self._intro = QLabel(f"Setting up a live agent to: {self._task}")
        self._intro.setWordWrap(True)
        root.addWidget(self._intro)

        self._question = QLabel("")
        self._question.setWordWrap(True)
        self._question.setStyleSheet("font-weight:600;")
        root.addWidget(self._question)

        self._examples = QLabel("")
        self._examples.setWordWrap(True)
        self._examples.setStyleSheet("color:#9aa0aa;")
        root.addWidget(self._examples)

        self._input = QLineEdit()
        self._input.returnPressed.connect(self._on_next)
        root.addWidget(self._input)

        btn_row = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self._next_btn = QPushButton("Next")
        self._next_btn.clicked.connect(self._on_next)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel)
        btn_row.addWidget(self._next_btn)
        root.addLayout(btn_row)

    def _show_step(self, step):
        self._question.setText(step.question)
        self._examples.setText(
            "Examples: " + ", ".join(step.examples) if step.examples else "")
        self._input.clear()
        self._input.setFocus()

    def _on_next(self):
        text = self._input.text().strip()
        if not text:
            return
        step = self._wizard.answer(text)
        if step.cancelled:
            self.reject()
            return
        if step.done:
            self._committed_state = get_runtime().commit_answers(step.answers)
            self.accept()
            return
        self._show_step(step)

    def get_committed_state(self):
        """Returns the AgentState created, or None if cancelled."""
        return self._committed_state
```

- [ ] **Step 2: Verify the module imports**

Run: `python -c "import gui.tabs.creation_wizard; print('creation_wizard OK')"`
Expected: prints `creation_wizard OK` with no traceback.

- [ ] **Step 3: Commit**

```bash
git add gui/tabs/creation_wizard.py
git commit -m "feat: add chat-channel CreationWizardDialog"
```

---

## Task 7: App-level wiring in `gui/app.py` and `gui/handlers.py`

**Files:**
- Modify: `gui/app.py` (`MainWindow.__init__`, new `_init_agent_runtime` + dispatcher signal handlers)
- Modify: `gui/handlers.py` (`ChatHandlers` — connect `live_agent_wizard_signal`, add `_on_live_agent_wizard`)

- [ ] **Step 1: Start the runtime in `MainWindow.__init__`**

In `gui/app.py`, find `MainWindow.__init__`. After `self._init_voice_assistant()` (line 97), add:

```python
        self._init_agent_runtime()
```

- [ ] **Step 2: Add the `_init_agent_runtime` method**

In `gui/app.py`, add this method to `MainWindow` (place it after `_init_voice_assistant`, before `_preload_models` or wherever fits):

```python
    def _init_agent_runtime(self):
        """Start the live-agent runtime: load persisted agents, arm the
        scheduler, and connect the ResultDispatcher to the UI."""
        try:
            from core.agent_runtime import get_runtime
            rt = get_runtime()
            rt.start()

            disp = rt.dispatcher
            disp.agent_history_appended.connect(self._on_agent_history_appended)
            disp.show_toast.connect(self._on_agent_toast)
            disp.dashboard_card_added.connect(self._on_agent_card)
            disp.comm_log_append.connect(self._on_agent_comm_log)
            print("[App] ✓ Agent runtime started")
        except Exception as e:
            print(f"[App] ✗ Agent runtime failed to start: {e}")
            import traceback
            traceback.print_exc()

    def _on_agent_history_appended(self, role_id: str):
        if self.agents_tab is not None and hasattr(self.agents_tab, "refresh"):
            self.agents_tab.refresh()

    def _on_agent_toast(self, title: str, body: str, success: bool):
        try:
            from qfluentwidgets import InfoBar, InfoBarPosition
            fn = InfoBar.success if success else InfoBar.error
            fn(title=title, content=body, duration=4000,
               position=InfoBarPosition.TOP_RIGHT, parent=self)
        except Exception as e:
            print(f"[App] toast failed: {e}")

    def _on_agent_card(self, payload: dict):
        if getattr(self, "dashboard_view", None) is not None:
            self.dashboard_view.add_agent_card(payload)

    def _on_agent_comm_log(self, role_id: str, title: str, body: str):
        if getattr(self, "dashboard_view", None) is not None:
            self.dashboard_view.add_system_message(f"{title}\n{body}", tag="system")
```

- [ ] **Step 3: Verify the `gui/app.py` changes import**

Run: `python -c "import gui.app; print('app OK')"`
Expected: prints `app OK` with no traceback.

- [ ] **Step 4: Commit the `gui/app.py` changes**

```bash
git add gui/app.py
git commit -m "feat: wire agent runtime + dispatcher signals into MainWindow"
```

> The chat `live_agent_wizard_signal` (added to `ChatWorker` in Phase 4 Task 8) is connected in `gui/handlers.py`, not `gui/app.py` — that is where every other `ChatWorker` signal is wired. Steps 5-8 handle it there.

- [ ] **Step 5: Connect `live_agent_wizard_signal` in `gui/handlers.py`**

In `gui/handlers.py`, the `ChatWorker` signals are connected inside `ChatHandlers` where the worker is created (around lines 1038-1054, and again around line 1200 — both blocks connect the same set of signals). Find each block that contains:

```python
        self._worker.build_agent_signal.connect(self._on_agent_built)
```

Immediately after each `build_agent_signal.connect(...)` line, add:

```python
        self._worker.live_agent_wizard_signal.connect(self._on_live_agent_wizard)
```

There are two such blocks (the earlier grep showed `build_agent_signal.connect` at lines ~1054 and ~1200). Add the sibling line in both.

- [ ] **Step 6: Add the `_on_live_agent_wizard` handler to `ChatHandlers`**

In `gui/handlers.py`, add this method to the `ChatHandlers` class (place it near `_on_agent_built`):

```python
    def _on_live_agent_wizard(self, task: str):
        """Open the chat-channel creation wizard for a live agent.

        Uses self.main_window as the dialog parent and refreshes the Active
        Agents tab on success.
        """
        try:
            from gui.tabs.creation_wizard import CreationWizardDialog
            dlg = CreationWizardDialog(task, parent=self.main_window)
            if dlg.exec():
                agents_tab = getattr(self.main_window, "agents_tab", None)
                if agents_tab is not None and hasattr(agents_tab, "refresh"):
                    agents_tab.refresh()
        except Exception as e:
            print(f"[ChatHandlers] live-agent wizard failed: {e}")
            import traceback
            traceback.print_exc()
```

- [ ] **Step 7: Verify `gui/handlers.py` imports**

Run: `python -c "import gui.handlers; print('handlers OK')"`
Expected: prints `handlers OK` with no traceback.

- [ ] **Step 8: Commit the `gui/handlers.py` changes**

```bash
git add gui/handlers.py
git commit -m "feat: route chat live-agent wizard signal to CreationWizardDialog"
```

---

## Task 8: Replace the voice `_on_done` stub with a real commit

**Files:**
- Modify: `core/voice_assistant.py` (`_start_agent_wizard` method added in Phase 4)

- [ ] **Step 1: Replace the `_on_done` body**

In `core/voice_assistant.py`, find `_start_agent_wizard`. The Phase 4 version's `_on_done` callback stores answers on `self._pending_agent_answers`. Replace the entire `_on_done` function with:

```python
        def _on_done(answers: dict):
            try:
                from core.agent_runtime import get_runtime
                state = get_runtime().commit_answers(answers)
                tts.queue_sentence(
                    f"Created {state.display_name}. "
                    "It is now live in your Active Agents tab."
                )
                self.refresh_agents_requested.emit()
            except Exception as exc:
                print(f"[VoiceAssistant] commit failed: {exc}")
                tts.queue_sentence(
                    "I configured the agent but could not save it. "
                    "Please check the logs."
                )
```

- [ ] **Step 2: Remove the now-unused import note**

The Phase 4 version imported `commit` and `AgentScheduler` inside `_start_agent_wizard` but never used them. In `core/voice_assistant.py`, inside `_start_agent_wizard`, delete these two lines if present:

```python
        from core.agent_creator import VoiceWizardSession, commit
        from core.agent_scheduler import AgentScheduler  # noqa: F401  (type ref)
```

and replace with just:

```python
        from core.agent_creator import VoiceWizardSession
```

(The `classify_executor` import inside `_classify` and `config` import stay as they were.)

- [ ] **Step 3: Verify the module imports**

Run: `python -c "import core.voice_assistant; print('voice_assistant OK')"`
Expected: prints `voice_assistant OK` with no traceback.

- [ ] **Step 4: Commit**

```bash
git add core/voice_assistant.py
git commit -m "feat: voice wizard now commits live agents via agent_runtime"
```

---

## Task 9: Write the manual smoke checklist

**Files:**
- Create: `tests/manual_smoke.md`

- [ ] **Step 1: Create the checklist**

Create `tests/manual_smoke.md`:

```markdown
# Multi-Agent System — Manual Smoke Checklist

Run after Phase 5. Requires Ollama running and the Plia app launched
(`python main.py`). The automated suite (`pytest tests/ -v`) must be green first.

## Creation — voice
- [ ] Say the wake word, then "create an agent that watches GitHub for related projects".
- [ ] Plia speaks the trigger question. Answer "scheduled".
- [ ] Plia asks cadence. Answer "every 6 hours".
- [ ] Plia asks persistence. Answer "persistent".
- [ ] Plia asks notify. Answer "communication log".
- [ ] Plia reads back the summary. Answer "yes".
- [ ] Plia confirms creation; the agent appears in the Active Agents tab → Live Agents section.

## Creation — chat
- [ ] In the chat tab, type "create an agent that summarises my emails".
- [ ] The CreationWizardDialog opens, pre-filled with the task.
- [ ] Walk through trigger / cadence-or-quota / persistence / notify / confirm.
- [ ] On confirm, the dialog closes and the agent appears in Live Agents.

## Controls (Active Agents tab → Live Agents)
- [ ] "▶ Run now" on a scheduled agent → a run starts; history row appears after it completes.
- [ ] "⏸ Pause" → status flips to paused; "▶ Resume" → status flips back to active.
- [ ] "⏹ Stop" → status flips to terminated; the row greys out but stays visible.
- [ ] "⚙ Edit" → LiveAgentEditorDialog opens; change cadence, save; subtitle updates.
- [ ] "🗑 Delete" → row disappears; the role YAML under ~/.plia_ai/roles/ is gone.
- [ ] Quota agent: subtitle shows "quota X/Y"; auto-terminates when the limit is reached.

## Reporting channels
- [ ] An agent with notify=tts → on run completion, Plia speaks a one-line summary.
- [ ] An agent with notify=toast_card → a toast appears top-right AND a card appears on the dashboard.
- [ ] An agent with notify=comm_log → an entry appears in the dashboard Communication Log.

## Persistence across restart
- [ ] Create one persistent agent and one session agent.
- [ ] Close Plia, reopen it.
- [ ] The persistent agent is still in Live Agents and re-armed (next-fire shown).
- [ ] The session agent is gone.
- [ ] If a persistent scheduled agent was overdue, it fires once shortly after launch (catch-up).

## Regression
- [ ] Normal chat still works (ask a plain question).
- [ ] Legacy "Custom Agents" section still shows prompt-only agents and Run/Delete still work.
- [ ] Voice weather / web search / desktop commands still work (not swallowed by the wizard intercept).
```

- [ ] **Step 2: Commit**

```bash
git add tests/manual_smoke.md
git commit -m "docs: add manual smoke checklist for multi-agent system"
```

---

## Task 10: Phase 5 final integration check

**Files:** none — verification only.

- [ ] **Step 1: Run the full automated suite**

Run: `pytest tests/ -v`
Expected: PASS — 89 from Phases 1-4 plus Phase 5:
`test_result_dispatcher.py` (7), `test_agent_runtime.py` (3) = 10 new → 99 passed total.

- [ ] **Step 2: Verify every new/modified module imports cleanly**

Run:
```bash
python -c "import core.agent_reporting, core.agent_runtime, gui.tabs.creation_wizard, gui.tabs.agents, gui.tabs.agent_editor, gui.tabs.dashboard, gui.app, core.voice_assistant; print('phase 5 imports OK')"
```
Expected: prints `phase 5 imports OK`.

- [ ] **Step 3: Launch the app**

Run: `python main.py`
Expected: app window opens with no traceback in the console; the console shows `[App] ✓ Agent runtime started`.

- [ ] **Step 4: Work through `tests/manual_smoke.md`**

Complete every checkbox in `tests/manual_smoke.md`. If any item fails, fix it and re-run the relevant section.

- [ ] **Step 5: Commit (if any fixes were needed)**

If steps 1-4 required fixes, commit them:

```bash
git add -A
git commit -m "fix: Phase 5 integration adjustments"
```

If no fixes were needed, skip this step.

---

## Phase 5 Complete — Feature Complete

**Deliverables:**
- `ResultDispatcher` — signal-based fan-out to history-refresh / TTS / toast+card / comm-log.
- `agent_runtime` — process-wide singletons + `commit_answers()` + startup `start()`.
- `DashboardView.add_agent_card` — live-agent result cards.
- `LiveAgentsSection` + `LiveAgentRow` — Active Agents tab controls (Run/Pause/Resume/Stop/Edit/Delete/History).
- `LiveAgentEditorDialog` — schedule / tools / notify / persistence editing.
- `CreationWizardDialog` — chat-channel creation wizard.
- `gui/app.py` — runtime startup, dispatcher signal wiring, chat wizard routing.
- Voice wizard now commits real live agents.
- 99 passing automated tests + a manual smoke checklist.

**Verification:** `pytest tests/ -v` green (99 passed), all modules import cleanly, app launches, manual smoke checklist signed off.

**The multi-agent system is now feature-complete:** users can create scheduled / on-demand / quota live agents by voice or chat; agents run via generated-script or LLM tool-loop executors; results report through the chosen channel; persistent agents survive restarts.
