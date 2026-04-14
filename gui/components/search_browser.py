"""
SearchBrowserWindow — floating browser-style search results panel.

Shown when the user triggers a web search (voice or chat).
Features:
  - Browser-style header with query, page indicator, nav buttons
  - Numbered, clickable result cards (title, snippet, URL)
  - Click hyperlink OR type/say the result number to open it
  - Next / Previous page navigation (5 results per page)
  - "Close" button or voice command to dismiss
  - Draggable floating window, always-on-top
  - Resizable: drag any edge/corner, or click ⤢ to maximise/restore
"""

import webbrowser
import threading
from typing import List, Dict, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QSizePolicy, QLineEdit, QPushButton, QApplication,
    QSizeGrip
)
from PySide6.QtCore import Qt, QPoint, QThread, Signal, QTimer, QUrl, QSize
from PySide6.QtGui import QFont, QCursor, QDesktopServices, QColor, QPalette

try:
    from qfluentwidgets import (
        BodyLabel, CaptionLabel, StrongBodyLabel,
        TransparentToolButton, FluentIcon as FIF, CardWidget,
        LineEdit, PushButton, IconWidget, ToolButton,
        TitleLabel
    )
    HAS_FLUENT = True
except ImportError:
    HAS_FLUENT = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RESULTS_PER_PAGE  = 5
WINDOW_WIDTH      = 800   # wide enough for readable snippets
WINDOW_MIN_HEIGHT = 560   # tall enough to show 5 result cards comfortably
WINDOW_MIN_WIDTH  = 520   # minimum useful width when user resizes

STYLE_WINDOW = """
    SearchBrowserWindow {
        background: #1a1d27;
        border: 1px solid #2d3348;
        border-radius: 12px;
    }
"""

STYLE_HEADER = """
    background: #12151f;
    border-radius: 10px 10px 0 0;
    border-bottom: 1px solid #2d3348;
"""

STYLE_CARD = """
    QFrame#resultCard {
        background: #1e2235;
        border: 1px solid #2a2f45;
        border-radius: 8px;
        margin: 2px 0;
    }
    QFrame#resultCard:hover {
        background: #242840;
        border: 1px solid #3d4466;
    }
"""

STYLE_NUMBER = """
    color: #5b8dee;
    font-size: 15px;
    font-weight: bold;
    min-width: 24px;
"""

STYLE_TITLE_LINK = """
    QPushButton {
        color: #7eb8f7;
        font-size: 14px;
        font-weight: 600;
        text-align: left;
        border: none;
        background: transparent;
        padding: 0;
    }
    QPushButton:hover {
        color: #a8d0ff;
        text-decoration: underline;
    }
"""

STYLE_SNIPPET = "color: #9aa5c0; font-size: 12px;"
STYLE_URL     = "color: #4caf82; font-size: 11px;"

STYLE_INPUT = """
    QLineEdit {
        background: #12151f;
        border: 1px solid #2d3348;
        border-radius: 6px;
        color: #e8eaed;
        padding: 6px 10px;
        font-size: 13px;
    }
    QLineEdit:focus { border: 1px solid #5b8dee; }
"""

STYLE_NAV_BTN = """
    QPushButton {
        background: #1e2235;
        border: 1px solid #2d3348;
        border-radius: 6px;
        color: #c8cdd8;
        padding: 5px 14px;
        font-size: 12px;
    }
    QPushButton:hover  { background: #2a3050; border-color: #5b8dee; }
    QPushButton:pressed{ background: #1a2040; }
    QPushButton:disabled { color: #44475a; border-color: #22253a; }
"""

STYLE_ICON_BTN = """
    QPushButton {
        background: transparent;
        border: none;
        color: #8b9bb4;
        font-size: 15px;
        padding: 2px 6px;
    }
    QPushButton:hover  { color: #c8d8f0; background: rgba(91,141,238,0.12); border-radius: 4px; }
"""

STYLE_CLOSE_BTN = """
    QPushButton {
        background: transparent;
        border: none;
        color: #8b9bb4;
        font-size: 16px;
        padding: 2px 6px;
    }
    QPushButton:hover  { color: #e06c75; background: rgba(224,108,117,0.12); border-radius: 4px; }
"""

STYLE_FOOTER = """
    background: #12151f;
    border-top: 1px solid #2d3348;
    border-radius: 0 0 10px 10px;
"""

STYLE_PAGE_LABEL = "color: #8b9bb4; font-size: 12px;"

STYLE_SIZE_GRIP = """
    QSizeGrip {
        background: transparent;
        width: 14px;
        height: 14px;
    }
"""


# ---------------------------------------------------------------------------
# Background fetch thread
# ---------------------------------------------------------------------------
class SearchFetchThread(QThread):
    """Fetches DuckDuckGo results off the main thread."""
    results_ready = Signal(list)   # list of {title, body, url}
    error_occurred = Signal(str)

    def __init__(self, query: str, max_results: int = 20):
        super().__init__()
        self.query       = query
        self.max_results = max_results

    def run(self):
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                raw = list(ddgs.text(self.query, max_results=self.max_results))

            results = []
            for r in raw:
                results.append({
                    "title": r.get("title", "(No title)"),
                    "body":  r.get("body", ""),
                    "url":   r.get("href", ""),
                })
            self.results_ready.emit(results)
        except Exception as e:
            self.error_occurred.emit(str(e))


# ---------------------------------------------------------------------------
# Single result card
# ---------------------------------------------------------------------------
class ResultCard(QFrame):
    """One numbered, clickable search result."""
    link_clicked = Signal(str)  # url

    def __init__(self, number: int, title: str, snippet: str, url: str, parent=None):
        super().__init__(parent)
        self.setObjectName("resultCard")
        self.url = url
        self.setStyleSheet(STYLE_CARD)
        self.setCursor(QCursor(Qt.PointingHandCursor))

        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(12)

        # Number badge
        num_lbl = QLabel(str(number))
        num_lbl.setStyleSheet(STYLE_NUMBER)
        num_lbl.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        num_lbl.setFixedWidth(24)
        outer.addWidget(num_lbl)

        # Content column
        content = QVBoxLayout()
        content.setSpacing(3)
        content.setContentsMargins(0, 0, 0, 0)

        # Title as clickable button
        title_display = title[:90] + "…" if len(title) > 90 else title
        title_btn = QPushButton(title_display)
        title_btn.setStyleSheet(STYLE_TITLE_LINK)
        title_btn.setCursor(QCursor(Qt.PointingHandCursor))
        title_btn.clicked.connect(lambda: self.link_clicked.emit(self.url))
        title_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        content.addWidget(title_btn)

        # URL display
        url_display = url[:80] + "…" if len(url) > 80 else url
        url_lbl = QLabel(url_display)
        url_lbl.setStyleSheet(STYLE_URL)
        url_lbl.setWordWrap(False)
        content.addWidget(url_lbl)

        # Snippet
        if snippet:
            snip_display = snippet[:220] + "…" if len(snippet) > 220 else snippet
            snip_lbl = QLabel(snip_display)
            snip_lbl.setStyleSheet(STYLE_SNIPPET)
            snip_lbl.setWordWrap(True)
            content.addWidget(snip_lbl)

        outer.addLayout(content)
        outer.addStretch()


# ---------------------------------------------------------------------------
# Main Search Browser Window
# ---------------------------------------------------------------------------
class SearchBrowserWindow(QWidget):
    """
    Floating browser-style window that displays paginated search results.

    The window is fully resizable:
      - Drag any edge or corner to resize (resize handles via Qt.SubWindow flag
        combined with a hidden size grip in the footer corner)
      - Click ⤢ in the header to maximise / restore
      - Drag the header bar to reposition

    Public API
    ----------
    show_results(query, results)   — populate and show with results list
    show_loading(query)            — show spinner while fetching
    show_error(msg)                — display error state
    close_browser()                — hide the window
    handle_user_input(text)        — handle voice/chat navigation commands
    next_page()                    — go to next results page (voice signal slot)
    previous_page()                — go to previous results page (voice signal slot)
    open_result(number)            — open result by 1-based number (voice signal slot)

    Voice commands recognised by handle_user_input()
    -------------------------------------------------
    "next search page" / "next search results page"  → next page
    "previous search page" / "previous search results page" → previous page
    "open search 3" / "open search result 3"         → open result #3
    "close" / "close search"                         → close window
    Typing a plain number in the footer box          → open that result
    """

    # Signal emitted when user selects a result (to notify chat / voice)
    result_opened = Signal(int, str)   # (number, url)
    closed        = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        self._all_results: List[Dict] = []
        self._current_page = 0         # 0-based page index
        self._query = ""
        self._drag_pos: Optional[QPoint] = None
        self._fetch_thread: Optional[SearchFetchThread] = None
        self._is_maximised = False
        self._pre_max_geometry = None  # saved geometry before maximise

        self._build_ui()

        # Set initial and minimum sizes so the window shows 5 cards cleanly
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.resize(WINDOW_WIDTH, WINDOW_MIN_HEIGHT)
        self.hide()

    # -----------------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------------
    def _build_ui(self):
        self.setStyleSheet(STYLE_WINDOW)
        self.setWindowTitle("Plia Search")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────────
        header_frame = QFrame()
        header_frame.setStyleSheet(STYLE_HEADER)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(14, 10, 10, 10)
        header_layout.setSpacing(10)

        # Search icon
        search_icon = QLabel("🔍")
        search_icon.setStyleSheet("font-size: 16px;")
        header_layout.addWidget(search_icon)

        # Query label
        self._query_label = QLabel("Search")
        self._query_label.setStyleSheet("color: #e8eaed; font-size: 14px; font-weight: 600;")
        self._query_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        header_layout.addWidget(self._query_label)

        # Status label (loading / result count)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #8b9bb4; font-size: 12px;")
        header_layout.addWidget(self._status_label)

        # Maximise / restore button
        self._max_btn = QPushButton("⤢")
        self._max_btn.setStyleSheet(STYLE_ICON_BTN)
        self._max_btn.setFixedSize(28, 28)
        self._max_btn.setToolTip("Maximise / Restore")
        self._max_btn.clicked.connect(self._toggle_maximise)
        header_layout.addWidget(self._max_btn)

        # Close button
        close_btn = QPushButton("✕")
        close_btn.setStyleSheet(STYLE_CLOSE_BTN)
        close_btn.setFixedSize(28, 28)
        close_btn.clicked.connect(self.close_browser)
        close_btn.setToolTip("Close (or say 'close search')")
        header_layout.addWidget(close_btn)

        root.addWidget(header_frame)

        # ── Scroll area for results ─────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: #1a1d27; border: none; }"
            "QScrollBar:vertical { background: #1a1d27; width: 6px; }"
            "QScrollBar::handle:vertical { background: #2d3348; border-radius: 3px; }"
        )

        self._results_container = QWidget()
        self._results_container.setStyleSheet("background: #1a1d27;")
        self._results_layout = QVBoxLayout(self._results_container)
        self._results_layout.setContentsMargins(14, 12, 14, 12)
        self._results_layout.setSpacing(8)
        self._results_layout.addStretch()

        scroll.setWidget(self._results_container)
        root.addWidget(scroll, 1)

        # ── Footer — input + navigation + size grip ─────────────────────────
        footer_frame = QFrame()
        footer_frame.setStyleSheet(STYLE_FOOTER)
        footer_layout = QVBoxLayout(footer_frame)
        footer_layout.setContentsMargins(14, 8, 14, 4)
        footer_layout.setSpacing(6)

        # Quick-open input row
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        input_hint = QLabel("Open #:")
        input_hint.setStyleSheet("color: #8b9bb4; font-size: 12px;")
        input_row.addWidget(input_hint)

        self._number_input = QLineEdit()
        self._number_input.setPlaceholderText("Type a number and press Enter…")
        self._number_input.setStyleSheet(STYLE_INPUT)
        self._number_input.setFixedHeight(32)
        self._number_input.returnPressed.connect(self._on_input_enter)
        self._number_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        input_row.addWidget(self._number_input)

        footer_layout.addLayout(input_row)

        # Navigation row
        nav_row = QHBoxLayout()
        nav_row.setSpacing(8)

        self._prev_btn = QPushButton("◀  Previous")
        self._prev_btn.setStyleSheet(STYLE_NAV_BTN)
        self._prev_btn.setFixedHeight(30)
        self._prev_btn.clicked.connect(self.previous_page)
        nav_row.addWidget(self._prev_btn)

        self._page_label = QLabel("Page 1")
        self._page_label.setStyleSheet(STYLE_PAGE_LABEL)
        self._page_label.setAlignment(Qt.AlignCenter)
        nav_row.addWidget(self._page_label, 1)

        self._next_btn = QPushButton("Next  ▶")
        self._next_btn.setStyleSheet(STYLE_NAV_BTN)
        self._next_btn.setFixedHeight(30)
        self._next_btn.clicked.connect(self.next_page)
        nav_row.addWidget(self._next_btn)

        footer_layout.addLayout(nav_row)

        # Size grip row — sits at the very bottom-right so users can drag-resize
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch()
        size_grip = QSizeGrip(self)
        size_grip.setStyleSheet(STYLE_SIZE_GRIP)
        grip_row.addWidget(size_grip, 0, Qt.AlignBottom | Qt.AlignRight)
        footer_layout.addLayout(grip_row)

        root.addWidget(footer_frame)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------
    def show_results(self, query: str, results: List[Dict]):
        """Populate window with results and show it."""
        self._query       = query
        self._all_results = results
        self._current_page = 0
        self._query_label.setText(f'"{query}"')
        self._status_label.setText(f"{len(results)} results")
        self._render_page()
        self._position_window()
        self.show()
        self.raise_()
        self.activateWindow()
        self._number_input.setFocus()

    def show_loading(self, query: str):
        """Show loading state while search is running."""
        self._query       = query
        self._all_results = []
        self._current_page = 0
        self._query_label.setText(f'"{query}"')
        self._status_label.setText("Searching…")
        self._clear_results()
        loading = QLabel("  🔄  Fetching results, please wait…")
        loading.setStyleSheet("color: #8b9bb4; font-size: 13px; padding: 20px;")
        loading.setAlignment(Qt.AlignCenter)
        self._results_layout.insertWidget(0, loading)
        self._update_nav_buttons()
        self._position_window()
        self.show()
        self.raise_()

    def show_error(self, message: str):
        """Show error state."""
        self._status_label.setText("Error")
        self._clear_results()
        err = QLabel(f"  ⚠  {message}")
        err.setStyleSheet("color: #e06c75; font-size: 13px; padding: 20px;")
        err.setAlignment(Qt.AlignCenter)
        self._results_layout.insertWidget(0, err)

    def close_browser(self):
        """Hide the search window."""
        self.hide()
        self.closed.emit()

    def handle_user_input(self, text: str) -> bool:
        """
        Handle voice or chat input while search window is visible.

        Recognised patterns
        -------------------
        Voice commands (say these):
          "next search page"                    → go to next page
          "next search results page"            → go to next page
          "previous search page"                → go to previous page
          "previous search results page"        → go to previous page
          "open search 3"                       → open result #3
          "open search result 3"                → open result #3
          "open search number 3"                → open result #3

        Footer text box (type these):
          A plain number e.g. "3"               → open result #3
          "close"                               → close the window
        """
        import re as _re
        t = text.strip().lower()

        # Next search page
        NEXT_PHRASES = (
            "next search page",
            "next search results page",
            "next results page",
            "next search results",
        )
        if any(p in t for p in NEXT_PHRASES):
            self.next_page()
            return True

        # Previous search page
        PREV_PHRASES = (
            "previous search page",
            "previous search results page",
            "previous results page",
            "previous search results",
            "prev search page",
        )
        if any(p in t for p in PREV_PHRASES):
            self.previous_page()
            return True

        # Open search result N — typed into the footer box
        open_match = _re.search(
            r'\bopen\s+search(?:\s+result(?:s)?)?(?:\s+number)?\s+(\d+)\b', t
        )
        if open_match:
            self._open_result_by_number(int(open_match.group(1)))
            return True

        # Close
        if t in ("close", "close search", "close browser", "hide search"):
            self.close_browser()
            return True

        # Plain number typed in footer input box
        if _re.fullmatch(r'\d+', t):
            self._open_result_by_number(int(t))
            return True

        return False

    # ── Slots wired to VoiceAssistant signals ────────────────────────────────
    def on_search_nav(self, direction: str):
        """Slot for VoiceAssistant.search_nav_requested signal."""
        if direction == "next":
            self.next_page()
        elif direction == "previous":
            self.previous_page()

    def open_result(self, number: int):
        """Slot for VoiceAssistant.search_open_requested signal."""
        self._open_result_by_number(number)

    def fetch_and_show(self, query: str):
        """
        Start an async DuckDuckGo search, show loading state, then populate.
        Called by ChatHandlers / VoiceAssistant integration.
        """
        self.show_loading(query)

        # Cancel any existing fetch
        if self._fetch_thread and self._fetch_thread.isRunning():
            self._fetch_thread.quit()

        self._fetch_thread = SearchFetchThread(query, max_results=20)
        self._fetch_thread.results_ready.connect(
            lambda results: self.show_results(query, results)
        )
        self._fetch_thread.error_occurred.connect(self.show_error)
        self._fetch_thread.start()

    # -----------------------------------------------------------------------
    # Page rendering
    # -----------------------------------------------------------------------
    def _render_page(self):
        self._clear_results()

        start = self._current_page * RESULTS_PER_PAGE
        end   = start + RESULTS_PER_PAGE
        page_results = self._all_results[start:end]

        if not page_results:
            empty = QLabel("  No results on this page.")
            empty.setStyleSheet("color: #8b9bb4; font-size: 13px; padding: 20px;")
            empty.setAlignment(Qt.AlignCenter)
            self._results_layout.insertWidget(0, empty)
        else:
            for i, result in enumerate(page_results, start=start + 1):
                card = ResultCard(
                    number  = i,
                    title   = result.get("title", "(No title)"),
                    snippet = result.get("body", ""),
                    url     = result.get("url", ""),
                )
                card.link_clicked.connect(self._open_url)
                # Insert before the trailing stretch
                self._results_layout.insertWidget(
                    self._results_layout.count() - 1, card
                )

        self._update_nav_buttons()

    def _clear_results(self):
        """Remove all result widgets (but keep the trailing stretch)."""
        while self._results_layout.count() > 1:
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _update_nav_buttons(self):
        total_pages = max(1, -(-len(self._all_results) // RESULTS_PER_PAGE))  # ceil div
        page_num    = self._current_page + 1

        self._page_label.setText(f"Page {page_num} of {total_pages}")
        self._prev_btn.setEnabled(self._current_page > 0)
        self._next_btn.setEnabled(self._current_page < total_pages - 1)

    # -----------------------------------------------------------------------
    # Navigation
    # -----------------------------------------------------------------------
    def next_page(self):
        total_pages = -(-len(self._all_results) // RESULTS_PER_PAGE)
        if self._current_page < total_pages - 1:
            self._current_page += 1
            self._render_page()

    def previous_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._render_page()

    # -----------------------------------------------------------------------
    # Opening results
    # -----------------------------------------------------------------------
    def _open_result_by_number(self, number: int):
        """Open result by its displayed number (1-based across all pages)."""
        idx = number - 1
        if 0 <= idx < len(self._all_results):
            url = self._all_results[idx].get("url", "")
            if url:
                self._open_url(url)
                self.result_opened.emit(number, url)
        else:
            # Number out of range — flash the input field red briefly
            self._number_input.setStyleSheet(
                STYLE_INPUT.replace("border: 1px solid #2d3348;",
                                    "border: 1px solid #e06c75;")
            )
            QTimer.singleShot(800, lambda: self._number_input.setStyleSheet(STYLE_INPUT))

    def _open_url(self, url: str):
        """Open a URL in the system default browser."""
        if url:
            QDesktopServices.openUrl(QUrl(url))

    # -----------------------------------------------------------------------
    # Input box (footer)
    # -----------------------------------------------------------------------
    def _on_input_enter(self):
        text = self._number_input.text().strip()
        self._number_input.clear()
        if text:
            self.handle_user_input(text)

    # -----------------------------------------------------------------------
    # Maximise / restore
    # -----------------------------------------------------------------------
    def _toggle_maximise(self):
        """Toggle between maximised (full available screen) and previous size."""
        screen = QApplication.primaryScreen()
        if not screen:
            return

        if self._is_maximised:
            # Restore saved geometry
            if self._pre_max_geometry:
                self.setGeometry(self._pre_max_geometry)
            self._max_btn.setText("⤢")
            self._is_maximised = False
        else:
            # Save current geometry, then fill available screen
            self._pre_max_geometry = self.geometry()
            self.setGeometry(screen.availableGeometry())
            self._max_btn.setText("⧉")  # restore icon
            self._is_maximised = True

    # -----------------------------------------------------------------------
    # Positioning & dragging
    # -----------------------------------------------------------------------
    def _position_window(self):
        """Centre on screen (or near parent) on first show, unless maximised."""
        if self._is_maximised:
            return
        if not self.parent():
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                self.move(
                    geo.center().x() - self.width() // 2,
                    geo.center().y() - self.height() // 2,
                )
        else:
            parent_geo = self.parent().geometry()
            self.move(
                parent_geo.center().x() - self.width() // 2,
                parent_geo.center().y() - self.height() // 2,
            )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)
