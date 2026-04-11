"""
Desktop Controller - Full-screen capture and mouse/keyboard control.

Fixes applied based on research:
  1. Apps are launched via URI protocols or resolved paths, not bare names.
  2. After launch, win32gui polls until the target window appears and brings
     it to the foreground using the SendKeys('%') workaround that bypasses
     Windows focus-stealing protection.
  3. Screenshots are taken after the target window is confirmed foreground,
     so the VLM always sees the right app - not Plia behind it.
  4. pyautogui is used for mouse/keyboard once the window is focused.

Requirements:
    mss>=9.0.0
    pyautogui>=0.9.54
    pywin32>=306        <- required for win32gui window focusing
    Pillow>=10.0.0
"""

import base64
import io
import os
import subprocess
import time

import mss
import pyautogui
import win32con
import win32gui
from PIL import Image

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.10

# ---------------------------------------------------------------------------
# App launch registry
# ---------------------------------------------------------------------------
_APP_REGISTRY = {
    "discord":      "discord://",
    "spotify":      "spotify://",
    "slack":        "slack://",
    "steam":        "steam://",
    "teams":        "msteams://",
    "notepad":      "notepad.exe",
    "wordpad":      "write.exe",
    "calculator":   "calc.exe",
    "explorer":     "explorer.exe",
    "cmd":          "cmd.exe",
    "powershell":   "powershell.exe",
    "task manager": "taskmgr.exe",
    "paint":        "mspaint.exe",
    "word":         "winword.exe",
    "excel":        "excel.exe",
    "powerpoint":   "powerpnt.exe",
    "outlook":      "outlook.exe",
    "onenote":      "onenote.exe",
    "chrome":       r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    "edge":         r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    "firefox":      r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
    "telegram":     r"%APPDATA%\Telegram Desktop\Telegram.exe",
    "zoom":         r"%LOCALAPPDATA%\Zoom\bin\Zoom.exe",
    "obs":          r"%ProgramFiles%\obs-studio\bin\64bit\obs64.exe",
    "vlc":          r"%ProgramFiles%\VideoLAN\VLC\vlc.exe",
    "vscode":       r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
}

_WINDOW_KEYWORDS = {
    "discord":      ["discord"],
    "spotify":      ["spotify"],
    "slack":        ["slack"],
    "steam":        ["steam"],
    "teams":        ["microsoft teams", "teams"],
    "notepad":      ["notepad"],
    "wordpad":      ["wordpad"],
    "calculator":   ["calculator"],
    "explorer":     ["file explorer", "this pc", "documents", "downloads"],
    "chrome":       ["google chrome", "chrome"],
    "edge":         ["microsoft edge", "edge"],
    "firefox":      ["mozilla firefox", "firefox"],
    "word":         ["word"],
    "excel":        ["excel"],
    "powerpoint":   ["powerpoint"],
    "outlook":      ["outlook"],
    "telegram":     ["telegram"],
    "zoom":         ["zoom"],
    "obs":          ["obs studio", "obs"],
    "vlc":          ["vlc media player", "vlc"],
    "vscode":       ["visual studio code", "vs code"],
    "task manager": ["task manager"],
    "paint":        ["paint"],
}


class DesktopController:
    MODEL_SPACE  = 1000
    JPEG_QUALITY = 70
    MAX_WIDTH    = 1280
    MAX_HEIGHT   = 720

    def __init__(self):
        self._sct      = None
        self._screen_w = 0
        self._screen_h = 0
        self._shell    = None

    def start(self):
        self._sct = mss.mss()
        mon = self._sct.monitors[1]
        self._screen_w = mon["width"]
        self._screen_h = mon["height"]
        try:
            import win32com.client
            self._shell = win32com.client.Dispatch("WScript.Shell")
        except Exception as e:
            print(f"[DesktopController] WScript.Shell unavailable: {e}")
        print(f"[DesktopController] Screen: {self._screen_w}x{self._screen_h}")

    def stop(self):
        if self._sct:
            self._sct.close()
            self._sct = None

    def get_screenshot(self) -> str:
        if not self._sct:
            self.start()
        raw = self._sct.grab(self._sct.monitors[1])
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        img.thumbnail((self.MAX_WIDTH, self.MAX_HEIGHT), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=self.JPEG_QUALITY)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def _scale(self, x: int, y: int):
        sx = int((x / self.MODEL_SPACE) * self._screen_w)
        sy = int((y / self.MODEL_SPACE) * self._screen_h)
        return sx, sy

    def _find_window(self, keywords: list) -> int:
        found = []
        def _cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).lower()
                if any(kw in title for kw in keywords):
                    found.append(hwnd)
        win32gui.EnumWindows(_cb, None)
        return found[0] if found else None

    def _bring_window_to_front(self, hwnd: int) -> bool:
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            # SendKeys('%') trick: sends a no-op Alt keystroke so Windows
            # treats our process as having received recent input, which is
            # required for SetForegroundWindow to work from a background thread.
            if self._shell:
                self._shell.SendKeys("%")
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.4)
            return True
        except Exception as e:
            print(f"[DesktopController] bring_to_front error: {e}")
            return False

    def _wait_for_window(self, keywords: list, timeout: float = 10.0) -> int:
        deadline = time.time() + timeout
        while time.time() < deadline:
            hwnd = self._find_window(keywords)
            if hwnd:
                return hwnd
            time.sleep(0.5)
        return None

    def launch_app(self, app_name: str, wait: float = 6.0) -> bool:
        """
        Open an application by spoken name and bring its window to front.

        Priority:
          1. Check if app is already open — just re-focus it.
          2. Look up URI protocol or executable path in _APP_REGISTRY.
          3. URI (contains "://") -> os.startfile().
          4. Path -> expand env vars -> subprocess.Popen().
          5. Fallback: subprocess.Popen with shell=True.
          6. Poll win32gui until window appears, then SetForegroundWindow.
        """
        name_lower = app_name.lower().strip()
        launch_cmd = _APP_REGISTRY.get(name_lower, app_name)
        keywords   = _WINDOW_KEYWORDS.get(name_lower, [name_lower])

        print(f"[DesktopController] Launch '{app_name}' -> '{launch_cmd}'")

        # Already open?
        hwnd = self._find_window(keywords)
        if hwnd:
            print(f"[DesktopController] Already open, focusing.")
            return self._bring_window_to_front(hwnd)

        # Launch
        try:
            if "://" in launch_cmd:
                os.startfile(launch_cmd)
            else:
                expanded = os.path.expandvars(launch_cmd)
                if os.path.exists(expanded):
                    subprocess.Popen([expanded], shell=False)
                else:
                    subprocess.Popen(launch_cmd, shell=True)
        except Exception as e:
            print(f"[DesktopController] Launch error: {e}")
            try:
                os.startfile(app_name)
            except Exception as e2:
                print(f"[DesktopController] Fallback failed: {e2}")
                return False

        # Wait and focus
        print(f"[DesktopController] Waiting for window {keywords}...")
        hwnd = self._wait_for_window(keywords, timeout=wait)
        if hwnd:
            print(f"[DesktopController] Window found (hwnd={hwnd}), focusing.")
            return self._bring_window_to_front(hwnd)
        else:
            print(f"[DesktopController] Window not found after {wait}s.")
            return False

    def execute_action(self, action: str, params: dict):
        coords = params.get("coordinate", [500, 500])
        x, y = self._scale(coords[0], coords[1])

        if action == "mouse_move":
            pyautogui.moveTo(x, y, duration=0.15)
        elif action == "left_click":
            pyautogui.click(x, y)
        elif action == "right_click":
            pyautogui.rightClick(x, y)
        elif action == "middle_click":
            pyautogui.middleClick(x, y)
        elif action == "double_click":
            pyautogui.doubleClick(x, y)
        elif action == "triple_click":
            pyautogui.click(x, y, clicks=3, interval=0.1)
        elif action == "left_click_drag":
            pyautogui.mouseDown()
            pyautogui.moveTo(x, y, duration=0.3)
            pyautogui.mouseUp()
        elif action == "type":
            text = params.get("text", "")
            try:
                import pyperclip
                pyperclip.copy(text)
                pyautogui.hotkey("ctrl", "v")
            except ImportError:
                pyautogui.write(text, interval=0.04)
        elif action == "key":
            keys = params.get("keys", "")
            if isinstance(keys, list):
                pyautogui.hotkey(*[k.lower() for k in keys])
            else:
                key_map = {"return": "enter", "escape": "esc",
                           "delete": "del", "backspace": "backspace"}
                pyautogui.press(key_map.get(keys.lower(), keys.lower()))
        elif action == "scroll":
            pixels = params.get("pixels", 300)
            pyautogui.scroll(-(pixels // 80), x=x, y=y)
        elif action == "hscroll":
            pixels = params.get("pixels", 300)
            pyautogui.hscroll(-(pixels // 80), x=x, y=y)
        elif action == "launch":
            self.launch_app(params.get("app", ""), wait=6.0)
        elif action == "wait":
            time.sleep(params.get("time", 1.0))
        elif action == "terminate":
            pass
        else:
            print(f"[DesktopController] Unknown action: {action}")

        time.sleep(0.30)
