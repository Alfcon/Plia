"""
agent_watchers.py — Conditional triggers for live agents.

When an AgentState has ``trigger == 'conditional'`` and a ``condition`` dict,
the scheduler hands it off to this module instead of arming a QTimer in
fixed-interval cadence mode. Each supported condition is a polling-based
watcher: it checks for "something changed" on its own interval, and on a
positive hit fires ``scheduler.fire_now(role_id)``.

Condition shapes (stored in ``AgentState.condition``):

  - File watch::

        {"type": "file_watch", "path": "/some/file/or/dir",
         "poll_interval_sec": 30, "watch_subdirs": false}

    Fires when ``mtime`` of the path (or any direct child if it's a directory,
    or any descendant if watch_subdirs is true) changes since the last check.

  - HTTP poll::

        {"type": "http_poll", "url": "https://example.com/page",
         "poll_interval_sec": 300}

    Fires when ``sha256(response_body)`` differs from the previous successful
    poll's hash. Non-2xx responses are skipped (no fire, no state update).

  - RSS feed::

        {"type": "rss", "url": "https://example.com/feed",
         "poll_interval_sec": 600}

    Fires once per never-seen-before entry id (or link if no id).

Watcher state (``seen_ids`` for RSS, ``last_hash`` / ``last_mtime``) is kept
in-memory; on Plia restart all watchers re-baseline their "current" state
so the first run after restart doesn't fire spuriously.
"""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal


# ──────────────────────────────────────────────────────────────────────────
#  Individual watcher classes (each one is pure logic + state, no Qt)
# ──────────────────────────────────────────────────────────────────────────


class _FileWatcher:
    """Polls ``mtime`` of a file or directory."""

    def __init__(self, *, path: str, watch_subdirs: bool = False):
        self.path = Path(path).expanduser()
        self.watch_subdirs = bool(watch_subdirs)
        self._baseline: Optional[float] = None

    def _current_mtime(self) -> Optional[float]:
        if not self.path.exists():
            return None
        if self.path.is_file():
            try:
                return self.path.stat().st_mtime
            except OSError:
                return None
        # Directory: max mtime across (recursive or shallow) children.
        latest = self.path.stat().st_mtime
        try:
            iterator = self.path.rglob("*") if self.watch_subdirs else self.path.iterdir()
            for child in iterator:
                try:
                    m = child.stat().st_mtime
                    if m > latest:
                        latest = m
                except OSError:
                    continue
        except OSError:
            return None
        return latest

    def check(self) -> bool:
        current = self._current_mtime()
        if current is None:
            return False
        if self._baseline is None:
            self._baseline = current
            return False  # establish baseline silently
        if current != self._baseline:
            self._baseline = current
            return True
        return False


class _HttpPollWatcher:
    """Polls a URL, fires when the response body hash changes."""

    def __init__(self, *, url: str, timeout: float = 15.0):
        self.url = url
        self.timeout = float(timeout)
        self._baseline_hash: Optional[str] = None

    def check(self) -> bool:
        try:
            import requests
            resp = requests.get(self.url, timeout=self.timeout,
                                headers={"User-Agent": "Plia-Watcher/1.0"})
            if resp.status_code < 200 or resp.status_code >= 300:
                return False
            body = resp.content or b""
        except Exception as exc:
            print(f"[watcher] http_poll error for {self.url}: {exc}")
            return False
        digest = hashlib.sha256(body).hexdigest()
        if self._baseline_hash is None:
            self._baseline_hash = digest
            return False
        if digest != self._baseline_hash:
            self._baseline_hash = digest
            return True
        return False


class _RssWatcher:
    """Polls an RSS/Atom feed; fires when there's an entry id we haven't seen."""

    def __init__(self, *, url: str, timeout: float = 15.0):
        self.url = url
        self.timeout = float(timeout)
        self._seen: set = set()
        self._initialised = False

    def check(self) -> bool:
        try:
            import feedparser
            # feedparser doesn't take a timeout arg in older versions; use
            # requests to fetch then hand off the body.
            import requests
            resp = requests.get(self.url, timeout=self.timeout,
                                headers={"User-Agent": "Plia-Watcher/1.0"})
            if resp.status_code < 200 or resp.status_code >= 300:
                return False
            parsed = feedparser.parse(resp.content)
        except Exception as exc:
            print(f"[watcher] rss error for {self.url}: {exc}")
            return False

        entries = getattr(parsed, "entries", None) or []
        ids = [
            getattr(e, "id", None) or getattr(e, "link", None) or getattr(e, "title", None)
            for e in entries
        ]
        ids = [str(i) for i in ids if i]
        if not self._initialised:
            self._seen.update(ids)
            self._initialised = True
            return False
        new = [i for i in ids if i not in self._seen]
        if not new:
            return False
        self._seen.update(new)
        return True


# ──────────────────────────────────────────────────────────────────────────
#  WatchManager: owns the watchers, polls them, fires the scheduler
# ──────────────────────────────────────────────────────────────────────────


def _build_watcher(condition: Dict[str, Any]):
    """Construct a watcher from a condition dict. Returns None on bad config."""
    if not isinstance(condition, dict):
        return None
    ctype = (condition.get("type") or "").strip().lower()
    try:
        if ctype == "file_watch":
            path = (condition.get("path") or "").strip()
            if not path:
                return None
            return _FileWatcher(
                path=path,
                watch_subdirs=bool(condition.get("watch_subdirs", False)),
            )
        if ctype == "http_poll":
            url = (condition.get("url") or "").strip()
            if not url:
                return None
            return _HttpPollWatcher(url=url)
        if ctype == "rss":
            url = (condition.get("url") or "").strip()
            if not url:
                return None
            return _RssWatcher(url=url)
    except Exception as exc:
        print(f"[watcher] could not build watcher for {ctype!r}: {exc}")
    return None


class WatchManager(QObject):
    """Manages a single polling thread that checks every registered watcher
    against its own configured interval and fires ``triggered(role_id)`` when
    a watcher detects a change.

    Used by AgentScheduler: when a state has ``trigger == 'conditional'``,
    ``arm()`` registers it here instead of starting a QTimer cadence.
    """

    triggered = Signal(str)  # role_id

    DEFAULT_POLL = 60  # seconds when condition doesn't specify one

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        # role_id → (watcher, interval_sec, next_due_at)
        self._watchers: Dict[str, Dict[str, Any]] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._start_thread()

    # ── lifecycle ────────────────────────────────────────────────────────
    def _start_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="WatchManager",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ── registration ─────────────────────────────────────────────────────
    def register(self, role_id: str, condition: Dict[str, Any]) -> bool:
        """Add or replace a watcher for ``role_id``. Returns True if a watcher
        was successfully built; False if the condition was malformed.
        """
        watcher = _build_watcher(condition or {})
        if watcher is None:
            self.unregister(role_id)
            return False
        try:
            interval = int(condition.get("poll_interval_sec", self.DEFAULT_POLL))
        except (TypeError, ValueError):
            interval = self.DEFAULT_POLL
        interval = max(5, interval)  # don't allow hammering
        with self._lock:
            self._watchers[role_id] = {
                "watcher":    watcher,
                "interval":   interval,
                "next_due":   time.time() + interval,
            }
        return True

    def unregister(self, role_id: str) -> None:
        with self._lock:
            self._watchers.pop(role_id, None)

    def watched(self) -> List[str]:
        with self._lock:
            return list(self._watchers.keys())

    # ── poll loop ────────────────────────────────────────────────────────
    def _run(self) -> None:
        while not self._stop.is_set():
            # Snapshot the watcher table so we can iterate without holding
            # the lock while doing potentially slow I/O.
            with self._lock:
                snapshot = list(self._watchers.items())

            now = time.time()
            for role_id, entry in snapshot:
                if entry["next_due"] > now:
                    continue
                watcher = entry["watcher"]
                try:
                    hit = bool(watcher.check())
                except Exception as exc:
                    print(f"[watcher] check error for {role_id!r}: {exc}")
                    hit = False
                # Reschedule the next check regardless of outcome.
                with self._lock:
                    if role_id in self._watchers:
                        self._watchers[role_id]["next_due"] = (
                            time.time() + entry["interval"]
                        )
                if hit:
                    try:
                        self.triggered.emit(role_id)
                    except Exception as exc:
                        print(f"[watcher] could not emit triggered: {exc}")

            # Short sleep — granular enough to catch new registrations
            # without burning CPU. Real wakes are driven by each watcher's
            # own interval, not this tick.
            self._stop.wait(timeout=2.0)
