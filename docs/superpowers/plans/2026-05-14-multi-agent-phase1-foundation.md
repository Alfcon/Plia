# Multi-Agent System — Phase 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the persistent runtime-state layer (`AgentState` + JSON-backed store) and repoint the `MultiAgentSystem` singleton's role directory, so later phases have a foundation to build on.

**Architecture:** A new `core/agent_state.py` defines an `AgentState` dataclass and an `AgentStateStore` QObject that loads/saves `~/.plia_ai/agent_state.json`, drops session-scoped entries on load, and emits a `changed` signal. `core/multi_agent.py`'s singleton is repointed from the relative `"roles"` directory to `~/.plia_ai/roles/`.

**Tech Stack:** Python 3, PySide6 (`QObject`/`Signal`/`QTimer`), `dataclasses`, `json`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-05-14-multi-agent-system-design.md` (Data model section).

---

## File Structure

| Path | Responsibility |
|---|---|
| `core/agent_state.py` (create) | `AgentState` dataclass + `AgentStateStore` (load/save/upsert/remove, `changed` signal, debounced save) |
| `core/multi_agent.py` (modify) | Repoint `multi_agent_system` singleton's `roles_dir` to `~/.plia_ai/roles/` |
| `tests/__init__.py` (create) | Empty — makes `tests/` a package |
| `tests/test_agent_state.py` (create) | Unit tests for `AgentState` serialization + `AgentStateStore` behaviour |
| `tests/test_multi_agent_rolesdir.py` (create) | Test the singleton points at the right directory |

---

## Task 1: Create the `AgentState` dataclass

**Files:**
- Create: `core/agent_state.py`
- Create: `tests/__init__.py`
- Create: `tests/test_agent_state.py`

- [ ] **Step 1: Create the empty tests package**

Create `tests/__init__.py` with no content (empty file).

- [ ] **Step 2: Write the failing test**

Create `tests/test_agent_state.py`:

```python
from core.agent_state import AgentState


def _sample_state(**overrides):
    base = dict(
        role_id="github_watcher",
        instance_id="uuid-123",
        display_name="GitHub Watcher",
        icon="🔍",
        executor="tool_loop",
        script_path=None,
        trigger="scheduled",
        cadence={"interval_sec": 3600, "anchor_iso": "2026-05-14T15:00:00"},
        quota=None,
        persistence="persistent",
        notify="comm_log",
        status="active",
        next_fire_at="2026-05-14T16:00:00",
        last_fire_at=None,
        runs=0,
        history=[],
        created_at="2026-05-14T15:00:00",
    )
    base.update(overrides)
    return AgentState(**base)


def test_agent_state_round_trips_through_dict():
    state = _sample_state()
    restored = AgentState.from_dict(state.to_dict())
    assert restored == state


def test_agent_state_from_dict_tolerates_missing_optional_fields():
    minimal = {
        "role_id": "r1",
        "instance_id": "i1",
        "display_name": "R1",
        "icon": "🤖",
        "executor": "script",
        "trigger": "on_demand",
        "persistence": "session",
        "notify": "tts",
        "status": "active",
        "created_at": "2026-05-14T15:00:00",
    }
    state = AgentState.from_dict(minimal)
    assert state.script_path is None
    assert state.cadence is None
    assert state.quota is None
    assert state.next_fire_at is None
    assert state.last_fire_at is None
    assert state.runs == 0
    assert state.history == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_agent_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.agent_state'`

- [ ] **Step 4: Write minimal implementation**

Create `core/agent_state.py`:

```python
"""
agent_state.py — Runtime state for Plia live agents.

AgentState holds *how an agent is currently running* (schedule, quota,
persistence, notification channel, run history). It is the companion to a
RoleDefinition YAML, which holds *what the agent is*.

AgentStateStore persists a list of AgentState to ~/.plia_ai/agent_state.json,
drops session-scoped entries on load, and emits `changed` on every mutation.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal, QTimer

PLIA_DIR = Path.home() / ".plia_ai"
PLIA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = PLIA_DIR / "agent_state.json"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class AgentState:
    role_id: str
    instance_id: str
    display_name: str
    icon: str
    executor: str                       # "script" | "tool_loop"
    trigger: str                        # "scheduled" | "on_demand" | "quota"
    persistence: str                    # "persistent" | "session"
    notify: str                         # "tts" | "toast_card" | "comm_log"
    status: str                         # "active" | "paused" | "terminated"
    created_at: str
    script_path: Optional[str] = None
    cadence: Optional[Dict[str, Any]] = None   # {"interval_sec": int, "anchor_iso": str}
    quota: Optional[Dict[str, Any]] = None     # {"limit": int, "criterion": str, "progress": int}
    next_fire_at: Optional[str] = None
    last_fire_at: Optional[str] = None
    runs: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "AgentState":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in raw.items() if k in known}
        return cls(**filtered)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_agent_state.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add core/agent_state.py tests/__init__.py tests/test_agent_state.py
git commit -m "feat: add AgentState dataclass for live-agent runtime state"
```

---

## Task 2: Add `AgentStateStore` load/save round-trip

**Files:**
- Modify: `core/agent_state.py`
- Test: `tests/test_agent_state.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_state.py`:

```python
from core.agent_state import AgentStateStore


def test_store_save_and_load_round_trip(tmp_path):
    path = tmp_path / "agent_state.json"
    store = AgentStateStore(path=path)
    store.upsert(_sample_state(role_id="a"))
    store.upsert(_sample_state(role_id="b"))

    fresh = AgentStateStore(path=path)
    fresh.load()
    ids = sorted(s.role_id for s in fresh.all())
    assert ids == ["a", "b"]


def test_store_get_returns_none_for_unknown(tmp_path):
    store = AgentStateStore(path=tmp_path / "s.json")
    assert store.get("nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_state.py -v`
Expected: FAIL with `ImportError: cannot import name 'AgentStateStore'`

- [ ] **Step 3: Write minimal implementation**

Append to `core/agent_state.py`:

```python
class AgentStateStore(QObject):
    """Thread-safe JSON-backed store of AgentState with a `changed` signal."""

    changed = Signal()

    def __init__(self, path: Path = STATE_FILE, parent=None):
        super().__init__(parent)
        self._path = Path(path)
        self._lock = threading.Lock()
        self._states: Dict[str, AgentState] = {}
        self._save_timer: Optional[QTimer] = None

    # ── Persistence ───────────────────────────────────────────────────────
    def load(self) -> None:
        """Read the state file. Session-scoped entries are dropped."""
        with self._lock:
            self._states = {}
            if not self._path.exists():
                return
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"[AgentStateStore] Load failed: {exc}")
                return
            for entry in raw if isinstance(raw, list) else []:
                try:
                    state = AgentState.from_dict(entry)
                except Exception as exc:
                    print(f"[AgentStateStore] Skipping bad entry: {exc}")
                    continue
                if state.persistence == "session":
                    continue
                self._states[state.role_id] = state

    def save(self) -> None:
        with self._lock:
            data = [s.to_dict() for s in self._states.values()]
            try:
                self._path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                )
            except Exception as exc:
                print(f"[AgentStateStore] Save failed: {exc}")

    def save_debounced(self, delay_ms: int = 500) -> None:
        """Coalesce rapid mutations into a single disk write."""
        if self._save_timer is None:
            self._save_timer = QTimer()
            self._save_timer.setSingleShot(True)
            self._save_timer.timeout.connect(self.save)
        self._save_timer.start(delay_ms)

    # ── CRUD ──────────────────────────────────────────────────────────────
    def all(self) -> List[AgentState]:
        with self._lock:
            return list(self._states.values())

    def get(self, role_id: str) -> Optional[AgentState]:
        with self._lock:
            return self._states.get(role_id)

    def upsert(self, state: AgentState) -> None:
        with self._lock:
            self._states[state.role_id] = state
        self.save()
        self.changed.emit()

    def remove(self, role_id: str) -> None:
        with self._lock:
            self._states.pop(role_id, None)
        self.save()
        self.changed.emit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_state.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add core/agent_state.py tests/test_agent_state.py
git commit -m "feat: add AgentStateStore with JSON persistence"
```

---

## Task 3: Drop session-scoped entries on load

**Files:**
- Test: `tests/test_agent_state.py`

(Behaviour was implemented in Task 2; this task adds the explicit regression test the spec requires.)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_state.py`:

```python
def test_store_drops_session_entries_on_load(tmp_path):
    path = tmp_path / "agent_state.json"
    store = AgentStateStore(path=path)
    store.upsert(_sample_state(role_id="keep", persistence="persistent"))
    store.upsert(_sample_state(role_id="drop", persistence="session"))

    fresh = AgentStateStore(path=path)
    fresh.load()
    ids = [s.role_id for s in fresh.all()]
    assert ids == ["keep"]


def test_store_keeps_persistent_entries_on_load(tmp_path):
    path = tmp_path / "agent_state.json"
    store = AgentStateStore(path=path)
    store.upsert(_sample_state(role_id="p1", persistence="persistent"))
    store.upsert(_sample_state(role_id="p2", persistence="persistent"))

    fresh = AgentStateStore(path=path)
    fresh.load()
    assert len(fresh.all()) == 2
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_agent_state.py -v`
Expected: PASS (6 passed) — the load logic from Task 2 already handles this.

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_state.py
git commit -m "test: cover session-vs-persistent load behaviour"
```

---

## Task 4: `changed` signal fires on upsert and remove

**Files:**
- Test: `tests/test_agent_state.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_state.py`:

```python
def test_changed_signal_fires_on_upsert_and_remove(tmp_path):
    store = AgentStateStore(path=tmp_path / "s.json")
    hits = []
    store.changed.connect(lambda: hits.append(1))

    store.upsert(_sample_state(role_id="x"))
    assert len(hits) == 1

    store.remove("x")
    assert len(hits) == 2
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_agent_state.py -v`
Expected: PASS (7 passed) — `changed.emit()` was added in Task 2.

> Note: PySide6 signals deliver synchronously when emitter and receiver share a thread and there is no running event loop, so the counts assert immediately. No `QApplication` is required for direct-connection signal delivery in tests.

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_state.py
git commit -m "test: cover changed signal on store mutations"
```

---

## Task 5: Repoint the `MultiAgentSystem` singleton at `~/.plia_ai/roles/`

**Files:**
- Modify: `core/multi_agent.py:477`
- Create: `tests/test_multi_agent_rolesdir.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_multi_agent_rolesdir.py`:

```python
from pathlib import Path

from core.multi_agent import multi_agent_system


def test_singleton_roles_dir_is_under_plia_home():
    expected = Path.home() / ".plia_ai" / "roles"
    assert Path(multi_agent_system.roles_dir) == expected


def test_roles_dir_exists_after_import():
    # importing core.multi_agent must create the directory
    assert (Path.home() / ".plia_ai" / "roles").is_dir()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_multi_agent_rolesdir.py -v`
Expected: FAIL — `roles_dir` is currently the relative string `"roles"`.

- [ ] **Step 3: Change the singleton construction**

In `core/multi_agent.py`, the file currently ends with:

```python
multi_agent_system = MultiAgentSystem()
```

Replace that final line with:

```python
_ROLES_DIR = Path.home() / ".plia_ai" / "roles"
_ROLES_DIR.mkdir(parents=True, exist_ok=True)
multi_agent_system = MultiAgentSystem(str(_ROLES_DIR))
```

`Path` is already imported at the top of `core/multi_agent.py` (`from pathlib import Path`), so no new import is needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_multi_agent_rolesdir.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/ -v`
Expected: PASS (9 passed total — 7 from `test_agent_state.py`, 2 here)

- [ ] **Step 6: Verify the app still imports**

Run: `python -c "import core.multi_agent; import core.agent_state; print('imports OK')"`
Expected: prints `imports OK` with no traceback.

- [ ] **Step 7: Commit**

```bash
git add core/multi_agent.py tests/test_multi_agent_rolesdir.py
git commit -m "feat: point MultiAgentSystem singleton at ~/.plia_ai/roles/"
```

---

## Phase 1 Complete

**Deliverables:**
- `AgentState` dataclass with tolerant `from_dict` / `to_dict`.
- `AgentStateStore` — JSON-backed, thread-safe, `changed` signal, debounced save, drops session entries on load.
- `MultiAgentSystem` singleton now discovers roles from `~/.plia_ai/roles/`.
- 9 passing tests; `tests/` is a package.

**Verification before moving to Phase 2:** `pytest tests/ -v` green, `python -c "import core.multi_agent; import core.agent_state"` clean.

**Next:** Phase 2 (Executors) builds `RunResult` and the two runner factories on top of `AgentState`.
