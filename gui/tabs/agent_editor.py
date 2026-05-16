"""
agent_editor.py — Jarvis-style agent role editor for Plia

Provides a window for creating, editing, and deleting role YAML files.
The editor works with the multi-agent runtime in core.multi_agent and
persists role definitions to ~/.plia_ai/roles.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import CardWidget, InfoBar, InfoBarPosition, PrimaryPushButton, PushButton, TitleLabel, StrongBodyLabel, CaptionLabel, LineEdit, TextEdit

from core.multi_agent import multi_agent_system

PLIA_DIR = Path.home() / ".plia_ai"
ROLES_DIR = PLIA_DIR / "roles"
ROLES_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class RoleFormData:
    id: str = ""
    name: str = ""
    description: str = ""
    responsibilities: str = ""
    autonomous_actions: str = ""
    approval_required: str = ""
    kpis: str = ""
    tone: str = ""
    verbosity: str = "adaptive"
    formality: str = "adaptive"
    heartbeat_instructions: str = ""
    sub_roles: str = ""
    tools: str = ""
    authority_level: str = "5"


def _comma_lines(text: str) -> List[str]:
    return [item.strip() for item in text.splitlines() if item.strip()]


def _parse_csv_lines(text: str) -> List[str]:
    items: List[str] = []
    for line in text.splitlines():
        for part in line.split(","):
            item = part.strip()
            if item:
                items.append(item)
    return items


def _role_file(role_id: str) -> Path:
    """Return the existing role file for `role_id` (.yml or .yaml).

    Phase 4's wizard writes `.yml`; the legacy editor writes `.yaml`. Prefer
    whichever already exists; otherwise default to `.yml` for new saves so
    we converge on a single extension.
    """
    yml = ROLES_DIR / f"{role_id}.yml"
    yaml_ = ROLES_DIR / f"{role_id}.yaml"
    if yml.exists():
        return yml
    if yaml_.exists():
        return yaml_
    return yml  # new file → write as .yml


def _load_role_files() -> List[Dict[str, Any]]:
    roles: List[Dict[str, Any]] = []
    if not ROLES_DIR.exists():
        return roles
    for file in sorted(ROLES_DIR.glob("*.y*ml")):
        try:
            data = yaml.safe_load(file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                roles.append(data)
        except Exception:
            continue
    return roles


def _save_role(data: Dict[str, Any]) -> None:
    role_id = data["id"].strip()
    path = _role_file(role_id)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _delete_role(role_id: str) -> None:
    path = _role_file(role_id)
    if path.exists():
        path.unlink()


def _normalize_role_data(form: RoleFormData) -> Dict[str, Any]:
    kpis: List[Dict[str, str]] = []
    for line in _comma_lines(form.kpis):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 4:
            kpis.append(
                {"name": parts[0], "metric": parts[1], "target": parts[2], "check_interval": parts[3]}
            )

    sub_roles: List[Dict[str, Any]] = []
    for line in _comma_lines(form.sub_roles):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 6:
            sub_roles.append(
                {
                    "role_id": parts[0],
                    "name": parts[1],
                    "description": parts[2],
                    "spawned_by": parts[3],
                    "reports_to": parts[4],
                    "max_budget_per_task": int(parts[5]),
                }
            )

    return {
        "id": form.id.strip(),
        "name": form.name.strip(),
        "description": form.description.strip(),
        "responsibilities": _parse_csv_lines(form.responsibilities),
        "autonomous_actions": _parse_csv_lines(form.autonomous_actions),
        "approval_required": _parse_csv_lines(form.approval_required),
        "kpis": kpis,
        "communication_style": {
            "tone": form.tone.strip(),
            "verbosity": form.verbosity.strip() or "adaptive",
            "formality": form.formality.strip() or "adaptive",
        },
        "heartbeat_instructions": form.heartbeat_instructions.strip(),
        "sub_roles": sub_roles,
        "tools": _parse_csv_lines(form.tools),
        "authority_level": int(form.authority_level or "5"),
    }


class RoleEditorDialog(QDialog):
    def __init__(self, parent=None, role: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self._role = role or {}
        # Distinct title for new vs edit so the user knows which mode they're in.
        if self._role:
            self.setWindowTitle(
                f"Edit Role — {self._role.get('name') or self._role.get('id') or 'untitled'}"
            )
        else:
            self.setWindowTitle("New Agent Role")
        # Resizable; sized so the form is comfortably visible by default.
        self.setMinimumSize(720, 560)
        self.resize(900, 760)
        self.setSizeGripEnabled(True)
        self._build()

    def _build(self) -> None:
        from PySide6.QtWidgets import QScrollArea, QWidget as _QWidget

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(10)

        outer.addWidget(TitleLabel("Jarvis-Style Agent Editor"))

        info = CaptionLabel(
            "Edit role YAML used by the multi-agent runtime.\n"
            "Fields like responsibilities and tools can be entered as comma-separated lists.\n"
            "KPIs use one line per item: name|metric|target|check_interval"
        )
        info.setWordWrap(True)
        outer.addWidget(info)

        # ── Scrollable form area ─────────────────────────────────────────
        # Without this, the ~14 fields get vertically squished by the dialog's
        # min-height and labels visually overlap their inputs.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        form_host = _QWidget()
        layout = QVBoxLayout(form_host)
        layout.setContentsMargins(0, 0, 8, 0)  # right padding for scrollbar
        layout.setSpacing(10)

        self.id_edit = LineEdit()
        self.name_edit = LineEdit()
        self.desc_edit = TextEdit()
        self.resp_edit = TextEdit()
        self.auto_edit = TextEdit()
        self.approval_edit = TextEdit()
        self.kpi_edit = TextEdit()
        self.tone_edit = LineEdit()
        self.verbosity_edit = LineEdit()
        self.formality_edit = LineEdit()
        self.heartbeat_edit = TextEdit()
        self.sub_roles_edit = TextEdit()
        self.tools_edit = TextEdit()
        self.authority_edit = LineEdit()

        fields = [
            ("Role ID", self.id_edit),
            ("Display Name", self.name_edit),
            ("Description", self.desc_edit),
            ("Responsibilities", self.resp_edit),
            ("Autonomous Actions", self.auto_edit),
            ("Approval Required", self.approval_edit),
            ("KPIs", self.kpi_edit),
            ("Communication Tone", self.tone_edit),
            ("Verbosity", self.verbosity_edit),
            ("Formality", self.formality_edit),
            ("Heartbeat Instructions", self.heartbeat_edit),
            ("Sub-Roles", self.sub_roles_edit),
            ("Tools", self.tools_edit),
            ("Authority Level", self.authority_edit),
        ]

        for label_text, widget in fields:
            layout.addWidget(StrongBodyLabel(label_text))
            if isinstance(widget, QTextEdit):
                widget.setMinimumHeight(88)
                widget.setMaximumHeight(140)
            else:
                widget.setMinimumHeight(34)
            layout.addWidget(widget)

        scroll.setWidget(form_host)
        outer.addWidget(scroll, 1)  # let the scroll area take all stretch

        self.verbosity_edit.setPlaceholderText("adaptive | concise | detailed")
        self.formality_edit.setPlaceholderText("adaptive | formal | casual")
        self.authority_edit.setPlaceholderText("1-10")

        role = self._role
        if role:
            self.id_edit.setText(role.get("id", ""))
            self.name_edit.setText(role.get("name", ""))
            self.desc_edit.setPlainText(role.get("description", ""))
            self.resp_edit.setPlainText("\n".join(role.get("responsibilities", [])))
            self.auto_edit.setPlainText("\n".join(role.get("autonomous_actions", [])))
            self.approval_edit.setPlainText("\n".join(role.get("approval_required", [])))
            self.kpi_edit.setPlainText(
                "\n".join(
                    "|".join([k.get("name", ""), k.get("metric", ""), k.get("target", ""), k.get("check_interval", "")])
                    for k in role.get("kpis", [])
                )
            )
            comm = role.get("communication_style", {})
            self.tone_edit.setText(comm.get("tone", ""))
            self.verbosity_edit.setText(comm.get("verbosity", "adaptive"))
            self.formality_edit.setText(comm.get("formality", "adaptive"))
            self.heartbeat_edit.setPlainText(role.get("heartbeat_instructions", ""))
            self.sub_roles_edit.setPlainText(
                "\n".join(
                    "|".join(
                        [
                            s.get("role_id", ""),
                            s.get("name", ""),
                            s.get("description", ""),
                            s.get("spawned_by", ""),
                            s.get("reports_to", ""),
                            str(s.get("max_budget_per_task", 0)),
                        ]
                    )
                    for s in role.get("sub_roles", [])
                )
            )
            self.tools_edit.setPlainText("\n".join(role.get("tools", [])))
            self.authority_edit.setText(str(role.get("authority_level", 5)))

        # Buttons live on the OUTER layout so they stay pinned to the bottom
        # of the dialog while the form above scrolls.
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = PrimaryPushButton("Save Role")
        save.clicked.connect(self._save)
        btn_row.addWidget(cancel)
        btn_row.addWidget(save)
        outer.addLayout(btn_row)

    def _save(self) -> None:
        data = _normalize_role_data(
            RoleFormData(
                id=self.id_edit.text(),
                name=self.name_edit.text(),
                description=self.desc_edit.toPlainText(),
                responsibilities=self.resp_edit.toPlainText(),
                autonomous_actions=self.auto_edit.toPlainText(),
                approval_required=self.approval_edit.toPlainText(),
                kpis=self.kpi_edit.toPlainText(),
                tone=self.tone_edit.text(),
                verbosity=self.verbosity_edit.text(),
                formality=self.formality_edit.text(),
                heartbeat_instructions=self.heartbeat_edit.toPlainText(),
                sub_roles=self.sub_roles_edit.toPlainText(),
                tools=self.tools_edit.toPlainText(),
                authority_level=self.authority_edit.text(),
            )
        )

        if not data["id"] or not data["name"] or not data["description"]:
            QMessageBox.warning(self, "Missing Fields", "Role ID, name, and description are required.")
            return

        try:
            _save_role(data)
            multi_agent_system.reload_roles()
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))

    @staticmethod
    def open_new(parent=None) -> None:
        dlg = RoleEditorDialog(parent=parent)
        dlg.exec()

    @staticmethod
    def open_edit(parent=None, role_id: Optional[str] = None) -> None:
        role = None
        if role_id:
            path = _role_file(role_id)
            if path.exists():
                role = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        dlg = RoleEditorDialog(parent=parent, role=role)
        dlg.exec()


class AgentEditorWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Agent Editor")
        self.setMinimumSize(980, 760)
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)

        left_card = CardWidget()
        left_layout = QVBoxLayout(left_card)
        left_layout.addWidget(TitleLabel("Roles"))
        self._roles_area = QVBoxLayout()
        left_layout.addLayout(self._roles_area)
        left_layout.addStretch()

        right_card = CardWidget()
        right_layout = QVBoxLayout(right_card)
        right_layout.addWidget(TitleLabel("Actions"))

        self._details = CaptionLabel("Select a role to view details.")
        self._details.setWordWrap(True)
        right_layout.addWidget(self._details)

        # Edit is the primary action — clicking a role then Edit is the main
        # path. Add Role is a secondary action so it doesn't visually compete.
        edit_btn = PrimaryPushButton("Edit Selected")
        edit_btn.clicked.connect(lambda: self._edit_selected())
        right_layout.addWidget(edit_btn)

        add_btn = PushButton("Add Role")
        add_btn.clicked.connect(lambda: self._open_new())
        right_layout.addWidget(add_btn)

        delete_btn = PushButton("Delete Selected")
        delete_btn.clicked.connect(lambda: self._delete_selected())
        right_layout.addWidget(delete_btn)

        close_btn = PushButton("Close")
        close_btn.clicked.connect(self.reject)
        right_layout.addWidget(close_btn)
        right_layout.addStretch()

        layout.addWidget(left_card, 2)
        layout.addWidget(right_card, 1)

        self._selected_role_id: Optional[str] = None

    def refresh(self) -> None:
        while self._roles_area.count():
            item = self._roles_area.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        roles = _load_role_files()
        if not roles:
            self._roles_area.addWidget(CaptionLabel("No role files found in ~/.plia_ai/roles"))
            self._role_buttons = {}
            return

        # Track buttons so we can visually mark the selected role.
        self._role_buttons = {}
        for role in roles:
            rid = role.get("id", "")
            btn = PushButton(f"{role.get('name', rid or 'role')}  ({rid})")
            btn.setCheckable(True)
            btn.setToolTip("Click to select. Double-click to edit.")
            btn.clicked.connect(lambda _, _rid=rid: self._select_role(_rid))
            # Double-click → open edit dialog directly so users don't have to
            # remember to hit "Edit Selected" afterwards.
            btn.mouseDoubleClickEvent = (
                lambda ev, _rid=rid: self._double_click_role(_rid)
            )
            self._roles_area.addWidget(btn)
            self._role_buttons[rid] = btn

        # Restore visual selection if a role was already picked.
        if self._selected_role_id and self._selected_role_id in self._role_buttons:
            btn = self._role_buttons[self._selected_role_id]
            btn.setChecked(True)
            btn.setStyleSheet(self._SELECTED_BTN_QSS)

    # Stylesheet snippets for the role list's selected vs unselected state.
    _SELECTED_BTN_QSS = (
        "PushButton { background-color: #00b4d8; color: white; "
        "border: 1px solid #00b4d8; }"
        "PushButton:hover { background-color: #0094b3; }"
    )
    _UNSELECTED_BTN_QSS = ""  # fall back to the default theme

    def _select_role(self, role_id: str) -> None:
        self._selected_role_id = role_id
        # Highlight the chosen role; un-check + un-style all others.
        for rid, btn in getattr(self, "_role_buttons", {}).items():
            is_selected = (rid == role_id)
            btn.setChecked(is_selected)
            btn.setStyleSheet(
                self._SELECTED_BTN_QSS if is_selected
                else self._UNSELECTED_BTN_QSS
            )
        path = _role_file(role_id)
        if path.exists():
            role = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            self._details.setText(
                f"ID: {role.get('id', '')}\n"
                f"Name: {role.get('name', '')}\n"
                f"Authority: {role.get('authority_level', '')}\n\n"
                f"{role.get('description', '')}"
            )

    def _open_new(self) -> None:
        RoleEditorDialog.open_new(self)
        self.refresh()

    def _double_click_role(self, role_id: str) -> None:
        """Double-clicking a role selects it AND opens the editor."""
        self._select_role(role_id)
        RoleEditorDialog.open_edit(self, role_id)
        self.refresh()

    def _edit_selected(self) -> None:
        if not self._selected_role_id:
            QMessageBox.information(
                self,
                "No role selected",
                "Click a role in the list on the left first, then press "
                "Edit Selected.",
            )
            return
        RoleEditorDialog.open_edit(self, self._selected_role_id)
        self.refresh()

    def _delete_selected(self) -> None:
        if not self._selected_role_id:
            QMessageBox.information(
                self,
                "No role selected",
                "Click a role in the list on the left first, then press "
                "Delete Selected.",
            )
            return
        reply = QMessageBox.question(self, "Delete Role", f"Delete role '{self._selected_role_id}'?")
        if reply == QMessageBox.Yes:
            _delete_role(self._selected_role_id)
            multi_agent_system.reload_roles()
            self._selected_role_id = None
            self.refresh()


class LiveAgentEditorDialog(QDialog):
    """Edit a live agent's schedule, tools, notification channel, and
    persistence. Executor type is read-only (changing it needs recreation)."""

    # confirmed tool names from core/function_executor.py
    ALL_TOOLS = [
        "web_search", "http_get", "list_plia_features", "github_readme",
        "list_agents", "run_agent",
        "read_emails", "get_system_info",
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
            QCheckBox, QPushButton, QScrollArea, QWidget, QTextEdit,
        )

        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"<b>{self._state.icon}  {self._state.display_name}</b>"))
        root.addWidget(QLabel(f"Engine: {self._state.executor} (read-only)"))

        # ── Display name (editable) ───────────────────────────────────────
        root.addWidget(QLabel("Display name"))
        self._display_name = QLineEdit()
        self._display_name.setText(self._state.display_name)
        root.addWidget(self._display_name)

        # ── Task description (editable) — fixes STT mishears etc. ─────────
        root.addWidget(QLabel("Task description (what the agent does each run)"))
        self._task = QTextEdit()
        self._task.setPlaceholderText(
            "e.g. watches GitHub for projects related to Jarvis-style assistants")
        self._task.setMaximumHeight(80)
        # Pull current task from the role YAML's responsibilities[0]
        from core.multi_agent import multi_agent_system
        role = multi_agent_system.roles.get(self._state.role_id)
        current_task = ""
        if role is not None:
            resp = getattr(role, "responsibilities", None) or []
            if resp:
                current_task = resp[0]
        self._task.setPlainText(current_task)
        root.addWidget(self._task)

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

        # ── Notify channels (multi-select) ────────────────────────────────
        root.addWidget(QLabel("Notify channels (pick one or more)"))
        notify_box = QWidget()
        notify_row = QHBoxLayout(notify_box)
        notify_row.setContentsMargins(0, 0, 0, 0)
        current_channels = set(
            c.strip() for c in (self._state.notify or "").split(",") if c.strip())
        self._notify_checks = {}
        for ch in ("tts", "chat", "comm_log", "file", "web_searches", "toast_card"):
            cb = QCheckBox(ch)
            cb.setChecked(ch in current_channels)
            notify_row.addWidget(cb)
            self._notify_checks[ch] = cb
        notify_row.addStretch(1)
        root.addWidget(notify_box)

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
        # Notify: multi-select → comma-joined; never empty
        selected_channels = [
            ch for ch, cb in self._notify_checks.items() if cb.isChecked()
        ]
        state.notify = ",".join(selected_channels) if selected_channels else "comm_log"
        state.persistence = self._persistence.currentText()

        # Display name — purely cosmetic but propagates to role YAML below.
        new_display_name = self._display_name.text().strip() or state.display_name
        state.display_name = new_display_name

        new_task = self._task.toPlainText().strip()

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

        # ── Update role YAML (tools, name, task) ──────────────────────────
        selected = [t for t, cb in self._tool_checks.items() if cb.isChecked()]
        role_file = Path.home() / ".plia_ai" / "roles" / f"{state.role_id}.yml"
        if role_file.exists():
            raw = yaml.safe_load(role_file.read_text(encoding="utf-8")) or {}
            raw["tools"] = selected
            raw["autonomous_actions"] = selected
            raw["name"] = new_display_name
            if new_task:
                raw["description"] = f"Agent that {new_task}."
                raw["responsibilities"] = [new_task]
                raw["heartbeat_instructions"] = (
                    f"Your task: {new_task}. Report concise, useful results each run."
                )
            role_file.write_text(
                yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
                encoding="utf-8")
            multi_agent_system.reload_roles()

        rt.store.upsert(state)
        if state.status == "active":
            rt.scheduler.arm(state)
        self.accept()
