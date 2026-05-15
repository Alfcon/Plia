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
