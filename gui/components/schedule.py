"""
gui/components/schedule.py
--------------------------
ScheduleComponent  — A dashboard widget showing today's calendar events,
                     with an add-event button.
AddEventDialog     — A dialog for creating new calendar events.

Matches the Aura dark theme used throughout Plia (see alarm.py).
Public API consumed by app.py and handlers.py:
    schedule_component.refresh_events()
"""

import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QListWidget, QListWidgetItem, QComboBox, QSpinBox,
    QLineEdit, QSizePolicy
)
from PySide6.QtCore import Qt, QSize, QTimer, QDate
# QFont imported if needed for future use

from qfluentwidgets import MessageBoxBase, SubtitleLabel, BodyLabel

from core.calendar_manager import calendar_manager


# ---------------------------------------------------------------------------
# Category colours — kept consistent with Plia's palette
# ---------------------------------------------------------------------------
CATEGORY_COLOURS = {
    "WORK":     "#33b5e5",
    "PERSONAL": "#a78bfa",
    "HEALTH":   "#4ade80",
    "FAMILY":   "#fb923c",
    "OTHER":    "#94a3b8",
}

CATEGORIES = list(CATEGORY_COLOURS.keys())


# ---------------------------------------------------------------------------
# AddEventDialog
# ---------------------------------------------------------------------------

class AddEventDialog(MessageBoxBase):
    """Dialog for adding a new calendar event."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.titleLabel = SubtitleLabel("New Event", self)
        self.viewLayout.addWidget(self.titleLabel)

        # ── Shared spinbox style ──────────────────────────────────────────
        _spin_style = """
            QSpinBox {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 5px;
                color: #e8eaed;
                font-size: 14px;
                padding: 4px 6px;
            }
            QSpinBox:hover { background-color: rgba(255, 255, 255, 0.1); }
        """
        _input_style = """
            QLineEdit {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 5px;
                color: #e8eaed;
                font-size: 14px;
                padding: 6px 8px;
            }
            QLineEdit:hover { background-color: rgba(255, 255, 255, 0.1); }
        """
        _combo_style = """
            QComboBox {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 5px;
                color: #e8eaed;
                font-size: 14px;
                padding: 6px 8px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #0f1524;
                color: #e8eaed;
                selection-background-color: #1a2e4a;
            }
        """

        # ── Title field ───────────────────────────────────────────────────
        lbl_title = QLabel("Title")
        lbl_title.setStyleSheet("color:#8a8a8a; font-size:12px;")
        self.viewLayout.addWidget(lbl_title)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Event title…")
        self.title_input.setStyleSheet(_input_style)
        self.viewLayout.addWidget(self.title_input)

        # ── Category ─────────────────────────────────────────────────────
        lbl_cat = QLabel("Category")
        lbl_cat.setStyleSheet("color:#8a8a8a; font-size:12px; margin-top:6px;")
        self.viewLayout.addWidget(lbl_cat)

        self.category_combo = QComboBox()
        self.category_combo.addItems(CATEGORIES)
        self.category_combo.setStyleSheet(_combo_style)
        self.viewLayout.addWidget(self.category_combo)

        # ── Date ─────────────────────────────────────────────────────────
        lbl_date = QLabel("Date  (YYYY-MM-DD)")
        lbl_date.setStyleSheet("color:#8a8a8a; font-size:12px; margin-top:6px;")
        self.viewLayout.addWidget(lbl_date)

        self.date_input = QLineEdit()
        self.date_input.setText(datetime.date.today().isoformat())
        self.date_input.setStyleSheet(_input_style)
        self.viewLayout.addWidget(self.date_input)

        # ── Start time ───────────────────────────────────────────────────
        lbl_start = QLabel("Start time")
        lbl_start.setStyleSheet("color:#8a8a8a; font-size:12px; margin-top:6px;")
        self.viewLayout.addWidget(lbl_start)

        start_row = QHBoxLayout()
        start_row.setSpacing(6)

        self.start_hour = QSpinBox()
        self.start_hour.setRange(0, 23)
        self.start_hour.setButtonSymbols(QSpinBox.NoButtons)
        self.start_hour.setAlignment(Qt.AlignCenter)
        self.start_hour.setFixedSize(56, 36)
        self.start_hour.setStyleSheet(_spin_style)

        colon1 = QLabel(":")
        colon1.setStyleSheet("color:#e8eaed; font-size:18px; font-weight:bold;")

        self.start_min = QSpinBox()
        self.start_min.setRange(0, 59)
        self.start_min.setButtonSymbols(QSpinBox.NoButtons)
        self.start_min.setAlignment(Qt.AlignCenter)
        self.start_min.setFixedSize(56, 36)
        self.start_min.setStyleSheet(_spin_style)

        now = datetime.datetime.now()
        self.start_hour.setValue(now.hour)
        self.start_min.setValue(now.minute)

        start_row.addStretch()
        start_row.addWidget(self.start_hour)
        start_row.addWidget(colon1)
        start_row.addWidget(self.start_min)
        start_row.addStretch()
        self.viewLayout.addLayout(start_row)

        # ── End time ─────────────────────────────────────────────────────
        lbl_end = QLabel("End time")
        lbl_end.setStyleSheet("color:#8a8a8a; font-size:12px; margin-top:6px;")
        self.viewLayout.addWidget(lbl_end)

        end_row = QHBoxLayout()
        end_row.setSpacing(6)

        self.end_hour = QSpinBox()
        self.end_hour.setRange(0, 23)
        self.end_hour.setButtonSymbols(QSpinBox.NoButtons)
        self.end_hour.setAlignment(Qt.AlignCenter)
        self.end_hour.setFixedSize(56, 36)
        self.end_hour.setStyleSheet(_spin_style)

        colon2 = QLabel(":")
        colon2.setStyleSheet("color:#e8eaed; font-size:18px; font-weight:bold;")

        self.end_min = QSpinBox()
        self.end_min.setRange(0, 59)
        self.end_min.setButtonSymbols(QSpinBox.NoButtons)
        self.end_min.setAlignment(Qt.AlignCenter)
        self.end_min.setFixedSize(56, 36)
        self.end_min.setStyleSheet(_spin_style)

        end_default = now + datetime.timedelta(hours=1)
        self.end_hour.setValue(end_default.hour)
        self.end_min.setValue(end_default.minute)

        end_row.addStretch()
        end_row.addWidget(self.end_hour)
        end_row.addWidget(colon2)
        end_row.addWidget(self.end_min)
        end_row.addStretch()
        self.viewLayout.addLayout(end_row)

        # ── Optional description ──────────────────────────────────────────
        lbl_desc = QLabel("Description  (optional)")
        lbl_desc.setStyleSheet("color:#8a8a8a; font-size:12px; margin-top:6px;")
        self.viewLayout.addWidget(lbl_desc)

        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Notes…")
        self.desc_input.setStyleSheet(_input_style)
        self.viewLayout.addWidget(self.desc_input)

        self.yesButton.setText("Add Event")
        self.cancelButton.setText("Cancel")

    # ── Public helpers ────────────────────────────────────────────────────

    def get_event_data(self) -> dict:
        """Return a dict ready for CalendarManager.add_event()."""
        date_str   = self.date_input.text().strip()
        start_str  = f"{date_str} {self.start_hour.value():02d}:{self.start_min.value():02d}:00"
        end_str    = f"{date_str} {self.end_hour.value():02d}:{self.end_min.value():02d}:00"
        return {
            "title":       self.title_input.text().strip() or "Untitled",
            "start_time":  start_str,
            "end_time":    end_str,
            "category":    self.category_combo.currentText(),
            "description": self.desc_input.text().strip(),
        }


# ---------------------------------------------------------------------------
# ScheduleComponent
# ---------------------------------------------------------------------------

class ScheduleComponent(QWidget):
    """
    Dashboard widget showing today's calendar events.
    Mirrors the Aura card style from AlarmComponent.

    Public API:
        refresh_events()  — reload and redraw from the database.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self.refresh_events()

        # Auto-refresh at midnight to switch to the new day
        self._midnight_timer = QTimer(self)
        self._midnight_timer.timeout.connect(self._schedule_midnight_refresh)
        self._midnight_timer.start(60_000)   # check every minute

    # ── UI construction ───────────────────────────────────────────────────

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Aura-style card
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #0f1524;
                border-radius: 12px;
                border: 1px solid #1a2236;
            }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)

        # Header row: label + add button
        header = QHBoxLayout()

        self._title_label = QLabel("TODAY'S EVENTS")
        self._title_label.setStyleSheet(
            "color: #e8eaed; font-size: 13px; font-weight: bold;"
            " letter-spacing: 1px; background: transparent; border: none;"
        )
        header.addWidget(self._title_label)
        header.addStretch()

        self._date_label = QLabel(datetime.date.today().strftime("%d %b %Y"))
        self._date_label.setStyleSheet(
            "color: #4a6080; font-size: 11px; background: transparent; border: none;"
        )
        header.addWidget(self._date_label)

        add_btn = QPushButton("+")
        add_btn.setFixedSize(28, 28)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setToolTip("Add event")
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(51, 181, 229, 0.1);
                color: #33b5e5;
                border: 1px solid #33b5e5;
                border-radius: 14px;
                font-weight: bold;
                font-size: 18px;
                padding-bottom: 2px;
            }
            QPushButton:hover {
                background-color: rgba(51, 181, 229, 0.3);
                color: white;
            }
        """)
        add_btn.clicked.connect(self._open_add_dialog)
        header.addWidget(add_btn)

        card_layout.addLayout(header)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #1a2236; border: none;")
        card_layout.addWidget(sep)

        # Event list
        self._event_list = QListWidget()
        self._event_list.setStyleSheet(
            "background: transparent; border: none; outline: none;"
        )
        self._event_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._event_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        card_layout.addWidget(self._event_list)

        outer.addWidget(card)

    # ── Public API ────────────────────────────────────────────────────────

    def refresh_events(self):
        """Reload today's events from the database and redraw the list."""
        today_str = datetime.date.today().isoformat()
        self._date_label.setText(datetime.date.today().strftime("%d %b %Y"))

        try:
            events = calendar_manager.get_events(today_str)
        except Exception as e:
            print(f"[ScheduleComponent] Error loading events: {e}")
            events = []

        self._event_list.clear()

        if not events:
            self._add_empty_state()
            return

        for ev in events:
            self._add_event_item(ev)

    # ── Private helpers ───────────────────────────────────────────────────

    def _add_empty_state(self):
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 36))
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)

        lbl = QLabel("No events scheduled for today.")
        lbl.setStyleSheet("color: #4a5568; font-size: 12px;")
        lbl.setAlignment(Qt.AlignCenter)

        self._event_list.addItem(item)
        self._event_list.setItemWidget(item, lbl)

    def _add_event_item(self, ev: dict):
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 58))
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)

        # Row widget
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 4, 4, 4)
        row_layout.setSpacing(10)

        # Category colour pip
        category = ev.get("category", "OTHER")
        colour   = CATEGORY_COLOURS.get(category, CATEGORY_COLOURS["OTHER"])
        pip = QFrame()
        pip.setFixedSize(4, 40)
        pip.setStyleSheet(f"background: {colour}; border-radius: 2px; border: none;")
        row_layout.addWidget(pip)

        # Text block
        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title_lbl = QLabel(ev.get("title", "Untitled"))
        title_lbl.setStyleSheet("color: #e8eaed; font-size: 13px; font-weight: 600;")
        title_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        text_col.addWidget(title_lbl)

        # Format times for display
        time_str = self._format_time_range(ev.get("start_time", ""), ev.get("end_time", ""))
        time_lbl = QLabel(time_str)
        time_lbl.setStyleSheet("color: #8b9bb4; font-size: 11px;")
        text_col.addWidget(time_lbl)

        row_layout.addLayout(text_col)
        row_layout.addStretch()

        # Category badge
        cat_lbl = QLabel(category)
        cat_lbl.setStyleSheet(
            f"color: {colour}; font-size: 10px; font-weight: bold;"
            " background: transparent; border: none;"
        )
        row_layout.addWidget(cat_lbl)

        # Delete button
        del_btn = QPushButton("×")
        del_btn.setFixedSize(22, 22)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setStyleSheet("""
            QPushButton { color: #6e6e6e; background: transparent; border: none;
                          font-size: 16px; font-weight: bold; }
            QPushButton:hover { color: #ef5350; }
        """)
        ev_id = ev["id"]
        del_btn.clicked.connect(lambda checked=False, eid=ev_id: self._delete_event(eid))
        row_layout.addWidget(del_btn)

        self._event_list.addItem(item)
        self._event_list.setItemWidget(item, row)

    def _format_time_range(self, start: str, end: str) -> str:
        """Convert 'YYYY-MM-DD HH:MM:SS' timestamps to '09:00 – 10:00'."""
        try:
            s = datetime.datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
            e = datetime.datetime.strptime(end,   "%Y-%m-%d %H:%M:%S")
            return f"{s.strftime('%H:%M')} – {e.strftime('%H:%M')}"
        except Exception:
            return ""

    def _open_add_dialog(self):
        dlg = AddEventDialog(self.window())
        if dlg.exec():
            data = dlg.get_event_data()
            try:
                calendar_manager.add_event(
                    title       = data["title"],
                    start_time  = data["start_time"],
                    end_time    = data["end_time"],
                    category    = data["category"],
                    description = data["description"],
                )
            except Exception as e:
                print(f"[ScheduleComponent] Error saving event: {e}")
            self.refresh_events()

    def _delete_event(self, event_id: str):
        try:
            calendar_manager.delete_event(event_id)
        except Exception as e:
            print(f"[ScheduleComponent] Error deleting event: {e}")
        self.refresh_events()

    def _schedule_midnight_refresh(self):
        """Refresh date heading and list at the start of a new day."""
        now = datetime.datetime.now()
        if now.hour == 0 and now.minute == 0:
            self.refresh_events()
