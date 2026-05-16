"""
web_searches.py — Sidebar tab showing the Web Searches log.

Renders WebSearchLog entries as a scrollable list of search-results-style
cards. Each result item is a clickable link. The tab subscribes to the
ResultDispatcher's web_search_logged signal for live updates and also
re-reads the log on demand via Refresh.
"""

from __future__ import annotations

import webbrowser
from typing import Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from qfluentwidgets import (
    BodyLabel, CaptionLabel, PushButton, ScrollArea, SubtitleLabel,
    TitleLabel, FluentIcon as FIF,
)

from core.web_search_log import log as _ws_log


class _ResultLink(QLabel):
    """A clickable result line: title (link) + body snippet."""

    def __init__(self, title: str, url: str, body: str, parent=None):
        text = (
            f'<a href="{url}" style="color:#7ec8e3; text-decoration:none;">'
            f'<b>{title or url}</b></a>'
        )
        if body:
            text += f'<br><span style="color:#9aa0aa;">{body[:240]}</span>'
        super().__init__(text, parent)
        self.setTextFormat(Qt.RichText)
        self.setOpenExternalLinks(False)  # we handle in slot below
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.linkActivated.connect(self._on_link)
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def _on_link(self, url: str) -> None:
        try:
            webbrowser.open(url)
        except Exception as exc:
            print(f"[WebSearches] failed to open {url}: {exc}")


class _EntryCard(QFrame):
    """One log entry: header (agent + timestamp + query) + result links."""

    def __init__(self, entry: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setObjectName("webSearchCard")
        self.setStyleSheet(
            "QFrame#webSearchCard { border: 1px solid #1b2236;"
            " border-radius: 8px; background: rgba(255,255,255,0.03);"
            " padding: 10px; }"
        )
        outer = QVBoxLayout(self)
        outer.setSpacing(4)

        head = QLabel(
            f"<b>🔎 {entry.get('agent_name', 'Agent')}</b>"
            f"  <span style='color:#7d828c'>· {entry.get('ts', '')}</span>"
        )
        outer.addWidget(head)

        query = entry.get("query") or ""
        if query:
            q = QLabel(f'<i>"{query}"</i>')
            q.setStyleSheet("color:#cccccc;")
            q.setWordWrap(True)
            outer.addWidget(q)

        items: List[Dict[str, Any]] = entry.get("items") or []
        if not items:
            empty = QLabel("(no results)")
            empty.setStyleSheet("color:#7d828c;")
            outer.addWidget(empty)
        else:
            for it in items:
                outer.addWidget(_ResultLink(
                    it.get("title", ""),
                    it.get("url", ""),
                    it.get("body", ""),
                ))


class WebSearchesTab(QWidget):
    """List of every web-search-style entry an agent has produced."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("webSearchesView")
        self._build()
        self.refresh()

        # Live updates when an agent posts a new entry.
        try:
            _ws_log.entry_added.connect(lambda _e: self.refresh())
            _ws_log.cleared.connect(self.refresh)
        except Exception as exc:
            print(f"[WebSearchesTab] could not connect log signals: {exc}")

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 30, 30, 30)
        root.setSpacing(14)

        header = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(TitleLabel("Web Searches", self))
        sub = BodyLabel(
            "Search-result-style output from agents whose notify channel "
            "includes 'web_searches'. Click a title to open the link.", self,
        )
        sub.setStyleSheet("color:#9aa0aa;")
        sub.setWordWrap(True)
        col.addWidget(sub)
        header.addLayout(col)
        header.addStretch()

        refresh_btn = PushButton(FIF.SYNC, "Refresh")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)

        clear_btn = PushButton(FIF.DELETE, "Clear")
        clear_btn.clicked.connect(self._on_clear)
        header.addWidget(clear_btn)

        root.addLayout(header)

        self._scroll = ScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("background: transparent; border: none;")
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(container)
        self._list_layout.setSpacing(10)
        self._list_layout.setAlignment(Qt.AlignTop)
        self._scroll.setWidget(container)
        root.addWidget(self._scroll, 1)

    def _clear_rows(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def refresh(self) -> None:
        self._clear_rows()
        entries = _ws_log.all()
        if not entries:
            empty = SubtitleLabel("No web searches yet.")
            empty.setStyleSheet("color:#7d828c;")
            self._list_layout.addWidget(empty)
            hint = CaptionLabel(
                "Run an agent with notify channel 'web_searches' to populate this view."
            )
            hint.setStyleSheet("color:#5a6070;")
            hint.setWordWrap(True)
            self._list_layout.addWidget(hint)
            return
        for entry in reversed(entries):  # newest at top
            self._list_layout.addWidget(_EntryCard(entry))

    def _on_clear(self) -> None:
        _ws_log.clear()
