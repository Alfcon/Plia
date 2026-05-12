"""
Media Controller — system media keys, YouTube search, Spotify integration.
"""

import subprocess
import platform
import re
from typing import Optional

import requests

SYSTEM = platform.system()


class MediaController:

    @staticmethod
    def play_pause() -> bool:
        """Toggle play/pause."""
        if SYSTEM == "Windows":
            try:
                import pyautogui
                pyautogui.press("playpause")
                return True
            except ImportError:
                pass
            try:
                subprocess.run(
                    ["powershell", "-c", "(New-Object -ComObject WScript.Shell).SendKeys([char]0xB3)"],
                    capture_output=True, timeout=3,
                )
                return True
            except Exception:
                pass
        elif SYSTEM == "Linux":
            try:
                subprocess.run(["playerctl", "play-pause"], capture_output=True, timeout=3)
                return True
            except Exception:
                pass
        return False

    @staticmethod
    def next_track() -> bool:
        """Skip to next track."""
        if SYSTEM == "Windows":
            try:
                import pyautogui
                pyautogui.press("nexttrack")
                return True
            except ImportError:
                pass
            try:
                subprocess.run(
                    ["powershell", "-c", "(New-Object -ComObject WScript.Shell).SendKeys([char]0xB0)"],
                    capture_output=True, timeout=3,
                )
                return True
            except Exception:
                pass
        elif SYSTEM == "Linux":
            try:
                subprocess.run(["playerctl", "next"], capture_output=True, timeout=3)
                return True
            except Exception:
                pass
        return False

    @staticmethod
    def previous_track() -> bool:
        """Go to previous track."""
        if SYSTEM == "Windows":
            try:
                import pyautogui
                pyautogui.press("prevtrack")
                return True
            except ImportError:
                pass
            try:
                subprocess.run(
                    ["powershell", "-c", "(New-Object -ComObject WScript.Shell).SendKeys([char]0xB1)"],
                    capture_output=True, timeout=3,
                )
                return True
            except Exception:
                pass
        elif SYSTEM == "Linux":
            try:
                subprocess.run(["playerctl", "previous"], capture_output=True, timeout=3)
                return True
            except Exception:
                pass
        return False

    @staticmethod
    def stop() -> bool:
        """Stop playback."""
        if SYSTEM == "Linux":
            try:
                subprocess.run(["playerctl", "stop"], capture_output=True, timeout=3)
                return True
            except Exception:
                pass
        return False

    @staticmethod
    def search_youtube(query: str) -> Optional[str]:
        """Search YouTube and return the first video URL."""
        try:
            resp = requests.get(
                "https://www.youtube.com/results",
                params={"search_query": query},
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            matches = re.findall(r'/watch\?v=([a-zA-Z0-9_-]{11})', resp.text)
            if matches:
                return f"https://www.youtube.com/watch?v={matches[0]}"
        except Exception:
            pass
        return None

    @staticmethod
    def play_youtube(query: str) -> Optional[str]:
        """Search YouTube and open the first result in the browser."""
        url = MediaController.search_youtube(query)
        if url:
            import webbrowser
            webbrowser.open(url)
            return url
        return None

    @staticmethod
    def search_music(query: str) -> Optional[str]:
        """Search for music on YouTube (optimized for music results)."""
        return MediaController.search_youtube(f"{query} music audio")

    @staticmethod
    def spotify_open():
        """Open Spotify desktop app."""
        if SYSTEM == "Windows":
            try:
                subprocess.Popen(["start", "spotify:"], shell=True)
                return True
            except Exception:
                pass
        return False


media_controller = MediaController()
