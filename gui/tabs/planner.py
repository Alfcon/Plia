from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel,
    QListWidgetItem, QSizePolicy, QWidget, QScrollArea
)
from PySide6.QtCore import Qt, QSize, QThread, Signal, QTimer, QDate

from qfluentwidgets import (
    LineEdit, ListWidget, CheckBox, PushButton,
    TransparentToolButton, FluentIcon as FIF,
    CardWidget, HeaderCardWidget, BodyLabel, TitleLabel,
    StrongBodyLabel, InfoBar, InfoBarPosition, TogglePushButton
)

from gui.components.timer import TimerComponent
from gui.components.alarm import AlarmComponent
from core.tasks import task_manager
from core.settings_store import settings


# ---------------------------------------------------------------------------
# Background thread — fetches Google + Outlook events
# ---------------------------------------------------------------------------

class CalendarSyncThread(QThread):
    synced = Signal(list)
    error  = Signal(str)

    def run(self):
        events = []
        try:
            from core.calendar_sync import fetch_google_events, fetch_outlook_events

            if settings.get("calendar.google.enabled", False):
                try:
                    events += fetch_google_events(days_ahead=60)
                except Exception as e:
                    print(f"[CalendarSync] Google error: {e}")

            if settings.get("calendar.outlook.enabled", False):
                try:
                    events += fetch_outlook_events(days_ahead=60)
                except Exception as e:
                    print(f"[CalendarSync] Outlook error: {e}")

        except ImportError:
            self.error.emit("calendar_sync module not found")
            return

        self.synced.emit(events)


# ---------------------------------------------------------------------------
# Provider toggle bar — two compact toggle buttons, nothing else
# ---------------------------------------------------------------------------

class CalendarToggleBar(QFrame):
    """
    Two toggle buttons (Google / Outlook).
    Toggling on fetches and shows events on the calendar.
    Toggling off hides those events immediately.
    """
    filter_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._thread = None
        self._all_events: list = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)

        self._google_btn = TogglePushButton("🗓  Google")
        self._google_btn.setChecked(settings.get("calendar.google.enabled", False))
        self._google_btn.setFixedHeight(30)
        self._google_btn.toggled.connect(self._on_google_toggled)
        layout.addWidget(self._google_btn)

        self._outlook_btn = TogglePushButton("📅  Outlook")
        self._outlook_btn.setChecked(settings.get("calendar.outlook.enabled", False))
        self._outlook_btn.setFixedHeight(30)
        self._outlook_btn.toggled.connect(self._on_outlook_toggled)
        layout.addWidget(self._outlook_btn)

        self._status_lbl = BodyLabel("")
        self._status_lbl.setStyleSheet("color:#8b9bb4; font-size:11px;")
        layout.addWidget(self._status_lbl)

        layout.addStretch()

        self._sync_btn = TransparentToolButton(FIF.SYNC)
        self._sync_btn.setFixedSize(28, 28)
        self._sync_btn.setToolTip("Sync external calendars")
        self._sync_btn.clicked.connect(self.sync)
        layout.addWidget(self._sync_btn)

        QTimer.singleShot(600, self._auto_sync)

    # ── Public ───────────────────────────────────────────────────────────────

    def sync(self):
        if self._thread and self._thread.isRunning():
            return
        g = settings.get("calendar.google.enabled", False)
        o = settings.get("calendar.outlook.enabled", False)
        if not g and not o:
            return

        self._status_lbl.setText("Syncing…")
        self._sync_btn.setEnabled(False)

        self._thread = CalendarSyncThread()
        self._thread.synced.connect(self._on_synced)
        self._thread.error.connect(lambda msg: self._status_lbl.setText(f"Error: {msg}"))
        self._thread.finished.connect(lambda: self._sync_btn.setEnabled(True))
        self._thread.start()

    def active_events(self) -> list:
        result = []
        g = self._google_btn.isChecked()
        o = self._outlook_btn.isChecked()
        for ev in self._all_events:
            src = ev.get("source", "")
            if (src == "google" and g) or (src == "outlook" and o):
                result.append(ev)
        return result

    def events_for_date(self, date: QDate) -> list:
        """
        Return active events that fall on *date*.
        Handles all date/datetime formats Google and Outlook return:
          - "2026-04-07"                     (all-day)
          - "2026-04-07T09:00:00"            (local datetime)
          - "2026-04-07T09:00:00Z"           (UTC datetime)
          - "Tue 07 Apr, 09:00 AM"           (already-formatted by _fmt_dt)
        """
        import datetime as _dt

        target_date = date.toPython()          # Python datetime.date
        target_str  = date.toString("yyyy-MM-dd")  # "2026-04-07" fallback

        result = []
        for ev in self.active_events():
            # Check every field that might carry a date
            raw = (
                ev.get("start_iso", "")
                or ev.get("start_raw", "")
                or ev.get("start", "")
            )

            matched = False

            # 1. Quick substring check for ISO date portion
            if target_str in raw:
                matched = True

            # 2. Try parsing as ISO datetime / date
            if not matched and raw:
                try:
                    clean = raw.replace("Z", "").split("+")[0].split(".")[0]
                    parsed = _dt.datetime.fromisoformat(clean).date()
                    matched = (parsed == target_date)
                except Exception:
                    pass

            # 3. Try the human-readable format _fmt_dt produces: "Tue 07 Apr, 09:00 AM"
            if not matched and raw:
                try:
                    parsed = _dt.datetime.strptime(raw, "%a %d %b, %I:%M %p").date()
                    # strptime has no year — assume current or next year
                    for yr in (target_date.year, target_date.year + 1):
                        if parsed.replace(year=yr) == target_date:
                            matched = True
                            break
                except Exception:
                    pass

            if matched:
                result.append(ev)

        return result

    # ── Private ──────────────────────────────────────────────────────────────

    def _auto_sync(self):
        g = settings.get("calendar.google.enabled", False)
        o = settings.get("calendar.outlook.enabled", False)
        if g or o:
            self.sync()

    def _on_synced(self, events: list):
        self._all_events = events
        n = len(self.active_events())
        self._status_lbl.setText(f"Synced · {n} event{'s' if n != 1 else ''}")
        self.filter_changed.emit()

    def _on_google_toggled(self, checked: bool):
        settings.set("calendar.google.enabled", checked)
        self.filter_changed.emit()
        if checked:
            self.sync()

    def _on_outlook_toggled(self, checked: bool):
        settings.set("calendar.outlook.enabled", checked)
        self.filter_changed.emit()
        if checked:
            self.sync()


# ---------------------------------------------------------------------------
# Event Detail Dialog — popup with full event info
# ---------------------------------------------------------------------------

class EventDetailDialog(QWidget):
    """
    Floating detail window shown when the user clicks an event card.
    Displays all available fields: title, time, calendar, location, notes, URL.
    """

    def __init__(self, ev: dict, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowCloseButtonHint
            | Qt.WindowTitleHint
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMinimumWidth(480)
        self.setMaximumWidth(640)
        self.setWindowTitle("Event Details")
        self.setStyleSheet("""
            QWidget {
                background-color: #0b1120;
                color: #e0e6f0;
                font-family: 'Segoe UI';
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Coloured header bar ──────────────────────────────────────────────
        source = ev.get("source", "google")
        accent = "#4caf50" if source == "google" else "#33b5e5"
        provider_name = "Google Calendar" if source == "google" else "Outlook Calendar"
        provider_icon = "🗓" if source == "google" else "📅"

        header = QFrame()
        header.setStyleSheet(
            f"background: {accent}22; border-bottom: 2px solid {accent};"
        )
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(24, 18, 24, 18)
        h_layout.setSpacing(12)

        icon_lbl = QLabel(provider_icon)
        icon_lbl.setStyleSheet("font-size: 28px; background: transparent;")
        h_layout.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        title_lbl = QLabel(ev.get("title", "Untitled Event"))
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(
            "color:#ffffff; font-size:18px; font-weight:700; background:transparent;"
        )
        title_col.addWidget(title_lbl)

        source_lbl = QLabel(provider_name)
        source_lbl.setStyleSheet(
            f"color:{accent}; font-size:12px; font-weight:600; background:transparent;"
        )
        title_col.addWidget(source_lbl)
        h_layout.addLayout(title_col, 1)
        root.addWidget(header)

        # ── Scrollable body ──────────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 20, 24, 24)
        body_layout.setSpacing(12)

        def _row(icon: str, label: str, value: str, val_color: str = "#e0e6f0"):
            if not value or not str(value).strip():
                return
            row = QFrame()
            row.setStyleSheet(
                "background:#0f1a2e; border:1px solid #1a2e4a; border-radius:8px;"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 10, 14, 10)
            rl.setSpacing(12)

            ic = QLabel(icon)
            ic.setFixedWidth(22)
            ic.setStyleSheet("font-size:16px; background:transparent;")
            rl.addWidget(ic)

            lc = QVBoxLayout()
            lc.setSpacing(1)

            lbl_w = QLabel(label.upper())
            lbl_w.setStyleSheet(
                "color:#4a5a70; font-size:10px; font-weight:700; background:transparent;"
            )
            lc.addWidget(lbl_w)

            val_w = QLabel(str(value))
            val_w.setWordWrap(True)
            val_w.setStyleSheet(
                f"color:{val_color}; font-size:13px; background:transparent;"
            )
            lc.addWidget(val_w)
            rl.addLayout(lc, 1)
            body_layout.addWidget(row)

        # Time
        start = ev.get("start", "")
        end   = ev.get("end",   "")
        if start and end and start != end:
            _row("🕐", "Time", f"{start}  →  {end}", accent)
        elif start:
            _row("🕐", "Time", start, accent)

        # Calendar name
        _row("📁", "Calendar", ev.get("calendar", ""))

        # Location
        _row("📍", "Location", ev.get("location", ""))

        # Description / notes — strip basic HTML Google sometimes includes
        import re
        desc = ev.get("description", ev.get("body", ev.get("notes", "")))
        if desc:
            desc = re.sub(r"<[^>]+>", "", str(desc)).strip()
            _row("📝", "Notes", desc)

        # URL
        url = ev.get("url", ev.get("webLink", ""))
        _row("🔗", "Link", url, "#33b5e5")

        # Organiser
        organiser = ev.get("organizer", ev.get("organiser", ""))
        if isinstance(organiser, dict):
            organiser = organiser.get("email", organiser.get("displayName", ""))
        _row("👤", "Organiser", str(organiser) if organiser else "")

        # Attendees
        attendees = ev.get("attendees", [])
        if attendees:
            if isinstance(attendees, list):
                lines = []
                for a in attendees:
                    if isinstance(a, dict):
                        name  = a.get("displayName", "")
                        email = a.get("email", "")
                        lines.append(f"{name} <{email}>" if name else email)
                    else:
                        lines.append(str(a))
                _row("👥", "Attendees", "\n".join(lines))

        # Open in browser button
        if url:
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            open_btn = PushButton(FIF.LINK, "Open in Browser")
            open_btn.setFixedHeight(36)
            open_btn.clicked.connect(lambda: __import__("webbrowser").open(url))
            btn_row.addWidget(open_btn)
            body_layout.addLayout(btn_row)

        body_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:transparent; border:none;")
        scroll.viewport().setStyleSheet("background:transparent;")
        scroll.setWidget(body)
        root.addWidget(scroll)

        self.adjustSize()

    def show_centered(self):
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.center().x() - self.width() // 2,
            screen.center().y() - self.height() // 2,
        )
        self.show()


# ---------------------------------------------------------------------------
# Day Events Panel — shown to the right of the calendar
# ---------------------------------------------------------------------------

class DayEventsPanel(QFrame):
    """
    Shows external calendar events for the selected day.
    Fills all available width — no fixed max.
    No gap/border on the left; blends seamlessly with the Timeline card.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # No border, no background tint — matches the card background
        self.setStyleSheet("QFrame { background: transparent; }")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(8)

        # Date heading
        self._date_label = StrongBodyLabel("Select a day")
        self._date_label.setStyleSheet(
            "color:#33b5e5; font-size:14px; font-weight:700;"
        )
        layout.addWidget(self._date_label)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#1a2236;")
        layout.addWidget(sep)

        # Scrollable event list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:transparent; border:none;")
        scroll.viewport().setStyleSheet("background:transparent;")

        self._container = QWidget()
        self._container.setStyleSheet("background:transparent;")
        self._items_layout = QVBoxLayout(self._container)
        self._items_layout.setContentsMargins(0, 4, 0, 0)
        self._items_layout.setSpacing(8)
        self._items_layout.addStretch()

        scroll.setWidget(self._container)
        layout.addWidget(scroll)

    # ── Public ───────────────────────────────────────────────────────────────

    def show_day(self, date: QDate, external_events: list):
        """Populate with events from external calendars for *date*."""
        self._date_label.setText(date.toString("dddd, d MMMM yyyy"))
        self._clear()

        if not external_events:
            lbl = BodyLabel("No events scheduled.")
            lbl.setStyleSheet("color:#444; font-size:12px;")
            self._items_layout.insertWidget(self._items_layout.count() - 1, lbl)
            return

        for ev in external_events:
            self._add_event_card(ev)

    # ── Private ──────────────────────────────────────────────────────────────

    def _clear(self):
        while self._items_layout.count() > 1:
            item = self._items_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_event_card(self, ev: dict):
        card = QFrame()
        card.setCursor(Qt.PointingHandCursor)
        card.setStyleSheet("""
            QFrame {
                background:#0f1a2e;
                border:1px solid #1a2e4a;
                border-radius:8px;
            }
            QFrame:hover {
                background:#152540;
                border:1px solid #33b5e5;
            }
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 8, 12, 8)
        cl.setSpacing(3)

        icon = "🗓" if ev.get("source") == "google" else "📅"

        # Title row with arrow hint
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title = BodyLabel(f"{icon}  {ev.get('title', 'Untitled')}")
        title.setStyleSheet("color:#e0e6f0; font-size:13px; font-weight:600;")
        title.setWordWrap(True)
        title_row.addWidget(title, 1)

        arrow = QLabel("›")
        arrow.setStyleSheet("color:#33b5e5; font-size:18px; font-weight:bold;")
        arrow.setFixedWidth(14)
        title_row.addWidget(arrow)
        cl.addLayout(title_row)

        ts = ev.get("start", "")
        if ts:
            tl = BodyLabel(ts)
            tl.setStyleSheet("color:#8b9bb4; font-size:11px;")
            cl.addWidget(tl)

        cal_name = ev.get("calendar", "")
        if cal_name:
            cn = BodyLabel(cal_name)
            cn.setStyleSheet("color:#4a6080; font-size:10px;")
            cl.addWidget(cn)

        # Click → open detail dialog
        # Capture ev in closure
        def _open(event, _ev=ev):
            dlg = EventDetailDialog(_ev, parent=self.window())
            dlg.show_centered()

        card.mousePressEvent = _open

        self._items_layout.insertWidget(self._items_layout.count() - 1, card)


# ---------------------------------------------------------------------------
# PlannerTab
# ---------------------------------------------------------------------------

class PlannerTab(QFrame):
    """
    Three-column layout with adjusted proportions:
      Focus Tasks  → stretch 2  (reduced ~10%)
      Timeline     → stretch 5  (enlarged ~20%)
      Perf Timers  → 288px fixed (reduced from 320px, ~10% narrower)
    """

    def __init__(self):
        super().__init__()
        self.setObjectName("plannerPanel")
        self.setStyleSheet("background: transparent;")
        self.completed_expanded = False
        self._setup_ui()
        self._load_tasks()

    def _setup_ui(self):
        planner_layout = QHBoxLayout(self)
        planner_layout.setContentsMargins(30, 30, 30, 30)
        planner_layout.setSpacing(25)

        # ── Column 1: Focus Tasks (stretch=2) ────────────────────────────────
        tasks_col = HeaderCardWidget("Focus Tasks")
        tasks_col.setBorderRadius(12)

        t_layout = QVBoxLayout()
        t_layout.setContentsMargins(20, 20, 20, 20)
        t_layout.setSpacing(15)

        self.task_input = LineEdit()
        self.task_input.setPlaceholderText("Add objective...")
        self.task_input.returnPressed.connect(self._add_task)
        self.task_input.setClearButtonEnabled(True)
        t_layout.addWidget(self.task_input)

        self.task_list = ListWidget()
        self.task_list.setStyleSheet("background: transparent; border: none;")
        t_layout.addWidget(self.task_list, 1)

        header_layout = QHBoxLayout()
        self.completed_header_btn = TransparentToolButton(FIF.CHEVRON_RIGHT)
        self.completed_header_btn.clicked.connect(self._toggle_completed_section)
        header_layout.addWidget(self.completed_header_btn)

        self.completed_label = BodyLabel("Completed 0")
        self.completed_label.setStyleSheet("color: #8b9bb4;")
        header_layout.addWidget(self.completed_label)
        header_layout.addStretch()
        t_layout.addLayout(header_layout)

        self.completed_list = ListWidget()
        self.completed_list.setStyleSheet("background: transparent; border: none;")
        self.completed_list.setVisible(False)
        t_layout.addWidget(self.completed_list)

        tasks_col.viewLayout.addLayout(t_layout)
        planner_layout.addWidget(tasks_col, 2)

        # ── Column 2: Timeline (stretch=5) ───────────────────────────────────
        schedule_col = HeaderCardWidget("Timeline")
        schedule_col.setBorderRadius(12)

        s_layout = QVBoxLayout()
        s_layout.setContentsMargins(10, 10, 10, 10)
        s_layout.setSpacing(8)

        # Toggle bar — two buttons only
        self.toggle_bar = CalendarToggleBar()
        self.toggle_bar.filter_changed.connect(self._on_filter_changed)
        s_layout.addWidget(self.toggle_bar)

        # Left side: two calendars stacked vertically (50% of row width)
        # Right side: day events panel (50% of row width)
        from PySide6.QtWidgets import QCalendarWidget

        CAL_STYLE = """
            QCalendarWidget {
                background: transparent;
                color: #e0e6f0;
                font-size: 12px;
            }
            QCalendarWidget QAbstractItemView {
                background: #0b1120;
                selection-background-color: #33b5e5;
                selection-color: white;
                color: #e0e6f0;
                gridline-color: #1a2236;
            }
            QCalendarWidget QWidget#qt_calendar_navigationbar {
                background: #0f1524;
                border-radius: 6px;
                padding: 2px;
            }
            QCalendarWidget QToolButton {
                color: #e0e6f0;
                background: transparent;
                font-size: 12px;
                font-weight: bold;
            }
            QCalendarWidget QToolButton:hover {
                background: #1a2e4a;
                border-radius: 4px;
            }
            QCalendarWidget QSpinBox {
                color: #e0e6f0;
                background: transparent;
                font-size: 12px;
            }
            QCalendarWidget QAbstractItemView:enabled  { color: #e0e6f0; }
            QCalendarWidget QAbstractItemView:disabled { color: #2a3040; }
        """

        cal_row = QHBoxLayout()
        cal_row.setSpacing(12)

        # Left column: two calendars stacked
        cal_col = QVBoxLayout()
        cal_col.setSpacing(6)

        # Month 1 — current month
        self._calendar = QCalendarWidget()
        self._calendar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._calendar.setStyleSheet(CAL_STYLE)
        self._calendar.selectionChanged.connect(
            lambda: self._on_day_clicked(self._calendar.selectedDate())
        )
        cal_col.addWidget(self._calendar, 1)

        # Month 2 — next month (read-only, clicking a day syncs selection to cal 1)
        self._calendar2 = QCalendarWidget()
        self._calendar2.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._calendar2.setStyleSheet(CAL_STYLE)
        # Advance to next month
        today = QDate.currentDate()
        next_month = today.addMonths(1)
        self._calendar2.setCurrentPage(next_month.year(), next_month.month())
        self._calendar2.selectionChanged.connect(
            lambda: self._on_day_clicked(self._calendar2.selectedDate())
        )
        cal_col.addWidget(self._calendar2, 1)

        # Wrap in a widget so stretch works cleanly
        cal_widget = QWidget()
        cal_widget.setStyleSheet("background:transparent;")
        cal_widget.setLayout(cal_col)
        cal_row.addWidget(cal_widget, 1)   # stretch=1 → 50% of row

        # Right column: day events panel
        self.day_panel = DayEventsPanel()
        cal_row.addWidget(self.day_panel, 1)  # stretch=1 → 50% of row

        s_layout.addLayout(cal_row, 1)
        schedule_col.viewLayout.addLayout(s_layout)
        planner_layout.addWidget(schedule_col, 5)

        # ── Column 3: Performance Timers (288px fixed) ───────────────────────
        flow_col = QFrame()
        flow_col.setFixedWidth(288)
        flow_col.setStyleSheet("background: transparent; border: none;")
        flow_layout = QVBoxLayout(flow_col)
        flow_layout.setContentsMargins(0, 0, 0, 0)
        flow_layout.setSpacing(25)

        p_title = StrongBodyLabel("Performance Timers")
        p_title.setStyleSheet("color: #e8eaed; font-size: 14px;")
        flow_layout.addWidget(p_title)

        self.timer_component = TimerComponent()
        flow_layout.addWidget(self.timer_component)

        self.alarm_component = AlarmComponent()
        flow_layout.addWidget(self.alarm_component)

        flow_layout.addStretch()
        planner_layout.addWidget(flow_col)

    # ── Calendar hooks ────────────────────────────────────────────────────────

    def _on_day_clicked(self, date: QDate):
        self._last_selected = date
        ext = self.toggle_bar.events_for_date(date)
        self.day_panel.show_day(date, ext)

    def _on_filter_changed(self):
        date = getattr(self, "_last_selected", QDate.currentDate())
        self._on_day_clicked(date)

    # ── Task management ───────────────────────────────────────────────────────

    def _load_tasks(self):
        tasks = task_manager.get_tasks()
        self.task_list.clear()
        self.completed_list.clear()
        for task in tasks:
            self._create_task_item(task)
        self._update_task_counter()

    def _add_task(self):
        if hasattr(self, 'task_input'):
            task_text = self.task_input.text().strip()
            if task_text:
                self._add_task_from_text(task_text)
                self.task_input.clear()

    def _add_task_from_text(self, task_text):
        new_task = task_manager.add_task(task_text)
        if new_task:
            self._create_task_item(new_task)
        self._update_task_counter()

    def _on_task_checked(self, state: int, item: QListWidgetItem, source_list: ListWidget):
        widget = source_list.itemWidget(item)
        if not widget:
            return
        task_id = item.data(Qt.UserRole)
        label = widget.findChild(BodyLabel) or widget.findChild(QLabel)
        if not label:
            return
        task_text = label.text()
        row = source_list.row(item)
        is_completed = (state == Qt.Checked.value)
        task_manager.toggle_task(task_id, is_completed)
        source_list.takeItem(row)
        task_data = {"id": task_id, "text": task_text, "completed": is_completed}
        self._create_task_item(task_data)
        self._update_task_counter()

    def _create_task_item(self, task_data: dict):
        completed = task_data.get('completed', False)
        text = task_data.get('text', '')
        task_id = task_data.get('id')
        target_list = self.completed_list if completed else self.task_list

        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 50))
        item.setData(Qt.UserRole, task_id)

        task_widget = QWidget()
        task_layout = QHBoxLayout(task_widget)
        task_layout.setContentsMargins(10, 5, 10, 5)
        task_layout.setSpacing(12)

        checkbox = CheckBox()
        checkbox.setChecked(completed)
        checkbox.stateChanged.connect(
            lambda state, i=item, l=target_list: self._on_task_checked(state, i, l)
        )
        task_layout.addWidget(checkbox)

        task_label = BodyLabel(text)
        if completed:
            task_label.setStyleSheet("color: #8a8a8a; text-decoration: line-through;")
        else:
            task_label.setStyleSheet("color: #e8eaed;")
        task_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        task_layout.addWidget(task_label, 1)

        delete_btn = TransparentToolButton(FIF.DELETE)
        delete_btn.clicked.connect(lambda: self._delete_task(item, target_list))
        task_layout.addWidget(delete_btn)

        target_list.addItem(item)
        target_list.setItemWidget(item, task_widget)

    def _delete_task(self, item: QListWidgetItem, source_list: ListWidget = None):
        if source_list is None:
            source_list = self.task_list
        task_id = item.data(Qt.UserRole)
        task_manager.delete_task(task_id)
        row = source_list.row(item)
        if row >= 0:
            source_list.takeItem(row)
            self._update_task_counter()

    def _toggle_completed_section(self):
        self.completed_expanded = not self.completed_expanded
        self.completed_list.setVisible(self.completed_expanded)
        icon = FIF.CHEVRON_DOWN_MED if self.completed_expanded else FIF.CHEVRON_RIGHT
        self.completed_header_btn.setIcon(icon)

    def _update_task_counter(self):
        self.completed_label.setText(f"Completed {self.completed_list.count()}")
