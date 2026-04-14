# gui/tabs/agents.py
# ─────────────────────────────────────────────────────────────────────────────
#  Plia — Custom Agents Tab
#
#  Changes in this version:
#  1. Unified Create Agent dialog — Internet Search is an optional checkbox,
#     not a separate tab. All fields are optional.
#  2. Search Query and Task are no longer collected at creation time.
#     They are asked in a RunAgentDialog when the user clicks Run.
#  3. Agent list buttons (Run / Edit / Delete) use QSizePolicy.Expanding,
#     setMinimumWidth(), and icon+text so they never get clipped regardless
#     of window width.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations
import json
import uuid
from pathlib import Path
from typing import Optional

from PySide6.QtCore    import Qt, Signal, QThread, QObject
from PySide6.QtGui     import QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QSizePolicy, QSpacerItem, QDialog,
    QDialogButtonBox, QApplication,
)

from qfluentwidgets import (
    FluentIcon as FIF,
    PushButton,
    PrimaryPushButton,
    TransparentPushButton,
    LineEdit,
    TextEdit,
    BodyLabel,
    SubtitleLabel,
    StrongBodyLabel,
    CaptionLabel,
    CheckBox,
    CardWidget,
    SmoothScrollArea,
    InfoBar,
    InfoBarPosition,
    MessageBoxBase,
    setTheme,
    Theme,
)

# ── Colour palette (matches Plia Aura theme) ─────────────────────────────────
CYAN    = "#00d4d4"
BG_CARD = "#1e2233"
BG_DARK = "#141726"
TEXT    = "#e0e4f0"
MUTED   = "#7b82a0"

# ── Agent data store path ────────────────────────────────────────────────────
_STORE_PATH = Path.home() / ".plia_ai" / "custom_agents.json"


# ─────────────────────────────────────────────────────────────────────────────
#  Lightweight JSON-backed agent registry
# ─────────────────────────────────────────────────────────────────────────────
class _AgentStore:
    """Thread-safe JSON store for custom agent configs."""

    def __init__(self) -> None:
        _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not _STORE_PATH.exists():
            _STORE_PATH.write_text("[]", encoding="utf-8")

    def load(self) -> list[dict]:
        try:
            return json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

    def save(self, agents: list[dict]) -> None:
        _STORE_PATH.write_text(
            json.dumps(agents, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def add(self, agent: dict) -> None:
        agents = self.load()
        agents.append(agent)
        self.save(agents)

    def update(self, agent_id: str, agent: dict) -> None:
        agents = self.load()
        for i, a in enumerate(agents):
            if a.get("id") == agent_id:
                agents[i] = agent
                break
        self.save(agents)

    def delete(self, agent_id: str) -> None:
        agents = [a for a in self.load() if a.get("id") != agent_id]
        self.save(agents)

    def increment_runs(self, agent_id: str) -> int:
        agents = self.load()
        count = 0
        for a in agents:
            if a.get("id") == agent_id:
                a["run_count"] = a.get("run_count", 0) + 1
                count = a["run_count"]
                break
        self.save(agents)
        return count


_store = _AgentStore()


# ─────────────────────────────────────────────────────────────────────────────
#  Agent runner (QThread worker)
# ─────────────────────────────────────────────────────────────────────────────
class _AgentWorker(QObject):
    """Runs the agent in a background thread, emits result when done."""
    finished = Signal(str)   # result text
    error    = Signal(str)   # error message

    def __init__(self, agent: dict, search_query: str, task: str) -> None:
        super().__init__()
        self._agent        = agent
        self._search_query = search_query
        self._task         = task

    def run(self) -> None:
        try:
            # Try to use the project's agent_builder if available;
            # fall back to a direct Ollama call otherwise.
            try:
                from core.agent_builder import run_custom_agent  # type: ignore
                result = run_custom_agent(
                    self._agent,
                    search_query=self._search_query,
                    task=self._task,
                )
            except ImportError:
                # Minimal fallback: call Ollama directly
                import requests  # type: ignore
                system_prompt = self._agent.get("system_prompt", "You are a helpful assistant.")
                user_content  = self._task or self._search_query or "Hello"
                if self._search_query and self._task:
                    user_content = (
                        f"Search query: {self._search_query}\n\nTask: {self._task}"
                    )
                payload = {
                    "model"   : "llama3",
                    "prompt"  : user_content,
                    "system"  : system_prompt,
                    "stream"  : False,
                }
                resp = requests.post(
                    "http://localhost:11434/api/generate",
                    json=payload,
                    timeout=120,
                )
                resp.raise_for_status()
                result = resp.json().get("response", "(no response)")
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


# ─────────────────────────────────────────────────────────────────────────────
#  Create / Edit Agent Dialog  (unified — all fields optional)
# ─────────────────────────────────────────────────────────────────────────────
class CreateAgentDialog(QDialog):
    """
    Unified Create / Edit Agent dialog.
    Internet Search is an optional checkbox — no separate tab.
    All fields are optional so users can create minimal agents quickly.
    """

    def __init__(self, parent: Optional[QWidget] = None,
                 agent: Optional[dict] = None) -> None:
        super().__init__(parent)
        self._editing = agent is not None
        self._agent   = agent or {}
        self._build_ui()
        if self._editing:
            self._populate(agent)

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        title = "Edit Agent" if self._editing else "Create New Agent"
        self.setWindowTitle(title)
        self.setMinimumWidth(540)
        self.setMinimumHeight(480)
        self.setStyleSheet(f"""
            QDialog {{
                background: {BG_DARK};
                color: {TEXT};
                border-radius: 12px;
            }}
            QLabel {{
                color: {TEXT};
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        # ── Title row ─────────────────────────────────────────────────────────
        title_lbl = QLabel(
            "✏️  Edit Agent" if self._editing else "🤖  Create Agent"
        )
        title_lbl.setStyleSheet(
            f"color: {TEXT}; font-size: 20px; font-weight: 700;"
        )
        root.addWidget(title_lbl)

        # ── Optional notice ───────────────────────────────────────────────────
        notice = CaptionLabel("All fields are optional — fill in what you need.")
        notice.setStyleSheet(f"color: {MUTED};")
        root.addWidget(notice)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"border: 1px solid #2a2f44;")
        root.addWidget(sep)

        # ── Display Name ──────────────────────────────────────────────────────
        root.addWidget(self._field_label("Display Name"))
        self.name_edit = LineEdit()
        self.name_edit.setPlaceholderText("e.g.  Email Summariser")
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.setFixedHeight(40)
        root.addWidget(self.name_edit)

        # ── Short Description ─────────────────────────────────────────────────
        root.addWidget(self._field_label("Short Description"))
        self.desc_edit = LineEdit()
        self.desc_edit.setPlaceholderText("e.g.  Summarises emails into bullet points")
        self.desc_edit.setClearButtonEnabled(True)
        self.desc_edit.setFixedHeight(40)
        root.addWidget(self.desc_edit)

        # ── System Prompt ─────────────────────────────────────────────────────
        root.addWidget(self._field_label("System Prompt"))
        self.prompt_edit = TextEdit()
        self.prompt_edit.setPlaceholderText(
            "You are a specialised assistant. Your job is to…"
        )
        self.prompt_edit.setMinimumHeight(120)
        self.prompt_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self.prompt_edit)

        # ── Internet Search checkbox ───────────────────────────────────────────
        self.web_search_cb = CheckBox("Enable Internet Search")
        self.web_search_cb.setStyleSheet(f"color: {TEXT};")
        self.web_search_cb.setToolTip(
            "When checked, Plia will perform a live web search before running this agent."
        )
        root.addWidget(self.web_search_cb)

        root.addStretch(1)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        cancel_btn = PushButton("Cancel")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        btn_row.addStretch(1)

        ok_text   = "💾  Save Agent" if self._editing else "🤖  Create Agent"
        self.ok_btn = PrimaryPushButton(ok_text)
        self.ok_btn.setMinimumWidth(140)
        self.ok_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(self.ok_btn)

        root.addLayout(btn_row)

    @staticmethod
    def _field_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 13px;")
        return lbl

    # ── Populate for edit mode ────────────────────────────────────────────────
    def _populate(self, agent: dict) -> None:
        self.name_edit.setText(agent.get("display_name", ""))
        self.desc_edit.setText(agent.get("description", ""))
        self.prompt_edit.setPlainText(agent.get("system_prompt", ""))
        self.web_search_cb.setChecked(agent.get("enable_web_search", False))

    # ── Accept handler ────────────────────────────────────────────────────────
    def _on_accept(self) -> None:
        agent = {
            "id"               : self._agent.get("id", str(uuid.uuid4())),
            "display_name"     : self.name_edit.text().strip() or "Unnamed Agent",
            "description"      : self.desc_edit.text().strip(),
            "system_prompt"    : self.prompt_edit.toPlainText().strip(),
            "enable_web_search": self.web_search_cb.isChecked(),
            "run_count"        : self._agent.get("run_count", 0),
        }
        self._result_agent = agent
        self.accept()

    # ── Public accessor ───────────────────────────────────────────────────────
    def result_agent(self) -> dict:
        return getattr(self, "_result_agent", {})


# ─────────────────────────────────────────────────────────────────────────────
#  Run Agent Dialog — asks for Search Query + Task at runtime
# ─────────────────────────────────────────────────────────────────────────────
class RunAgentDialog(QDialog):
    """
    Shown when the user presses Run on an agent.
    Collects search query (optional) and task before execution.
    """

    def __init__(self, agent: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._agent = agent
        self._build_ui()

    def _build_ui(self) -> None:
        name = self._agent.get("display_name", "Agent")
        self.setWindowTitle(f"Run — {name}")
        self.setMinimumWidth(480)
        self.setStyleSheet(f"""
            QDialog {{
                background: {BG_DARK};
                color: {TEXT};
                border-radius: 10px;
            }}
            QLabel {{ color: {TEXT}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        # Header
        hdr = QLabel(f"▶  Run: <b>{name}</b>")
        hdr.setStyleSheet(f"color: {TEXT}; font-size: 17px;")
        root.addWidget(hdr)

        if self._agent.get("description"):
            desc = CaptionLabel(self._agent["description"])
            desc.setStyleSheet(f"color: {MUTED};")
            root.addWidget(desc)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: 1px solid #2a2f44;")
        root.addWidget(sep)

        # Search Query (only shown if web search is enabled)
        if self._agent.get("enable_web_search"):
            sq_lbl = QLabel("Search Query  <span style='color:#7b82a0'>(optional)</span>")
            sq_lbl.setStyleSheet(f"color: {TEXT}; font-weight: 600;")
            root.addWidget(sq_lbl)
            self.query_edit = LineEdit()
            self.query_edit.setPlaceholderText("e.g.  latest AI news 2026")
            self.query_edit.setClearButtonEnabled(True)
            self.query_edit.setFixedHeight(40)
            root.addWidget(self.query_edit)
        else:
            self.query_edit = None

        # Task
        task_lbl = QLabel("Task  <span style='color:#7b82a0'>(optional)</span>")
        task_lbl.setStyleSheet(f"color: {TEXT}; font-weight: 600;")
        root.addWidget(task_lbl)
        self.task_edit = TextEdit()
        self.task_edit.setPlaceholderText("Describe what you want the agent to do…")
        self.task_edit.setMinimumHeight(90)
        root.addWidget(self.task_edit)

        root.addStretch(1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        cancel_btn = PushButton("Cancel")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        btn_row.addStretch(1)

        run_btn = PrimaryPushButton("▶  Run Agent")
        run_btn.setMinimumWidth(130)
        run_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(run_btn)

        root.addLayout(btn_row)

    def _on_accept(self) -> None:
        self._result_query = (
            self.query_edit.text().strip() if self.query_edit else ""
        )
        self._result_task = self.task_edit.toPlainText().strip()
        self.accept()

    def result_query(self) -> str:
        return getattr(self, "_result_query", "")

    def result_task(self) -> str:
        return getattr(self, "_result_task", "")


# ─────────────────────────────────────────────────────────────────────────────
#  Agent Result Dialog — shows the output after agent run
# ─────────────────────────────────────────────────────────────────────────────
class AgentResultDialog(QDialog):
    """Displays the agent's response in a scrollable dialog."""

    def __init__(self, agent_name: str, result: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Result — {agent_name}")
        self.setMinimumWidth(520)
        self.setMinimumHeight(350)
        self.setStyleSheet(f"""
            QDialog {{ background: {BG_DARK}; color: {TEXT}; }}
            QLabel  {{ color: {TEXT}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        hdr = QLabel(f"🤖  {agent_name}")
        hdr.setStyleSheet(f"color: {TEXT}; font-size: 16px; font-weight: 700;")
        root.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        result_lbl = QLabel(result)
        result_lbl.setWordWrap(True)
        result_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        result_lbl.setStyleSheet(
            f"color: {TEXT}; background: {BG_CARD}; "
            "border-radius: 8px; padding: 14px;"
        )
        scroll.setWidget(result_lbl)
        root.addWidget(scroll)

        close_btn = PrimaryPushButton("Close")
        close_btn.setMinimumWidth(100)
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)


# ─────────────────────────────────────────────────────────────────────────────
#  Agent Card  — one card per agent in the list
# ─────────────────────────────────────────────────────────────────────────────
class AgentCard(QFrame):
    """
    Card widget for a single custom agent.
    Buttons use setSizePolicy(Expanding, Fixed) + setMinimumWidth() so they
    never clip their labels regardless of window width.
    """
    run_requested    = Signal(dict)
    edit_requested   = Signal(dict)
    delete_requested = Signal(str)   # emits agent id

    def __init__(self, agent: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._agent = agent
        self._thread: Optional[QThread]  = None
        self._worker: Optional[_AgentWorker] = None
        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        self.setObjectName("agentCard")
        self.setFixedHeight(72)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(12)

        # ── Icon ──────────────────────────────────────────────────────────────
        icon_lbl = QLabel("🤖")
        icon_lbl.setFixedWidth(36)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 22px;")
        row.addWidget(icon_lbl)

        # ── Info column ───────────────────────────────────────────────────────
        info = QVBoxLayout()
        info.setSpacing(2)

        self.name_lbl = QLabel(self._agent.get("display_name", "Agent"))
        self.name_lbl.setStyleSheet(
            f"color: {TEXT}; font-size: 14px; font-weight: 700;"
        )
        info.addWidget(self.name_lbl)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(10)

        desc = self._agent.get("description", "")
        if desc:
            desc_lbl = CaptionLabel(desc)
            desc_lbl.setStyleSheet(f"color: {CYAN};")
            meta_row.addWidget(desc_lbl)

        self.runs_lbl = CaptionLabel(f"Runs: {self._agent.get('run_count', 0)}")
        self.runs_lbl.setStyleSheet(f"color: {MUTED};")
        meta_row.addWidget(self.runs_lbl)

        if self._agent.get("enable_web_search"):
            ws_lbl = CaptionLabel("🌐 Web")
            ws_lbl.setStyleSheet(f"color: {CYAN};")
            meta_row.addWidget(ws_lbl)

        meta_row.addStretch(1)
        info.addLayout(meta_row)

        row.addLayout(info, stretch=1)

        # ── Buttons ───────────────────────────────────────────────────────────
        # Each button: text + icon, Preferred/Fixed size policy, min width.
        # This ensures they resize with the window but never clip.
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.run_btn = PrimaryPushButton("▶  Run")
        self.run_btn.setMinimumWidth(90)
        self.run_btn.setFixedHeight(36)
        self.run_btn.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.run_btn.setToolTip("Run this agent")
        self.run_btn.clicked.connect(self._on_run)
        btn_layout.addWidget(self.run_btn)

        edit_btn = PushButton("✏  Edit")
        edit_btn.setMinimumWidth(80)
        edit_btn.setFixedHeight(36)
        edit_btn.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        edit_btn.setToolTip("Edit this agent's configuration")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self._agent))
        btn_layout.addWidget(edit_btn)

        del_btn = PushButton("🗑  Delete")
        del_btn.setMinimumWidth(90)
        del_btn.setFixedHeight(36)
        del_btn.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        del_btn.setToolTip("Delete this agent")
        del_btn.setStyleSheet(
            "PushButton { color: #ff6b6b; }"
            "PushButton:hover { background: #3a1a1a; }"
        )
        del_btn.clicked.connect(
            lambda: self.delete_requested.emit(self._agent["id"])
        )
        btn_layout.addWidget(del_btn)

        row.addLayout(btn_layout)

    def _apply_style(self) -> None:
        self.setStyleSheet(f"""
            QFrame#agentCard {{
                background: {BG_CARD};
                border-radius: 10px;
                border: 1px solid #2a2f44;
            }}
            QFrame#agentCard:hover {{
                border: 1px solid {CYAN};
            }}
        """)

    # ── Update displayed run count ────────────────────────────────────────────
    def refresh_runs(self, count: int) -> None:
        self.runs_lbl.setText(f"Runs: {count}")

    # ── Update busy state ─────────────────────────────────────────────────────
    def set_busy(self, busy: bool) -> None:
        self.run_btn.setEnabled(not busy)
        self.run_btn.setText("⏳  Running…" if busy else "▶  Run")

    # ── Run clicked ───────────────────────────────────────────────────────────
    def _on_run(self) -> None:
        self.run_requested.emit(self._agent)

    # ── Update internal agent dict (after edit) ───────────────────────────────
    def update_agent(self, agent: dict) -> None:
        self._agent = agent
        self.name_lbl.setText(agent.get("display_name", "Agent"))
        self.runs_lbl.setText(f"Runs: {agent.get('run_count', 0)}")


# ─────────────────────────────────────────────────────────────────────────────
#  Active Agents Tab
# ─────────────────────────────────────────────────────────────────────────────
class ActiveAgentsTab(QWidget):
    """
    Main Agents tab — lists custom agents and provides Create / Run / Edit /
    Delete controls.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cards: dict[str, AgentCard] = {}   # agent_id → card
        self._threads: dict[str, QThread] = {}
        self._build_ui()
        self._load_agents()

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        self.setStyleSheet(f"background: {BG_DARK};")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # ── Header row ─────────────────────────────────────────────────────────
        header_row = QHBoxLayout()

        title = SubtitleLabel("Custom Agents")
        title.setStyleSheet(f"color: {TEXT}; font-size: 18px; font-weight: 700;")
        header_row.addWidget(title)

        self.count_lbl = CaptionLabel("(0 created)")
        self.count_lbl.setStyleSheet(f"color: {CYAN};")
        header_row.addWidget(self.count_lbl)

        header_row.addStretch(1)

        create_btn = PrimaryPushButton("＋  Create Agent")
        create_btn.setMinimumWidth(140)
        create_btn.setFixedHeight(38)
        create_btn.clicked.connect(self._on_create)
        header_row.addWidget(create_btn)

        root.addLayout(header_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: 1px solid #2a2f44;")
        root.addWidget(sep)

        # ── Scroll area for cards ──────────────────────────────────────────────
        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)
        self._list_layout.addStretch(1)

        scroll.setWidget(self._list_widget)
        root.addWidget(scroll, stretch=1)

        # ── Empty state label ──────────────────────────────────────────────────
        self._empty_lbl = QLabel(
            "No agents yet.\nClick  ＋ Create Agent  to build your first one."
        )
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(f"color: {MUTED}; font-size: 14px;")
        # Insert before the stretch
        self._list_layout.insertWidget(0, self._empty_lbl)

    # ── Load agents from disk ─────────────────────────────────────────────────
    def _load_agents(self) -> None:
        for agent in _store.load():
            self._add_card(agent)
        self._refresh_count()

    # ── Add a card to the list ────────────────────────────────────────────────
    def _add_card(self, agent: dict) -> None:
        card = AgentCard(agent, self)
        card.run_requested.connect(self._on_run_agent)
        card.edit_requested.connect(self._on_edit_agent)
        card.delete_requested.connect(self._on_delete_agent)
        # Insert before the trailing stretch
        self._list_layout.insertWidget(
            self._list_layout.count() - 1, card
        )
        self._cards[agent["id"]] = card
        self._empty_lbl.setVisible(False)

    # ── Refresh agent count label ─────────────────────────────────────────────
    def _refresh_count(self) -> None:
        n = len(self._cards)
        self.count_lbl.setText(f"({n} created)")
        self._empty_lbl.setVisible(n == 0)

    # ── Create new agent ──────────────────────────────────────────────────────
    def _on_create(self) -> None:
        dlg = CreateAgentDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            agent = dlg.result_agent()
            _store.add(agent)
            self._add_card(agent)
            self._refresh_count()
            InfoBar.success(
                title="Agent Created",
                content=f'"{agent["display_name"]}" is ready to run.',
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                duration=3000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )

    # ── Edit existing agent ───────────────────────────────────────────────────
    def _on_edit_agent(self, agent: dict) -> None:
        dlg = CreateAgentDialog(parent=self, agent=agent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.result_agent()
            _store.update(updated["id"], updated)
            card = self._cards.get(updated["id"])
            if card:
                card.update_agent(updated)
            InfoBar.success(
                title="Agent Updated",
                content=f'"{updated["display_name"]}" saved.',
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                duration=2500,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )

    # ── Delete agent ──────────────────────────────────────────────────────────
    def _on_delete_agent(self, agent_id: str) -> None:
        card = self._cards.pop(agent_id, None)
        if card:
            self._list_layout.removeWidget(card)
            card.deleteLater()
        _store.delete(agent_id)
        self._refresh_count()

    # ── Run agent: collect query + task, then execute ─────────────────────────
    def _on_run_agent(self, agent: dict) -> None:
        run_dlg = RunAgentDialog(agent, parent=self)
        if run_dlg.exec() != QDialog.DialogCode.Accepted:
            return

        search_query = run_dlg.result_query()
        task         = run_dlg.result_task()

        card = self._cards.get(agent["id"])
        if card:
            card.set_busy(True)

        # Run in background thread
        thread = QThread(self)
        worker = _AgentWorker(agent, search_query, task)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda result, a=agent, c=card, t=thread:
                self._on_agent_done(a, c, t, result)
        )
        worker.error.connect(
            lambda err, a=agent, c=card, t=thread:
                self._on_agent_error(a, c, t, err)
        )

        self._threads[agent["id"]] = thread
        thread.start()

    def _on_agent_done(
        self, agent: dict, card: Optional[AgentCard],
        thread: QThread, result: str
    ) -> None:
        thread.quit()
        thread.wait()
        self._threads.pop(agent["id"], None)

        new_count = _store.increment_runs(agent["id"])
        if card:
            card.set_busy(False)
            card.refresh_runs(new_count)

        AgentResultDialog(
            agent.get("display_name", "Agent"),
            result,
            parent=self,
        ).exec()

    def _on_agent_error(
        self, agent: dict, card: Optional[AgentCard],
        thread: QThread, error: str
    ) -> None:
        thread.quit()
        thread.wait()
        self._threads.pop(agent["id"], None)

        if card:
            card.set_busy(False)

        InfoBar.error(
            title="Agent Error",
            content=error[:200],
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            duration=5000,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self,
        )
