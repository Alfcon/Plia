"""
help.py — Help / Documentation tab.

Reads markdown files from <repo>/docs/help/*.md and renders them in a
QTextBrowser. The left sidebar lists each file as a button (sorted by
filename — prefix files with NN- to control order). Selecting a file
renders it in the right pane.

Adding a new help page is just "drop a new .md file in docs/help/".
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget,
)

from qfluentwidgets import (
    BodyLabel, PushButton, ScrollArea, TitleLabel, FluentIcon as FIF,
)


# Plia repo lives at the project root; docs/help is alongside core/ and gui/.
_HELP_DIR = Path(__file__).resolve().parents[2] / "docs" / "help"


def _pretty_title(path: Path) -> str:
    """`02-live-agents.md` → 'Live Agents'."""
    stem = path.stem
    if "-" in stem and stem.split("-", 1)[0].isdigit():
        stem = stem.split("-", 1)[1]
    return stem.replace("_", " ").replace("-", " ").title()


class HelpTab(QWidget):
    """Markdown-rendered help / docs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("helpView")
        self._files: List[Path] = []
        self._buttons: dict[Path, PushButton] = {}
        self._build()
        self._load_index()

    # ── Layout ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        # Title strip
        header = QVBoxLayout()
        header.addWidget(TitleLabel("Help & Documentation", self))
        sub = BodyLabel(
            "Quick reference for everything Plia can do. "
            "Files are sourced from docs/help/*.md — drop a new file there "
            "and it'll appear in the sidebar.",
            self,
        )
        sub.setStyleSheet("color:#9aa0aa;")
        sub.setWordWrap(True)
        header.addWidget(sub)
        root.addLayout(header)

        # Two-column body: nav (left) + content (right)
        body = QHBoxLayout()
        body.setSpacing(14)

        nav_frame = QFrame(self)
        nav_frame.setStyleSheet(
            "QFrame { border: 1px solid #1b2236; border-radius: 8px;"
            "         background: rgba(255,255,255,0.02); }"
        )
        nav_frame.setMinimumWidth(220)
        nav_frame.setMaximumWidth(280)
        nav_outer = QVBoxLayout(nav_frame)
        nav_outer.setContentsMargins(8, 8, 8, 8)
        nav_outer.setSpacing(6)

        nav_scroll = ScrollArea(self)
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setStyleSheet("background: transparent; border: none;")
        nav_inner = QWidget()
        self._nav_layout = QVBoxLayout(nav_inner)
        self._nav_layout.setSpacing(4)
        self._nav_layout.setAlignment(Qt.AlignTop)
        nav_scroll.setWidget(nav_inner)
        nav_outer.addWidget(nav_scroll)

        # Refresh button so users can re-scan docs/help after editing.
        refresh = PushButton(FIF.SYNC, "Refresh")
        refresh.clicked.connect(self._load_index)
        nav_outer.addWidget(refresh)

        body.addWidget(nav_frame, 0)

        # Content area
        self._content = QTextBrowser(self)
        self._content.setOpenExternalLinks(False)
        self._content.anchorClicked.connect(self._on_link_clicked)
        self._content.setStyleSheet(
            "QTextBrowser { background: rgba(255,255,255,0.02);"
            "               border: 1px solid #1b2236; border-radius: 8px;"
            "               padding: 16px; color: #e6e8ec; }"
        )
        body.addWidget(self._content, 1)

        root.addLayout(body, 1)

    # ── Loading ──────────────────────────────────────────────────────────
    def _load_index(self) -> None:
        # Clear the nav buttons.
        while self._nav_layout.count():
            item = self._nav_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._files = []
        self._buttons = {}

        if not _HELP_DIR.exists():
            self._content.setPlainText(
                f"No docs/help/ directory found at {_HELP_DIR}.\n\n"
                "Create that directory and drop .md files in it for them to "
                "appear here."
            )
            return

        files = sorted(_HELP_DIR.glob("*.md"))
        if not files:
            self._content.setPlainText(
                "No help pages yet — drop a .md file in docs/help/."
            )
            return

        for path in files:
            self._files.append(path)
            btn = PushButton(_pretty_title(path))
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, p=path: self._show(p))
            self._nav_layout.addWidget(btn)
            self._buttons[path] = btn

        # Auto-load the first page.
        self._show(files[0])

    def _show(self, path: Path) -> None:
        for p, btn in self._buttons.items():
            btn.setChecked(p == path)
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            self._content.setPlainText(f"Could not read {path}: {exc}")
            return
        try:
            self._content.setMarkdown(text)
        except Exception:
            # Fallback to plain text if Qt's markdown parser chokes.
            self._content.setPlainText(text)

    def _on_link_clicked(self, url):
        """Open external links in the user's browser instead of inside the
        QTextBrowser (which can't render arbitrary web content)."""
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)
            return
        # Allow internal anchors to navigate within the page.
        self._content.setSource(url)
