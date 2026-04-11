"""
Active Agents tab — shows the live status of every AI model,
core service, function agent, and backend manager in Plia.
"""

import os
import requests
import threading

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor

from qfluentwidgets import (
    TitleLabel, BodyLabel, StrongBodyLabel, CaptionLabel,
    CardWidget, PushButton, FluentIcon as FIF,
    ScrollArea, SubtitleLabel
)

from config import OLLAMA_URL, LOCAL_ROUTER_PATH, VOICE_ASSISTANT_ENABLED, RESPONDER_MODEL


# ---------------------------------------------------------------------------
# Status colours (Aura theme)
# ---------------------------------------------------------------------------
STATUS_COLOURS = {
    "active":   "#4caf50",   # green
    "idle":     "#33b5e5",   # cyan
    "offline":  "#ef5350",   # red
    "disabled": "#555e70",   # muted grey
    "loading":  "#ffb300",   # amber
}


def _dot(colour: str) -> str:
    """Unicode bullet coloured via rich-text span."""
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

        # ── VLM Browser Agent (qwen3-vl) ─────────────────────────────────
        if not ollama_ok:
            statuses["vlm"] = ("offline", "Ollama not reachable")
        else:
            vlm_loaded = any("qwen" in m.lower() and "vl" in m.lower() for m in running_models)
            statuses["vlm"] = ("active", "In VRAM") if vlm_loaded else ("idle", "Available, not loaded")

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
        except Exception as e:
            for key in ("task_manager", "calendar_manager", "kasa_manager",
                        "weather_manager", "news_manager"):
                statuses[key] = ("offline", "Executor not reachable")

        # ── Desktop Agent availability ───────────────────────────────────
        try:
            import mss          # noqa: F401
            import pyautogui    # noqa: F401
            from core.agent.desktop_agent import DesktopAgent  # noqa: F401
            statuses["desktop_agent"] = ("idle", "Ready — mss + pyautogui installed")
        except ImportError as e:
            statuses["desktop_agent"] = ("offline", f"Missing dependency: {e}")

        # ── Web Search availability ──────────────────────────────────────
        try:
            from duckduckgo_search import DDGS
            statuses["web_search"] = ("idle", "DuckDuckGo ready")
        except ImportError:
            statuses["web_search"] = ("offline", "duckduckgo-search not installed")

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
        self._dot_label.setStyleSheet(
            f"color: {colour}; font-size: 14px;"
        )
        self._status_lbl.setText(detail)
        self._status_lbl.setStyleSheet(f"color: {colour};")


# ---------------------------------------------------------------------------
# Section card (groups related rows)
# ---------------------------------------------------------------------------

def _make_section(title: str) -> tuple[CardWidget, QVBoxLayout]:
    card = CardWidget()
    card.setBorderRadius(10)
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(0, 10, 0, 10)
    card_layout.setSpacing(0)

    # Section heading
    heading = StrongBodyLabel(f"  {title}")
    heading.setStyleSheet("color: #33b5e5; padding: 4px 12px 8px 12px;")
    card_layout.addWidget(heading)

    # Divider
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet("color: #1a2236;")
    card_layout.addWidget(line)

    return card, card_layout


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------

class AgentsTab(QWidget):
    """
    Active Agents page — shows real-time status of every AI model,
    service, function agent, and manager running inside Plia.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("agentsView")
        self._rows: dict[str, AgentRow] = {}
        self._thread: AgentStatusThread | None = None
        self._setup_ui()
        # First poll immediately
        self.refresh()
        # Auto-refresh every 15 seconds
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(15_000)

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
        self._add_row(lay1, "router",  "Function Gemma Router", "Fine-tuned Gemma — routes all queries to functions")
        self._add_row(lay1, "llm",     "Responder LLM",         f"{RESPONDER_MODEL} via Ollama — generates replies")
        self._add_row(lay1, "vlm",     "VLM Browser Agent",     "qwen3-vl:4b — vision model for web browsing")
        self._content.addWidget(card1)

        # ── Section 2: Core Services ─────────────────────────────────────
        card2, lay2 = _make_section("Core Services")
        self._add_row(lay2, "voice_assistant", "Voice Assistant", "Wake-word → STT → Router → LLM → TTS pipeline")
        self._add_row(lay2, "stt",             "STT",             "RealTimeSTT — speech to text (Whisper-base)")
        self._add_row(lay2, "tts",             "TTS",             "Piper — Northern English Male voice synthesis")
        self._content.addWidget(card2)

        # ── Section 3: Function Agents ───────────────────────────────────
        card3, lay3 = _make_section("Function Agents  (routed by Gemma)")
        self._add_row(lay3, "kasa_devices", "Smart Lights",        "control_light — Kasa TP-Link smart home control")
        self._add_row(lay3, "task_manager", "Task Manager",        "add_task — to-do list management")
        self._add_row(lay3, "calendar_manager","Calendar Manager", "create_calendar_event — event creation")
        self._add_row(lay3, "calendar_sync","Calendar Sync",       "Google / Outlook event synchronisation")
        self._add_row(lay3, "web_search",   "Web Search",          "web_search — DuckDuckGo live search")
        self._add_row(lay3, "weather_manager","Weather",           "get_system_info — current conditions")
        self._add_row(lay3, "news_manager",    "News",             "briefing — ABC Australia RSS feeds")
        self._add_row(lay3, "desktop_agent",   "Desktop Agent",    "control_desktop — VLM screenshot + mouse/keyboard control")
        self._content.addWidget(card3)

        scroll.setWidget(container)
        root.addWidget(scroll)

    def _add_row(self, layout: QVBoxLayout, key: str, label: str, description: str):
        row = AgentRow(label, description)
        self._rows[key] = row
        layout.addWidget(row)
        # thin separator between rows
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #0d1526; margin: 0 12px;")
        layout.addWidget(sep)

    # ── Refresh logic ─────────────────────────────────────────────────────

    def refresh(self):
        if self._thread and self._thread.isRunning():
            return  # Already polling
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("Checking…")
        # Mark all rows as loading
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
