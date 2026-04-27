"""
agent_list.py — Sidebar Agent List view for Plia

Jarvis-style agent list presentation:
- shows the available agents in a compact list
- keeps add/edit/delete controls inside the list tab
- uses the registry as the source of truth
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    FluentIcon as FIF,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
)

from core.agent_registry import agent_registry


class AgentListRow(CardWidget):
    """Single agent row in the Agent List."""

    run_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, name: str, info: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._name = name
        self._info = info
        self._build_ui()

    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        display_name = self._info.get("display_name") or self._name
        description = self._info.get("description") or "No description provided."
        prompt = self._info.get("prompt") or ""
        agent_type = self._info.get("agent_type") or "custom"
        runs = self._info.get("runs", 0)
        last_run = self._info.get("last_run") or "Never"

        title = StrongBodyLabel(display_name, self)
        subtitle = BodyLabel(description, self)
        meta = BodyLabel(f"Name: {self._name}  •  Type: {agent_type}  •  Runs: {runs}", self)
        last = BodyLabel(f"Last run: {last_run}", self)

        subtitle.setWordWrap(True)
        meta.setWordWrap(True)
        last.setWordWrap(True)

        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        text_col.addWidget(meta)
        text_col.addWidget(last)

        if prompt:
            prompt_label = BodyLabel(prompt[:180] + ("..." if len(prompt) > 180 else ""), self)
            prompt_label.setWordWrap(True)
            text_col.addWidget(prompt_label)

        lay.addLayout(text_col, 1)

        run_btn = PushButton(FIF.PLAY, "Run")
        run_btn.clicked.connect(lambda: self.run_requested.emit(self._name))
        lay.addWidget(run_btn)

        delete_btn = PushButton(FIF.DELETE, "Delete")
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self._name))
        lay.addWidget(delete_btn)


class AgentListTab(QWidget):
    """Sidebar Agent List tab matching Jarvis-style list presentation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        agent_registry.agents_changed.connect(self.refresh)
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QVBoxLayout()
        title = TitleLabel("Agent List", self)
        subtitle = SubtitleLabel("Available agents from the registry", self)
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        actions = QHBoxLayout()
        self._add_btn = PrimaryPushButton(FIF.ADD, "Add Agent")
        self._add_btn.clicked.connect(self._open_create)
        actions.addWidget(self._add_btn)

        self._refresh_btn = PushButton(FIF.SYNC, "Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        actions.addWidget(self._refresh_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        self._scroll = ScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._list_layout = QVBoxLayout(self._scroll_content)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)
        self._scroll.setWidget(self._scroll_content)
        root.addWidget(self._scroll, 1)

    def _clear_rows(self):
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def refresh(self):
        self._clear_rows()
        agents = agent_registry.all_agents()

        if not agents:
            empty = CardWidget(self._scroll_content)
            lay = QVBoxLayout(empty)
            lay.setContentsMargins(16, 16, 16, 16)
            lay.addWidget(BodyLabel("No agents available.", empty))
            self._list_layout.addWidget(empty)
            return

        for agent in agents:
            name = agent.get("name", "")
            row = AgentListRow(name, agent, self._scroll_content)
            row.run_requested.connect(self._on_run_agent)
            row.delete_requested.connect(self._on_delete_agent)
            self._list_layout.addWidget(row)

        self._list_layout.addStretch(1)

    def _open_create(self):
        # Placeholder: keep the Add button working without breaking the list view.
        # The existing agent creation flow remains in the broader Agents UI.
        pass

    def _on_run_agent(self, name: str):
        agent = agent_registry.get_agent(name)
        if not agent:
            return

        fp = agent.get("file_path", "")
        if fp:
            agent_registry.run_agent_file(name)
            return

        agent_registry.record_run(name)

    def _on_delete_agent(self, name: str):
        agent_registry.delete_agent(name)
        self.refresh()
