"""
schedule_tool_dialog.py — "Schedule a Tool Call" dialog.

A lightweight alternative to the LLM wizard for creating a deterministic
agent that just runs one tool on a schedule. Picks from every callable tool
(built-ins, plugins, MCP tools) and lets the user supply JSON arguments,
cadence (or on-demand), and notify channels.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from qfluentwidgets import (
    BodyLabel, CaptionLabel, PrimaryPushButton, TitleLabel,
)


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\s]", "", (text or "").lower())
    s = re.sub(r"\s+", "_", s.strip())
    return s[:40] or "tool_agent"


def _list_all_tools() -> List[str]:
    """Every tool an agent can call: built-ins from the FunctionExecutor
    dispatch chain, plus user plugins. MCP tools live behind ``mcp_tool_call``
    so the user picks that and routes via the arguments."""
    tools: List[str] = []
    try:
        from core.function_executor import executor
        out = executor.execute("list_plia_features", {})
        if out.get("success") and isinstance(out.get("data"), dict):
            tools = list(out["data"].get("tools") or [])
    except Exception:
        pass
    return sorted(set(t for t in tools if t and t != "list_plia_features"))


class ScheduleToolDialog(QDialog):
    """Configure + create a direct_tool agent in one step (no wizard)."""

    CHANNELS = ("tts", "chat", "comm_log", "file", "web_searches", "toast_card")
    CADENCE_EXAMPLES = (
        "on demand (no schedule)",
        "every hour",
        "every 30 minutes",
        "every 6 hours",
        "twice a day",
        "daily",
        "daily at 8am",
        "every Monday morning",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Schedule a Tool Call")
        self.setMinimumSize(640, 620)
        self.resize(720, 680)
        self.setSizeGripEnabled(True)
        self._created_state = None
        self._build()

    # ── Layout ───────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.addWidget(TitleLabel("Schedule a Tool Call"))
        root.addWidget(BodyLabel(
            "Create a deterministic agent that invokes ONE tool with fixed "
            "arguments. No LLM is involved at run time — fast, predictable, "
            "and ideal for periodic checks."
        ))

        # Name
        root.addWidget(QLabel("Display name"))
        self._name = QLineEdit()
        self._name.setPlaceholderText("e.g. 'Hourly GitHub notifications'")
        root.addWidget(self._name)

        # Tool picker
        root.addWidget(QLabel("Tool"))
        self._tool = QComboBox()
        self._tool.setEditable(True)  # allow typing unknown names (e.g. MCP)
        for t in _list_all_tools():
            self._tool.addItem(t)
        self._tool.setCurrentText("")
        root.addWidget(self._tool)
        hint = CaptionLabel(
            "For MCP servers, pick 'mcp_tool_call' and provide "
            'arguments like {"tool_id": "github:list_notifications", "arguments": {...}}.'
        )
        hint.setStyleSheet("color:#7d828c;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # JSON arguments
        root.addWidget(QLabel("Arguments  (JSON object, may be empty)"))
        self._args = QPlainTextEdit()
        self._args.setPlaceholderText('{\n  "query": "AI news"\n}')
        self._args.setPlainText("{}")
        self._args.setMaximumHeight(140)
        root.addWidget(self._args)

        # Cadence
        cad_row = QHBoxLayout()
        cad_row.addWidget(QLabel("Cadence"))
        self._cadence = QComboBox()
        self._cadence.setEditable(True)
        for ex in self.CADENCE_EXAMPLES:
            self._cadence.addItem(ex)
        self._cadence.setCurrentText("every hour")
        cad_row.addWidget(self._cadence, 1)
        root.addLayout(cad_row)

        # Notify channels
        root.addWidget(QLabel("Notify channels  (pick one or more)"))
        notify_box = QWidget()
        notify_row = QHBoxLayout(notify_box)
        notify_row.setContentsMargins(0, 0, 0, 0)
        self._notify_checks: Dict[str, QCheckBox] = {}
        for ch in self.CHANNELS:
            cb = QCheckBox(ch)
            if ch == "chat":
                cb.setChecked(True)  # sane default
            notify_row.addWidget(cb)
            self._notify_checks[ch] = cb
        notify_row.addStretch(1)
        root.addWidget(notify_box)

        # Persistence
        pers_row = QHBoxLayout()
        pers_row.addWidget(QLabel("Persistence"))
        self._persistence = QComboBox()
        self._persistence.addItems(["persistent", "session"])
        pers_row.addWidget(self._persistence)
        pers_row.addStretch(1)
        root.addLayout(pers_row)

        root.addStretch(1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = PrimaryPushButton("Create & Schedule")
        save.clicked.connect(self._on_save)
        btn_row.addWidget(cancel)
        btn_row.addWidget(save)
        root.addLayout(btn_row)

    # ── Save ─────────────────────────────────────────────────────────────
    def _parse_arguments(self) -> Optional[Dict[str, Any]]:
        text = self._args.toPlainText().strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            QMessageBox.warning(
                self, "Invalid JSON",
                f"The Arguments field must be a JSON object.\n\n{exc}",
            )
            return None
        if not isinstance(parsed, dict):
            QMessageBox.warning(
                self, "Invalid JSON",
                "Arguments must be a JSON object (e.g. {}, not a list or scalar).",
            )
            return None
        return parsed

    def _parse_cadence(self):
        from core.agent_scheduler import parse_cadence
        text = (self._cadence.currentText() or "").strip().lower()
        if not text or "on demand" in text or "no schedule" in text:
            return None
        return parse_cadence(text)

    def _on_save(self):
        name = self._name.text().strip()
        tool_id = self._tool.currentText().strip()
        if not name:
            QMessageBox.warning(self, "Missing name", "Display name is required.")
            return
        if not tool_id:
            QMessageBox.warning(self, "Missing tool", "Tool is required.")
            return
        args = self._parse_arguments()
        if args is None:
            return  # parse error already shown

        cadence = self._parse_cadence()
        cadence_text = (self._cadence.currentText() or "").strip().lower()
        wants_schedule = cadence is not None
        if wants_schedule and not cadence:
            QMessageBox.warning(
                self, "Unrecognised cadence",
                f"Could not parse cadence {cadence_text!r}. "
                "Try one of the example phrases.",
            )
            return

        channels = [c for c, cb in self._notify_checks.items() if cb.isChecked()]
        if not channels:
            channels = ["comm_log"]   # never end up with empty notify

        # Build the AgentState directly — bypass the LLM wizard's
        # classify/heartbeat pipeline since direct_tool is, well, direct.
        from core.agent_creator import write_role_yaml
        from core.agent_state import AgentState, now_iso
        from core.agent_runtime import get_runtime, _ROLES_DIR
        from core.multi_agent import multi_agent_system

        rt = get_runtime()
        base_slug = _slugify(name)
        slug = base_slug
        i = 2
        while rt.store.get(slug) is not None:
            slug = f"{base_slug}_{i}"
            i += 1

        task_desc = (
            f"Scheduled tool call: invokes {tool_id} with fixed arguments. "
            "This agent does not use an LLM — it just runs the tool and "
            "reports the result through the configured channels."
        )
        try:
            write_role_yaml(
                roles_dir=_ROLES_DIR,
                slug=slug,
                display_name=name,
                task=task_desc,
                tools=[tool_id],
            )
            multi_agent_system.reload_roles()
            instance = rt._make_instance(slug, name)
            state = AgentState(
                role_id=slug,
                instance_id=getattr(instance, "id", slug),
                display_name=name,
                icon="⏱",
                executor="direct_tool",
                trigger="scheduled" if cadence else "on_demand",
                persistence=self._persistence.currentText(),
                notify=",".join(channels),
                status="active",
                created_at=now_iso(),
                script_path=None,
                cadence=cadence,
                quota=None,
                direct_tool_id=tool_id,
                direct_tool_args=args,
            )
            rt.store.upsert(state)
            if state.status == "active" and cadence:
                rt.scheduler.arm(state)
        except Exception as exc:
            QMessageBox.critical(self, "Could not create agent", str(exc))
            return

        self._created_state = state
        self.accept()

    def get_created_state(self):
        return self._created_state
