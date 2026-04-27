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
    return ROLES_DIR / f"{role_id}.yaml"


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
        self.setWindowTitle("Edit Agent Role")
        self.setMinimumSize(760, 760)
        self._role = role or {}
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        layout.addWidget(TitleLabel("Jarvis-Style Agent Editor"))

        info = CaptionLabel(
            "Edit role YAML used by the multi-agent runtime.\n"
            "Fields like responsibilities and tools can be entered as comma-separated lists.\n"
            "KPIs use one line per item: name|metric|target|check_interval"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

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
            widget.setMinimumHeight(72 if isinstance(widget, QTextEdit) else 36)
            layout.addWidget(widget)

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

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = PrimaryPushButton("Save Role")
        save.clicked.connect(self._save)
        btn_row.addWidget(cancel)
        btn_row.addWidget(save)
        layout.addLayout(btn_row)

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

        add_btn = PrimaryPushButton("Add Role")
        add_btn.clicked.connect(lambda: self._open_new())
        right_layout.addWidget(add_btn)

        edit_btn = PushButton("Edit Selected")
        edit_btn.clicked.connect(lambda: self._edit_selected())
        right_layout.addWidget(edit_btn)

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
            return

        for role in roles:
            btn = PushButton(f"{role.get('name', role.get('id', 'role'))}  ({role.get('id', '')})")
            btn.clicked.connect(lambda _, rid=role.get("id", ""): self._select_role(rid))
            self._roles_area.addWidget(btn)

    def _select_role(self, role_id: str) -> None:
        self._selected_role_id = role_id
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

    def _edit_selected(self) -> None:
        if not self._selected_role_id:
            return
        RoleEditorDialog.open_edit(self, self._selected_role_id)
        self.refresh()

    def _delete_selected(self) -> None:
        if not self._selected_role_id:
            return
        reply = QMessageBox.question(self, "Delete Role", f"Delete role '{self._selected_role_id}'?")
        if reply == QMessageBox.Yes:
            _delete_role(self._selected_role_id)
            multi_agent_system.reload_roles()
            self._selected_role_id = None
            self.refresh()
