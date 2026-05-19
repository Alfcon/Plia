"""
Function Executor - Executes Gemma-routed functions with actual backend calls.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
import threading
import time


@dataclass
class ActiveTimer:
    """Represents an active countdown timer."""
    label: str
    duration_seconds: int
    start_time: float
    
    @property
    def remaining_seconds(self) -> int:
        elapsed = time.time() - self.start_time
        return max(0, int(self.duration_seconds - elapsed))
    
    @property
    def is_expired(self) -> bool:
        return self.remaining_seconds <= 0
    
    def format_remaining(self) -> str:
        secs = self.remaining_seconds
        mins, secs = divmod(secs, 60)
        hours, mins = divmod(mins, 60)
        if hours:
            return f"{hours}h {mins}m {secs}s"
        elif mins:
            return f"{mins}m {secs}s"
        return f"{secs}s"


# Thread-local recursion depth for run_agent — caps sub-agent call depth so
# A → B → A → ... can't infinite-loop.
_RUN_AGENT_DEPTH = threading.local()
_RUN_AGENT_MAX_DEPTH = 3


class FunctionExecutor:
    """Central executor for all Gemma-routed functions."""
    
    def __init__(self):
        self.task_manager = None
        self.calendar_manager = None
        self.weather_manager = None
        self.news_manager = None
        
        # In-memory timer storage
        self.active_timers: Dict[str, ActiveTimer] = {}
        self._timer_lock = threading.Lock()
        
        # Lazy load managers
        self._init_managers()
    
    def _init_managers(self):
        """Initialize manager references."""
        try:
            from core.tasks import TaskManager
            self.task_manager = TaskManager()
        except Exception as e:
            print(f"[FunctionExecutor] TaskManager init failed: {e}")
        
        try:
            from core.calendar_manager import CalendarManager
            self.calendar_manager = CalendarManager()
        except Exception as e:
            print(f"[FunctionExecutor] CalendarManager init failed: {e}")
        
        try:
            from core.weather import WeatherManager
            self.weather_manager = WeatherManager()
        except Exception as e:
            print(f"[FunctionExecutor] WeatherManager init failed: {e}")
        
        try:
            from core.news import NewsManager
            self.news_manager = NewsManager()
        except Exception as e:
            print(f"[FunctionExecutor] NewsManager init failed: {e}")
    
    def execute(self, func_name: str, params: Dict[str, Any],
                *, _progress=None) -> Dict[str, Any]:
        """
        Execute a function and return structured result.

        ``_progress`` is an optional ``Callable[[str], None]`` invoked for
        long-running tools that emit per-step updates (currently only
        ``control_desktop``). Other tools ignore it.

        Returns:
            {
                "success": bool,
                "message": str,  # Human-readable result
                "data": Any      # Raw data if applicable
            }
        """
        try:
            if func_name == "set_timer":
                return self._set_timer(params)
            elif func_name == "set_alarm":
                return self._set_alarm(params)
            elif func_name == "create_calendar_event":
                return self._create_calendar_event(params)
            elif func_name == "add_task":
                return self._add_task(params)
            elif func_name == "web_search":
                return self._web_search(params)
            elif func_name == "get_system_info":
                return self._get_system_info()
            elif func_name == "control_desktop":
                return self._control_desktop(params, progress_callback=_progress)
            elif func_name == "system_command":
                return self._system_command(params)
            elif func_name == "manage_notes":
                return self._manage_notes(params)
            elif func_name == "send_email":
                return self._send_email(params)
            elif func_name == "read_emails":
                return self._read_emails(params)
            elif func_name == "clipboard_action":
                return self._clipboard_action(params)
            elif func_name == "file_operations":
                return self._file_operations(params)
            elif func_name == "get_stock_price":
                return self._get_stock_price(params)
            elif func_name == "convert_currency":
                return self._convert_currency(params)
            elif func_name == "translate_text":
                return self._translate_text(params)
            elif func_name == "control_media":
                return self._control_media(params)
            elif func_name == "network_tools":
                return self._network_tools(params)
            elif func_name == "mcp_tool_call":
                return self._mcp_tool_call(params)
            elif func_name == "http_get":
                return self._http_get(params)
            elif func_name == "list_plia_features":
                return self._list_plia_features(params)
            elif func_name == "github_readme":
                return self._github_readme(params)
            elif func_name == "list_agents":
                return self._list_agents(params)
            elif func_name == "run_agent":
                return self._run_agent(params)
            else:
                # User plugin tools live under ``<plugin>:<name>``.
                if ":" in func_name:
                    try:
                        from core.plugins import registry as _plugins
                        plugin_out = _plugins.call(func_name, params or {})
                        if plugin_out is not None:
                            return plugin_out
                    except Exception as exc:
                        return {"success": False,
                                "message": f"Plugin dispatch error: {exc}",
                                "data": None}
                return {"success": False, "message": f"Unknown function: {func_name}", "data": None}
        except Exception as e:
            return {"success": False, "message": f"Error: {str(e)}", "data": None}
    
    # === Action Functions ===

    def _set_timer(self, params: Dict) -> Dict:
        """Set a countdown timer."""
        duration_str = params.get("duration", "")
        label = params.get("label", "Timer")
        
        # Parse duration string
        seconds = self._parse_duration(duration_str)
        if seconds <= 0:
            return {"success": False, "message": f"Invalid duration: {duration_str}", "data": None}
        
        timer = ActiveTimer(
            label=label,
            duration_seconds=seconds,
            start_time=time.time()
        )
        
        with self._timer_lock:
            self.active_timers[label] = timer
        
        return {
            "success": True,
            "message": f"Timer '{label}' set for {duration_str}",
            "data": {"label": label, "duration": duration_str, "seconds": seconds}
        }
    
    def _parse_duration(self, duration_str: str) -> int:
        """Parse duration string like '10 minutes' or '1 hour 30 minutes' to seconds."""
        duration_str = duration_str.lower().strip()
        total_seconds = 0
        
        import re
        # Match patterns like "10 minutes", "1 hour", "30 seconds"
        patterns = [
            (r'(\d+)\s*h(?:our)?s?', 3600),
            (r'(\d+)\s*m(?:in(?:ute)?s?)?', 60),
            (r'(\d+)\s*s(?:ec(?:ond)?s?)?', 1),
        ]
        
        for pattern, multiplier in patterns:
            match = re.search(pattern, duration_str)
            if match:
                total_seconds += int(match.group(1)) * multiplier
        
        # If no pattern matched, try to extract just a number (assume minutes)
        if total_seconds == 0:
            nums = re.findall(r'\d+', duration_str)
            if nums:
                total_seconds = int(nums[0]) * 60  # Default to minutes
        
        return total_seconds
    
    def _set_alarm(self, params: Dict) -> Dict:
        """Set an alarm via TaskManager."""
        time_str = params.get("time", "")
        label = params.get("label", "Alarm")
        
        if not self.task_manager:
            return {"success": False, "message": "Task manager not available", "data": None}
        
        # Normalize time format
        normalized_time = self._normalize_time(time_str)
        
        alarm_id = self.task_manager.add_alarm(normalized_time, label)
        
        if alarm_id:
            return {
                "success": True,
                "message": f"Alarm set for {normalized_time}" + (f" ({label})" if label != "Alarm" else ""),
                "data": {"id": alarm_id, "time": normalized_time, "label": label}
            }
        return {"success": False, "message": "Failed to set alarm", "data": None}
    
    def _normalize_time(self, time_str: str) -> str:
        """Normalize time string to HH:MM format."""
        time_str = time_str.lower().strip()
        
        import re
        # Match patterns like "7am", "7:30am", "14:30"
        match = re.match(r'(\d{1,2}):?(\d{2})?\s*(am|pm)?', time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            period = match.group(3)
            
            if period == 'pm' and hour < 12:
                hour += 12
            elif period == 'am' and hour == 12:
                hour = 0
            
            return f"{hour:02d}:{minute:02d}"
        
        return time_str
    
    def _create_calendar_event(self, params: Dict) -> Dict:
        """Create a calendar event."""
        title = params.get("title", "Event")
        date = params.get("date", "today")
        time_str = params.get("time", "09:00")
        duration = params.get("duration", 60)  # Default 1 hour
        
        if not self.calendar_manager:
            return {"success": False, "message": "Calendar manager not available", "data": None}
        
        # Parse date
        event_date = self._parse_date(date)
        
        # Parse time
        normalized_time = self._normalize_time(time_str) if time_str else "09:00"
        
        # Create datetime strings
        start_dt = f"{event_date} {normalized_time}:00"
        
        # Calculate end time
        try:
            start = datetime.strptime(start_dt, "%Y-%m-%d %H:%M:%S")
            end = start + timedelta(minutes=duration if isinstance(duration, int) else 60)
            end_dt = end.strftime("%Y-%m-%d %H:%M:%S")
        except:
            end_dt = start_dt
        
        event = self.calendar_manager.add_event(title, start_dt, end_dt)
        
        if event:
            return {
                "success": True,
                "message": f"Created event '{title}' on {date}" + (f" at {time_str}" if time_str else ""),
                "data": event
            }
        return {"success": False, "message": "Failed to create event", "data": None}
    
    def _parse_date(self, date_str: str) -> str:
        """Parse date string to YYYY-MM-DD format."""
        date_str = date_str.lower().strip()
        
        # Try to parse as explicit date first
        try:
            val = datetime.strptime(date_str, "%Y-%m-%d")
            return val.strftime("%Y-%m-%d")
        except ValueError:
            pass
            
        today = datetime.now()
        
        if date_str in ("today", ""):
            return today.strftime("%Y-%m-%d")
        elif date_str == "tomorrow":
            return (today + timedelta(days=1)).strftime("%Y-%m-%d")
        
        # Day names
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for i, day in enumerate(days):
            if day in date_str:
                current_day = today.weekday()
                days_ahead = i - current_day
                if days_ahead <= 0:
                    days_ahead += 7
                if "next" in date_str:
                    days_ahead += 7
                target = today + timedelta(days=days_ahead)
                return target.strftime("%Y-%m-%d")
        
        return today.strftime("%Y-%m-%d")
    
    def _add_task(self, params: Dict) -> Dict:
        """Add a task to the to-do list."""
        text = params.get("text", "")
        
        if not text:
            return {"success": False, "message": "No task text provided", "data": None}
        
        if not self.task_manager:
            return {"success": False, "message": "Task manager not available", "data": None}
        
        task = self.task_manager.add_task(text)
        
        if task:
            return {
                "success": True,
                "message": f"Added task: {text}",
                "data": task
            }
        return {"success": False, "message": "Failed to add task", "data": None}
    
    def _web_search(self, params: Dict) -> Dict:
        """Perform a web search.

        Returns up to 20 results so the SearchBrowserWindow can paginate them.
        The 'results' list contains dicts with keys: title, body, url.

        Backend is chosen from settings.search.backend:
          - "brave"      → Brave Search API (requires brave_api_key)
          - "duckduckgo" → DuckDuckGo via ddgs (no key)
          - "auto"       → Brave if a key is set, otherwise DuckDuckGo
        """
        query = params.get("query", "")
        if not query:
            return {"success": False, "message": "No search query provided", "data": None}

        # Resolve backend lazily so live settings changes take effect.
        backend = "duckduckgo"
        brave_key = ""
        try:
            from core.settings_store import settings as app_settings
            backend = (app_settings.get("search.backend", "auto") or "auto").lower()
            brave_key = (app_settings.get("search.brave_api_key", "") or "").strip()
        except Exception:
            pass
        if backend == "auto":
            backend = "brave" if brave_key else "duckduckgo"

        if backend == "brave":
            result = self._search_brave(query, brave_key)
            if result is not None:
                return result
            # Brave failed (no key, network error, quota) — fall back to DDG.
            print("[web_search] Brave search failed; falling back to DuckDuckGo.")

        return self._search_duckduckgo(query)

    def _search_brave(self, query: str, api_key: str) -> Optional[Dict]:
        """Brave Search API. Returns None if the key is missing or the call
        fails, so the caller can fall back to another backend."""
        if not api_key:
            return None
        try:
            import requests
            resp = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": 20},
                headers={"Accept": "application/json",
                         "X-Subscription-Token": api_key},
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"[web_search] Brave HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            payload = resp.json()
            results = (payload.get("web") or {}).get("results") or []
            formatted = []
            for r in results[:20]:
                formatted.append({
                    "title": r.get("title", ""),
                    "body":  (r.get("description", "") or "")[:300],
                    "url":   r.get("url", ""),
                })
            return {
                "success": True,
                "message": f"Found {len(formatted)} results for '{query}' (Brave)",
                "data": {"query": query, "results": formatted, "backend": "brave"},
            }
        except Exception as e:
            print(f"[web_search] Brave error: {e}")
            return None

    def _search_duckduckgo(self, query: str) -> Dict:
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=20))
            if raw:
                formatted = [
                    {"title": r.get("title", ""),
                     "body":  r.get("body", "")[:300],
                     "url":   r.get("href", "")}
                    for r in raw
                ]
                return {
                    "success": True,
                    "message": f"Found {len(formatted)} results for '{query}' (DuckDuckGo)",
                    "data": {"query": query, "results": formatted, "backend": "duckduckgo"},
                }
            return {"success": True,
                    "message": f"No results found for '{query}'",
                    "data": {"query": query, "results": [], "backend": "duckduckgo"}}
        except Exception as e:
            return {"success": False, "message": f"Search failed: {e}", "data": None}
    
    # === System Info ===
    
    def _get_system_info(self) -> Dict:
        """Aggregate all system information."""
        info = {
            "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "timers": [],
            "alarms": [],
            "calendar_today": [],
            "tasks": [],
            "weather": None,
            "news": []
        }
        
        # Active timers
        with self._timer_lock:
            for label, timer in list(self.active_timers.items()):
                if timer.is_expired:
                    del self.active_timers[label]
                else:
                    info["timers"].append({
                        "label": timer.label,
                        "remaining": timer.format_remaining()
                    })
        
        # Alarms
        if self.task_manager:
            try:
                alarms = self.task_manager.get_alarms()
                info["alarms"] = [{"time": a["time"], "label": a["label"]} for a in alarms]
            except:
                pass
        
        # Calendar events today
        if self.calendar_manager:
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                events = self.calendar_manager.get_events(today)
                info["calendar_today"] = [{"title": e["title"], "time": e["start_time"]} for e in events]
            except:
                pass
        
        # Tasks
        if self.task_manager:
            try:
                tasks = self.task_manager.get_tasks()
                info["tasks"] = [{"text": t["text"], "completed": t["completed"]} for t in tasks]
            except:
                pass
        
        # Weather
        if self.weather_manager:
            try:
                weather = self.weather_manager.get_weather()
                if weather and "current" in weather:
                    current = weather["current"]
                    info["weather"] = {
                        "temp": current.get("temp"),
                        "condition": current.get("condition"),
                        "high": weather.get("daily", {}).get("high"),
                        "low": weather.get("daily", {}).get("low")
                    }
            except:
                pass
        
        # News
        if self.news_manager:
            try:
                # Get recent news (cached or fresh)
                news_items = self.news_manager.get_briefing(use_ai=False)
                # Limit to top 5 for system info
                info["news"] = [
                    {
                        "title": item.get("title", ""),
                        "category": item.get("category", "News"),
                        "url": item.get("url", "")
                    }
                    for item in news_items[:5]
                ]
            except Exception as e:
                print(f"[FunctionExecutor] News fetch error: {e}")
                pass
        
        return {
            "success": True,
            "message": "System info retrieved",
            "data": info
        }

    # === Desktop Agent ===

    def _control_desktop(self, params: Dict, *, progress_callback=None) -> Dict:
        """
        Run a natural language desktop task using the VLM desktop agent.
        For simple 'open X' commands the app is launched directly via subprocess
        without going through the VLM, which is faster and more reliable.

        ``progress_callback(line: str)`` is forwarded to
        ``DesktopAgent.run_task_sync`` so callers see live per-step updates.
        """
        task = params.get("task", "").strip()
        if not task:
            return {"success": False, "message": "No task specified.", "data": None}

        # --- Fast path: direct launch for simple "open X" commands ---
        direct_result = self._try_direct_launch(task)
        if direct_result is not None:
            return direct_result

        # --- Slow path: VLM desktop agent ---
        try:
            from core.agent.desktop_agent import DesktopAgent
            agent = DesktopAgent()
            return agent.run_task_sync(task, progress_callback=progress_callback)
        except ImportError as e:
            return {
                "success": False,
                "message": (
                    f"Desktop agent unavailable — make sure mss and pyautogui "
                    f"are installed (pip install mss pyautogui): {e}"
                ),
                "data": None,
            }
        except Exception as e:
            return {"success": False, "message": f"Desktop agent error: {e}", "data": None}

    # Maps voice phrase → exe filename (used for path searching)
    # System apps (notepad, calc, etc.) are always found via PATH.
    # Everything else is located by _find_executable().
    _APP_MAP = {
        # --- Windows built-ins (always on PATH) ---
        "notepad":              "notepad.exe",
        "calculator":           "calc.exe",
        "paint":                "mspaint.exe",
        "task manager":         "taskmgr.exe",
        "file explorer":        "explorer.exe",
        "explorer":             "explorer.exe",
        "powershell":           "powershell.exe",
        "cmd":                  "cmd.exe",
        "terminal":             "wt.exe",
        # --- Microsoft Office ---
        "outlook":              "OUTLOOK.EXE",
        "word":                 "WINWORD.EXE",
        "microsoft word":       "WINWORD.EXE",
        "excel":                "EXCEL.EXE",
        "microsoft excel":      "EXCEL.EXE",
        "powerpoint":           "POWERPNT.EXE",
        "microsoft powerpoint": "POWERPNT.EXE",
        "teams":                "ms-teams.exe",
        "microsoft teams":      "ms-teams.exe",
        # --- Common apps ---
        "discord":              "Discord.exe",
        "spotify":              "Spotify.exe",
        "steam":                "steam.exe",
        "obs":                  "obs64.exe",
        "vlc":                  "vlc.exe",
        "chrome":               "chrome.exe",
        "google chrome":        "chrome.exe",
        "firefox":              "firefox.exe",
        "edge":                 "msedge.exe",
        "microsoft edge":       "msedge.exe",
        "vscode":               "Code.exe",
        "visual studio code":   "Code.exe",
        "slack":                "slack.exe",
        "zoom":                 "Zoom.exe",
        "settings":             "ms-settings:",
    }

    # Common install root directories to search (ordered by likelihood)
    _SEARCH_ROOTS = [
        r"%LOCALAPPDATA%",
        r"%APPDATA%",
        r"%PROGRAMFILES%",
        r"%PROGRAMFILES(X86)%",
        r"%PROGRAMDATA%",
    ]

    def _find_executable(self, exe_name: str) -> str | None:
        """
        Search common Windows install locations for exe_name.
        Returns the full path if found, otherwise None.
        """
        import os
        import glob

        # 1. If it's a URI protocol (ms-settings:, etc.) return as-is
        if ":" in exe_name and not exe_name.endswith(".exe"):
            return exe_name

        # 2. Check if already on PATH (handles notepad.exe, calc.exe, wt.exe, etc.)
        import shutil
        found_on_path = shutil.which(exe_name)
        if found_on_path:
            return found_on_path

        # 3. Search common install directories (up to 3 levels deep)
        for root_env in self._SEARCH_ROOTS:
            root = os.path.expandvars(root_env)
            if not os.path.isdir(root):
                continue
            # glob: root\*\exe, root\*\*\exe, root\*\*\*\exe
            for depth in ("*", "*/*", "*/*/*"):
                pattern = os.path.join(root, depth, exe_name)
                matches = glob.glob(pattern, recursive=False)
                if matches:
                    # Prefer the most recently modified (usually latest version)
                    matches.sort(key=os.path.getmtime, reverse=True)
                    print(f"[FunctionExecutor] Found '{exe_name}' at: {matches[0]}")
                    return matches[0]

        return None

    def _try_direct_launch(self, task: str) -> Dict | None:
        """
        If the task is a simple 'open/launch <app>' command, find the app
        on disk and launch it. Returns None for complex tasks (sent to VLM).
        """
        import re
        import subprocess
        import os

        task_lower = task.lower().strip()

        # Only intercept simple open/launch/start/run commands
        m = re.match(r'^(?:open|launch|start|run)\s+(.+?)\.?$', task_lower)
        if not m:
            return None

        app_phrase = m.group(1).strip()

        # Look up the exe filename from the map
        exe_name = self._APP_MAP.get(app_phrase)
        if not exe_name:
            # Unknown app — try phrase as exe name, fall through to VLM if not found
            exe_name = app_phrase.split()[0] + ".exe"

        print(f"[FunctionExecutor] Direct launch: resolving '{exe_name}' for task: '{task}'")

        # --- Handle URI protocols (ms-settings:, etc.) ---
        if exe_name.endswith(":") or (not exe_name.endswith(".exe") and ":" in exe_name):
            try:
                os.startfile(exe_name)
                return {
                    "success": True,
                    "message": f"Opening {app_phrase.title()}.",
                    "data": {"app": exe_name, "task": task},
                }
            except Exception as e:
                print(f"[FunctionExecutor] URI launch failed: {e}")
                return None

        # --- Find the executable on disk ---
        full_path = self._find_executable(exe_name)

        if not full_path:
            print(f"[FunctionExecutor] Could not find '{exe_name}' anywhere on disk.")
            # Last resort: use Windows 'start' command (searches Start Menu shortcuts)
            try:
                subprocess.Popen(
                    f'start "" "{app_phrase}"',
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return {
                    "success": True,
                    "message": f"Opening {app_phrase.title()}.",
                    "data": {"app": app_phrase, "task": task},
                }
            except Exception as e:
                print(f"[FunctionExecutor] Start-menu fallback failed: {e}")
                return None  # Let VLM agent try

        # --- Launch the found executable ---
        try:
            subprocess.Popen(
                [full_path],
                creationflags=subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"[FunctionExecutor] ✓ Launched '{full_path}'")
            return {
                "success": True,
                "message": f"Opening {app_phrase.title()}.",
                "data": {"app": full_path, "task": task},
            }
        except Exception as e:
            print(f"[FunctionExecutor] Launch failed for '{full_path}': {e}")
            return None


    # ══════════════════════════════════════════════════════════════════════════
    #  New Jarvis Module Integrations
    # ══════════════════════════════════════════════════════════════════════════

    def _system_command(self, params: Dict) -> Dict:
        """Execute system commands: volume, brightness, power, network."""
        from core.system_control import system_controller
        action = params.get("action", "")
        value = params.get("value")

        try:
            if action == "shutdown":
                delay = int(value) if value and value.isdigit() else 60
                ok = system_controller.shutdown(delay)
                return {"success": ok, "message": "Shutting down..." if ok else "Shutdown failed", "data": None}
            elif action == "restart":
                delay = int(value) if value and value.isdigit() else 60
                ok = system_controller.restart(delay)
                return {"success": ok, "message": "Restarting..." if ok else "Restart failed", "data": None}
            elif action == "sleep":
                ok = system_controller.sleep()
                return {"success": ok, "message": "Going to sleep..." if ok else "Sleep failed", "data": None}
            elif action == "lock":
                ok = system_controller.lock()
                return {"success": ok, "message": "Locking workstation..." if ok else "Lock failed", "data": None}
            elif action == "volume_up":
                vol = system_controller.get_volume() or 50
                system_controller.set_volume(min(100, vol + 10))
                return {"success": True, "message": f"Volume set to {min(100, vol + 10)}%", "data": None}
            elif action == "volume_down":
                vol = system_controller.get_volume() or 50
                system_controller.set_volume(max(0, vol - 10))
                return {"success": True, "message": f"Volume set to {max(0, vol - 10)}%", "data": None}
            elif action == "set_volume":
                level = int(value) if value else 50
                ok = system_controller.set_volume(level)
                return {"success": ok, "message": f"Volume set to {level}%" if ok else "Failed", "data": None}
            elif action in ("mute", "unmute"):
                result = system_controller.toggle_mute()
                muted = result if action == "mute" else not result
                return {"success": True, "message": "Muted" if muted else "Unmuted", "data": {"muted": muted}}
            elif action in ("brightness_up", "brightness_down"):
                b = system_controller.get_brightness() or 50
                new_b = min(100, b + 10) if action == "brightness_up" else max(0, b - 10)
                system_controller.set_brightness(new_b)
                return {"success": True, "message": f"Brightness set to {new_b}%", "data": None}
            elif action == "set_brightness":
                level = int(value) if value else 50
                ok = system_controller.set_brightness(level)
                return {"success": ok, "message": f"Brightness set to {level}%" if ok else "Failed", "data": None}
            elif action == "battery_status":
                info = system_controller.get_battery()
                if info.get("available"):
                    status = "charging" if info["charging"] else "discharging"
                    return {"success": True, "message": f"Battery at {info['percent']}% ({status})", "data": info}
                return {"success": False, "message": "No battery detected", "data": None}
            elif action == "network_info":
                info = system_controller.get_network_info()
                ip = info.get("local_ip", "Unknown")
                ssid = info.get("ssid", "Unknown")
                return {"success": True, "message": f"IP: {ip}, Network: {ssid}", "data": info}
            else:
                return {"success": False, "message": f"Unknown system action: {action}", "data": None}
        except Exception as e:
            return {"success": False, "message": f"System command error: {e}", "data": None}

    def _manage_notes(self, params: Dict) -> Dict:
        """Create, read, search, delete notes."""
        from core.notes import notes_manager
        action = params.get("action", "list")
        try:
            if action == "create":
                title = params.get("title", "Untitled")
                body = params.get("body", "")
                note = notes_manager.create(title, body)
                return {"success": True, "message": f"Note created: {title}", "data": note}
            elif action == "read":
                note_id = params.get("note_id", "")
                note = notes_manager.get(note_id)
                if note:
                    return {"success": True, "message": f"Note: {note['title']}", "data": note}
                return {"success": False, "message": "Note not found", "data": None}
            elif action == "search":
                query = params.get("query", "")
                results = notes_manager.search(query)
                count = len(results)
                return {"success": True, "message": f"Found {count} note(s)", "data": {"results": results}}
            elif action == "delete":
                note_id = params.get("note_id", "")
                ok = notes_manager.delete(note_id)
                return {"success": ok, "message": "Note deleted" if ok else "Note not found", "data": None}
            else:
                results = notes_manager.list()
                count = len(results)
                return {"success": True, "message": f"You have {count} note(s)", "data": {"notes": results}}
        except Exception as e:
            return {"success": False, "message": f"Notes error: {e}", "data": None}

    def _send_email(self, params: Dict) -> Dict:
        """Send an email via configured SMTP."""
        from core.email_manager import email_manager
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")
        if not to:
            return {"success": False, "message": "No recipient specified", "data": None}
        return email_manager.send_from_settings(to, subject, body)

    def _read_emails(self, params: Dict) -> Dict:
        """Read recent emails from configured IMAP."""
        from core.email_manager import email_manager
        limit = int(params.get("limit", 5))
        result = email_manager.read_recent_from_settings(limit=limit)
        if result.get("success") and result.get("emails"):
            emails = result["emails"]
            summary = [f"{e['from']}: {e['subject']}" for e in emails[:limit]]
            return {
                "success": True,
                "message": f"Found {len(emails)} recent emails",
                "data": {"emails": emails, "summary": summary},
            }
        return result

    def _clipboard_action(self, params: Dict) -> Dict:
        """Read, write, or manage clipboard."""
        from core.clipboard import clipboard_manager
        action = params.get("action", "read")
        try:
            if action == "read":
                text = clipboard_manager.get_text()
                if text:
                    preview = text[:200] + ("..." if len(text) > 200 else "")
                    return {"success": True, "message": f"Clipboard: {preview}", "data": {"text": text}}
                return {"success": False, "message": "Clipboard is empty", "data": None}
            elif action == "write":
                text = params.get("text", "")
                if not text:
                    return {"success": False, "message": "No text to write", "data": None}
                ok = clipboard_manager.set_text(text)
                return {"success": ok, "message": "Copied to clipboard" if ok else "Failed", "data": None}
            elif action == "append":
                text = params.get("text", "")
                ok = clipboard_manager.append(text)
                return {"success": ok, "message": "Appended to clipboard" if ok else "Failed", "data": None}
            elif action == "history":
                items = clipboard_manager.get_history(limit=10)
                return {"success": True, "message": f"Clipboard history: {len(items)} item(s)", "data": {"history": items}}
            elif action == "clear":
                clipboard_manager.clear_history()
                return {"success": True, "message": "Clipboard history cleared", "data": None}
            return {"success": False, "message": f"Unknown action: {action}", "data": None}
        except Exception as e:
            return {"success": False, "message": f"Clipboard error: {e}", "data": None}

    def _file_operations(self, params: Dict) -> Dict:
        """Find files, disk usage, organize directories."""
        from core.file_ops import file_ops
        action = params.get("action", "disk_usage")
        path = params.get("path")
        pattern = params.get("pattern")
        try:
            if action == "find":
                results = file_ops.find(pattern or "*", path)
                count = len(results)
                return {"success": True, "message": f"Found {count} file(s)", "data": {"files": results}}
            elif action == "disk_usage":
                info = file_ops.disk_usage(path)
                return {
                    "success": True,
                    "message": f"Disk: {info['used_hr']} used of {info['total_hr']} ({info['percent']}%)",
                    "data": info,
                }
            elif action == "list_dir":
                entries = file_ops.list_directory(path or ".")
                return {"success": True, "message": f"Listed {len(entries)} item(s)", "data": {"entries": entries}}
            elif action == "organize_downloads":
                result = file_ops.organize_downloads(path)
                count = result.get("total_moved", 0)
                return {"success": True, "message": f"Organized {count} file(s)", "data": result}
            elif action == "create_dir":
                ok = file_ops.create_directory(path or ".")
                return {"success": ok, "message": "Directory created" if ok else "Failed", "data": None}
            return {"success": False, "message": f"Unknown action: {action}", "data": None}
        except Exception as e:
            return {"success": False, "message": f"File ops error: {e}", "data": None}

    def _get_stock_price(self, params: Dict) -> Dict:
        """Get current stock price."""
        from core.finance import finance_manager
        symbol = params.get("symbol", "").upper()
        if not symbol:
            return {"success": False, "message": "No symbol specified", "data": None}
        data = finance_manager.stock_price_with_change(symbol)
        if data and data.get("price") is not None:
            change = data.get("change_pct")
            direction = data.get("direction", "flat")
            change_str = f" ({'+' if direction == 'up' else ''}{change}%)" if change is not None else ""
            return {
                "success": True,
                "message": f"{symbol}: ${data['price']}{change_str}",
                "data": data,
            }
        return {"success": False, "message": f"Could not fetch price for {symbol}", "data": None}

    def _convert_currency(self, params: Dict) -> Dict:
        """Convert between currencies."""
        from core.finance import finance_manager
        amount = float(params.get("amount", 1))
        from_c = params.get("from_currency", "USD").upper()
        to_c = params.get("to_currency", "EUR").upper()
        data = finance_manager.convert_currency(amount, from_c, to_c)
        if data:
            return {
                "success": True,
                "message": f"{amount} {from_c} = {data['result']} {to_c} (rate: {data['rate']})",
                "data": data,
            }
        return {"success": False, "message": f"Could not convert {from_c} to {to_c}", "data": None}

    def _translate_text(self, params: Dict) -> Dict:
        """Translate text using local Ollama."""
        from core.translator import translator
        text = params.get("text", "")
        target = params.get("target_language", "English")
        if not text:
            return {"success": False, "message": "No text to translate", "data": None}
        translated = translator.translate(text, target)
        if translated:
            return {"success": True, "message": f"Translation ({target}): {translated}", "data": {"original": text, "translated": translated, "language": target}}
        return {"success": False, "message": "Translation failed", "data": None}

    def _control_media(self, params: Dict) -> Dict:
        """Control media playback."""
        from core.media_controller import media_controller
        action = params.get("action", "play_pause")
        query = params.get("query")
        try:
            if action == "play_pause":
                ok = media_controller.play_pause()
                return {"success": ok, "message": "Toggled play/pause" if ok else "Failed", "data": None}
            elif action == "next":
                ok = media_controller.next_track()
                return {"success": ok, "message": "Next track" if ok else "Failed", "data": None}
            elif action == "previous":
                ok = media_controller.previous_track()
                return {"success": ok, "message": "Previous track" if ok else "Failed", "data": None}
            elif action == "stop":
                ok = media_controller.stop()
                return {"success": ok, "message": "Stopped" if ok else "Failed", "data": None}
            elif action == "play_youtube":
                if not query:
                    return {"success": False, "message": "No search query", "data": None}
                url = media_controller.play_youtube(query)
                if url:
                    return {"success": True, "message": f"Playing '{query}' on YouTube", "data": {"url": url}}
                return {"success": False, "message": f"Could not find '{query}' on YouTube", "data": None}
            elif action == "search_music":
                if not query:
                    return {"success": False, "message": "No search query", "data": None}
                url = media_controller.search_music(query)
                if url:
                    return {"success": True, "message": f"Found music for '{query}'", "data": {"url": url}}
                return {"success": False, "message": f"Could not find music for '{query}'", "data": None}
            return {"success": False, "message": f"Unknown action: {action}", "data": None}
        except Exception as e:
            return {"success": False, "message": f"Media control error: {e}", "data": None}

    def _network_tools(self, params: Dict) -> Dict:
        """Network diagnostics."""
        from core.network_tools import network_tools
        action = params.get("action", "public_ip")
        target = params.get("target")
        try:
            if action == "public_ip":
                ip = network_tools.public_ip()
                if ip:
                    return {"success": True, "message": f"Your public IP: {ip}", "data": {"ip": ip}}
                return {"success": False, "message": "Could not determine public IP", "data": None}
            elif action == "public_ip_info":
                info = network_tools.public_ip_info()
                if info and info.get("ip"):
                    parts = [f"IP: {info['ip']}"]
                    if info.get("city"): parts.append(f"City: {info['city']}")
                    if info.get("country"): parts.append(f"Country: {info['country']}")
                    if info.get("isp"): parts.append(f"ISP: {info['isp']}")
                    return {"success": True, "message": " | ".join(parts), "data": info}
                return {"success": False, "message": "Could not get IP info", "data": None}
            elif action == "ping":
                host = target or "8.8.8.8"
                result = network_tools.ping(host)
                alive = result.get("alive", False)
                avg = result.get("avg_ms")
                loss = result.get("packet_loss_pct", 100)
                msg = f"{host}: {'alive' if alive else 'dead'}"
                if avg is not None: msg += f", avg {avg}ms"
                if loss is not None: msg += f", {loss}% loss"
                return {"success": True, "message": msg, "data": result}
            elif action == "dns_lookup":
                host = target or "google.com"
                ips = network_tools.dns_lookup(host)
                if ips:
                    return {"success": True, "message": f"{host} resolves to: {', '.join(ips[:5])}", "data": {"host": host, "ips": ips}}
                return {"success": False, "message": f"Could not resolve {host}", "data": None}
            return {"success": False, "message": f"Unknown action: {action}", "data": None}
        except Exception as e:
            return {"success": False, "message": f"Network tools error: {e}", "data": None}


    def _mcp_tool_call(self, params: Dict) -> Dict:
        """
        Execute a generic MCP tool call via core/mcp_client.py.

        Expected params (from router schema):
          - tool_id: "<serverId>:<toolName>"
          - arguments: JSON string or dict of tool arguments
        """
        from core.mcp_client import mcp_client

        tool_id = params.get("tool_id") or params.get("toolId")
        arguments = params.get("arguments")
        if arguments is None:
            arguments = params.get("argument")

        if not tool_id:
            return {
                "success": False,
                "message": "Missing MCP tool_id (expected '<serverId>:<toolName>').",
                "data": None,
            }

        result = mcp_client.execute(tool_id=tool_id, arguments=arguments)
        # Ensure shape
        if not isinstance(result, dict) or "success" not in result:
            return {"success": False, "message": "Invalid MCP client response.", "data": None}

        return result

    def _http_get(self, params: Dict) -> Dict:
        """Read-only HTTP GET. Returns status code + size-capped text body.

        Used by API-driven live agents (GitHub, generic REST). Only http/https
        URLs are allowed; the body is capped at 100 KB of text.
        """
        url = (params.get("url") or "").strip()
        if not url or not url.startswith(("http://", "https://")):
            return {"success": False,
                    "message": "Invalid or missing URL (must be http/https).",
                    "data": None}
        MAX_BODY = 100_000
        try:
            import requests
            headers = {"User-Agent": "Plia-Agent/1.0"}
            resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
            body = (resp.text or "")[:MAX_BODY]
            return {
                "success": bool(resp.ok),
                "message": f"HTTP {resp.status_code} ({len(body)} chars)",
                "data": {
                    "status_code": resp.status_code,
                    "body": body,
                    "url": resp.url,
                },
            }
        except Exception as e:
            return {"success": False, "message": f"HTTP GET failed: {e}", "data": None}

    def _list_plia_features(self, params: Dict) -> Dict:
        """Authoritative inventory of Plia's capabilities — for live agents
        that compare Plia against external projects (e.g. Jarvis-style repos).

        The `tools` list is auto-discovered from this class's dispatch chain
        so it stays in sync when new tools are added. The `capabilities` map
        is curated text describing higher-level features that aren't single
        tools (voice pipeline, multi-agent orchestration, UI surfaces, etc.).
        """
        import inspect
        import re

        try:
            dispatch_src = inspect.getsource(self.execute)
        except (OSError, TypeError):
            dispatch_src = ""
        tools = sorted(set(re.findall(r'func_name\s*==\s*"(\w+)"', dispatch_src)))
        # list_plia_features itself shouldn't appear as an "external" tool
        tools = [t for t in tools if t != "list_plia_features"]
        # Append any user-installed plugin tools so agents can discover them.
        try:
            from core.plugins import registry as _plugins
            tools.extend(_plugins.names())
        except Exception:
            pass

        capabilities = {
            "voice_pipeline": [
                "Wake-word activation via Porcupine (jarvis / terminator / computer / ...)",
                "Speech-to-text via RealTimeSTT + Whisper (CUDA if available)",
                "Text-to-speech via Piper (multiple voices, length/volume control)",
                "Multi-turn wizard mode (STT primed for follow-up — no repeated wake word)",
            ],
            "live_agents": [
                "Scheduled / on-demand / quota triggers",
                "Tool-loop executor (LLM-driven, calls allowed tools via Ollama)",
                "Script executor (runs a generated .py file as a subprocess)",
                "Multi-channel notify: tts, chat, comm_log, file, toast_card (combinable)",
                "Per-agent chat session (results land in their own sidebar entry)",
                "Per-agent run log at ~/.plia_ai/agent_results/<id>.log",
                "Quota auto-termination + run history (50-entry FIFO cap)",
                "Missed-tick catch-up on startup for persistent scheduled agents",
                "Hallucination guard: forces tool use before answering",
            ],
            "multi_agent_system": [
                "Role hierarchy (primary + sub-agents) loaded from YAML",
                "AgentTaskManager with on_complete callbacks",
                "ResultDispatcher fan-out via Qt signals",
                "Process-wide singleton runtime (one store, one scheduler)",
            ],
            "ui": [
                "Active Agents tab with Run/Stop/Edit/Delete + history per agent",
                "Agent List tab showing live + custom agents",
                "Dashboard with communication log, system monitor, agent cards",
                "Settings tab with model picker, voice config, search backend",
                "Chat with persistent SQLite history + session sidebar",
                "Briefing tab (RSS / morning digest), Planner (calendar, tasks, timer, alarm)",
                "Model Browser (hardware-aware LLM recommendations)",
            ],
            "search": [
                "Brave Search API (primary if key configured)",
                "DuckDuckGo via ddgs (fallback, no key needed)",
                "Backend selectable in Settings → Web Search",
            ],
            "models": [
                "Local LLM via Ollama (default qwen3:8b for tool use)",
                "Function-Gemma router for intent classification",
                "qwen2.5vl:7b vision model for desktop / screenshot agent",
                "Whisper-base STT, Piper TTS",
            ],
            "integrations": [
                "Email read/send via IMAP/SMTP",
                "Calendar event creation, task list, notes",
                "Weather (BOM AU + Open-Meteo)",
                "News via RSS feeds",
                "Stocks, currency conversion, translation",
                "Screen control / desktop agent (VLM screenshots + mouse/keyboard)",
                "MCP (Model Context Protocol) tool calls via mcp_tool_call",
            ],
            "privacy_and_local": [
                "Local-first: runs on user's machine, no required cloud calls",
                "Redaction of sensitive data (emails, phones, secrets) before LLM",
                "Persistent settings at ~/.plia/settings.json",
                "Agent state at ~/.plia_ai/agent_state.json + roles/*.yml",
            ],
        }

        return {
            "success": True,
            "message": (
                f"Plia inventory: {len(tools)} agent-callable tools, "
                f"{sum(len(v) for v in capabilities.values())} capabilities "
                f"across {len(capabilities)} categories"
            ),
            "data": {
                "name": "Plia",
                "tagline": "Pocket Local Intelligent Assistant — voice-driven local AI",
                "tools": tools,
                "capabilities": capabilities,
            },
        }

    def _github_readme(self, params: Dict) -> Dict:
        """Fetch the raw README markdown for a GitHub repository.

        Accepts:
          - params['repo'] = 'owner/repo'                       (preferred)
          - params['url']  = 'https://github.com/owner/repo'    (any GitHub URL — extra path components ignored)

        Uses the GitHub REST API which serves raw markdown directly when
        the Accept: application/vnd.github.raw header is set. Unauthenticated
        requests are rate-limited to 60/hour by GitHub.
        """
        import re
        raw_target = (params.get("repo") or params.get("url")
                      or params.get("query") or "").strip()
        if not raw_target:
            return {"success": False,
                    "message": ("Provide repo='owner/name' or "
                                "url='https://github.com/owner/name'."),
                    "data": None}

        m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", raw_target)
        if m:
            owner, repo = m.group(1), m.group(2)
        elif raw_target.count("/") == 1 and not raw_target.startswith("http"):
            owner, repo = raw_target.split("/", 1)
        else:
            return {"success": False,
                    "message": f"Could not parse '{raw_target}' as a GitHub repo.",
                    "data": None}
        repo = repo.removesuffix(".git").rstrip("/")

        try:
            import requests
            api_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
            resp = requests.get(
                api_url,
                headers={"Accept": "application/vnd.github.raw",
                         "User-Agent": "Plia-Agent/1.0"},
                timeout=15,
            )
            if resp.status_code == 200:
                body = (resp.text or "")[:100_000]
                return {
                    "success": True,
                    "message": f"Fetched README for {owner}/{repo} ({len(body)} chars).",
                    "data": {
                        "repo": f"{owner}/{repo}",
                        "url": f"https://github.com/{owner}/{repo}",
                        "readme": body,
                    },
                }
            if resp.status_code == 404:
                return {"success": False,
                        "message": f"{owner}/{repo} has no README (HTTP 404).",
                        "data": None}
            if resp.status_code == 403:
                return {"success": False,
                        "message": ("GitHub API rate-limited (HTTP 403). "
                                    "Unauthenticated limit is 60/hour."),
                        "data": None}
            return {"success": False,
                    "message": f"GitHub API HTTP {resp.status_code} for {owner}/{repo}.",
                    "data": None}
        except Exception as e:
            return {"success": False, "message": f"github_readme failed: {e}", "data": None}

    def _list_agents(self, params: Dict) -> Dict:
        """List every live agent in the runtime so a manager agent can decide
        which sub-agent(s) to invoke via run_agent."""
        try:
            from core.agent_runtime import get_runtime
            from core.multi_agent import multi_agent_system
            rt = get_runtime()
            agents = []
            for s in rt.store.all():
                role = multi_agent_system.roles.get(s.role_id)
                desc = ""
                if role is not None:
                    resp = getattr(role, "responsibilities", None) or []
                    if resp:
                        desc = resp[0]
                agents.append({
                    "role_id":      s.role_id,
                    "name":         s.display_name,
                    "executor":     s.executor,
                    "trigger":      s.trigger,
                    "status":       s.status,
                    "description":  desc,
                })
            return {
                "success": True,
                "message": f"{len(agents)} live agent(s) available.",
                "data": {"agents": agents},
            }
        except Exception as e:
            return {"success": False, "message": f"list_agents failed: {e}", "data": None}

    def _run_agent(self, params: Dict) -> Dict:
        """Run another live agent synchronously and return its RunResult.

        Lets one agent call another as a sub-tool (e.g. a Manager that calls
        a Searcher and a Formatter and stitches the outputs together).

        Params:
          agent / role_id : the sub-agent to invoke (role_id, preferred)
          name            : alternatively, match by display_name (case-insensitive)
          task            : optional one-off task override for this call
        """
        # ── Recursion guard ───────────────────────────────────────────────
        depth = getattr(_RUN_AGENT_DEPTH, "value", 0)
        if depth >= _RUN_AGENT_MAX_DEPTH:
            return {
                "success": False,
                "message": (
                    f"run_agent recursion limit ({_RUN_AGENT_MAX_DEPTH}) exceeded. "
                    "Refusing to call another agent from this depth."
                ),
                "data": None,
            }

        role_id = (params.get("agent") or params.get("role_id") or "").strip()
        name    = (params.get("name") or "").strip()
        task_override = (params.get("task") or "").strip()

        try:
            from core.agent_runtime import get_runtime
            rt = get_runtime()
        except Exception as e:
            return {"success": False, "message": f"agent runtime unavailable: {e}", "data": None}

        state = rt.store.get(role_id) if role_id else None
        if state is None and name:
            for s in rt.store.all():
                if s.display_name.lower() == name.lower():
                    state = s
                    break
        if state is None:
            return {
                "success": False,
                "message": f"No live agent matched (agent={role_id!r}, name={name!r}).",
                "data": None,
            }
        if state.status == "terminated":
            return {
                "success": False,
                "message": f"Agent {state.display_name!r} is terminated; cannot invoke.",
                "data": None,
            }

        instance = rt._get_instance(state.role_id)
        if instance is None:
            return {
                "success": False,
                "message": f"Agent instance for {state.role_id!r} is not registered.",
                "data": None,
            }

        try:
            runner = rt._build_runner(state)
        except Exception as e:
            return {"success": False, "message": f"could not build runner: {e}", "data": None}
        final_task = task_override or state.display_name

        # Bump depth, run, restore.
        _RUN_AGENT_DEPTH.value = depth + 1
        try:
            result = runner(agent=instance, task=final_task, context="")
        except Exception as e:
            return {"success": False, "message": f"sub-agent crashed: {e}", "data": None}
        finally:
            _RUN_AGENT_DEPTH.value = depth

        return {
            "success": True,
            "message": f"{state.display_name}: {result.summary}",
            "data": {
                "agent":       state.display_name,
                "role_id":     state.role_id,
                "success":     bool(result.success),
                "summary":     result.summary,
                "items_found": result.items_found,
                "items":       result.items,
                "error":       result.error,
                "details":     result.details,
            },
        }


# Global instance
executor = FunctionExecutor()
