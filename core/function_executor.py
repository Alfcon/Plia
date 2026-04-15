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
    
    def execute(self, func_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a function and return structured result.
        
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
                return self._control_desktop(params)
            else:
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
        """
        query = params.get("query", "")

        if not query:
            return {"success": False, "message": "No search query provided", "data": None}

        try:
            # Try ddgs first (metasearch aggregator), fall back to duckduckgo_search
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=20))

            if raw:
                # Normalise all results (body truncated to 300 chars for LLM context)
                formatted = []
                for r in raw:
                    formatted.append({
                        "title": r.get("title", ""),
                        "body":  r.get("body", "")[:300],
                        "url":   r.get("href", ""),
                    })

                return {
                    "success": True,
                    "message": f"Found {len(formatted)} results for '{query}'",
                    "data": {"query": query, "results": formatted},
                }

            return {"success": True, "message": f"No results found for '{query}'", "data": None}

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

    def _control_desktop(self, params: Dict) -> Dict:
        """
        Run a natural language desktop task using the VLM desktop agent.
        For simple 'open X' commands the app is launched directly via subprocess
        without going through the VLM, which is faster and more reliable.
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
            return agent.run_task_sync(task)
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


# Global instance
executor = FunctionExecutor()
