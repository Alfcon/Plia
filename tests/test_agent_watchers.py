"""Tests for the polling watchers behind conditional triggers.

We exercise the watcher classes in isolation (each `check()` should be silent
on first call to establish a baseline, then return True only when the watched
thing changes). The WatchManager dispatch loop is covered separately by
test_scheduler_conditional via dependency injection.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from core.agent_watchers import (
    _build_watcher,
    _FileWatcher,
    _HttpPollWatcher,
    _RssWatcher,
    WatchManager,
)


# ── _FileWatcher ──────────────────────────────────────────────────────────


def test_filewatcher_silent_on_first_check(tmp_path):
    f = tmp_path / "thing.txt"
    f.write_text("hello")
    w = _FileWatcher(path=str(f))
    assert w.check() is False


def test_filewatcher_fires_when_mtime_changes(tmp_path):
    f = tmp_path / "thing.txt"
    f.write_text("hello")
    w = _FileWatcher(path=str(f))
    assert w.check() is False  # baseline

    # mtime needs to actually move; force it by writing with a +2s timestamp.
    new_ts = f.stat().st_mtime + 2
    f.write_text("changed")
    import os
    os.utime(f, (new_ts, new_ts))

    assert w.check() is True
    # Second check after firing: silent again.
    assert w.check() is False


def test_filewatcher_directory_shallow(tmp_path):
    d = tmp_path / "watched"
    d.mkdir()
    w = _FileWatcher(path=str(d))
    assert w.check() is False  # baseline

    # Add a file -> directory mtime changes.
    new_file = d / "a.txt"
    new_file.write_text("x")
    # Ensure mtime is strictly different on fast filesystems.
    future = d.stat().st_mtime + 2
    import os
    os.utime(d, (future, future))
    assert w.check() is True


def test_filewatcher_returns_false_when_path_missing(tmp_path):
    missing = tmp_path / "nope.txt"
    w = _FileWatcher(path=str(missing))
    assert w.check() is False
    assert w.check() is False  # still no fire after re-check


# ── _HttpPollWatcher ──────────────────────────────────────────────────────


class _StubResp:
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self.content = body


def test_httppollwatcher_fires_on_body_change(monkeypatch):
    bodies = [b"v1", b"v1", b"v2"]
    calls = {"n": 0}

    def fake_get(url, timeout=None, headers=None):
        out = bodies[calls["n"]]
        calls["n"] += 1
        return _StubResp(200, out)

    import requests
    monkeypatch.setattr(requests, "get", fake_get)

    w = _HttpPollWatcher(url="https://example.com")
    assert w.check() is False  # baseline (v1)
    assert w.check() is False  # still v1
    assert w.check() is True   # now v2
    # Next call would need a 4th body; cap at 3 calls.
    assert calls["n"] == 3


def test_httppollwatcher_skips_non_2xx(monkeypatch):
    def fake_get(url, timeout=None, headers=None):
        return _StubResp(503, b"down")

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    w = _HttpPollWatcher(url="https://example.com")
    assert w.check() is False
    assert w.check() is False  # still no baseline established → no fire


def test_httppollwatcher_swallows_exceptions(monkeypatch):
    def fake_get(url, timeout=None, headers=None):
        raise RuntimeError("network down")

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    w = _HttpPollWatcher(url="https://example.com")
    assert w.check() is False


# ── _RssWatcher ───────────────────────────────────────────────────────────


def _make_feed_resp(entry_ids):
    body_items = "".join(
        f"<item><guid>{eid}</guid><title>{eid}</title></item>" for eid in entry_ids
    )
    body = (
        f"<rss><channel>{body_items}</channel></rss>"
    ).encode("utf-8")
    return _StubResp(200, body)


def test_rsswatcher_fires_on_new_entry(monkeypatch):
    seqs = [["a", "b"], ["a", "b"], ["a", "b", "c"]]
    calls = {"n": 0}

    def fake_get(url, timeout=None, headers=None):
        ids = seqs[calls["n"]]
        calls["n"] += 1
        return _make_feed_resp(ids)

    import requests
    monkeypatch.setattr(requests, "get", fake_get)

    w = _RssWatcher(url="https://example.com/feed")
    assert w.check() is False  # baseline {a, b}
    assert w.check() is False  # no change
    assert w.check() is True   # new id "c"
    # And after recording "c", we should be quiet again on a static feed.
    seqs.append(["a", "b", "c"])
    assert w.check() is False


# ── _build_watcher ─────────────────────────────────────────────────────────


def test_build_watcher_file_watch(tmp_path):
    w = _build_watcher({"type": "file_watch", "path": str(tmp_path)})
    assert isinstance(w, _FileWatcher)


def test_build_watcher_http_poll():
    w = _build_watcher({"type": "http_poll", "url": "https://example.com"})
    assert isinstance(w, _HttpPollWatcher)


def test_build_watcher_rss():
    w = _build_watcher({"type": "rss", "url": "https://example.com/feed"})
    assert isinstance(w, _RssWatcher)


def test_build_watcher_returns_none_on_bad_input():
    assert _build_watcher(None) is None
    assert _build_watcher({"type": "unknown"}) is None
    assert _build_watcher({"type": "file_watch", "path": ""}) is None
    assert _build_watcher({"type": "http_poll"}) is None


# ── WatchManager ──────────────────────────────────────────────────────────


def test_watchmanager_register_and_unregister(tmp_path, qtbot=None):
    wm = WatchManager()
    try:
        ok = wm.register("agent-1", {"type": "file_watch", "path": str(tmp_path)})
        assert ok is True
        assert "agent-1" in wm.watched()
        wm.unregister("agent-1")
        assert "agent-1" not in wm.watched()
    finally:
        wm.stop()


def test_watchmanager_register_rejects_bad_condition():
    wm = WatchManager()
    try:
        ok = wm.register("agent-1", {"type": "nope"})
        assert ok is False
        assert "agent-1" not in wm.watched()
    finally:
        wm.stop()
