import webbrowser
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QWidget, QHBoxLayout
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor


class NewsCard(QFrame):
    """
    A card widget representing a single news story.
    Displays headline, source, date, and a brief summary.
    Clicking opens the article URL in the browser.
    """

    # ── Category → (colour hex, emoji) ──────────────────────────────────────
    _CATEGORY_MAP = {
        "top stories":    ("#ffbb33", "📰"),
        "australia":      ("#ff8c42", "🦘"),
        "world":          ("#33b5e5", "🌏"),
        "science & tech": ("#00c8ff", "🔬"),
        "science":        ("#aa66cc", "🧬"),
        "tech":           ("#33b5e5", "💻"),
        "space":          ("#7c4dff", "🚀"),
        "business":       ("#00c853", "📈"),
        "markets":        ("#00c853", "📊"),
        "culture":        ("#ff4444", "🎭"),
    }
    _DEFAULT = ("#ffbb33", "📰")

    def __init__(self, article: dict, parent=None):
        super().__init__(parent)
        self.article = article
        self.url = article.get("url", "")

        self.setObjectName("newsCard")
        self.setCursor(QCursor(Qt.PointingHandCursor))

        colour, icon = self._cat_style(article.get("category", ""))

        # ── Card shell styling ────────────────────────────────────────────────
        self.setStyleSheet(f"""
            QFrame#newsCard {{
                background-color: #111625;
                border: 1px solid #1a2236;
                border-radius: 12px;
            }}
            QFrame#newsCard:hover {{
                background-color: #1a2236;
                border: 1px solid {colour};
            }}
        """)

        # ── Outer layout ──────────────────────────────────────────────────────
        outer = QHBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(18)

        # Left icon badge
        icon_lbl = QLabel(icon)
        icon_lbl.setFixedSize(52, 52)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet(f"""
            background-color: {colour}18;
            border: 1px solid {colour}40;
            border-radius: 10px;
            font-size: 26px;
        """)
        outer.addWidget(icon_lbl)

        # Right content column
        content = QVBoxLayout()
        content.setSpacing(5)
        content.setContentsMargins(0, 0, 0, 0)

        # Headline
        headline = QLabel(article.get("title", "No Title"))
        headline.setWordWrap(True)
        headline.setStyleSheet(
            "color:#ffffff; font-size:15px; font-weight:600; font-family:'Segoe UI';"
            " background:transparent;"
        )
        content.addWidget(headline)

        # Summary (plain text, 2-line preview)
        summary_text = article.get("summary", "") or article.get("body", "")
        if summary_text:
            summary_lbl = QLabel(summary_text)
            summary_lbl.setWordWrap(True)
            summary_lbl.setMaximumHeight(44)   # ~2 lines
            summary_lbl.setStyleSheet(
                "color:#8a9ab8; font-size:12px; font-family:'Segoe UI';"
                " background:transparent;"
            )
            content.addWidget(summary_lbl)

        # Meta row: source • date • read-more arrow
        meta = QHBoxLayout()
        meta.setSpacing(8)
        meta.setContentsMargins(0, 2, 0, 0)

        source_lbl = QLabel(article.get("source", "Unknown"))
        source_lbl.setStyleSheet(
            f"color:{colour}; font-weight:bold; font-size:11px; background:transparent;"
        )
        meta.addWidget(source_lbl)

        dot = QLabel("•")
        dot.setStyleSheet("color:#444; background:transparent;")
        meta.addWidget(dot)

        date_lbl = QLabel(article.get("date", "Just now"))
        date_lbl.setStyleSheet("color:#6a7a8e; font-size:11px; background:transparent;")
        meta.addWidget(date_lbl)

        meta.addStretch()

        arrow = QLabel("Read →")
        arrow.setStyleSheet(
            f"color:{colour}; font-size:11px; font-weight:600; background:transparent;"
        )
        meta.addWidget(arrow)

        content.addLayout(meta)
        outer.addLayout(content, 1)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _cat_style(self, category: str):
        cat = str(category).lower()
        for key, val in self._CATEGORY_MAP.items():
            if key in cat:
                return val
        return self._DEFAULT

    def mousePressEvent(self, event):
        if self.url:
            webbrowser.open(self.url)
