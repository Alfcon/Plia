import threading
import sys
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QSizePolicy, QLabel
from PySide6.QtCore import Qt, QSize, QThread
from PySide6.QtGui import QIcon

from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon as FIF,
    SplashScreen
)

from gui.handlers import ChatHandlers
from core.model_manager import unload_all_models
from core.voice_assistant import voice_assistant
from core.tts import tts
from config import VOICE_ASSISTANT_ENABLED, GREEN, RESET

from gui.styles import AURA_STYLESHEET 

from gui.tabs.dashboard import DashboardView
from gui.tabs.chat import ChatTab
from gui.tabs.planner import PlannerTab
from gui.tabs.settings import SettingsTab
from gui.tabs.briefing import BriefingView
from gui.tabs.agents import AgentsTab
from gui.tabs.agent_list import AgentListTab
from gui.tabs.model_browser import ModelBrowserTab
from gui.tabs.reading_files import ReadingFilesTab
from gui.components.system_monitor import SystemMonitor
from gui.components.weather_window import WeatherWindow
from gui.components.search_browser import SearchBrowserWindow
from core.llm import preload_models
from core.settings_store import settings as app_settings


class ModelPreloaderThread(QThread):
    """Background thread to preload models at startup."""
    def run(self):
        preload_models()


class LazyTab(QWidget):
    """Placeholder widget that loads the actual tab on demand."""
    def __init__(self, factory, object_name):
        super().__init__()
        self.setObjectName(object_name)
        self.factory = factory
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.actual_widget = None

    def initialize(self):
        if not self.actual_widget:
            self.actual_widget = self.factory()
            self.layout.addWidget(self.actual_widget)
            return self.actual_widget
        return self.actual_widget

    def get_widget(self):
        """Return the actual widget if it has been initialised, else None."""
        return self.actual_widget

class MainWindow(FluentWindow):
    """Main application window using Fluent Design."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Plia")
        self.setMinimumSize(1100, 750)
        self.resize(1200, 800)
        
        self.setStyleSheet(AURA_STYLESHEET)
        
        # Initialize handlers
        self.handlers = ChatHandlers(self)
        
        # Add system monitor to title bar
        self._init_system_monitor()
        
        # Initialize sub-interfaces pointers
        self.chat_tab = None
        self.planner_tab = None
        self.briefing_view = None
        self.agents_tab = None
        self.agent_list_tab = None
        self._weather_window = None  # Floating weather window
        self.search_browser = SearchBrowserWindow(self)  # Floating search results browser
        
        # Flag to prevent duplicate signal connections
        self._chat_signals_connected = False
        self._agent_list_signals_connected = False

        self._init_window()
        self._connect_signals()
        self._init_background()
        self._preload_models()
        self._init_voice_assistant()
        self._init_agent_runtime()

    def _init_agent_runtime(self):
        """Start the live-agent runtime: load persisted agents, arm the
        scheduler, and connect the ResultDispatcher to the UI."""
        try:
            from core.agent_runtime import get_runtime
            rt = get_runtime()
            rt.start()

            disp = rt.dispatcher
            disp.agent_history_appended.connect(self._on_agent_history_appended)
            disp.show_toast.connect(self._on_agent_toast)
            disp.dashboard_card_added.connect(self._on_agent_card)
            disp.comm_log_append.connect(self._on_agent_comm_log)
            disp.chat_message_append.connect(self._on_agent_chat_message)
            disp.file_saved.connect(self._on_agent_file_saved)
            # Tell the user (TTS + comm log) when the responder LLM is
            # auto-unloaded to free VRAM, so they understand the "not loaded"
            # state in the Active Agents tab.
            try:
                from core.model_persistence import events as _model_events
                _model_events.responder_unloaded.connect(
                    self._on_responder_unloaded
                )
            except Exception as e:
                print(f"[App] model_persistence signal connect failed: {e}")
            print("[App] ✓ Agent runtime started")
        except Exception as e:
            print(f"[App] ✗ Agent runtime failed to start: {e}")
            import traceback
            traceback.print_exc()

    def _on_agent_history_appended(self, role_id: str):
        if self.agents_tab is not None and hasattr(self.agents_tab, "refresh"):
            self.agents_tab.refresh()

    def _on_agent_toast(self, title: str, body: str, success: bool):
        try:
            from qfluentwidgets import InfoBar, InfoBarPosition
            fn = InfoBar.success if success else InfoBar.error
            fn(title=title, content=body, duration=4000,
               position=InfoBarPosition.TOP_RIGHT, parent=self)
        except Exception as e:
            print(f"[App] toast failed: {e}")

    def _on_agent_card(self, payload: dict):
        if getattr(self, "dashboard_view", None) is not None:
            self.dashboard_view.add_agent_card(payload)

    def _on_agent_comm_log(self, role_id: str, title: str, body: str):
        if getattr(self, "dashboard_view", None) is not None:
            self.dashboard_view.add_system_message(f"{title}\n{body}", tag="system")

    def _on_agent_chat_message(self, role_id: str, body: str):
        """Post an agent result to its OWN chat session (sidebar entry).

        Each live agent gets a dedicated session so reports don't pollute the
        user's active conversation and stay browsable in the chat history.
        A toast announces the new entry; the user clicks the sidebar to read it.
        """
        from core.history import history_manager

        # Lazy init the chat tab so the sidebar shows the new session.
        try:
            if self.chat_tab is None and getattr(self, "chat_lazy", None) is not None:
                real = self.chat_lazy.initialize()
                if real is not None:
                    self.chat_tab = real
                    if not self._chat_signals_connected:
                        self._connect_chat_signals()
        except Exception as exc:
            print(f"[App] chat tab init failed: {exc}")

        # Map role_id → session_id (per-agent session), created on first message.
        if not hasattr(self, "_agent_chat_sessions"):
            self._agent_chat_sessions = {}
        session_id = self._agent_chat_sessions.get(role_id)

        try:
            if session_id is None:
                # Title the session after the agent so it's easy to spot.
                rt_state = None
                try:
                    from core.agent_runtime import get_runtime
                    rt_state = get_runtime().store.get(role_id)
                except Exception:
                    pass
                title = (
                    f"🤖 {rt_state.display_name}"
                    if rt_state is not None else f"🤖 Agent {role_id}"
                )
                session_id = history_manager.create_session(title=title)
                self._agent_chat_sessions[role_id] = session_id

            history_manager.add_message(session_id, "assistant", body)

            # Refresh the chat sidebar so the new session appears immediately.
            if self.chat_tab is not None and hasattr(self.handlers, "refresh_sidebar"):
                self.handlers.refresh_sidebar()

            # Brief toast so the user knows where to look.
            try:
                from qfluentwidgets import InfoBar, InfoBarPosition
                title_short = (
                    rt_state.display_name if rt_state is not None else "Agent"
                )
                InfoBar.success(
                    title=f"💬 {title_short}",
                    content="Posted to its chat session — see the sidebar.",
                    duration=3000,
                    position=InfoBarPosition.TOP_RIGHT,
                    parent=self,
                )
            except Exception:
                pass
            return
        except Exception as exc:
            print(f"[App] per-agent chat session write failed: {exc}")

        # Last-resort fallback so the result isn't lost.
        if getattr(self, "dashboard_view", None) is not None:
            self.dashboard_view.add_system_message(body, tag="system")

    def _on_responder_unloaded(self, model_name: str, reason: str, elapsed: float):
        """Notify the user when the responder LLM is auto-unloaded to free VRAM.
        Posts to the Communication Log and speaks via TTS."""
        msg = (
            f"Responder model {model_name} unloaded after "
            f"{int(elapsed)}s idle to free VRAM. "
            "It will reload automatically on next use."
        ) if reason == "timeout" else (
            f"Responder model {model_name} unloaded ({reason})."
        )
        try:
            if getattr(self, "dashboard_view", None) is not None:
                self.dashboard_view.add_system_message(f"🧠 {msg}", tag="system")
        except Exception as exc:
            print(f"[App] comm-log append failed: {exc}")
        try:
            from core.tts import tts
            tts.queue_sentence(msg)
        except Exception as exc:
            print(f"[App] tts queue failed: {exc}")

    def _on_agent_file_saved(self, role_id: str, file_path: str):
        """Show a brief toast pointing at the file the agent wrote to."""
        try:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.success(
                title="Agent result saved",
                content=file_path,
                duration=4000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self,
            )
        except Exception as exc:
            print(f"[App] file-saved toast failed: {exc}")

    def _preload_models(self):
        """Start the background thread to preload models."""
        self.preloader_thread = ModelPreloaderThread()
        self.preloader_thread.start()
    
    def _init_voice_assistant(self):
        """Initialize and start voice assistant if enabled.

        Voice activation is controlled by two flags that must both be True:
          1. VOICE_ASSISTANT_ENABLED in config.py  (developer master switch)
          2. voice.auto_start in settings.json     (user preference, defaults to True)

        TTS is initialized in the same background thread so the Whisper model
        and the Piper TTS model are both fully loaded before the first greeting.
        """
        auto_start = app_settings.get("voice.auto_start", True)
        print(
            f"[App] Initializing voice assistant "
            f"(enabled={VOICE_ASSISTANT_ENABLED}, auto_start={auto_start})..."
        )

        if not VOICE_ASSISTANT_ENABLED:
            print(f"[App] Voice assistant disabled in config.py")
            return

        if not auto_start:
            print(f"[App] Voice auto-start disabled in settings — voice will not activate")
            return

        # ── Connect all VA signals to UI handlers ────────────────────────
        print(f"[App] Connecting voice assistant signals...")
        voice_assistant.wake_word_detected.connect(self._on_wake_word_detected)
        voice_assistant.speech_recognized.connect(self._on_speech_recognized)
        voice_assistant.processing_finished.connect(self._on_processing_finished)
        voice_assistant.timer_set.connect(self._on_voice_timer_set)
        voice_assistant.alarm_added.connect(self._on_voice_alarm_added)
        voice_assistant.calendar_updated.connect(self._on_voice_calendar_updated)
        voice_assistant.task_added.connect(self._on_voice_task_added)
        voice_assistant.weather_requested.connect(self._on_voice_weather_requested)
        voice_assistant.close_weather_requested.connect(self._on_voice_close_weather)
        voice_assistant.web_search_requested.connect(self._on_voice_web_search_requested)
        voice_assistant.close_search_requested.connect(self._on_voice_close_search)
        voice_assistant.search_nav_requested.connect(self._on_voice_search_nav)
        voice_assistant.search_open_requested.connect(self._on_voice_search_open)
        voice_assistant.search_maximise_requested.connect(self._on_voice_search_maximise)
        voice_assistant.search_help_minimise_requested.connect(self._on_voice_search_help_minimise)
        voice_assistant.desktop_task_started.connect(self._on_voice_desktop_started)
        voice_assistant.desktop_task_finished.connect(self._on_voice_desktop_finished)
        voice_assistant.refresh_agents_requested.connect(self._on_voice_refresh_agents)
        voice_assistant.help_requested.connect(self._on_voice_help_requested)
        voice_assistant.read_file_requested.connect(self.read_file_option)
        print(f"[App] ✓ Voice assistant signals connected")

        # ── Connect TTS speaking signals to UI handlers ─────────────────
        print(f"[App] Connecting TTS signals...")
        tts.signals.speaking_started.connect(self._on_tts_speaking_started)
        tts.signals.speaking_finished.connect(self._on_tts_speaking_finished)
        print(f"[App] ✓ TTS signals connected")

        # ── Load TTS + STT + start listening — all in one background thread
        def init_va():
            import time
            print(f"[App] Background thread: Initializing TTS...")
            # Initialise TTS first so the greeting can play as soon as STT is ready
            tts.toggle(True)
            print(f"[App] Background thread: ✓ TTS ready")

            print(f"[App] Background thread: Initializing voice assistant (STT/wake-word)...")
            if voice_assistant.initialize():
                print(f"[App] Background thread: ✓ Voice assistant initialized")
                voice_assistant.start()
                print(f"[App] Background thread: ✓ Voice assistant started — listening for wake word")

                # Post confirmation to the Dashboard Communication Log (main-thread safe)
                from PySide6.QtCore import QTimer
                wake_display = app_settings.get("voice.wake_word", "jarvis").capitalize()
                QTimer.singleShot(
                    0,
                    lambda ww=wake_display: self.dashboard_view.add_system_message(
                        f"Voice assistant started. Say '{ww}' to activate.", "plia"
                    ),
                )

                # Speak a startup greeting so the user knows voice is active
                if app_settings.get("voice.startup_greeting", True):
                    wake = app_settings.get("voice.wake_word", "jarvis")
                    time.sleep(1.5)   # brief pause so TTS worker settles
                    tts.queue_sentence(
                        f"Plia voice assistant is online. Say {wake} to activate."
                    )
            else:
                print(f"[App] Background thread: ✗ Failed to initialize voice assistant")

        threading.Thread(target=init_va, daemon=True, name="VA-Init").start()
    
    def _dashboard_voice_widget(self):
        """Return the embedded voice widget from the dashboard, or None."""
        return getattr(self.dashboard_view, "voice_widget", None)

    def _on_wake_word_detected(self):
        """Wake word detected — show pulsing Plia logo overlay."""
        print(f"{GREEN}[App] ✓ Wake word detected — showing Plia indicator{RESET}")
        if VOICE_ASSISTANT_ENABLED:
            self.system_monitor.show_listening()
            dw = self._dashboard_voice_widget()
            if dw:
                dw.show_listening()

    def _on_speech_recognized(self, text: str):
        """Speech received — switch to processing animation."""
        if VOICE_ASSISTANT_ENABLED:
            dw = self._dashboard_voice_widget()
            if dw:
                dw.show_processing()

    def _on_processing_finished(self):
        """AI finished generating — fallback safety for voice indicator.

        If the embedding voice widget is still in PROCESSING state (i.e. no
        TTS was queued, e.g. an error occurred), force it back to idle so
        the indicator doesn't get stuck.
        """
        if VOICE_ASSISTANT_ENABLED:
            dw = self._dashboard_voice_widget()
            if dw and getattr(dw, '_state', None) == dw.STATE_PROCESSING:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(2000, lambda: (
                    dw.show_idle(),
                    self.system_monitor.hide_listening(),
                ))

    def _on_tts_speaking_started(self):
        """TTS playback started — show speaking animation."""
        if VOICE_ASSISTANT_ENABLED:
            self.system_monitor.show_speaking()
            dw = self._dashboard_voice_widget()
            if dw:
                dw.show_speaking()

    def _on_tts_speaking_finished(self):
        """TTS playback finished — return to idle after a short delay."""
        if VOICE_ASSISTANT_ENABLED:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(500, lambda: self.system_monitor.hide_listening())
            dw = self._dashboard_voice_widget()
            if dw:
                QTimer.singleShot(500, lambda: dw.show_idle())

    def _on_voice_timer_set(self, seconds: int, label: str):
        """Handle timer set via voice - update GUI."""
        # Ensure planner tab is loaded
        if not self.planner_tab:
            # Try to initialize if lazy
            if hasattr(self, 'planner_lazy'):
                self.planner_tab = self.planner_lazy.initialize()
        
        if self.planner_tab and hasattr(self.planner_tab, 'timer_component'):
            self.planner_tab.timer_component.set_and_start(seconds, label)
            print(f"[App] Timer updated via voice: {seconds}s, {label}")
    
    def _on_voice_alarm_added(self):
        """Handle alarm added via voice - update GUI."""
        # Ensure planner tab is loaded
        if not self.planner_tab:
            if hasattr(self, 'planner_lazy'):
                self.planner_tab = self.planner_lazy.initialize()
        
        if self.planner_tab and hasattr(self.planner_tab, 'alarm_component'):
            self.planner_tab.alarm_component.reload()
            print(f"[App] Alarms refreshed via voice")
    
    def _on_voice_calendar_updated(self):
        """Handle calendar event added via voice - refresh calendar."""
        # Ensure planner tab is loaded
        if not self.planner_tab:
            if hasattr(self, 'planner_lazy'):
                self.planner_tab = self.planner_lazy.initialize()
        
        if self.planner_tab and hasattr(self.planner_tab, 'schedule_component'):
            self.planner_tab.schedule_component.refresh_events()
            print(f"[App] Calendar refreshed via voice")
    
    def _on_voice_task_added(self):
        """Handle task added via voice - refresh task list."""
        # Ensure planner tab is loaded
        if not self.planner_tab:
            if hasattr(self, 'planner_lazy'):
                self.planner_tab = self.planner_lazy.initialize()
        
        if self.planner_tab and hasattr(self.planner_tab, '_load_tasks'):
            self.planner_tab._load_tasks()
            print(f"[App] Tasks refreshed via voice")

    def _on_voice_weather_requested(self, data: dict):
        """Show the floating weather window with fresh data."""
        if self._weather_window is None:
            self._weather_window = WeatherWindow(self)
        self._weather_window.show_weather(data)

    def _on_voice_close_weather(self):
        """Hide the floating weather window."""
        if self._weather_window is not None:
            self._weather_window.close_weather()

    def _on_voice_web_search_requested(self, query: str, results: list):
        """Show the floating search browser with voice-triggered results."""
        if self.search_browser:
            self.search_browser.show_results(query, results)

    def _on_voice_close_search(self):
        """Hide the floating search browser (voice command)."""
        if self.search_browser:
            self.search_browser.close_browser()

    def _on_voice_search_nav(self, direction: str):
        """Next / previous page in the search browser (voice command)."""
        if self.search_browser and self.search_browser.isVisible():
            self.search_browser.on_search_nav(direction)

    def _on_voice_search_open(self, number: int):
        """Open a numbered search result in the browser (voice command)."""
        if self.search_browser and self.search_browser.isVisible():
            self.search_browser.open_result(number)

    def _on_voice_search_maximise(self):
        """
        Toggle the search browser between full-screen and its previous size.

        Voice phrases that reach this handler:
          'Jarvis, expand search window'
          'Jarvis, maximise search window'
          'Jarvis, search full screen'
          'Jarvis, restore search window'
        The window must be visible; if it is hidden the command is silently
        ignored (there is nothing meaningful to maximise).
        """
        if self.search_browser and self.search_browser.isVisible():
            self.search_browser.voice_maximise()

    def _on_voice_search_help_minimise(self):
        """
        Collapse the Search Help panel inside the search browser.

        Voice phrases that reach this handler:
          'Jarvis, hide search help'
          'Jarvis, minimise search help'
          'Jarvis, collapse search help'
        Works whether or not the search window is currently visible so the
        panel is pre-collapsed for the next time the window is shown.
        """
        if self.search_browser:
            self.search_browser.voice_collapse_help()

    def _init_window(self):
        # Dashboard is loaded immediately as it's the home screen
        self.dashboard_view = DashboardView()
        self.dashboard_view.setObjectName("dashboardInterface")
        self.dashboard_view.navigate_to.connect(self._navigate_to_tab)
        self.addSubInterface(self.dashboard_view, FIF.LAYOUT, "Dashboard")

        # Lazy load other tabs
        self.chat_lazy = LazyTab(ChatTab, "chatInterface")
        self.planner_lazy = LazyTab(PlannerTab, "plannerInterface")
        # Eager load briefing for startup fetch
        self.briefing_view = BriefingView()
        self.briefing_view.setObjectName("briefingInterface")

        self.agents_lazy = LazyTab(AgentsTab, "agentsInterface")
        self.agent_list_lazy = LazyTab(AgentListTab, "agentListInterface")
        self.model_browser_lazy = LazyTab(ModelBrowserTab, "modelBrowserInterface")
        self.reading_files_lazy = LazyTab(ReadingFilesTab, "readingFilesInterface")
        # Web Searches tab — receives output from agents that notify on the
        # "web_searches" channel. Persistent log under ~/.plia_ai/.
        from gui.tabs.web_searches import WebSearchesTab
        self.web_searches_lazy = LazyTab(WebSearchesTab, "webSearchesInterface")
        # MCP Servers tab — manage external Model Context Protocol servers
        # configured at ~/.plia/mcp.json.
        from gui.tabs.mcp_servers import MCPServersTab
        self.mcp_servers_lazy = LazyTab(MCPServersTab, "mcpServersInterface")
        # Help / Docs tab — renders docs/help/*.md.
        from gui.tabs.help import HelpTab
        self.help_lazy = LazyTab(HelpTab, "helpInterface")

        self.addSubInterface(self.chat_lazy, FIF.CHAT, "Chat")
        self.addSubInterface(self.planner_lazy, FIF.CALENDAR, "Planner")
        self.addSubInterface(self.briefing_view, FIF.DATE_TIME, "Briefing")
        self.addSubInterface(self.agents_lazy, FIF.ROBOT, "Active Agents")
        self.addSubInterface(self.agent_list_lazy, FIF.ROBOT, "Agent List")
        self.addSubInterface(self.web_searches_lazy, FIF.SEARCH, "Web Searches")
        self.addSubInterface(self.mcp_servers_lazy, FIF.CONNECT, "MCP Servers")
        self.addSubInterface(self.model_browser_lazy, FIF.MARKET, "Model Browser")
        self.addSubInterface(self.reading_files_lazy, FIF.FOLDER, "Reading Files")
        self.addSubInterface(self.help_lazy, FIF.HELP, "Help")
        
        # Settings at bottom
        self.settings_lazy = LazyTab(SettingsTab, "settingsInterface")
        self.addSubInterface(
            self.settings_lazy, FIF.SETTING, "Settings",
            NavigationItemPosition.BOTTOM
        )
        
    def _connect_signals(self):
        """Connect signals. Signals for lazy tabs are connected upon initialization."""
        self.stackedWidget.currentChanged.connect(self._on_tab_changed)

    def _connect_chat_signals(self):
        """Connect ChatTab signals (called when ChatTab is initialized)."""
        if not self.chat_tab or self._chat_signals_connected:
            return
        self._chat_signals_connected = True
        self.chat_tab.new_chat_requested.connect(self.handlers.clear_chat)
        self.chat_tab.send_message_requested.connect(self._on_send)
        self.chat_tab.stop_generation_requested.connect(self.handlers.stop_generation)
        self.chat_tab.tts_toggled.connect(self.handlers.toggle_tts)
        self.chat_tab.session_selected.connect(self._on_session_clicked)
        
        self.chat_tab.session_pin_requested.connect(self.handlers.pin_session)
        self.chat_tab.session_rename_requested.connect(self.handlers.rename_session)
        self.chat_tab.session_delete_requested.connect(self.handlers.delete_session)
        
        # Initial sidebar refresh
        self.chat_tab.refresh_sidebar()

    @staticmethod
    def _parse_read_command(text: str):
        """
        Return the 1-based file index if *text* matches a read/open command,
        otherwise return None.  Kept as a static so it can be called before
        the ReadingFilesTab is initialised.
        """
        import re as _re
        patterns = [
            r"read\s+option\s+(\d+)",
            r"read\s+file\s+(\d+)",
            r"open\s+option\s+(\d+)",
            r"open\s+file\s+(\d+)",
            r"^option\s+(\d+)$",
        ]
        lower = text.lower().strip()
        for pat in patterns:
            m = _re.search(pat, lower)
            if m:
                return int(m.group(1))
        return None

    def _on_send(self, text):
        """
        Forward send request to handlers, intercepting file-read commands.

        When a 'read option N' command is detected:
          1. Ensure the ReadingFilesTab is initialised.
          2. Switch to the Reading Files tab so the user sees the content.
          3. Call read_option_with_callback — it shows the file in the UI
             panel AND, once extraction finishes, calls inject_file_and_respond
             which injects the content into the LLM context and streams an
             acknowledgment/summary response back in the Chat tab.
        """
        n = self._parse_read_command(text)
        if n is not None:
            rft = self.reading_files_lazy.get_widget()
            if rft is None:
                rft = self.reading_files_lazy.initialize()
            self.switchTo(self.reading_files_lazy)
            rft.read_option_with_callback(
                n,
                lambda fname, content: self.handlers.inject_file_and_respond(
                    fname, content
                ),
            )
            return
        self.handlers.send_message(text)
        
    def _on_session_clicked(self, session_id):
        """Load session."""
        self.handlers.load_session(session_id)
    
    def _init_background(self):
        """Initialize app status + background schedulers."""
        self.set_status("Ready")

        # ── Morning digest scheduler (Priority 4) ─────────────────────────
        # Runs daily at settings.morning_digest.time (local time, HH:MM).
        self._morning_digest_last_run_date = None

        from PySide6.QtCore import QTimer
        import datetime

        self._digest_timer = QTimer(self)
        self._digest_timer.setInterval(30_000)  # check every 30s
        self._digest_timer.timeout.connect(self._check_morning_digest)
        self._digest_timer.start()

        # initial check shortly after UI is ready
        QTimer.singleShot(2_000, self._check_morning_digest)

    def _check_morning_digest(self) -> None:
        try:
            enabled = app_settings.get("morning_digest.enabled", True)
            if not enabled:
                return

            time_str = app_settings.get("morning_digest.time", "08:00")
            use_ai = app_settings.get("morning_digest.use_ai", True)
            speak = app_settings.get("morning_digest.speak", True)

            # Parse HH:MM
            try:
                hh_s, mm_s = (time_str or "08:00").split(":")
                target_h = int(hh_s)
                target_m = int(mm_s)
            except Exception:
                target_h, target_m = 8, 0

            now = datetime.datetime.now()
            today = now.date()

            if self._morning_digest_last_run_date == today:
                return

            # Run once the current time is past the target time.
            if (now.hour, now.minute) < (target_h, target_m):
                return

            # Mark immediately so we don't double-fire while loading
            self._morning_digest_last_run_date = today

            from core.news import news_manager

            self.set_status("Morning digest: fetching…")

            def _run_digest():
                digest_items = news_manager.get_briefing(use_ai=use_ai)
                # Keep it short for TTS/log.
                top = (digest_items or [])[:6]

                if top:
                    lines = []
                    for idx, item in enumerate(top, 1):
                        title = (item.get("title") or "").strip()
                        cat = (item.get("category") or "").strip()
                        src = (item.get("source") or "").strip()
                        if cat and src:
                            lines.append(f"{idx}. {title} ({cat} — {src})")
                        else:
                            lines.append(f"{idx}. {title}")
                    digest_text = "Morning digest: " + " ".join(lines)
                else:
                    digest_text = "Morning digest: no news items available right now."

                def _post_to_ui():
                    try:
                        if self.dashboard_view:
                            self.dashboard_view.add_system_message(digest_text, "plia")
                    except Exception:
                        pass
                    try:
                        if speak:
                            tts.queue_sentence(digest_text)
                    except Exception:
                        pass
                    try:
                        self.set_status("Ready")
                    except Exception:
                        pass

                from PySide6.QtCore import QTimer as _QTimer
                _QTimer.singleShot(0, _post_to_ui)

            threading.Thread(target=_run_digest, daemon=True, name="MorningDigest").start()

        except Exception:
            # Never break the UI loop; just fail quietly.
            try:
                self.set_status("Ready")
            except Exception:
                pass
            return
    
    def _init_system_monitor(self):
        """Add system monitor widget to the title bar. Also replaces title text with logo."""
        self.system_monitor = SystemMonitor()

        # Replace 'Plia' text with logo image
        self._replace_title_with_logo()

        # Get the title bar layout
        layout = self.titleBar.hBoxLayout

        # dynamic search for min button index to ensure we insert BEFORE the window controls
        min_btn_index = layout.indexOf(self.titleBar.minBtn)

        # Insert a stretch to push monitor toward center (after title/icon, before buttons)
        layout.insertStretch(min_btn_index, 1)
        # Insert the system monitor
        layout.insertWidget(min_btn_index + 1, self.system_monitor, 0, Qt.AlignmentFlag.AlignCenter)
        # Insert another stretch after monitor to balance centering
        layout.insertStretch(min_btn_index + 2, 1)

    def _replace_title_with_logo(self):
        """
        Hide the Plia title text and show the logo image in the title bar.
        Uses flexible sizing so the logo auto-adjusts when the window is resized
        instead of being clipped.
        """
        from PySide6.QtWidgets import QLabel, QSizePolicy as _QSP
        from PySide6.QtGui import QPixmap
        from PySide6.QtCore import Qt as _Qt
        import os

        # Hide the default text title label
        if hasattr(self.titleBar, "titleLabel"):
            self.titleBar.titleLabel.hide()

        # Hide the small default icon label (logo replaces both)
        if hasattr(self.titleBar, "iconLabel"):
            self.titleBar.iconLabel.hide()

        # Locate logo — prefer logo_64 for sharpness at small size
        assets_dir = os.path.join(os.path.dirname(__file__), "assets")
        for name in ("logo_64.png", "logo.png", "logo_128.png"):
            logo_path = os.path.join(assets_dir, name)
            if os.path.exists(logo_path):
                break
        else:
            return  # No logo file found

        # Pre-scale the pixmap to the desired height once
        pixmap = QPixmap(logo_path)
        scaled_pixmap = pixmap.scaledToHeight(28, _Qt.TransformationMode.SmoothTransformation)

        # Create logo label — flexible width so it auto-adjusts, fixed height
        logo_label = QLabel()
        logo_label.setPixmap(scaled_pixmap)
        logo_label.setMaximumHeight(28)
        logo_label.setMinimumWidth(20)
        logo_label.setSizePolicy(
            _QSP.Policy.Preferred,
            _QSP.Policy.Fixed
        )
        logo_label.setStyleSheet("background: transparent; margin-left: 6px;")
        logo_label.setScaledContents(True)

        # Insert at position 0 (far left of title bar)
        self.titleBar.hBoxLayout.insertWidget(
            0, logo_label, 0, _Qt.AlignmentFlag.AlignVCenter
        )
    
    def _on_tab_changed(self, index):
        """Handle lazy loading when switching tabs."""
        widget = self.stackedWidget.widget(index)
        
        if isinstance(widget, LazyTab):
            obj_name = widget.objectName()
            try:
                real_widget = widget.initialize()
            except Exception as e:
                import traceback
                print(f"[App] Failed to initialise lazy tab '{obj_name}': {e}")
                traceback.print_exc()

                # Replace placeholder content with the error so UI isn't "blank"
                try:
                    if hasattr(widget, "layout") and widget.layout:
                        # remove existing children
                        for i in reversed(range(widget.layout.count())):
                            item = widget.layout.itemAt(i)
                            w = item.widget() if item else None
                            if w is not None:
                                w.setParent(None)

                        err_lbl = QLabel(
                            f"Settings/Tab failed to load.\n\n{type(e).__name__}: {e}",
                            widget,
                        )
                        err_lbl.setWordWrap(True)
                        widget.layout.addWidget(err_lbl)
                except Exception:
                    pass

                self.set_status("Tab init failed")
                return

            # Map lazy widget to attribute
            if obj_name == "chatInterface":
                self.chat_tab = real_widget
                self._connect_chat_signals()
            elif obj_name == "plannerInterface":
                self.planner_tab = real_widget
            elif obj_name == "briefingInterface":
                self.briefing_view = real_widget
            elif obj_name == "agentsInterface":
                self.agents_tab = real_widget
            elif obj_name == "agentListInterface":
                self.agent_list_tab = real_widget
                if not self._agent_list_signals_connected:
                    self._agent_list_signals_connected = True
                    self.agent_list_tab.agent_output_ready.connect(
                        self.handlers._on_agent_result
                    )
            elif obj_name == "modelBrowserInterface":
                pass  # ModelBrowserTab self-initialises
                
        self.set_status("Ready")
    
    def _navigate_to_tab(self, route_key: str):
        """Navigate to a tab by its object name (route key)."""
        for i in range(self.stackedWidget.count()):
            widget = self.stackedWidget.widget(i)
            if widget.objectName() == route_key:
                self.switchTo(widget)
                return
    
    def navigate_to_agents(self):
        """Navigate to the Active Agents tab (lazy init if needed)."""
        widget = self.agents_lazy.get_widget()
        if widget is None:
            widget = self.agents_lazy.initialize()
        self.switchTo(self.agents_lazy)

    def navigate_to_agent_list(self):
        """Navigate to the Agent List tab (lazy init if needed)."""
        widget = self.agent_list_lazy.get_widget()
        if widget is None:
            widget = self.agent_list_lazy.initialize()
        self.switchTo(self.agent_list_lazy)
    
    # --- Public Methods for Handlers (Proxy/Facade) ---
    # These now check if the tab exists before calling
    
    def set_status(self, text: str):
        if self.chat_tab: self.chat_tab.set_status(text)
    
    def clear_input(self):
        if self.chat_tab: self.chat_tab.clear_input()
    
    def set_generating_state(self, is_generating: bool):
        if self.chat_tab: self.chat_tab.set_generating_state(is_generating)
    
    def add_message_bubble(self, role: str, text: str, is_thinking: bool = False):
        if self.chat_tab: self.chat_tab.add_message_bubble(role, text, is_thinking)
    
    def add_streaming_widgets(self, thinking_ui, search_indicator, response_bubble):
        if self.chat_tab: self.chat_tab.add_streaming_widgets(thinking_ui, search_indicator, response_bubble)
    
    def clear_chat_display(self):
        if self.chat_tab: self.chat_tab.clear_chat_display()
    
    def refresh_sidebar(self, current_session_id: str = None):
        if self.chat_tab: self.chat_tab.refresh_sidebar(current_session_id)
    
    def scroll_to_bottom(self):
        if self.chat_tab: self.chat_tab.scroll_to_bottom()

    def reading_files_tab(self):
        """Return the ReadingFilesTab if already initialised, else None."""
        return self.reading_files_lazy.get_widget()

    def read_file_option(self, n: int) -> None:
        """
        Navigate to Reading Files tab and read option n (1-indexed).
        Also injects the file content into the LLM context via
        inject_file_and_respond so the model can acknowledge and summarise.
        """
        rft = self.reading_files_lazy.initialize()
        self.switchTo(self.reading_files_lazy)
        rft.read_option_with_callback(
            n,
            lambda fname, content: self.handlers.inject_file_and_respond(
                fname, content
            ),
        )

    def _on_voice_desktop_started(self, task: str):
        """Show status bar message when the desktop agent begins a task."""
        self.set_status(f"Desktop agent: {task[:60]}…")

    def _on_voice_desktop_finished(self, result: str):
        """Show a toast notification when the desktop agent finishes."""
        try:
            from gui.components.toast import ToastNotification
            # Treat as failure if the result starts with a known error prefix
            is_error = any(result.lower().startswith(p) for p in
                           ("error", "desktop agent error", "windows-use"))
            ToastNotification.show_toast(self, result[:120], not is_error)
        except Exception:
            pass
        self.set_status("Ready")

    def _on_voice_refresh_agents(self):
        """Refresh agent-related UI when triggered by voice command."""
        try:
            # Active Agents live status
            agents_widget = self.agents_lazy.get_widget()
            if agents_widget is not None:
                agents_widget.refresh()

            # Agent List custom agents
            agent_list_widget = self.agent_list_lazy.get_widget()
            if agent_list_widget is not None:
                agent_list_widget.refresh()
        except Exception as e:
            print(f"[App] _on_voice_refresh_agents error: {e}")

    def _on_voice_help_requested(self):
        """Show the help panel on the dashboard when triggered by voice or text command."""
        try:
            # Navigate to Dashboard so the user can see the help output
            self.switchTo(self.dashboard_view)
            # Trigger the help display
            self.dashboard_view._cmd_help()
        except Exception as e:
            print(f"[App] _on_voice_help_requested error: {e}")

    def closeEvent(self, event):
        """Handle application close event."""
        print("[App] Closing application, unloading models...")
        self.set_status("Closing...")

        # ── Stop long-lived QThreads before Qt's atexit destroys them ───────
        # Without this, the dashboard's SystemMonitor worker thread (running
        # the whole app lifetime) is GC'd while still alive, producing
        # "QThread: Destroyed while thread '...' is still running" + SIGABRT.
        try:
            sys_mon = getattr(self.dashboard_view, "sys_monitor", None)
            if sys_mon is not None and hasattr(sys_mon, "cleanup"):
                sys_mon.cleanup()
        except Exception as exc:
            print(f"[App] sys_monitor cleanup failed: {exc}")

        # Title-bar SystemMonitor is a SEPARATE component with its own QThread.
        try:
            tb_mon = getattr(self, "system_monitor", None)
            if tb_mon is not None and hasattr(tb_mon, "cleanup"):
                tb_mon.cleanup()
        except Exception as exc:
            print(f"[App] titlebar system_monitor cleanup failed: {exc}")

        # AgentStatusThread fires on Active Agents tab refresh; usually short
        # but join it defensively if mid-flight.
        try:
            agents_tab = self.agents_tab
            if agents_tab is not None and getattr(agents_tab, "_thread", None) is not None:
                t = agents_tab._thread
                if t.isRunning():
                    t.quit()
                    t.wait(2000)
        except Exception as exc:
            print(f"[App] agents_tab thread cleanup failed: {exc}")

        # Stop voice assistant if it was started
        if VOICE_ASSISTANT_ENABLED and app_settings.get("voice.auto_start", True):
            voice_assistant.stop()

        unload_all_models(sync=True)
        event.accept()


def create_app():
    """Create and return the main window."""
    return MainWindow()
