"""
Active Agents tab — shows the live status of every AI model,
core service, function agent, and backend manager in Plia.

Now also supports dynamic CUSTOM AGENTS:
  • "Create Agent" button opens a unified dialog.
  • Users can fill in a Name + optional System Prompt / OpenAI API Key.
  • Leaving the API Key blank → local Ollama agent.
  • Filling in the API Key → Internet Search Agent (DuckDuckGo + GPT-4o).
  • Search Query and Task are asked at run-time (not at creation time).
  • Custom agents appear in a dedicated "Custom Agents" section with
    Run / Delete controls.
  • Asking Plia in chat "create an agent that does X" triggers the same
    creation flow automatically.

Changes in this version:
  1. CreateAgentDialog is now a single unified form — no separate tabs.
     All fields except Name are optional. Search Query and Task removed.
  2. RunAgentDialog asks for Search Query + Task when running an Internet
     Search Agent; shows generic prompt for custom Ollama agents.
  3. CustomAgentRow Run / Delete buttons now use minimum widths and
     flexible size policies so text and icons stay readable on any window size.
"""

import os
import re
import requests
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QSizePolicy, QDialog, QLineEdit, QTextEdit, QMessageBox,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont

from qfluentwidgets import (
    TitleLabel, BodyLabel, StrongBodyLabel, CaptionLabel,
    CardWidget, PushButton, FluentIcon as FIF,
    ScrollArea, SubtitleLabel, LineEdit, TextEdit,
    PrimaryPushButton, MessageBoxBase, SubtitleLabel as DialogSubtitle,
    InfoBar, InfoBarPosition,
)

from config import OLLAMA_URL, LOCAL_ROUTER_PATH, VOICE_ASSISTANT_ENABLED, RESPONDER_MODEL
from core.agent_registry import agent_registry


# ---------------------------------------------------------------------------
# Status colours (Aura theme)
# ---------------------------------------------------------------------------
STATUS_COLOURS = {
    "active":   "#4caf50",   # green
    "idle":     "#33b5e5",   # cyan
    "offline":  "#ef5350",   # red
    "disabled": "#555e70",   # muted grey
    "loading":  "#ffb300",   # amber
    "custom":   "#bb86fc",   # purple for custom agents
}


def _dot(colour: str) -> str:
    return f'<span style="color:{colour}; font-size:16px;">●</span>'


# ---------------------------------------------------------------------------
# Background status-polling thread
# ---------------------------------------------------------------------------

class AgentStatusThread(QThread):
    """Polls every agent's status in one background pass."""
    finished = Signal(dict)

    def run(self):
        statuses = {}

        # ── Ollama reachable? ────────────────────────────────────────────
        ollama_ok = False
        running_models: list[str] = []
        try:
            r = requests.get(f"{OLLAMA_URL}/ps", timeout=2)
            if r.status_code == 200:
                ollama_ok = True
                running_models = [m.get("name", "") for m in r.json().get("models", [])]
        except Exception:
            pass

        statuses["ollama_reachable"] = ollama_ok
        statuses["running_models"]   = running_models

        # ── Function Gemma Router ────────────────────────────────────────
        from core.llm import is_router_loaded
        router_in_ram = is_router_loaded()
        router_files  = os.path.exists(os.path.join(LOCAL_ROUTER_PATH, "model.safetensors"))
        if router_in_ram:
            statuses["router"] = ("active", "Loaded in RAM")
        elif router_files:
            statuses["router"] = ("idle", "Ready — not yet loaded")
        else:
            statuses["router"] = ("offline", "Model files missing")

        # ── Responder LLM (Qwen via Ollama) ─────────────────────────────
        if not ollama_ok:
            statuses["llm"] = ("offline", "Ollama not reachable")
        else:
            loaded = any(RESPONDER_MODEL in m for m in running_models)
            if loaded:
                statuses["llm"] = ("active", f"{RESPONDER_MODEL} — in VRAM")
            else:
                statuses["llm"] = ("idle", f"{RESPONDER_MODEL} — available, not loaded")

        # ── Voice Assistant ──────────────────────────────────────────────
        if not VOICE_ASSISTANT_ENABLED:
            statuses["voice_assistant"] = ("disabled", "Disabled in config")
        else:
            try:
                from core.voice_assistant import voice_assistant
                if voice_assistant.running:
                    statuses["voice_assistant"] = ("active", "Listening")
                else:
                    statuses["voice_assistant"] = ("idle", "Initialised, not running")
            except Exception:
                statuses["voice_assistant"] = ("offline", "Failed to import")

        # ── STT ──────────────────────────────────────────────────────────
        if not VOICE_ASSISTANT_ENABLED:
            statuses["stt"] = ("disabled", "Disabled in config")
        else:
            try:
                from core.voice_assistant import voice_assistant
                if voice_assistant.stt_listener and voice_assistant.stt_listener.running:
                    statuses["stt"] = ("active", "Listening for audio")
                elif voice_assistant.stt_listener:
                    statuses["stt"] = ("idle", "Initialised")
                else:
                    statuses["stt"] = ("offline", "Not initialised")
            except Exception:
                statuses["stt"] = ("offline", "Failed to import")

        # ── TTS ──────────────────────────────────────────────────────────
        try:
            from core.tts import tts
            if tts.piper_exe and tts.enabled:
                statuses["tts"] = ("active", "Piper ready, voice on")
            elif tts.piper_exe:
                statuses["tts"] = ("idle", "Piper ready, voice off")
            else:
                statuses["tts"] = ("offline", "Piper not found")
        except Exception:
            statuses["tts"] = ("offline", "Failed to import")

        # ── Function Executor managers ───────────────────────────────────
        try:
            from core.function_executor import executor
            statuses["task_manager"]     = ("active", "Ready") if executor.task_manager     else ("offline", "Not loaded")
            statuses["calendar_manager"] = ("active", "Ready") if executor.calendar_manager  else ("offline", "Not loaded")
            statuses["kasa_manager"]     = ("active", "Ready") if executor.kasa_manager      else ("offline", "Not loaded")
            statuses["weather_manager"]  = ("active", "Ready") if executor.weather_manager   else ("offline", "Not loaded")
            statuses["news_manager"]     = ("active", "Ready") if executor.news_manager      else ("offline", "Not loaded")
        except Exception:
            for key in ("task_manager", "calendar_manager", "kasa_manager",
                        "weather_manager", "news_manager"):
                statuses[key] = ("offline", "Executor not reachable")

        # ── Desktop Agent availability ───────────────────────────────────
        try:
            import mss
            import pyautogui
            from core.agent.desktop_agent import DesktopAgent
            statuses["desktop_agent"] = ("idle", "Ready — mss + pyautogui installed")
        except ImportError as e:
            statuses["desktop_agent"] = ("offline", f"Missing dependency: {e}")

        # ── Web Search availability ──────────────────────────────────────
        try:
            from ddgs import DDGS
            statuses["web_search"] = ("idle", "DuckDuckGo ready")
        except ImportError:
            statuses["web_search"] = ("offline", "ddgs not installed")

        # ── Calendar sync providers ──────────────────────────────────────
        try:
            from core.settings_store import settings
            g_on = settings.get("calendar.google.enabled", False)
            o_on = settings.get("calendar.outlook.enabled", False)
            parts = []
            if g_on:  parts.append("Google")
            if o_on:  parts.append("Outlook")
            if parts:
                statuses["calendar_sync"] = ("active", f"Syncing: {', '.join(parts)}")
            else:
                statuses["calendar_sync"] = ("idle", "No providers enabled")
        except Exception:
            statuses["calendar_sync"] = ("offline", "Settings not available")

        # ── Kasa smart-home reachability ─────────────────────────────────
        try:
            from core.kasa_control import kasa_manager
            devices = getattr(kasa_manager, "devices", {})
            if devices:
                statuses["kasa_devices"] = ("active", f"{len(devices)} device(s) found")
            else:
                statuses["kasa_devices"] = ("idle", "No devices discovered yet")
        except Exception:
            statuses["kasa_devices"] = ("offline", "Kasa module not reachable")

        self.finished.emit(statuses)


# ---------------------------------------------------------------------------
# Individual agent card row
# ---------------------------------------------------------------------------

class AgentRow(QFrame):
    """A single horizontal row: dot + name + description + status badge."""

    def __init__(self, label: str, description: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setStyleSheet("background: transparent;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(10)

        # Status dot
        self._dot_label = QLabel("●")
        self._dot_label.setFixedWidth(18)
        self._dot_label.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)
        self._dot_label.setStyleSheet(f"color: {STATUS_COLOURS['loading']}; font-size: 14px;")
        layout.addWidget(self._dot_label)

        # Name
        name_lbl = StrongBodyLabel(label)
        name_lbl.setFixedWidth(190)
        layout.addWidget(name_lbl)

        # Description
        desc_lbl = CaptionLabel(description)
        desc_lbl.setStyleSheet("color: #555e70;")
        desc_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(desc_lbl)

        # Status badge
        self._status_lbl = CaptionLabel("Checking…")
        self._status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._status_lbl.setFixedWidth(230)
        self._status_lbl.setStyleSheet("color: #555e70;")
        layout.addWidget(self._status_lbl)

    def update_status(self, state: str, detail: str):
        colour = STATUS_COLOURS.get(state, STATUS_COLOURS["loading"])
        self._dot_label.setStyleSheet(f"color: {colour}; font-size: 14px;")
        self._status_lbl.setText(detail)
        self._status_lbl.setStyleSheet(f"color: {colour};")


# ---------------------------------------------------------------------------
# Custom Agent Row  (has Run + Delete buttons)
# FIX: buttons now use minimum widths + flexible size policies so text/icons
#      remain fully readable regardless of window size.
# ---------------------------------------------------------------------------

class CustomAgentRow(QFrame):
    """Row for a user-created custom agent with Run and Delete actions."""

    run_requested    = Signal(str)   # agent name
    delete_requested = Signal(str)   # agent name

    def __init__(self, agent: dict, parent=None):
        super().__init__(parent)
        self._name = agent["name"]
        # Removed setFixedHeight — row grows with content instead of clipping
        self.setMinimumHeight(56)
        self.setStyleSheet("background: transparent;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        # Icon + status dot
        icon_lbl = QLabel(agent.get("icon", "🤖"))
        icon_lbl.setMinimumWidth(26)
        icon_lbl.setMaximumWidth(32)
        icon_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)
        icon_lbl.setStyleSheet("font-size: 18px;")
        layout.addWidget(icon_lbl)

        # Name + description (stacked vertically)
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.setContentsMargins(0, 0, 0, 0)

        name_lbl = StrongBodyLabel(agent.get("display_name", agent["name"]))
        name_lbl.setMinimumWidth(120)
        name_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        text_col.addWidget(name_lbl)

        runs = agent.get("runs", 0)
        last = agent.get("last_run")
        meta = f"Runs: {runs}"
        if last:
            meta += f"  ·  Last: {last[:10]}"
        meta_lbl = CaptionLabel(meta)
        meta_lbl.setStyleSheet("color: #555e70;")
        text_col.addWidget(meta_lbl)

        layout.addLayout(text_col, stretch=1)

        # Description
        desc_lbl = CaptionLabel(agent.get("description", ""))
        desc_lbl.setStyleSheet("color: #33b5e5;")
        desc_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        desc_lbl.setWordWrap(False)
        layout.addWidget(desc_lbl, stretch=2)

        # ── Run button ────────────────────────────────────────────────────
        # Uses minimum width so "▷ Run" is never cropped; grows with content.
        run_btn = PushButton(FIF.PLAY, "Run")
        run_btn.setMinimumWidth(88)
        run_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        run_btn.clicked.connect(lambda: self.run_requested.emit(self._name))
        layout.addWidget(run_btn)

        # ── Delete button ─────────────────────────────────────────────────
        # Shows both icon AND label so text is always readable.
        del_btn = PushButton(FIF.DELETE, "Delete")
        del_btn.setMinimumWidth(88)
        del_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        del_btn.setToolTip("Delete this agent")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._name))
        layout.addWidget(del_btn)


# ---------------------------------------------------------------------------
# Internet Search Agent — file writer helpers
# ---------------------------------------------------------------------------

_AGENTS_DIR = Path.home() / ".plia_ai" / "agents"
_AGENTS_DIR.mkdir(parents=True, exist_ok=True)


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\s]", "", text.lower())
    s = re.sub(r"\s+", "_", s.strip())
    return s[:40] or "agent"


def _build_internet_agent_source(slug: str, display_name: str, api_key: str,
                                  role: str, search_topic: str, task: str,
                                  file_path: str) -> str:
    """
    Build the complete Python source for an Internet Search Agent.
    search_topic and task default to empty strings — they are supplied
    at run-time via --search / --task CLI flags (or via the RunAgentDialog).
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _repr(s):
        return repr(str(s))

    safe_path = file_path.replace("\\", "/")

    lines = [
        '"""',
        f'Agent      : {display_name}',
        f'Built by   : Plia on {ts}',
        f'Role       : {role}',
        f'File       : {safe_path}',
        '',
        'Search Query and Task are supplied at run-time via:',
        '  --search "your query"  --task "what to do with results"',
        '"""',
        '',
        'import argparse',
        'import sys',
        '',
        'try:',
        '    from ddgs import DDGS',
        'except ImportError:',
        '    print("[ERROR] ddgs is not installed.")',
        '    print("  Run:  pip install ddgs")',
        '    sys.exit(1)',
        '',
        'try:',
        '    from openai import OpenAI',
        'except ImportError:',
        '    print("[ERROR] openai is not installed.")',
        '    print("  Run:  pip install openai")',
        '    sys.exit(1)',
        '',
        '',
        f'OPENAI_API_KEY = {_repr(api_key)}',
        f'DEFAULT_ROLE   = {_repr(role)}',
        f'DEFAULT_SEARCH = {_repr(search_topic)}',
        f'DEFAULT_TASK   = {_repr(task)}',
        '',
        '',
        'def search_internet(query, max_results=5):',
        '    """Search DuckDuckGo and return formatted results string."""',
        '    if not query:',
        '        return ""',
        '    print(f"[-] Searching the internet for: {query!r} ...")',
        '    try:',
        '        results = DDGS().text(query, max_results=max_results)',
        '        if not results:',
        '            print("No results found.")',
        '            return ""',
        '        lines = []',
        '        for r in results:',
        '            lines.append(',
        '                "Title: " + r.get("title", "") + "\\n" +',
        '                "Link:  " + r.get("href", "")  + "\\n" +',
        '                "Snippet: " + r.get("body", "") + "\\n"',
        '            )',
        '        print(f"[-] Found {len(results)} results.")',
        '        return "\\n".join(lines)',
        '    except Exception as exc:',
        '        print(f"[ERROR] Search failed: {exc}")',
        '        return ""',
        '',
        '',
        'def run_agent(api_key, role, context, task):',
        '    """Send context + task to OpenAI and return the response text."""',
        '    print(f"[-] Initialising AI agent: {role!r} ...")',
        '    client = OpenAI(api_key=api_key)',
        '    system_msg = (',
        '        "You are an advanced AI Agent.\\n"',
        '        f"Your designated role is: {role}\\n\\n"',
        '        "You have been provided with the following context retrieved from the internet:\\n"',
        '        f"{context}\\n\\n"',
        '        "Use this context to fulfil the user\'s request. "',
        '        "If the context is insufficient, say so clearly."',
        '    )',
        '    response = client.chat.completions.create(',
        '        model="gpt-4o",',
        '        messages=[',
        '            {"role": "system", "content": system_msg},',
        '            {"role": "user",   "content": task},',
        '        ],',
        '        temperature=0.7,',
        '    )',
        '    return response.choices[0].message.content',
        '',
        '',
        'def run(**kwargs):',
        '    """Programmatic entry-point used by Plia."""',
        '    api_key = kwargs.get("api_key", OPENAI_API_KEY)',
        '    role    = kwargs.get("role",    DEFAULT_ROLE)',
        '    search  = kwargs.get("search",  DEFAULT_SEARCH)',
        '    task    = kwargs.get("task",    DEFAULT_TASK)',
        '    if not search:',
        '        return "No search query provided — cannot run agent."',
        '    if not task:',
        '        return "No task provided — cannot run agent."',
        '    context = search_internet(search)',
        '    if not context:',
        '        return "No search results found — cannot complete task."',
        '    return run_agent(api_key, role, context, task)',
        '',
        '',
        'if __name__ == "__main__":',
        '    parser = argparse.ArgumentParser(description="Plia Internet Search Agent")',
        '    parser.add_argument("--api-key", default=OPENAI_API_KEY, help="OpenAI API key")',
        '    parser.add_argument("--role",    default=DEFAULT_ROLE,   help="Agent persona / role")',
        '    parser.add_argument("--search",  default=DEFAULT_SEARCH, help="Internet search query")',
        '    parser.add_argument("--task",    default=DEFAULT_TASK,   help="Task for the agent")',
        '    args = parser.parse_args()',
        '',
        '    if not args.search:',
        '        print("[ERROR] --search is required. e.g. --search \\"latest Python news\\"")',
        '        sys.exit(1)',
        '    if not args.task:',
        '        print("[ERROR] --task is required. e.g. --task \\"Summarise the top 5 results\\"")',
        '        sys.exit(1)',
        '',
        '    context = search_internet(args.search)',
        '    if not context:',
        '        print("No results found. Exiting.")',
        '        sys.exit(1)',
        '',
        '    result = run_agent(args.api_key, args.role, context, args.task)',
        '    SEP = "=" * 60',
        '    print(f"\\n{SEP}")',
        '    print("  AI AGENT OUTPUT")',
        '    print(SEP)',
        '    print(result)',
        '    print(SEP)',
        '    input("\\nPress ENTER to close...")',
    ]
    return "\n".join(lines) + "\n"


def _write_internet_agent(display_name: str, api_key: str, role: str,
                           search_topic: str = "", task: str = "") -> Path:
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
        f"# Standalone: python \"{path}\"\n\n"
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
# Create Agent Dialog — Unified single form (no tabs)
#
# CHANGE: Removed the separate "Internet Search Agent" tab.
#         All fields are now in one place. Fields:
#           - Agent Name         (required)
#           - Short Description  (optional)
#           - System Prompt      (optional — for local Ollama agents)
#           - OpenAI API Key     (optional — if filled → Internet Search Agent)
#           - Agent Role         (optional)
#
#         Search Query and Task are asked at run-time via RunAgentDialog.
# ---------------------------------------------------------------------------

class CreateAgentDialog(QDialog):
    """
    Unified dialog for creating a new custom agent.

    If "OpenAI API Key" is left blank → local Ollama agent (system prompt used).
    If "OpenAI API Key" is filled in → Internet Search Agent (DuckDuckGo + GPT-4o).
      Search Query and Task are supplied by the user when they click Run.

    All fields except Agent Name are optional.
    """

    def __init__(self, prefill: dict = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Agent")
        self.setMinimumWidth(560)
        self.setMinimumHeight(520)
        self.setStyleSheet("""
            QDialog { background: #0d1526; }
            QLabel  { color: #c8d6ef; }
        """)
        self._result = None
        self._build(prefill or {})

    def _build(self, prefill: dict):
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(24, 20, 24, 20)

        root.addWidget(TitleLabel("🤖  Create Agent"))

        # Info banner
        info = CaptionLabel(
            "All fields below are optional except Agent Name.\n"
            "• Leave OpenAI API Key blank → Local Ollama agent (uses your System Prompt).\n"
            "• Enter an OpenAI API Key → Internet Search Agent (DuckDuckGo + GPT-4o).\n"
            "  Search Query and Task will be asked when you click Run."
        )
        info.setStyleSheet(
            "color: #8a9ab5; background: #111c30; border: 1px solid #1a2236;"
            "border-radius: 6px; padding: 8px 10px;"
        )
        info.setWordWrap(True)
        root.addWidget(info)

        # ── Agent Name ────────────────────────────────────────────────────
        root.addWidget(StrongBodyLabel("Agent Name  *"))
        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText("e.g.  Python News Researcher")
        self._name_edit.setText(prefill.get("display_name", ""))
        root.addWidget(self._name_edit)

        # ── Short Description ─────────────────────────────────────────────
        root.addWidget(StrongBodyLabel("Short Description  (optional)"))
        self._desc_edit = LineEdit()
        self._desc_edit.setPlaceholderText("e.g.  Summarises emails into bullet points")
        self._desc_edit.setText(prefill.get("description", ""))
        root.addWidget(self._desc_edit)

        # ── System Prompt ─────────────────────────────────────────────────
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

        # ── OpenAI API Key ────────────────────────────────────────────────
        root.addWidget(StrongBodyLabel("OpenAI API Key  (optional — fills in → Internet Search Agent)"))
        self._key_edit = LineEdit()
        self._key_edit.setPlaceholderText("sk-…  (leave blank for a local Ollama agent)")
        self._key_edit.setEchoMode(QLineEdit.Password)
        root.addWidget(self._key_edit)

        # ── Agent Role / Persona ──────────────────────────────────────────
        root.addWidget(StrongBodyLabel("Agent Role / Persona  (optional)"))
        self._role_edit = LineEdit()
        self._role_edit.setPlaceholderText("e.g.  Financial Analyst, Python Coder")
        root.addWidget(self._role_edit)

        root.addStretch()

        # ── Buttons ───────────────────────────────────────────────────────
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
        name   = self._name_edit.text().strip()
        desc   = self._desc_edit.text().strip()
        prompt = self._prompt_edit.toPlainText().strip()
        key    = self._key_edit.text().strip()
        role   = self._role_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "Missing Name",
                                "Please enter a display name for the agent.")
            return

        if key:
            # Internet Search Agent
            self._result = {
                "type":         "internet_search",
                "display_name": name,
                "description":  desc or f"Internet search agent: {name}",
                "api_key":      key,
                "role":         role or "AI Research Assistant",
                "prompt":       prompt,
            }
        else:
            # Local Ollama agent
            if not prompt:
                # Auto-generate a minimal prompt from the name so it still works
                prompt = (
                    f"You are a specialised AI assistant named {name}. "
                    f"Your job is to help the user with {desc or 'their request'}. "
                    "Be concise, accurate, and helpful."
                )
            self._result = {
                "type":         "custom",
                "display_name": name,
                "description":  desc or f"Custom agent: {name}",
                "prompt":       prompt,
                "role":         role,
            }

        self.accept()

    def get_result(self) -> dict | None:
        return self._result


# ---------------------------------------------------------------------------
# Run Agent Dialog
#
# CHANGE: Now detects the agent type.
#   • internet_search agents → shows Search Query + Task fields.
#   • custom (Ollama) agents → shows the standard free-text prompt field.
# ---------------------------------------------------------------------------

class RunAgentDialog(QDialog):
    """
    Asks the user for input before running an agent.

    For Internet Search Agents: prompts for Search Query + Task.
    For Custom Ollama Agents:   prompts for a free-text request.
    """

    def __init__(self, agent: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Run — {agent.get('display_name', agent['name'])}")
        self.setMinimumWidth(480)
        self.setMinimumHeight(340)
        self.setStyleSheet("QDialog { background: #0d1526; } QLabel { color: #c8d6ef; }")
        self._result = None
        self._is_internet = (agent.get("agent_type") == "internet_search")
        self._build(agent)

    def _build(self, agent: dict):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        title = TitleLabel(f"{agent.get('icon','🤖')}  {agent.get('display_name', agent['name'])}")
        layout.addWidget(title)

        sub = CaptionLabel(agent.get("description", ""))
        sub.setStyleSheet("color: #33b5e5;")
        layout.addWidget(sub)

        if self._is_internet:
            # ── Internet Search Agent ─────────────────────────────────────
            badge = CaptionLabel("🌐  Internet Search Agent — powered by DuckDuckGo + GPT-4o")
            badge.setStyleSheet(
                "color: #bb86fc; background: #1a1035; border-radius: 4px;"
                "padding: 4px 8px;"
            )
            layout.addWidget(badge)

            layout.addWidget(StrongBodyLabel("Search Query  (what to look up on the internet)"))
            self._search_edit = LineEdit()
            self._search_edit.setPlaceholderText("e.g.  latest Python 3.13 features")
            layout.addWidget(self._search_edit)

            layout.addWidget(StrongBodyLabel("Task  (what the agent should do with the results)"))
            self._task_edit = TextEdit()
            self._task_edit.setPlaceholderText(
                "e.g.  Summarise the top 5 new features in Python 3.13 "
                "and give a code example for each one."
            )
            self._task_edit.setMinimumHeight(100)
            layout.addWidget(self._task_edit)

        else:
            # ── Custom Ollama Agent ───────────────────────────────────────
            layout.addWidget(StrongBodyLabel("What would you like the agent to do?"))
            self._input_edit = TextEdit()
            self._input_edit.setPlaceholderText("Type your request here…")
            self._input_edit.setMinimumHeight(110)
            layout.addWidget(self._input_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = PushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        run_btn = PrimaryPushButton(FIF.PLAY, "Run Agent")
        run_btn.clicked.connect(self._on_run)
        btn_row.addWidget(run_btn)
        layout.addLayout(btn_row)

    def _on_run(self):
        if self._is_internet:
            search = self._search_edit.text().strip()
            task   = self._task_edit.toPlainText().strip()
            if not search:
                QMessageBox.warning(self, "Missing Search Query",
                                    "Please enter a search query.")
                return
            if not task:
                QMessageBox.warning(self, "Missing Task",
                                    "Please describe the task for the agent.")
                return
            self._result = {"user_input": "", "search": search, "task": task}
        else:
            text = self._input_edit.toPlainText().strip()
            if not text:
                QMessageBox.warning(self, "Empty Input",
                                    "Please enter a prompt for the agent.")
                return
            self._result = {"user_input": text, "search": "", "task": ""}

        self.accept()

    def get_result(self) -> dict | None:
        """Returns {"user_input": str, "search": str, "task": str} or None."""
        return self._result


# ---------------------------------------------------------------------------
# Section card helper
# ---------------------------------------------------------------------------

def _make_section(title: str) -> tuple[CardWidget, QVBoxLayout]:
    card = CardWidget()
    card.setBorderRadius(10)
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(0, 10, 0, 10)
    card_layout.setSpacing(0)

    heading = StrongBodyLabel(f"  {title}")
    heading.setStyleSheet("color: #33b5e5; padding: 4px 12px 8px 12px;")
    card_layout.addWidget(heading)

    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet("color: #1a2236;")
    card_layout.addWidget(line)

    return card, card_layout


# ---------------------------------------------------------------------------
# Background worker for running a custom agent (non-blocking)
# CHANGE: now accepts search and task; passes them as CLI args to file agents.
# ---------------------------------------------------------------------------

class RunAgentThread(QThread):
    finished = Signal(str, dict)   # agent_name, result

    def __init__(self, name: str, user_input: str,
                 search: str = "", task: str = ""):
        super().__init__()
        self._name       = name
        self._input      = user_input
        self._search     = search
        self._task       = task

    def run(self):
        agent = agent_registry.get_agent(self._name)
        if not agent:
            self.finished.emit(
                self._name,
                {"success": False, "message": "Agent not found."}
            )
            return

        file_path = agent.get("file_path", "")
        if file_path:
            # Build extra CLI args for internet search agents
            extra_args: list[str] = []
            if self._search:
                extra_args.extend(["--search", self._search])
            if self._task:
                extra_args.extend(["--task", self._task])
            result = agent_registry.run_agent_file(self._name,
                                                    extra_args=extra_args)
        else:
            # Fallback: send the prompt to Ollama (LLM-only agents)
            from config import OLLAMA_URL, RESPONDER_MODEL
            result = agent_registry.run_agent(
                self._name,
                self._input,
                ollama_url=OLLAMA_URL,
                model=RESPONDER_MODEL,
            )
        self.finished.emit(self._name, result)


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------

class AgentsTab(QWidget):
    """
    Active Agents page — shows real-time status of every AI model,
    service, function agent, and manager running inside Plia.
    Also shows and manages user-created Custom Agents.
    """

    # Emitted when a custom agent produces output (so chat tab can show it)
    agent_output_ready = Signal(str, str)  # agent_display_name, response_text

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("agentsView")
        self._rows: dict[str, AgentRow] = {}
        self._thread: AgentStatusThread | None = None
        self._run_threads: list[RunAgentThread] = []
        self._custom_card: CardWidget | None = None
        self._custom_layout: QVBoxLayout | None = None
        self._setup_ui()
        self.refresh()

        # React to registry changes (agent created/deleted from chat)
        agent_registry.agents_changed.connect(self._rebuild_custom_section)

    # ── Layout ────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 30, 30, 30)
        root.setSpacing(20)

        # ── Header ──────────────────────────────────────────────────────
        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title = TitleLabel("Active Agents", self)
        subtitle = BodyLabel("Live status of every AI model and service in Plia.", self)
        subtitle.setStyleSheet("color: #8a8a8a;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col)
        header.addStretch()

        # Create Agent button
        self._create_btn = PrimaryPushButton(FIF.ADD, "Create Agent")
        self._create_btn.clicked.connect(self._on_create_agent)
        header.addWidget(self._create_btn)

        self._refresh_btn = PushButton(FIF.SYNC, "Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self._refresh_btn)

        root.addLayout(header)

        # ── Scroll area ──────────────────────────────────────────────────
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.viewport().setStyleSheet("background: transparent;")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self._content = QVBoxLayout(container)
        self._content.setSpacing(14)
        self._content.setContentsMargins(0, 0, 0, 20)
        self._content.setAlignment(Qt.AlignTop)

        # ── Section 1: AI Models ─────────────────────────────────────────
        card1, lay1 = _make_section("AI Models")
        self._add_row(lay1, "router", "Function Gemma Router", "Fine-tuned Gemma — routes all queries to functions")
        self._add_row(lay1, "llm",    "Responder LLM",         f"{RESPONDER_MODEL} via Ollama — generates replies")
        self._content.addWidget(card1)

        # ── Section 2: Core Services ─────────────────────────────────────
        card2, lay2 = _make_section("Core Services")
        self._add_row(lay2, "voice_assistant", "Voice Assistant", "Wake-word → STT → Router → LLM → TTS pipeline")
        self._add_row(lay2, "stt", "STT", "RealTimeSTT — speech to text (Whisper-base)")
        self._add_row(lay2, "tts", "TTS", "Piper — Northern English Male voice synthesis")
        self._content.addWidget(card2)

        # ── Section 3: Function Agents ───────────────────────────────────
        card3, lay3 = _make_section("Function Agents  (routed by Gemma)")
        self._add_row(lay3, "kasa_devices",    "Smart Lights",    "control_light — Kasa TP-Link smart home control")
        self._add_row(lay3, "task_manager",    "Task Manager",    "add_task — to-do list management")
        self._add_row(lay3, "calendar_manager","Calendar Manager","create_calendar_event — event creation")
        self._add_row(lay3, "calendar_sync",   "Calendar Sync",   "Google / Outlook event synchronisation")
        self._add_row(lay3, "web_search",      "Web Search",      "web_search — DuckDuckGo live search")
        self._add_row(lay3, "weather_manager", "Weather",         "get_system_info — current conditions")
        self._add_row(lay3, "news_manager",    "News",            "briefing — ABC Australia RSS feeds")
        self._add_row(lay3, "desktop_agent",   "Desktop Agent",   "control_desktop — VLM screenshot + mouse/keyboard control")
        self._content.addWidget(card3)

        # ── Section 4: Custom Agents (dynamic) ──────────────────────────
        self._build_custom_section()

        scroll.setWidget(container)
        root.addWidget(scroll)

    def _add_row(self, layout: QVBoxLayout, key: str, label: str, description: str):
        row = AgentRow(label, description)
        self._rows[key] = row
        layout.addWidget(row)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #0d1526; margin: 0 12px;")
        layout.addWidget(sep)

    # ── Custom Agents Section ─────────────────────────────────────────────

    def _build_custom_section(self):
        """Build or rebuild the Custom Agents card."""
        agents = agent_registry.all_agents()

        if self._custom_card is not None:
            self._content.removeWidget(self._custom_card)
            self._custom_card.deleteLater()
            self._custom_card = None

        count   = len(agents)
        heading = f"Custom Agents  ({count} created)" if count else "Custom Agents"
        card, lay = _make_section(heading)
        self._custom_card   = card
        self._custom_layout = lay

        if not agents:
            empty_lbl = CaptionLabel(
                "  No custom agents yet.  Click Create Agent above, or ask Plia in chat:\n"
                "  create an agent that summarises emails"
            )
            empty_lbl.setStyleSheet("color: #555e70; padding: 12px 12px 8px 12px;")
            empty_lbl.setWordWrap(True)
            lay.addWidget(empty_lbl)
        else:
            for agent in agents:
                row = CustomAgentRow(agent)
                row.run_requested.connect(self._on_run_agent)
                row.delete_requested.connect(self._on_delete_agent)
                lay.addWidget(row)
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setStyleSheet("color: #0d1526; margin: 0 12px;")
                lay.addWidget(sep)

        self._content.addWidget(card)

    def _rebuild_custom_section(self):
        """Slot connected to agent_registry.agents_changed."""
        self._build_custom_section()

    # ── Create Agent ──────────────────────────────────────────────────────

    def _on_create_agent(self, prefill: dict = None):
        """Open the unified Create Agent dialog."""
        dlg = CreateAgentDialog(prefill=prefill or {}, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        data = dlg.get_result()
        if not data:
            return

        if data.get("type") == "internet_search":
            # ── Write .py file then register with file_path ───────────────
            try:
                agent_path = _write_internet_agent(
                    display_name=data["display_name"],
                    api_key=data["api_key"],
                    role=data["role"],
                    # Search query and task left empty — provided at run-time
                    search_topic="",
                    task="",
                )
            except Exception as exc:
                QMessageBox.critical(
                    self, "File Write Error",
                    f"Could not save agent file:\n{exc}"
                )
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

        else:
            # ── Custom / Ollama agent ─────────────────────────────────────
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

    def create_agent_from_chat(self, prefill: dict):
        """
        Called by the chat handler when Plia detects a "create an agent" intent.
        Opens the dialog pre-filled with AI-parsed values so user can confirm.
        """
        self._on_create_agent(prefill=prefill)

    # ── Run Agent ─────────────────────────────────────────────────────────

    def _on_run_agent(self, name: str):
        agent = agent_registry.get_agent(name)
        if not agent:
            return

        dlg = RunAgentDialog(agent, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        result_data = dlg.get_result()
        if not result_data:
            return

        user_input = result_data.get("user_input", "")
        search     = result_data.get("search", "")
        task       = result_data.get("task", "")

        InfoBar.info(
            title="Running Agent…",
            content=f"'{agent['display_name']}' is working on your request.",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=2500,
        )

        t = RunAgentThread(name, user_input, search=search, task=task)
        t.finished.connect(self._on_agent_run_done)
        t.finished.connect(
            lambda n, r: self._run_threads.remove(t)
            if t in self._run_threads else None
        )
        self._run_threads.append(t)
        t.start()

    def _on_agent_run_done(self, name: str, result: dict):
        agent = agent_registry.get_agent(name)
        display = agent["display_name"] if agent else name

        if result["success"]:
            self.agent_output_ready.emit(display, result["message"])
            InfoBar.success(
                title=f"{display} — Launched" if agent and agent.get("file_path") else f"{display} — Done",
                content=result["message"][:120] + ("…" if len(result["message"]) > 120 else ""),
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=6000,
            )
        else:
            InfoBar.error(
                title=f"{display} — Error",
                content=result["message"][:120],
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=6000,
            )

        self._build_custom_section()

    # ── Delete Agent ──────────────────────────────────────────────────────

    def _on_delete_agent(self, name: str):
        agent = agent_registry.get_agent(name)
        if not agent:
            return
        reply = QMessageBox.question(
            self, "Delete Agent",
            f"Delete agent '{agent['display_name']}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            agent_registry.delete_agent(name)
            InfoBar.warning(
                title="Agent Deleted",
                content=f"'{agent['display_name']}' has been removed.",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000,
            )

    # ── Status refresh logic ───────────────────────────────────────────────

    def refresh(self):
        if self._thread and self._thread.isRunning():
            return
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("Checking…")
        for row in self._rows.values():
            row.update_status("loading", "Checking…")

        self._thread = AgentStatusThread()
        self._thread.finished.connect(self._apply_statuses)
        self._thread.start()

    def _apply_statuses(self, statuses: dict):
        for key, row in self._rows.items():
            if key in statuses:
                state, detail = statuses[key]
                row.update_status(state, detail)
            else:
                row.update_status("disabled", "No data")

        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("Refresh")
