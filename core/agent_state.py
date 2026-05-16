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
    # Used only when executor == "direct_tool": invoke this single tool
    # with these static arguments, no LLM in the loop.
    direct_tool_id: Optional[str] = None
    direct_tool_args: Optional[Dict[str, Any]] = None
    # Only used when trigger == "conditional": describes the event watcher
    # (see core/agent_watchers.py for supported shapes).
    condition: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "AgentState":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in raw.items() if k in known}
        return cls(**filtered)


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
