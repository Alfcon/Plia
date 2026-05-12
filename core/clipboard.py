"""
Clipboard Manager — get/set clipboard content, history.
Uses pyperclip (already in Plia's requirements.txt).
"""

from collections import deque
from typing import Optional
from datetime import datetime

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False


class ClipboardManager:

    MAX_HISTORY = 50

    def __init__(self):
        self._history: deque[str] = deque(maxlen=self.MAX_HISTORY)
        self._last_known: str = ""

    def _poll_history(self):
        """Check if clipboard has new content and add to history."""
        if not HAS_PYPERCLIP:
            return
        try:
            current = pyperclip.paste()
            if current and current != self._last_known:
                self._history.append(current)
                self._last_known = current
        except Exception:
            pass

    def get_text(self) -> Optional[str]:
        """Return current clipboard text content."""
        if not HAS_PYPERCLIP:
            return None
        try:
            text = pyperclip.paste()
            self._last_known = text
            return text
        except Exception:
            return None

    def set_text(self, text: str) -> bool:
        """Set clipboard text content. Returns True on success."""
        if not HAS_PYPERCLIP or not text:
            return False
        try:
            pyperclip.copy(text)
            self._history.append(text)
            self._last_known = text
            return True
        except Exception:
            return False

    def append(self, text: str) -> bool:
        """Append text to current clipboard content with newline."""
        current = self.get_text() or ""
        return self.set_text(current + "\n" + text)

    def get_history(self, limit: int = 10) -> list:
        """Return recent clipboard history entries."""
        self._poll_history()
        items = list(self._history)
        items.reverse()
        return items[:limit]

    def clear_history(self):
        """Clear clipboard history (does not clear system clipboard)."""
        self._history.clear()

    @property
    def available(self) -> bool:
        return HAS_PYPERCLIP


clipboard_manager = ClipboardManager()
