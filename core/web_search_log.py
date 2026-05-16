"""
web_search_log.py — Append-only log of web-search-style agent results.

When a live agent's notify list includes "web_searches", every successful run
appends one entry here. The Web Searches tab reads and renders the log.

Stored at ~/.plia_ai/web_searches.json as a JSON list, oldest first. Capped
at MAX_ENTRIES so the file doesn't grow unbounded.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal


PLIA_DIR = Path.home() / ".plia_ai"
DEFAULT_PATH = PLIA_DIR / "web_searches.json"
MAX_ENTRIES = 500


class WebSearchLog(QObject):
    """Thread-safe, signal-emitting log of web-search agent entries."""

    entry_added = Signal(dict)   # the newly-added entry payload
    cleared = Signal()

    def __init__(self, path: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self._path = Path(path) if path else DEFAULT_PATH
        self._lock = threading.Lock()
        self._entries: List[Dict[str, Any]] = []
        self.load()

    # ── Persistence ───────────────────────────────────────────────────────
    def load(self) -> None:
        with self._lock:
            self._entries = []
            if not self._path.exists():
                return
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"[WebSearchLog] load failed: {exc}")
                return
            if isinstance(raw, list):
                self._entries = [e for e in raw if isinstance(e, dict)]

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._entries, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"[WebSearchLog] save failed: {exc}")

    # ── Public API ────────────────────────────────────────────────────────
    def add(self, *, role_id: str, agent_name: str, query: str,
            items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Append a new entry. Caps at MAX_ENTRIES (oldest dropped first)."""
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "role_id": role_id,
            "agent_name": agent_name,
            "query": query,
            "items": [
                {
                    "title": i.get("title") or i.get("name") or "?",
                    "url":   i.get("url") or i.get("link") or i.get("href") or "",
                    "body":  i.get("body") or i.get("description")
                              or i.get("summary") or "",
                }
                for i in (items or [])
                if isinstance(i, dict)
            ],
        }
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > MAX_ENTRIES:
                self._entries = self._entries[-MAX_ENTRIES:]
            self._save()
        self.entry_added.emit(entry)
        return entry

    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries = []
            self._save()
        self.cleared.emit()


# Process-wide singleton
log = WebSearchLog()
