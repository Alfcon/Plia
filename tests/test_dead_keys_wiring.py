"""Wire the three dead settings keys the audit found.

DEFAULT_SETTINGS defined morning_digest.categories, notes.max_notes, and
finance.currency, but no consumer in the codebase actually read any of
them — adding UI controls without backend wiring would have shipped fake
controls. These tests cover the now-real backend usage; UI tests live in
test_misc_settings_ui.py.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


# ── morning_digest.categories → core/news.py ──────────────────────────────


def test_get_briefing_filters_by_categories(monkeypatch):
    """NewsManager.get_briefing(categories=[...]) must only fetch feeds in
    those categories."""
    from core import news as news_mod

    called_categories: list[str] = []

    def fake_parse_feed(url, category, source_name, max_items=5):
        called_categories.append(category)
        return [{
            "title": f"{category} article", "source": source_name,
            "date": "now", "fetched_iso": "2026-01-01",
            "category": category, "url": f"https://x/{category}",
            "image": None, "body": "",
        }]

    monkeypatch.setattr(news_mod, "_parse_feed", fake_parse_feed)

    mgr = news_mod.NewsManager()
    result = mgr.get_briefing(use_ai=False, categories=["Science"])

    assert called_categories == ["Science"], (
        f"expected only Science feed fetched, got {called_categories}"
    )
    assert result and all(item.get("category") == "Science" for item in result)


def test_get_briefing_without_categories_fetches_all(monkeypatch):
    from core import news as news_mod
    called: list[str] = []

    def fake_parse_feed(url, category, source_name, max_items=5):
        called.append(category)
        return []

    monkeypatch.setattr(news_mod, "_parse_feed", fake_parse_feed)
    news_mod.NewsManager().get_briefing(use_ai=False)
    assert set(called) == set(news_mod.RSS_FEEDS.keys())


def test_get_briefing_ignores_unknown_categories(monkeypatch):
    """Categories not in RSS_FEEDS are dropped silently — no crash."""
    from core import news as news_mod
    called: list[str] = []

    def fake_parse_feed(url, category, source_name, max_items=5):
        called.append(category)
        return []

    monkeypatch.setattr(news_mod, "_parse_feed", fake_parse_feed)
    news_mod.NewsManager().get_briefing(
        use_ai=False, categories=["Science", "NotARealCategory"],
    )
    assert called == ["Science"]


# ── notes.max_notes → core/notes.py ───────────────────────────────────────


def test_notes_max_cap_evicts_oldest(tmp_path, monkeypatch):
    from core.notes import NotesManager
    from core.settings_store import settings as app_settings

    # Cap at 3 for the test (default is 500).
    saved = app_settings.get("notes.max_notes", 500)
    app_settings.set("notes.max_notes", 3)
    try:
        db = tmp_path / "n.db"
        mgr = NotesManager(db_path=str(db))

        # Create 5 notes; max_notes=3 should evict the 2 oldest.
        ids = []
        for i in range(5):
            ids.append(mgr.create(f"note {i}", body=f"body {i}")["id"])

        remaining = mgr.list()
        assert len(remaining) == 3, (
            f"expected 3 notes after cap, got {len(remaining)}: "
            f"{[n['title'] for n in remaining]}"
        )
        remaining_titles = {n["title"] for n in remaining}
        assert remaining_titles == {"note 2", "note 3", "note 4"}, (
            f"expected the 3 newest, got {remaining_titles}"
        )
    finally:
        app_settings.set("notes.max_notes", saved)


def test_notes_no_cap_when_setting_zero(tmp_path, monkeypatch):
    """max_notes <= 0 means 'no cap' — never evict."""
    from core.notes import NotesManager
    from core.settings_store import settings as app_settings

    saved = app_settings.get("notes.max_notes", 500)
    app_settings.set("notes.max_notes", 0)
    try:
        mgr = NotesManager(db_path=str(tmp_path / "n.db"))
        for i in range(8):
            mgr.create(f"n{i}")
        assert len(mgr.list()) == 8
    finally:
        app_settings.set("notes.max_notes", saved)


# ── finance.currency → core/finance.py ────────────────────────────────────


def test_crypto_price_defaults_currency_from_settings(monkeypatch):
    """FinanceManager.crypto_price(currency=None) must default to the
    configured finance.currency."""
    from core import finance as finance_mod
    from core.settings_store import settings as app_settings

    saved = app_settings.get("finance.currency", "USD")
    app_settings.set("finance.currency", "EUR")

    captured = {}

    class _StubResp:
        def raise_for_status(self): pass
        def json(self):
            return {"bitcoin": {"eur": 50000, "eur_24h_change": 1.0}}

    def _stub_get(url, params=None, timeout=None):
        captured["params"] = params or {}
        return _StubResp()

    monkeypatch.setattr(finance_mod.requests, "get", _stub_get)
    try:
        result = finance_mod.FinanceManager.crypto_price(coin="bitcoin")
        assert captured["params"].get("vs_currencies") == "eur", (
            f"expected vs_currencies=eur, got {captured['params']}"
        )
        assert result is not None
        assert result["currency"] == "EUR"
    finally:
        app_settings.set("finance.currency", saved)


def test_crypto_price_explicit_currency_overrides_settings(monkeypatch):
    """Passing currency explicitly must win over the setting."""
    from core import finance as finance_mod
    from core.settings_store import settings as app_settings

    saved = app_settings.get("finance.currency", "USD")
    app_settings.set("finance.currency", "EUR")

    captured = {}

    class _StubResp:
        def raise_for_status(self): pass
        def json(self):
            return {"bitcoin": {"gbp": 40000, "gbp_24h_change": 0.5}}

    def _stub_get(url, params=None, timeout=None):
        captured["params"] = params or {}
        return _StubResp()

    monkeypatch.setattr(finance_mod.requests, "get", _stub_get)
    try:
        finance_mod.FinanceManager.crypto_price(coin="bitcoin", currency="GBP")
        assert captured["params"].get("vs_currencies") == "gbp"
    finally:
        app_settings.set("finance.currency", saved)
