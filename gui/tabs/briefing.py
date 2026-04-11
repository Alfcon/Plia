"""
Briefing tab — pulls live news from ABC Australia RSS feeds.
Articles are cached locally in a JSON file and can be expired via settings.
"""

import feedparser
import datetime
import json
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal
from gui.components.news_card import NewsCard
from core.news import news_manager

from qfluentwidgets import (
    PushButton, FluentIcon as FIF, ScrollArea, SegmentedWidget,
    TitleLabel, BodyLabel, CardWidget, InfoBar, InfoBarPosition
)

# ---------------------------------------------------------------------------
# Local storage
# ---------------------------------------------------------------------------
NEWS_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "news_cache.json")
NEWS_CACHE_FILE = os.path.normpath(NEWS_CACHE_FILE)

# ---------------------------------------------------------------------------
# Feed URLs per tab
# ---------------------------------------------------------------------------
import re as _re

# Each tab maps to a LIST of (url, source_name) tuples so we can merge feeds
FEED_SOURCES = {
    "Top Stories":    [("https://www.abc.net.au/news/feed/10719986/rss.xml", "ABC News")],
    "Australia":      [("https://www.abc.net.au/news/feed/51120/rss.xml",    "ABC News")],
    "World":          [("https://www.abc.net.au/news/feed/104217382/rss.xml","ABC News")],
    "Science & Tech": [
        ("https://feeds.arstechnica.com/arstechnica/index",  "Ars Technica"),
        ("https://www.sciencedaily.com/rss/top/science.xml", "Science Daily"),
    ],
    "Space":          [("https://www.universetoday.com/feed/",               "Universe Today")],
    "Business":       [("https://www.abc.net.au/news/feed/104217374/rss.xml","ABC News")],
}

TAB_CATEGORIES = list(FEED_SOURCES.keys())
ABC_FEEDS = {k: v[0][0] for k, v in FEED_SOURCES.items()}  # compat alias


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = _re.sub(r"<[^>]+>", " ", text)
    for ent, rep in [("&amp;","&"),("&lt;","<"),("&gt;",">"),("&nbsp;"," "),("&#8230;","\u2026")]:
        text = text.replace(ent, rep)
    return _re.sub(r"\s+", " ", text).strip()


def _summarise(raw: str, max_chars: int = 220) -> str:
    text = _strip_html(raw)
    if len(text) > max_chars:
        return text[:max_chars].rsplit(" ", 1)[0] + "\u2026"
    return text


def _parse_feed(url: str, category: str, source_name: str = "ABC News", max_items: int = 10) -> list:
    """Fetch and parse a single RSS feed."""
    try:
        feed = feedparser.parse(url)
        articles = []
        for entry in feed.entries[:max_items]:
            pub = entry.get("published_parsed") or entry.get("updated_parsed")
            if pub:
                dt = datetime.datetime(*pub[:6])
                date_str = dt.strftime("%d %b %Y, %H:%M")
                fetched_iso = dt.isoformat()
            else:
                date_str = "Recently"
                fetched_iso = datetime.datetime.now().isoformat()

            image_url = None
            if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0].get("url")
            elif hasattr(entry, "media_content") and entry.media_content:
                image_url = entry.media_content[0].get("url")

            raw_body = ""
            if hasattr(entry, "content") and entry.content:
                raw_body = entry.content[0].get("value", "")
            if not raw_body:
                raw_body = entry.get("summary", "")

            articles.append({
                "title":       entry.get("title", "No title"),
                "source":      source_name,
                "date":        date_str,
                "fetched_iso": fetched_iso,
                "category":    category,
                "url":         entry.get("link", ""),
                "image":       image_url,
                "body":        entry.get("summary", ""),
                "summary":     _summarise(raw_body, 220),
            })
        return articles
    except Exception as e:
        print(f"[Briefing] Error fetching feed '{category}': {e}")
        return []


# ---------------------------------------------------------------------------
# Local cache helpers
# ---------------------------------------------------------------------------

def load_local_cache() -> dict:
    """Load the local news cache from disk."""
    try:
        if os.path.exists(NEWS_CACHE_FILE):
            with open(NEWS_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[Briefing] Cache load error: {e}")
    return {}


def save_local_cache(data: dict):
    """Save the news cache to disk."""
    try:
        os.makedirs(os.path.dirname(NEWS_CACHE_FILE), exist_ok=True)
        with open(NEWS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Briefing] Cache save error: {e}")


def purge_old_articles(max_age_days: int) -> int:
    """
    Remove articles older than max_age_days from the local cache.
    Returns number of articles removed.
    """
    cache = load_local_cache()
    cutoff = datetime.datetime.now() - datetime.timedelta(days=max_age_days)
    removed = 0
    new_cache = {}
    for category, articles in cache.items():
        kept = []
        for a in articles:
            try:
                fetched = datetime.datetime.fromisoformat(a.get("fetched_iso", ""))
                if fetched >= cutoff:
                    kept.append(a)
                else:
                    removed += 1
            except Exception:
                kept.append(a)   # keep if date unparseable
        new_cache[category] = kept
    save_local_cache(new_cache)
    return removed


# ---------------------------------------------------------------------------
# Background thread
# ---------------------------------------------------------------------------

class ABCNewsLoaderThread(QThread):
    """Loads ABC News RSS feeds in the background and merges with local cache."""
    loaded = Signal(dict)
    status_update = Signal(str)

    def run(self):
        all_news = {}
        for category in TAB_CATEGORIES:
            self.status_update.emit(f"Fetching {category}...")
            fresh = []
            seen_urls = set()
            for url, src in FEED_SOURCES[category]:
                for article in _parse_feed(url, category, src):
                    if article["url"] not in seen_urls:
                        fresh.append(article)
                        seen_urls.add(article["url"])
            # Sort merged results by date descending
            fresh.sort(key=lambda a: a.get("fetched_iso", ""), reverse=True)
            all_news[category] = fresh

        # Merge with local cache (deduplicate by URL)
        cache = load_local_cache()
        merged = {}
        for category in TAB_CATEGORIES:
            fresh = all_news.get(category, [])
            cached = cache.get(category, [])
            seen_urls = {a["url"] for a in fresh}
            for a in cached:
                if a["url"] not in seen_urls:
                    fresh.append(a)
                    seen_urls.add(a["url"])
            merged[category] = fresh

        # Persist merged result
        save_local_cache(merged)
        self.loaded.emit(merged)


# Keep legacy thread for any code that still references it
class NewsLoaderThread(QThread):
    loaded = Signal(list)
    status_update = Signal(str)

    def __init__(self, use_ai=True):
        super().__init__()
        self.use_ai = use_ai

    def run(self):
        news = news_manager.get_briefing(
            status_callback=self.status_update.emit,
            use_ai=self.use_ai
        )
        self.loaded.emit(news)


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------

class BriefingView(QWidget):
    """
    Briefing tab — live ABC Australia news with local caching.
    Supports navigation from the Dashboard and voice assistant.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("briefingView")

        self._all_news: dict = {}
        self._current_category = TAB_CATEGORIES[0]

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(30, 30, 30, 30)
        self.layout.setSpacing(20)

        # ── Header ──────────────────────────────────────────────────────────
        header_layout = QHBoxLayout()

        title_block = QVBoxLayout()
        title = TitleLabel("Briefing", self)
        subtitle = BodyLabel("Live intelligence from ABC News Australia.", self)
        subtitle.setStyleSheet("color: #8a8a8a;")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header_layout.addLayout(title_block)
        header_layout.addStretch()

        refresh_btn = PushButton(FIF.SYNC, "Refresh")
        refresh_btn.clicked.connect(self.load_news)
        header_layout.addWidget(refresh_btn)

        self.layout.addLayout(header_layout)

        # ── Breaking news banner ─────────────────────────────────────────────
        self.breaking_widget = CardWidget()
        self.breaking_widget.setBorderRadius(10)
        self.breaking_widget.setFixedHeight(60)
        bk_layout = QHBoxLayout(self.breaking_widget)
        bk_layout.setContentsMargins(15, 0, 15, 0)

        bk_label = BodyLabel("BREAKING")
        bk_label.setStyleSheet("color: #ef5350; font-weight: bold;")
        bk_layout.addWidget(bk_label)

        self.bk_text = BodyLabel("Loading ABC News...")
        bk_layout.addWidget(self.bk_text)
        bk_layout.addStretch()

        self.layout.addWidget(self.breaking_widget)

        # ── Category tabs ────────────────────────────────────────────────────
        self.pivot = SegmentedWidget()
        for c in TAB_CATEGORIES:
            self.pivot.addItem(routeKey=c, text=c)
        self.pivot.setCurrentItem(self._current_category)
        self.pivot.currentItemChanged.connect(self._on_category_changed)
        self.layout.addWidget(self.pivot)

        # ── Scrollable news list ─────────────────────────────────────────────
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.viewport().setStyleSheet("background: transparent;")

        self._news_container = QWidget()
        self.news_list_layout = QVBoxLayout(self._news_container)
        self.news_list_layout.setSpacing(15)
        self.news_list_layout.setContentsMargins(0, 0, 0, 20)
        self.news_list_layout.setAlignment(Qt.AlignTop)

        scroll.setWidget(self._news_container)
        self.layout.addWidget(scroll)

        # ── Try to show cached articles immediately, then refresh ────────────
        self._show_cached()
        self.load_news()

    # ── Public API ────────────────────────────────────────────────────────────

    def navigate_to_category(self, category: str = "Top Stories"):
        """
        Called by dashboard / voice assistant to jump to a specific category.
        """
        if category in TAB_CATEGORIES:
            self._current_category = category
            self.pivot.setCurrentItem(category)
            self._display_category(category)

    # ── Loading ──────────────────────────────────────────────────────────────

    def _show_cached(self):
        """Display whatever is in the local cache immediately on open."""
        cache = load_local_cache()
        if cache:
            self._all_news = cache
            self._display_category(self._current_category)
            top = cache.get(self._current_category, [])
            if top:
                self.bk_text.setText(f"{top[0]['title']}  —  ABC News (cached)")

    def load_news(self):
        """Fetch fresh ABC RSS feeds in the background."""
        self.bk_text.setText("Fetching latest headlines from ABC News...")

        self.thread = ABCNewsLoaderThread()
        self.thread.status_update.connect(self.bk_text.setText)
        self.thread.loaded.connect(self._on_news_loaded)
        self.thread.start()

    def _on_news_loaded(self, all_news: dict):
        self._all_news = all_news

        top = all_news.get(self._current_category, [])
        if top:
            self.bk_text.setText(f"{top[0]['title']}  —  ABC News")
        else:
            self.bk_text.setText("No articles found. Check your internet connection.")
            InfoBar.warning(
                title="News Offline",
                content="Could not fetch ABC News. Showing cached articles.",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
                parent=self
            )

        self._display_category(self._current_category)

    # ── Display ───────────────────────────────────────────────────────────────

    def _on_category_changed(self, route_key: str):
        self._current_category = route_key
        self._display_category(route_key)
        articles = self._all_news.get(route_key, [])
        if articles:
            self.bk_text.setText(f"{articles[0]['title']}  —  ABC News")

    def _display_category(self, category: str):
        self._clear_list()
        articles = self._all_news.get(category, [])

        if not articles:
            placeholder = BodyLabel("No articles available. Click Refresh to load.")
            placeholder.setStyleSheet("color: #666; padding: 20px;")
            self.news_list_layout.addWidget(placeholder)
            return

        for item in articles:
            card = NewsCard(item)
            self.news_list_layout.addWidget(card)

    def _clear_list(self):
        while self.news_list_layout.count():
            child = self.news_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
