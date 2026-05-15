"""
agent_list.py — Agent List (Custom Agent Management)

This tab is the main place to:
- Add/Create custom agents (CreateAgentDialog)
- Run agents (RunAgent dialogs)
- Edit agents (AgentEditorWindow)
- Delete agents
- Also supports chat-driven "create an agent that does X" via
  AgentListTab.create_agent_from_chat(prefill)

Agents are sourced/executed via core/agent_registry.py.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
    QMessageBox,
    QTextEdit,
    QLineEdit,
)

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
    LineEdit,
    TextEdit,
    InfoBar,
    InfoBarPosition,
)

from config import OLLAMA_URL, RESPONDER_MODEL
from core.agent_registry import agent_registry
from gui.tabs.agent_editor import AgentEditorWindow

# ---------------------------------------------------------------------------
# Internet Search Agent — file writer helpers (ported from AgentsTab)
# ---------------------------------------------------------------------------

_AGENTS_DIR = Path.home() / ".plia_ai" / "agents"
_AGENTS_DIR.mkdir(parents=True, exist_ok=True)


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\s]", "", text.lower())
    s = re.sub(r"\s+", "_", s.strip())
    return s[:40] or "agent"


def _build_internet_agent_source(
    slug: str,
    display_name: str,
    api_key: str,
    role: str,
    search_topic: str,
    task: str,
    file_path: str,
) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _repr(s: str) -> str:
        return repr(str(s))

    safe_path = file_path.replace("\\", "/")

    lines = [
        '"""',
        f"Agent      : {display_name}",
        f"Built by   : Plia on {ts}",
        f"Role       : {role}",
        f"File       : {safe_path}",
        "",
        "Search Query and Task are supplied at run-time via:",
        '  --search "your query"  --task "what to do with results"',
        '"""',
        "",
        "import argparse",
        "import sys",
        "",
        "try:",
        "    from ddgs import DDGS",
        "except ImportError:",
        '    print("[ERROR] ddgs is not installed.")',
        '    print("  Run:  pip install ddgs")',
        "    sys.exit(1)",
        "",
        "try:",
        "    from openai import OpenAI",
        "except ImportError:",
        '    print("[ERROR] openai is not installed.")',
        '    print("  Run:  pip install openai")',
        "    sys.exit(1)",
        "",
        "",
        f"OPENAI_API_KEY = {_repr(api_key)}",
        f"DEFAULT_ROLE   = {_repr(role)}",
        f"DEFAULT_SEARCH = {_repr(search_topic)}",
        f"DEFAULT_TASK   = {_repr(task)}",
        "",
        "",
        "def search_internet(query, max_results=5):",
        '    """Search DuckDuckGo and return formatted results string."""',
        "    if not query:",
        "        return \"\"",
        "    print(f\"[-] Searching the internet for: {query!r} ...\")",
        "    try:",
        "        results = DDGS().text(query, max_results=max_results)",
        "        if not results:",
        "            print(\"No results found.\")",
        "            return \"\"",
        "        lines = []",
        "        for r in results:",
        "            lines.append(",
        '                "Title: " + r.get("title", "") + "\\n" +',
        '                "Link:  " + r.get("href",  "") + "\\n" +',
        '                "Snippet: " + r.get("body", "") + "\\n"',
        "            )",
        "        print(f\"[-] Found {len(results)} results.\")",
        "        return \"\\n\".join(lines)",
        "    except Exception as exc:",
        "        print(f\"[ERROR] Search failed: {exc}\")",
        "        return \"\"",
        "",
        "",
        "def run_agent(api_key, role, context, task):",
        '    """Send context + task to OpenAI and return the response text."""',
        '    print(f"[-] Initialising AI agent: {role!r} ...")',
        "    client = OpenAI(api_key=api_key)",
        "    system_msg = (",
        '        "You are an advanced AI Agent.\\n"',
        '        f"Your designated role is: {role}\\n\\n"',
        '        "You have been provided with the following context retrieved from the internet:\\n"',
        "        f\"{context}\\n\\n\"",
        '        "Use this context to fulfil the user\\\'s request. "',
        '        "If the context is insufficient, say so clearly."',
        "    )",
        "    response = client.chat.completions.create(",
        '        model="gpt-4o",',
        "        messages=[",
        '            {"role": "system", "content": system_msg},',
        '            {"role": "user",   "content": task},',
        "        ],",
        "        temperature=0.7,",
        "    )",
        "    return response.choices[0].message.content",
        "",
        "",
        "def run(**kwargs):",
        '    """Programmatic entry-point used by Plia."""',
        '    api_key = kwargs.get("api_key", OPENAI_API_KEY)',
        '    role    = kwargs.get("role",    DEFAULT_ROLE)',
        '    search  = kwargs.get("search",  DEFAULT_SEARCH)',
        '    task    = kwargs.get("task",    DEFAULT_TASK)',
        "    if not search:",
        '        return "No search query provided — cannot run agent."',
        "    if not task:",
        '        return "No task provided — cannot run agent."',
        "    context = search_internet(search)",
        "    if not context:",
        '        return "No search results found — cannot complete task."',
        "    return run_agent(api_key, role, context, task)",
        "",
        "",
        'if __name__ == "__main__":',
        '    parser = argparse.ArgumentParser(description="Plia Internet Search Agent")',
        '    parser.add_argument("--api-key", default=OPENAI_API_KEY, help="OpenAI API key")',
        '    parser.add_argument("--role",    default=DEFAULT_ROLE,   help="Agent persona / role")',
        '    parser.add_argument("--search",  default=DEFAULT_SEARCH, help="Internet search query")',
        '    parser.add_argument("--task",    default=DEFAULT_TASK,   help="Task for the agent")',
        "    args = parser.parse_args()",
        "",
        "    if not args.search:",
        '        print("[ERROR] --search is required. e.g. --search \\"latest Python news\\"")',
        "        sys.exit(1)",
        "    if not args.task:",
        '        print("[ERROR] --task is required. e.g. --task \\"Summarise the top 5 results\\"")',
        "        sys.exit(1)",
        "",
        "    context = search_internet(args.search)",
        "    if not context:",
        "        print(\"No results found. Exiting.\")",
        "        sys.exit(1)",
        "",
        "    result = run_agent(args.api_key, args.role, context, args.task)",
        '    SEP = "=" * 60',
        "    print(f\"\\n{SEP}\")",
        '    print("  AI AGENT OUTPUT")',
        "    print(SEP)",
        "    print(result)",
        "    print(SEP)",
        '    input("\\nPress ENTER to close...")',
    ]
    return "\n".join(lines) + "\n"


def _write_internet_agent(
    display_name: str,
    api_key: str,
    role: str,
    search_topic: str = "",
    task: str = "",
) -> Path:
    """Write the agent .py to ~/.plia_ai/agents/<slug>.py and return the Path."""
    slug = _slugify(display_name)
    path = _AGENTS_DIR / f"{slug}.py"
    counter = 2
    while path.exists():
        path = _AGENTS_DIR / f"{slug}_{counter}.py"
        counter += 1

    header = (
        f"# Agent    : {slug}\n"
        f"# Built    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"# Location : {path}\n"
        f'# Standalone: python "{path}"\n\n'
    )

    src = _build_internet_agent_source(
        slug=slug,
        display_name=display_name,
        api_key=api_key,
        role=role,
        search_topic=search_topic,
        task=task,
        file_path=str(path),
    )

    path.write_text(header + src, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Create Agent Dialog (unified)
# ---------------------------------------------------------------------------

class CreateAgentDialog(QDialog):
    """
    Unified dialog for creating a new custom agent.

    If "OpenAI API Key" is left blank → local Ollama agent (system prompt used).
    If "OpenAI API Key" is filled in → Internet Search Agent (DuckDuckGo + GPT-4o).
    """

    def __init__(self, prefill: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Create New Agent")
        self.setMinimumWidth(560)
        self.setMinimumHeight(520)
        self.setStyleSheet("QDialog { background: #0d1526; } QLabel  { color: #c8d6ef; }")
        self._result: dict | None = None
        self._build(prefill or {})

    def _build(self, prefill: dict):
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(24, 20, 24, 20)

        root.addWidget(TitleLabel("🤖  Create Agent"))

        info = BodyLabel(
            "All fields below are optional except Agent Name.\n"
            "• Leave OpenAI API Key blank → Local Ollama agent (uses your System Prompt).\n"
            "• Enter an OpenAI API Key → Internet Search Agent (DuckDuckGo + GPT-4o).\n"
            "  Search Query and Task will be asked when you click Run."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        root.addWidget(StrongBodyLabel("Agent Name  *"))
        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText("e.g.  Python News Researcher")
        self._name_edit.setText(prefill.get("display_name", ""))
        root.addWidget(self._name_edit)

        root.addWidget(StrongBodyLabel("Short Description  (optional)"))
        self._desc_edit = LineEdit()
        self._desc_edit.setPlaceholderText("e.g.  Summarises emails into bullet points")
        self._desc_edit.setText(prefill.get("description", ""))
        root.addWidget(self._desc_edit)

        root.addWidget(StrongBodyLabel("System Prompt  (optional — used by local Ollama agents)"))
        self._prompt_edit = TextEdit()
        self._prompt_edit.setPlaceholderText(
            "You are a specialised assistant. Your job is to…\n\n"
            "Be concise and focused on the task.\n\n"
            "(Leave blank if using an OpenAI API Key below.)"
        )
        self._prompt_edit.setPlainText(prefill.get("prompt", ""))
        self._prompt_edit.setMinimumHeight(110)
        root.addWidget(self._prompt_edit)

        root.addWidget(StrongBodyLabel("OpenAI API Key  (optional — fills in → Internet Search Agent)"))
        self._key_edit = LineEdit()
        self._key_edit.setPlaceholderText("sk-…  (leave blank for a local Ollama agent)")
        self._key_edit.setEchoMode(QLineEdit.Password)
        root.addWidget(self._key_edit)

        root.addWidget(StrongBodyLabel("Agent Role / Persona  (optional)"))
        self._role_edit = LineEdit()
        self._role_edit.setPlaceholderText("e.g.  Financial Analyst, Python Coder")
        self._role_edit.setText(prefill.get("role", ""))
        root.addWidget(self._role_edit)

        root.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = PushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        create_btn = PrimaryPushButton("✨  Create Agent")
        create_btn.clicked.connect(self._on_create)
        btn_row.addWidget(create_btn)

        root.addLayout(btn_row)

    def _on_create(self):
        name = self._name_edit.text().strip()
        desc = self._desc_edit.text().strip()
        prompt = self._prompt_edit.toPlainText().strip()
        key = self._key_edit.text().strip()
        role = self._role_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "Missing Name", "Please enter a display name for the agent.")
            return

        if key:
            self._result = {
                "type": "internet_search",
                "display_name": name,
                "description": desc or f"Internet search agent: {name}",
                "api_key": key,
                "role": role or "AI Research Assistant",
                "prompt": prompt,
            }
        else:
            if not prompt:
                prompt = (
                    f"You are a specialised AI assistant named {name}. "
                    f"Your job is to help the user with {desc or 'their request'}. "
                    "Be concise, accurate, and helpful."
                )
            self._result = {
                "type": "custom",
                "display_name": name,
                "description": desc or f"Custom agent: {name}",
                "prompt": prompt,
                "role": role,
            }

        self.accept()

    def get_result(self) -> dict | None:
        return self._result


# ---------------------------------------------------------------------------
# Run dialogs
# ---------------------------------------------------------------------------

class _RunCustomAgentDialog(QDialog):
    """Dialog to collect runtime args for LLM-only agents (no file_path)."""

    def __init__(self, display_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Run — {display_name}")
        self.setMinimumWidth(520)
        self.setMinimumHeight(340)
        self.setStyleSheet("QDialog { background: #0d1526; } QLabel { color: #c8d6ef; }")
        self._result: dict | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        root.addWidget(TitleLabel("🤖 Run Agent (Ollama)", self))
        subtitle = SubtitleLabel(display_name, self)
        subtitle.setStyleSheet("color: #33b5e5;")
        root.addWidget(subtitle)

        root.addWidget(StrongBodyLabel("What would you like the agent to do?"))
        self._input_edit = TextEdit()
        self._input_edit.setPlaceholderText("Type your request here…")
        self._input_edit.setMinimumHeight(130)
        root.addWidget(self._input_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        cancel_btn = PushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        run_btn = PrimaryPushButton(FIF.PLAY, "Run Agent")
        run_btn.clicked.connect(self._on_run)
        btn_row.addWidget(run_btn)

        root.addLayout(btn_row)

    def _on_run(self):
        text = (self._input_edit.toPlainText() or "").strip()
        if not text:
            QMessageBox.warning(self, "Empty Input", "Please enter a prompt for the agent.")
            return
        self._result = {"user_input": text}
        self.accept()

    def get_result(self) -> dict | None:
        return self._result


class _RunInternetAgentDialog(QDialog):
    """Dialog to collect runtime args for internet_search agents."""

    def __init__(self, display_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Run — {display_name}")
        self.setMinimumWidth(520)
        self.setMinimumHeight(340)
        self.setStyleSheet("QDialog { background: #0d1526; } QLabel { color: #c8d6ef; }")
        self._result: dict | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        root.addWidget(TitleLabel("🌐 Run Internet Search Agent", self))
        subtitle = SubtitleLabel(display_name, self)
        subtitle.setStyleSheet("color: #33b5e5;")
        root.addWidget(subtitle)

        root.addSpacing(4)

        root.addWidget(StrongBodyLabel("Search Query"))
        self._search_edit = LineEdit()
        self._search_edit.setPlaceholderText("e.g. latest Python 3.13 features")
        root.addWidget(self._search_edit)

        root.addWidget(StrongBodyLabel("Task (what to do with results)"))
        self._task_edit = TextEdit()
        self._task_edit.setPlaceholderText(
            "e.g. Summarise the top 5 new features in Python 3.13 "
            "and give a small code example for each one."
        )
        self._task_edit.setMinimumHeight(120)
        root.addWidget(self._task_edit)

        root.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        cancel_btn = PushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        run_btn = PrimaryPushButton(FIF.PLAY, "Run Agent")
        run_btn.clicked.connect(self._on_run)
        btn_row.addWidget(run_btn)

        root.addLayout(btn_row)

    def _on_run(self):
        self._result = {
            "search": (self._search_edit.text() or "").strip(),
            "task": (self._task_edit.toPlainText() or "").strip(),
        }
        self.accept()

    def get_result(self) -> dict | None:
        return self._result


# ---------------------------------------------------------------------------
# Row
# ---------------------------------------------------------------------------

class AgentListRow(CardWidget):
    """Single agent row in the Agent List."""

    run_requested = Signal(str)
    edit_requested = Signal(str)
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

        edit_btn = PushButton(FIF.EDIT, "Edit")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self._name))
        lay.addWidget(edit_btn)

        delete_btn = PushButton(FIF.DELETE, "Delete")
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self._name))
        lay.addWidget(delete_btn)


# ---------------------------------------------------------------------------
# Main tab
# ---------------------------------------------------------------------------

class AgentListTab(QWidget):
    """Agent List tab — primary surface for custom agent management."""

    agent_output_ready = Signal(str, str)  # agent_display_name, response_text

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        agent_registry.agents_changed.connect(self.refresh)
        # Also refresh when the live-agent store changes (wizard creates / deletes)
        try:
            from core.agent_runtime import get_runtime
            get_runtime().store.changed.connect(self.refresh)
        except Exception as exc:
            print(f"[AgentListTab] could not connect to live-agent store: {exc}")
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

        live_states = self._fetch_live_states()
        custom_agents = agent_registry.all_agents()

        if not live_states and not custom_agents:
            empty = CardWidget(self._scroll_content)
            lay = QVBoxLayout(empty)
            lay.setContentsMargins(16, 16, 16, 16)
            lay.addWidget(BodyLabel("No agents available.", empty))
            self._list_layout.addWidget(empty)
            return

        # ── Live agents (wizard-created, scheduler-backed) ────────────────
        if live_states:
            self._list_layout.addWidget(SubtitleLabel("Live Agents", self._scroll_content))
            from gui.tabs.agents import LiveAgentRow
            for state in live_states:
                self._list_layout.addWidget(LiveAgentRow(state, self._scroll_content))

        # ── Custom (prompt-only) agents from the legacy registry ──────────
        if custom_agents:
            self._list_layout.addWidget(SubtitleLabel("Custom Agents", self._scroll_content))
            for agent in custom_agents:
                name = agent.get("name", "")
                row = AgentListRow(name, agent, self._scroll_content)
                row.run_requested.connect(self._on_run_agent)
                row.edit_requested.connect(self._on_edit_agent)
                row.delete_requested.connect(self._on_delete_agent)
                self._list_layout.addWidget(row)

        self._list_layout.addStretch(1)

    def _fetch_live_states(self):
        try:
            from core.agent_runtime import get_runtime
            return sorted(get_runtime().store.all(), key=lambda s: s.display_name)
        except Exception as exc:
            print(f"[AgentListTab] could not fetch live agents: {exc}")
            return []

    # ---------------------------------------------------------------------
    # Add/Create
    # ---------------------------------------------------------------------

    def _open_create(self):
        dlg = CreateAgentDialog(parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._create_from_dialog_result(dlg.get_result())

    def create_agent_from_chat(self, prefill: dict):
        dlg = CreateAgentDialog(prefill=prefill or {}, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._create_from_dialog_result(dlg.get_result())

    def _create_from_dialog_result(self, data: dict | None):
        if not data:
            return

        if data.get("type") == "internet_search":
            try:
                agent_path = _write_internet_agent(
                    display_name=data["display_name"],
                    api_key=data["api_key"],
                    role=data["role"],
                    search_topic="",
                    task="",
                )
            except Exception as exc:
                QMessageBox.critical(self, "File Write Error", f"Could not save agent file:\n{exc}")
                return

            agent_registry.create_agent(
                display_name=data["display_name"],
                description=data["description"],
                prompt=(
                    f"You are {data['role']}. "
                    "You search the internet and process results with OpenAI GPT-4o."
                ),
                icon="🌐",
                file_path=str(agent_path),
                agent_type="internet_search",
            )

            InfoBar.success(
                title="Internet Search Agent Created",
                content=(
                    f"'{data['display_name']}' saved — "
                    "click Run to enter your search query and task."
                ),
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=7000,
            )
            return

        agent_registry.create_agent(
            display_name=data["display_name"],
            description=data["description"],
            prompt=data["prompt"],
            agent_type="custom",
        )

        InfoBar.success(
            title="Agent Created",
            content=f"'{data['display_name']}' is ready. Click Run to use it.",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=4000,
        )

    # ---------------------------------------------------------------------
    # Run / Edit / Delete
    # ---------------------------------------------------------------------

    def _on_run_agent(self, name: str):
        agent = agent_registry.get_agent(name)
        if not agent:
            return

        fp = agent.get("file_path", "") or ""
        agent_type = agent.get("agent_type", "custom") or "custom"

        if fp:
            if agent_type == "internet_search":
                dlg = _RunInternetAgentDialog(
                    display_name=agent.get("display_name", name),
                    parent=self,
                )
                if dlg.exec() != QDialog.Accepted:
                    return
                payload = dlg.get_result() or {}

                search_query = (payload.get("search") or "").strip()
                task_text = (payload.get("task") or "").strip()

                if not search_query:
                    QMessageBox.warning(self, "Missing Search Query", "Please enter a search query.")
                    return
                if not task_text:
                    QMessageBox.warning(self, "Missing Task", "Please enter a task for the agent.")
                    return

                result = agent_registry.run_agent_file(
                    name,
                    extra_args=["--search", search_query, "--task", task_text],
                )
            else:
                result = agent_registry.run_agent_file(name)

            if result.get("success"):
                response_text = (result.get("message", "") or "").strip()
                InfoBar.success(
                    title="Agent Launched",
                    content=response_text[:140],
                    parent=self,
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=4500,
                )
                if response_text:
                    # Let chat UI show the same bubble/history flow as chat-triggered runs.
                    self.agent_output_ready.emit(agent.get("display_name", name), response_text)
            else:
                InfoBar.error(
                    title="Agent Error",
                    content=(result.get("message", "") or "")[:160],
                    parent=self,
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=6000,
                )

            self.refresh()
            return

        # LLM-only agents (no file_path)
        dlg = _RunCustomAgentDialog(
            display_name=agent.get("display_name", name),
            parent=self,
        )
        if dlg.exec() != QDialog.Accepted:
            return
        payload = dlg.get_result() or {}

        user_input = (payload.get("user_input") or "").strip()
        if not user_input:
            QMessageBox.warning(self, "Empty Input", "Please enter a prompt for the agent.")
            return

        result = agent_registry.run_agent(
            name,
            user_input,
            ollama_url=OLLAMA_URL,
            model=RESPONDER_MODEL,
        )

        if result.get("success"):
            response_text = (result.get("message", "") or "").strip()
            InfoBar.success(
                title="Agent Output Ready",
                content=response_text[:180],
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=6000,
            )
            if response_text:
                self.agent_output_ready.emit(agent.get("display_name", name), response_text)
        else:
            InfoBar.error(
                title="Agent Error",
                content=(result.get("message", "") or "")[:180],
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=6000,
            )

        self.refresh()

    def _on_edit_agent(self, name: str):
        # Current editor edits Jarvis multi-agent role YAML (not the registry agent JSON).
        # We open it anyway but pass the name for future extensibility.
        editor = AgentEditorWindow(self)
        if editor.exec() == QDialog.Accepted:
            # Registry is not modified by this editor; refresh to keep UI consistent.
            self.refresh()

    def _on_delete_agent(self, name: str):
        agent = agent_registry.get_agent(name)
        if not agent:
            return

        reply = QMessageBox.question(
            self,
            "Delete Agent",
            f"Delete agent '{agent.get('display_name', name)}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        agent_registry.delete_agent(name)
        InfoBar.warning(
            title="Agent Deleted",
            content=f"'{agent.get('display_name', name)}' has been removed.",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=3000,
        )
        self.refresh()
