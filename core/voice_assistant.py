import re as _re
import threading
import json
from typing import Optional

from PySide6.QtCore import QObject, Signal

from config import (
    RESPONDER_MODEL, OLLAMA_URL, MAX_HISTORY, GRAY, RESET, CYAN, GREEN, WAKE_WORD
)
from core.settings_store import settings as app_settings
from core.stt import STTListener
from core.llm import route_query, should_bypass_router, http_session
from core.model_persistence import ensure_qwen_loaded, mark_qwen_used, unload_qwen
from core.tts import tts, SentenceBuffer
from core.function_executor import executor as function_executor

# Functions that are actions (not passthrough)
ACTION_FUNCTIONS = {
    "control_light", "set_timer", "set_alarm",
    "create_calendar_event", "add_task", "web_search",
    "control_desktop",
}


class VoiceAssistant(QObject):
    """Main voice assistant orchestrator."""
    
    # Signals for UI updates (optional)
    wake_word_detected = Signal()
    speech_recognized = Signal(str)
    processing_started = Signal()
    processing_finished = Signal()
    error_occurred = Signal(str)
    # GUI update signals
    timer_set = Signal(int, str)  # seconds, label
    alarm_added = Signal()
    calendar_updated = Signal()
    task_added = Signal()
    # Weather window signals
    weather_requested = Signal(dict)  # emits weather data dict
    close_weather_requested = Signal()
    # Search browser signals
    web_search_requested = Signal(str, list)  # query, results list
    close_search_requested = Signal()
    search_nav_requested = Signal(str)   # "next" or "previous"
    search_open_requested = Signal(int)  # result number to open (1-based)
    search_maximise_requested = Signal()       # expand / restore window to full screen
    search_help_minimise_requested = Signal()  # collapse the Search Help panel
    # Desktop / Discord agent signals
    desktop_task_started = Signal(str)   # emits the task description
    desktop_task_finished = Signal(str)  # emits the result summary
    # Active Agents tab — voice-triggered refresh
    refresh_agents_requested = Signal()  # emits to AgentsTab.refresh()
    # Dashboard help panel — voice-triggered
    help_requested = Signal()            # emits to DashboardView._cmd_help()
    # Reading Files tab — voice-triggered file read
    read_file_requested = Signal(int)    # emits 1-based file index
    
    def __init__(self):
        super().__init__()
        self.stt_listener: Optional[STTListener] = None
        self.running = False
        self.messages = [
            {
                'role': 'system',
                'content': 'You are Plia, a Pocket Local Intelligent Assistant. Respond in short, complete sentences. Never use emojis or special characters. Keep responses concise and conversational.'
            }
        ]
        self.current_session_id = None
        
    def initialize(self) -> bool:
        """Initialize voice assistant components."""
        try:
            print(f"{CYAN}[VoiceAssistant] Initializing voice assistant components...{RESET}")
            # Initialize STT listener
            print(f"{CYAN}[VoiceAssistant] Creating STT listener...{RESET}")
            self.stt_listener = STTListener(
                wake_word_callback=self._on_wake_word,
                speech_callback=self._on_speech
            )
            print(f"{CYAN}[VoiceAssistant] ✓ STT listener created{RESET}")
            
            print(f"{CYAN}[VoiceAssistant] Initializing STT models...{RESET}")
            if not self.stt_listener.initialize():
                print(f"{GRAY}[VoiceAssistant] ✗ Failed to initialize STT.{RESET}")
                return False
            print(f"{CYAN}[VoiceAssistant] ✓ STT initialized{RESET}")
            
            # Ensure TTS is initialized — but guard against calling initialize()
            # a second time if the model preloader already did so.
            # The old check `if not tts.piper_exe` was ALWAYS True in Python
            # library mode (piper_exe is only set for the Windows executable
            # fallback), so initialize() was called twice, spawning two worker
            # threads that both tried to drive sounddevice concurrently,
            # causing a PortAudio segfault that crashed the whole app.
            if not tts._running:
                print(f"{CYAN}[VoiceAssistant] Initializing TTS...{RESET}")
                tts.initialize()
                print(f"{CYAN}[VoiceAssistant] ✓ TTS initialized{RESET}")
            else:
                print(f"{CYAN}[VoiceAssistant] ✓ TTS already initialized (skipping){RESET}")
            
            print(f"{CYAN}[VoiceAssistant] ✓ Voice assistant initialized successfully{RESET}")
            return True
        except Exception as e:
            print(f"{GRAY}[VoiceAssistant] ✗ Initialization error: {e}{RESET}")
            import traceback
            traceback.print_exc()
            return False
    
    def start(self):
        """Start the voice assistant."""
        if self.running:
            return
        
        if not self.stt_listener:
            if not self.initialize():
                return
        
        self.running = True
        self.stt_listener.start()
        from core.settings_store import settings as app_settings
        wake = app_settings.get("voice.wake_word", WAKE_WORD)
        print(f"{CYAN}[VoiceAssistant] Voice assistant started. Say '{GREEN}{wake}{RESET}{CYAN}' to activate.{RESET}")

    def stop(self):
        """Stop the voice assistant and reset so initialize() can be called again."""
        if not self.running:
            return

        self.running = False
        if self.stt_listener:
            self.stt_listener.stop()
            self.stt_listener = None   # reset so initialize() creates a fresh listener
        print(f"{GRAY}[VoiceAssistant] Voice assistant stopped.{RESET}")
    
    def _on_wake_word(self):
        """Handle wake word detection."""
        print(f"{GREEN}[VoiceAssistant] ✓ Wake word callback received!{RESET}")
        print(f"{GREEN}[VoiceAssistant] Emitting wake_word_detected signal...{RESET}")
        self.wake_word_detected.emit()
        print(f"{GREEN}[VoiceAssistant] ✓ Signal emitted. Listening for speech...{RESET}")
    
    def _on_speech(self, text: str):
        """Handle recognized speech after wake word."""
        if not text.strip():
            return

        # Wake word stripping is already handled in stt.py
        # Just clean up whitespace
        text = text.strip()
        if not text:
            return

        # ── Early intercept: "read option N" / "read file N" ────────────
        # Must be checked HERE before _process_query, because the desktop
        # agent trigger in _process_query can capture "read …" commands and
        # route them to the VLM pipeline before our regex fires.
        _read_m = _re.search(
            r'\b(?:read|open)\s+(?:option|file)\s+(\d+)',
            text.lower()
        )
        if _read_m:
            n = int(_read_m.group(1))
            print(f"{CYAN}[VoiceAssistant] Read file option {n} intercepted.{RESET}")
            self.speech_recognized.emit(text)
            self.processing_started.emit()
            # Emit the signal — inject_file_and_respond will speak
            # the file content once extraction completes.
            self.read_file_requested.emit(n)
            self.processing_finished.emit()
            return
        # ────────────────────────────────────────────────────────────────

        self.speech_recognized.emit(text)
        self.processing_started.emit()

        print(f"{CYAN}[VoiceAssistant] Processing: {text}{RESET}")

        # Process in background thread to avoid blocking
        thread = threading.Thread(
            target=self._process_query,
            args=(text,),
            daemon=True
        )
        thread.start()
    
    def _process_query(self, user_text: str):
        """Process user query through the pipeline."""
        try:
            text_lower = user_text.lower().strip()

            # ── Search browser navigation — MUST be checked first ────────
            # These must intercept before the desktop-trigger check because
            # "open search 3" starts with "open " which would otherwise be
            # swallowed by the desktop agent handler.

            # "next search page" / "next search results page"
            NEXT_SEARCH_PHRASES = (
                "next search page",
                "next search results page",
                "next results page",
                "next search results",
            )
            if any(p in text_lower for p in NEXT_SEARCH_PHRASES):
                self.search_nav_requested.emit("next")
                tts.queue_sentence("Going to the next search page.")
                self.processing_finished.emit()
                return

            # "previous search page" / "previous search results page"
            PREV_SEARCH_PHRASES = (
                "previous search page",
                "previous search results page",
                "previous results page",
                "previous search results",
                "prev search page",
            )
            if any(p in text_lower for p in PREV_SEARCH_PHRASES):
                self.search_nav_requested.emit("previous")
                tts.queue_sentence("Going to the previous search page.")
                self.processing_finished.emit()
                return

            # "open search 3" / "open search result 3" / "open search number 3"
            # Must match "open search" followed by a digit, to avoid clashing
            # with desktop "open <appname>" commands.
            open_search_match = _re.search(
                r'\bopen\s+search(?:\s+result(?:s)?)?(?:\s+number)?\s+(\d+)\b',
                text_lower
            )
            if open_search_match:
                num = int(open_search_match.group(1))
                self.search_open_requested.emit(num)
                tts.queue_sentence(f"Opening search result {num}.")
                self.processing_finished.emit()
                return

            # ── "Close weather" — hide the weather window ────────────────
            CLOSE_WEATHER_PHRASES = (
                "close weather", "hide weather", "dismiss weather",
                "close the weather", "hide the weather", "weather close",
                "shut weather", "exit weather"
            )
            if any(p in text_lower for p in CLOSE_WEATHER_PHRASES):
                self.close_weather_requested.emit()
                tts.queue_sentence("Closing the weather window.")
                self.processing_finished.emit()
                return

            # ── "Expand / maximise search window" — voice-triggered ──────
            # Must be checked BEFORE CLOSE_SEARCH_PHRASES and DESKTOP_TRIGGERS
            # because "maximise " appears in DESKTOP_TRIGGERS and would otherwise
            # intercept "maximise search window" for the desktop agent.
            SEARCH_MAXIMISE_PHRASES = (
                "expand search window", "expand the search window",
                "maximise search window", "maximize search window",
                "maximise search", "maximize search",
                "search full screen", "full screen search",
                "fullscreen search", "make search full",
                "search window full", "expand search",
                "restore search window", "restore search",
            )
            if any(p in text_lower for p in SEARCH_MAXIMISE_PHRASES):
                self.search_maximise_requested.emit()
                tts.queue_sentence("Toggling the search window size.")
                self.processing_finished.emit()
                return

            # ── "Collapse / hide search help panel" — voice-triggered ────
            # Must be checked BEFORE CLOSE_SEARCH_PHRASES because "hide search"
            # is already in that tuple and would intercept "hide search help".
            # Must also be checked BEFORE HELP_TRIGGERS because "help" appears
            # as a standalone trigger there and would match "collapse help".
            SEARCH_HELP_MINIMISE_PHRASES = (
                "hide search help", "minimise search help",
                "minimize search help", "collapse search help",
                "close search help", "hide the search help",
                "minimise help panel", "minimize help panel",
                "collapse help panel", "hide help panel",
                "close help panel", "minimise help section",
                "minimize help section", "collapse help",
                "hide help", "close help",
            )
            if any(p in text_lower for p in SEARCH_HELP_MINIMISE_PHRASES):
                self.search_help_minimise_requested.emit()
                tts.queue_sentence("Collapsing the search help panel.")
                self.processing_finished.emit()
                return

            # ── "Close search" — hide the search browser window ─────────
            CLOSE_SEARCH_PHRASES = (
                "close search", "hide search", "dismiss search",
                "close the search", "hide the search", "search close",
                "close browser", "exit search", "close results",
            )
            if any(p in text_lower for p in CLOSE_SEARCH_PHRASES):
                self.close_search_requested.emit()
                tts.queue_sentence("Closing the search window.")
                self.processing_finished.emit()
                return

            # ── Weather query — fetch data, speak it, show window ────────
            WEATHER_KEYWORDS = (
                "weather", "temperature", "forecast", "rain", "sunny",
                "raining", "hot", "cold", "windy", "wind", "humidity",
                "humid", "how warm", "how cold", "outside", "degrees",
                "umbrella", "jacket", "storm", "cloudy", "overcast"
            )
            # Use word-boundary matching so "window" does not trigger "wind",
            # "outside" does not trigger "out", etc.
            is_weather_query = any(
                _re.search(r'\b' + _re.escape(kw) + r'\b', text_lower)
                for kw in WEATHER_KEYWORDS
            )

            if is_weather_query:
                self._handle_weather_query(user_text)
                return

            # ── Desktop app launch / control ────────────────────────────
            # Detect requests to open or control any Windows application.
            # The desktop agent handles these visually — no API tokens needed.
            DESKTOP_TRIGGERS = (
                "open ", "launch ", "start ", "run ", "close ", "quit ",
                "switch to ", "bring up ", "minimise ", "minimize ",
                "maximise ", "maximize ", "resize ", "control ",
            )
            DESKTOP_APPS = (
                "discord", "spotify", "notepad", "file explorer", "chrome",
                "edge", "firefox", "steam", "outlook", "teams", "slack",
                "excel", "word", "powerpoint", "task manager",
            )
            is_desktop_command = (
                any(text_lower.startswith(t) for t in DESKTOP_TRIGGERS)
                or any(app in text_lower for app in DESKTOP_APPS)
            )
            if is_desktop_command and not is_weather_query:
                self._handle_desktop_task(user_text, user_text)
                return

            # ── Web Search — DuckDuckGo keyword lookup ───────────────────
            # Catches phrases that describe a plain web search but that the
            # FunctionGemma router sometimes misclassifies as nonthinking.
            # These are intercepted BEFORE the router so they always execute.
            WEB_SEARCH_TRIGGERS = (
                "do an internet search", "internet search",
                "do a web search", "web search for",
                "search the internet", "search the web",
                "search online", "online search",
                "search for ", "look up ", "look it up",
                "find information on", "find information about",
                "google ", "bing ", "find out about",
            )
            is_web_search_command = any(
                text_lower.startswith(t) or t in text_lower
                for t in WEB_SEARCH_TRIGGERS
            )
            if is_web_search_command and not is_weather_query and not is_desktop_command:
                # Extract the query: strip leading trigger phrase so the search
                # query itself is clean (e.g. "internet search on X" → "X")
                query = user_text.strip()
                for trigger in WEB_SEARCH_TRIGGERS:
                    idx = text_lower.find(trigger)
                    if idx != -1:
                        after = user_text[idx + len(trigger):].strip()
                        # Remove leading prepositions: "on", "for", "about"
                        for prep in ("on ", "for ", "about ", "into "):
                            if after.lower().startswith(prep):
                                after = after[len(prep):]
                        if after:
                            query = after
                        break
                print(f"{GRAY}[VoiceAssistant] Keyword-routed to: web_search (query={query!r}){RESET}")
                result = function_executor.execute("web_search", {"query": query})
                # Emit results to the floating search browser window
                if result.get("success") and result.get("data"):
                    data    = result["data"]
                    results = data.get("results", [])
                    self.web_search_requested.emit(query, results)
                self._generate_response_with_context("web_search", result, user_text)
                return

            # ── Help — show the help panel on the dashboard ──────────────
            # Caught BEFORE the router so it always works even when the router
            # misclassifies short phrases like "help" as nonthinking.
            HELP_TRIGGERS = (
                "help", "show help", "open help", "help me",
                "what can you do", "what commands", "list commands",
                "show commands", "available commands", "what are the commands",
                "how do i use", "how to use", "instructions", "guide",
                "show guide", "user guide",
            )
            if any(text_lower == t or text_lower.startswith(t + " ")
                   or t in text_lower
                   for t in HELP_TRIGGERS):
                self.help_requested.emit()
                tts.queue_sentence(
                    "Opening the help guide on your dashboard. "
                    "All available commands are listed there."
                )
                self.processing_finished.emit()
                return

            # ── Active Agents refresh — voice command ────────────────────
            # Triggered by phrases like:
            #   "refresh active agents"  /  "refresh the agents"
            #   "update active agents"   /  "reload agents"
            AGENTS_REFRESH_TRIGGERS = (
                "refresh active agents", "refresh the active agents",
                "refresh agents", "refresh the agents",
                "update active agents", "update agents",
                "reload active agents", "reload agents",
            )
            if any(text_lower.startswith(t) or t in text_lower
                   for t in AGENTS_REFRESH_TRIGGERS):
                self.refresh_agents_requested.emit()
                tts.queue_sentence("Refreshing active agents.")
                return

            # ── Reading Files — "read option N" / "read file N" ─────────
            # Matches spoken forms such as:
            #   "read option 1"  /  "read file 2"  /  "open option 3"
            # The digit is captured and forwarded to ReadingFilesTab.read_option()
            # via the read_file_requested signal wired in app.py.
            _read_match = _re.search(
                r'\b(?:read|open)\s+(?:option|file)\s+(\d+)\b',
                text_lower
            )
            if _read_match:
                n = int(_read_match.group(1))
                # inject_file_and_respond speaks the content once extracted
                self.read_file_requested.emit(n)
                self.processing_finished.emit()
                return

            # ── Discord channel reading ──────────────────────────────────
            # "channel" alone is enough to trigger this — covers phrases like
            # "open the general channel" or "close the announcements channel".

            # Step 1: Route through Function Gemma
            if should_bypass_router(user_text):
                func_name = "nonthinking"
                params = {"prompt": user_text}
            else:
                func_name, params = route_query(user_text)
            
            print(f"{GRAY}[VoiceAssistant] Routed to: {func_name}{RESET}")
            
            # Step 2: Handle based on function type
            if func_name in ACTION_FUNCTIONS:
                # Execute action function
                result = function_executor.execute(func_name, params)
                response_text = result.get("message", "Done.")
                
                # Emit GUI update signals for specific actions
                if func_name == "set_timer" and result.get("success"):
                    seconds = result.get("data", {}).get("seconds", 0)
                    label = result.get("data", {}).get("label", "Timer")
                    self.timer_set.emit(seconds, label)
                elif func_name == "set_alarm" and result.get("success"):
                    self.alarm_added.emit()
                elif func_name == "create_calendar_event" and result.get("success"):
                    self.calendar_updated.emit()
                elif func_name == "add_task" and result.get("success"):
                    self.task_added.emit()
                elif func_name == "control_desktop":
                    self.desktop_task_finished.emit(response_text)
                
                # Generate Qwen response with context
                self._generate_response_with_context(func_name, result, user_text)
                
            elif func_name == "get_system_info":
                # Get system info
                result = function_executor.execute(func_name, params)
                self._generate_response_with_context(func_name, result, user_text, enable_thinking=True)
                
            elif func_name in ("thinking", "nonthinking"):
                # Direct Qwen passthrough
                enable_thinking = (func_name == "thinking")
                self._stream_qwen_response(user_text, enable_thinking)
            
            else:
                # Fallback to nonthinking
                self._stream_qwen_response(user_text, False)
                
        except Exception as e:
            error_msg = f"Error processing query: {e}"
            print(f"{GRAY}[VoiceAssistant] {error_msg}{RESET}")
            self.error_occurred.emit(error_msg)
            self.processing_finished.emit()
    
    def _handle_weather_query(self, user_text: str):
        """Fetch weather, speak a summary, and emit signal to show the weather window."""
        try:
            from core.weather import weather_manager
            data = weather_manager.get_weather()

            if data:
                temp     = data.get("temp", "--")
                unit     = data.get("unit", "°C")
                cond     = data.get("condition", "Unknown")
                high     = data.get("high", "--")
                low      = data.get("low", "--")
                humidity = data.get("humidity")
                wind_spd = data.get("wind_spd")
                wind_dir = data.get("wind_dir", "")
                station  = data.get("station", "")

                # Convert unit symbol to full spoken words for TTS
                if "F" in unit:
                    unit_spoken = "degrees Fahrenheit"
                else:
                    unit_spoken = "degrees Celsius"

                # Build spoken summary
                parts = [f"Currently {temp} {unit_spoken} and {cond}."]
                parts.append(f"Today's high is {high} {unit_spoken}, low is {low} {unit_spoken}.")
                if humidity is not None:
                    parts.append(f"Humidity is {humidity} percent.")
                if wind_spd is not None:
                    wind_str = (
                        f"Wind {wind_dir} at {wind_spd} kilometres per hour."
                        if wind_dir else
                        f"Wind at {wind_spd} kilometres per hour."
                    )
                    parts.append(wind_str)

                spoken = " ".join(parts)
                tts.queue_sentence(spoken)

                # Show the weather window via signal (must happen on main thread)
                self.weather_requested.emit(data)
            else:
                tts.queue_sentence("Sorry, I couldn't fetch the weather right now.")

        except Exception as e:
            print(f"[VoiceAssistant] Weather query error: {e}")
            tts.queue_sentence("Sorry, there was an error getting the weather.")
        finally:
            self.processing_finished.emit()

    def _handle_desktop_task(self, task: str, user_text: str):
        """Run a Windows desktop task via the desktop agent."""
        try:
            self.desktop_task_started.emit(task)
            result = function_executor.execute("control_desktop", {"task": task})
            self.desktop_task_finished.emit(result.get("message", "Done."))
            self._generate_response_with_context("control_desktop", result, user_text)
        except Exception as e:
            print(f"{GRAY}[VoiceAssistant] Desktop task error: {e}{RESET}")
            self.processing_finished.emit()


    def _generate_response_with_context(self, func_name: str, result: dict, user_text: str, enable_thinking: bool = False):
        """Generate Qwen response with function execution context."""
        try:
            # Ensure Qwen is loaded
            if not ensure_qwen_loaded():
                print(f"{GRAY}[VoiceAssistant] Failed to load Qwen model.{RESET}")
                self.processing_finished.emit()
                return
            
            mark_qwen_used()
            
            # Build context message
            success = result.get("success", False)
            message = result.get("message", "")
            
            # Enhanced context for get_system_info
            if func_name == "get_system_info" and success:
                data = result.get("data", {})
                context_parts = []
                if data.get("timers"):
                    context_parts.append(f"Active timers: {data['timers']}")
                if data.get("alarms"):
                    context_parts.append(f"Alarms: {data['alarms']}")
                if data.get("calendar_today"):
                    context_parts.append(f"Today's events: {data['calendar_today']}")
                if data.get("tasks"):
                    pending = [t for t in data['tasks'] if not t.get('completed')]
                    context_parts.append(f"Pending tasks: {len(pending)} items")
                if data.get("smart_devices"):
                    on_devices = [d['name'] for d in data['smart_devices'] if d.get('is_on')]
                    context_parts.append(f"Devices on: {on_devices if on_devices else 'none'}")
                if data.get("weather"):
                    w = data['weather']
                    context_parts.append(f"Weather: {w.get('temp')}°F, {w.get('condition')}")
                if data.get("news"):
                    news_items = data['news']
                    if news_items:
                        news_titles = [item.get('title', '')[:50] for item in news_items[:3]]
                        context_parts.append(f"Top news: {', '.join(news_titles)}")
                context_msg = "SYSTEM CONTEXT:\n" + "\n".join(context_parts) if context_parts else "No system information available."
            else:
                context_msg = f"Function {func_name} executed. Success: {success}. Result: {message}"
            
            # Manage context window
            max_hist = MAX_HISTORY
            if len(self.messages) > max_hist:
                self.messages = [self.messages[0]] + self.messages[-(max_hist-1):]
            
            # Add context as user message
            context_prompt = f"{context_msg}\n\nUser asked: {user_text}\n\nRespond naturally and concisely."
            self.messages.append({'role': 'user', 'content': context_prompt})
            
            # Prepare payload — read model from settings so user changes take effect immediately
            _chat_model = app_settings.get("models.chat", RESPONDER_MODEL)
            payload = {
                "model": _chat_model,
                "messages": self.messages,
                "stream": True,
                "think": enable_thinking,
                "keep_alive": "5m",
                "options": {
                    "num_predict": 512,
                    "num_ctx": 4096,
                }
            }
            
            sentence_buffer = SentenceBuffer()
            full_response = ""
            
            # Stream response
            with http_session.post(f"{OLLAMA_URL}/chat", json=payload, stream=True) as r:
                r.raise_for_status()
                
                for line in r.iter_lines():
                    if line:
                        try:
                            chunk = json.loads(line.decode('utf-8'))
                            msg = chunk.get('message', {})
                            
                            if 'content' in msg and msg['content']:
                                content = msg['content']
                                full_response += content
                                
                                # Queue for TTS
                                sentences = sentence_buffer.add(content)
                                for s in sentences:
                                    tts.queue_sentence(s)
                        except:
                            continue
            
            # Flush remaining
            rem = sentence_buffer.flush()
            if rem:
                tts.queue_sentence(rem)
            
            # Update messages
            self.messages.append({'role': 'assistant', 'content': full_response})
            
            mark_qwen_used()  # Update usage time
            
            print(f"{GREEN}[VoiceAssistant] Response generated.{RESET}")
            self.processing_finished.emit()
            
        except Exception as e:
            print(f"{GRAY}[VoiceAssistant] Error generating response: {e}{RESET}")
            self.processing_finished.emit()
    
    def _stream_qwen_response(self, user_text: str, enable_thinking: bool):
        """Stream direct Qwen response."""
        try:
            # Ensure Qwen is loaded
            if not ensure_qwen_loaded():
                print(f"{GRAY}[VoiceAssistant] Failed to load Qwen model.{RESET}")
                self.processing_finished.emit()
                return
            
            mark_qwen_used()
            
            # Manage context window
            max_hist = MAX_HISTORY
            if len(self.messages) > max_hist:
                self.messages = [self.messages[0]] + self.messages[-(max_hist-1):]
            
            self.messages.append({'role': 'user', 'content': user_text})
            
            # Prepare payload — read model from settings so user changes take effect immediately
            _chat_model = app_settings.get("models.chat", RESPONDER_MODEL)
            payload = {
                "model": _chat_model,
                "messages": self.messages,
                "stream": True,
                "think": enable_thinking,
                "keep_alive": "5m",
                "options": {
                    "num_predict": 512,
                    "num_ctx": 4096,
                }
            }
            
            sentence_buffer = SentenceBuffer()
            full_response = ""
            
            # Stream response
            with http_session.post(f"{OLLAMA_URL}/chat", json=payload, stream=True) as r:
                r.raise_for_status()
                
                for line in r.iter_lines():
                    if line:
                        try:
                            chunk = json.loads(line.decode('utf-8'))
                            msg = chunk.get('message', {})
                            
                            if 'content' in msg and msg['content']:
                                content = msg['content']
                                full_response += content
                                
                                # Queue for TTS
                                sentences = sentence_buffer.add(content)
                                for s in sentences:
                                    tts.queue_sentence(s)
                        except:
                            continue
            
            # Flush remaining
            rem = sentence_buffer.flush()
            if rem:
                tts.queue_sentence(rem)
            
            # Update messages
            self.messages.append({'role': 'assistant', 'content': full_response})
            
            mark_qwen_used()  # Update usage time
            
            print(f"{GREEN}[VoiceAssistant] Response generated.{RESET}")
            self.processing_finished.emit()
            
        except Exception as e:
            print(f"{GRAY}[VoiceAssistant] Error streaming response: {e}{RESET}")
            self.processing_finished.emit()


# Global voice assistant instance
voice_assistant = VoiceAssistant()
