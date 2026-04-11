"""
WeatherWindow — floating, draggable weather card.

Shown when the user asks about weather via voice.
Closed when the user says "close weather" or clicks the X button.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, QPoint, QThread, Signal
from PySide6.QtGui import QFont, QCursor

from qfluentwidgets import (
    BodyLabel, CaptionLabel, StrongBodyLabel, TitleLabel,
    TransparentToolButton, FluentIcon as FIF, CardWidget
)

# ---------------------------------------------------------------------------
# WMO weather code → emoji + description
# ---------------------------------------------------------------------------
CONDITION_ICON = {
    "Clear":   "☀️",
    "Cloudy":  "⛅",
    "Foggy":   "🌫️",
    "Rain":    "🌧️",
    "Storm":   "⛈️",
    "Snow":    "❄️",
    "Windy":   "💨",
    "Smoky":   "🌁",
    "Dusty":   "🌪️",
    "Unknown": "🌡️",
}


def _condition_icon(condition: str) -> str:
    return CONDITION_ICON.get(condition, "🌡️")


# ---------------------------------------------------------------------------
# Background fetch thread (re-fetches fresh data when window opens)
# ---------------------------------------------------------------------------
class WeatherFetchThread(QThread):
    fetched = Signal(dict)

    def run(self):
        try:
            from core.weather import weather_manager
            data = weather_manager.get_weather()
            if data:
                self.fetched.emit(data)
        except Exception as e:
            print(f"[WeatherWindow] Fetch error: {e}")


# ---------------------------------------------------------------------------
# Forecast step widget
# ---------------------------------------------------------------------------
class ForecastStep(QFrame):
    def __init__(self, time: str, temp: float, unit: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: rgba(255,255,255,0.04); border-radius: 8px;")
        self.setFixedWidth(70)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 8, 6, 8)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignCenter)

        time_lbl = CaptionLabel(time)
        time_lbl.setAlignment(Qt.AlignCenter)
        time_lbl.setStyleSheet("color: #8b9bb4;")

        temp_lbl = StrongBodyLabel(f"{temp}°")
        temp_lbl.setAlignment(Qt.AlignCenter)
        temp_lbl.setStyleSheet("color: #e8eaed;")

        lay.addWidget(time_lbl)
        lay.addWidget(temp_lbl)


# ---------------------------------------------------------------------------
# Main floating weather window
# ---------------------------------------------------------------------------
class WeatherWindow(QWidget):
    """
    Frameless, always-on-top, draggable weather card.
    Call show_weather(data) to populate and display.
    Call close_weather() to hide.
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(380)

        self._drag_pos = QPoint()
        self._fetch_thread = None

        self._build_ui()

    # ── UI build ──────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Outer card
        self._card = QFrame()
        self._card.setStyleSheet("""
            QFrame {
                background-color: #0f1524;
                border: 1px solid #1a2236;
                border-radius: 16px;
            }
        """)
        card_lay = QVBoxLayout(self._card)
        card_lay.setContentsMargins(24, 20, 24, 20)
        card_lay.setSpacing(12)

        # ── Top bar (title + close button) ───────────────────────────────
        top = QHBoxLayout()
        self._loc_label = CaptionLabel("Current Weather")
        self._loc_label.setStyleSheet("color: #8b9bb4;")
        top.addWidget(self._loc_label)
        top.addStretch()

        close_btn = TransparentToolButton(FIF.CLOSE)
        close_btn.setFixedSize(28, 28)
        close_btn.clicked.connect(self.close_weather)
        top.addWidget(close_btn)
        card_lay.addLayout(top)

        # ── Main temperature row ─────────────────────────────────────────
        main_row = QHBoxLayout()
        main_row.setSpacing(16)

        self._icon_label = QLabel("🌡️")
        self._icon_label.setFont(QFont("Segoe UI Emoji", 52))
        self._icon_label.setAlignment(Qt.AlignCenter)
        main_row.addWidget(self._icon_label)

        temp_col = QVBoxLayout()
        temp_col.setSpacing(2)
        self._temp_label = TitleLabel("--°C")
        self._temp_label.setStyleSheet("color: #e8eaed; font-size: 40px; font-weight: bold;")
        self._cond_label = StrongBodyLabel("Loading…")
        self._cond_label.setStyleSheet("color: #33b5e5;")
        self._feels_label = CaptionLabel("")
        self._feels_label.setStyleSheet("color: #8b9bb4;")
        temp_col.addWidget(self._temp_label)
        temp_col.addWidget(self._cond_label)
        temp_col.addWidget(self._feels_label)
        main_row.addLayout(temp_col)
        main_row.addStretch()
        card_lay.addLayout(main_row)

        # ── High / Low / Humidity / Wind row ────────────────────────────
        stats_row = QHBoxLayout()
        stats_row.setSpacing(20)
        self._high_lbl  = self._stat_widget("High",  "--")
        self._low_lbl   = self._stat_widget("Low",   "--")
        self._hum_lbl   = self._stat_widget("Humid", "--")
        self._wind_lbl  = self._stat_widget("Wind",  "--")
        for w in (self._high_lbl, self._low_lbl, self._hum_lbl, self._wind_lbl):
            stats_row.addWidget(w)
        stats_row.addStretch()
        card_lay.addLayout(stats_row)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("color: #1a2236;")
        card_lay.addWidget(div)

        # ── Forecast row ─────────────────────────────────────────────────
        forecast_lbl = CaptionLabel("HOURLY FORECAST")
        forecast_lbl.setStyleSheet("color: #555e70; letter-spacing: 1px;")
        card_lay.addWidget(forecast_lbl)

        self._forecast_row = QHBoxLayout()
        self._forecast_row.setSpacing(8)
        self._forecast_row.setAlignment(Qt.AlignLeft)
        card_lay.addLayout(self._forecast_row)

        # ── Source label ─────────────────────────────────────────────────
        self._source_label = CaptionLabel("")
        self._source_label.setStyleSheet("color: #2a3550; font-size: 10px;")
        self._source_label.setAlignment(Qt.AlignRight)
        card_lay.addWidget(self._source_label)

        root.addWidget(self._card)

    def _stat_widget(self, label: str, value: str) -> QFrame:
        f = QFrame()
        f.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)

        lbl = CaptionLabel(label)
        lbl.setStyleSheet("color: #555e70;")
        val = StrongBodyLabel(value)
        val.setStyleSheet("color: #e8eaed;")
        val.setObjectName(f"stat_{label.lower()}")

        lay.addWidget(lbl)
        lay.addWidget(val)
        f.setProperty("val_widget", val)
        return f

    def _set_stat(self, frame: QFrame, value: str):
        val = frame.property("val_widget")
        if val:
            val.setText(value)

    # ── Public API ────────────────────────────────────────────────────────

    def show_weather(self, data: dict = None):
        """Show the window. If data is None, fetch fresh data."""
        # Position near top-right of screen
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 40, screen.top() + 80)

        if data:
            self._populate(data)
        else:
            self._temp_label.setText("--")
            self._cond_label.setText("Fetching…")
            self._fetch()

        self.show()
        self.raise_()
        self.activateWindow()

    def close_weather(self):
        """Hide the window."""
        self.hide()

    def update_data(self, data: dict):
        """Called when fresh weather data arrives from voice assistant."""
        self._populate(data)
        if not self.isVisible():
            self.show_weather(data)

    # ── Data population ───────────────────────────────────────────────────

    def _fetch(self):
        if self._fetch_thread and self._fetch_thread.isRunning():
            return
        self._fetch_thread = WeatherFetchThread()
        self._fetch_thread.fetched.connect(self._populate)
        self._fetch_thread.start()

    def _populate(self, data: dict):
        if not data:
            self._cond_label.setText("No data available")
            return

        unit     = data.get("unit", "°C")
        temp     = data.get("temp", "--")
        cond     = data.get("condition", "Unknown")
        high     = data.get("high", "--")
        low      = data.get("low", "--")
        humidity = data.get("humidity")
        wind_spd = data.get("wind_spd")
        wind_dir = data.get("wind_dir", "")
        apparent = data.get("apparent")
        station  = data.get("station", "")
        provider = data.get("provider", "")
        forecast = data.get("forecast", [])

        self._temp_label.setText(f"{temp}{unit}")
        self._cond_label.setText(cond)
        self._icon_label.setText(_condition_icon(cond))

        feels = f"Feels like {apparent}{unit}" if apparent else ""
        self._feels_label.setText(feels)

        self._set_stat(self._high_lbl, f"{high}{unit}")
        self._set_stat(self._low_lbl,  f"{low}{unit}")
        self._set_stat(self._hum_lbl,  f"{humidity}%" if humidity is not None else "--")

        if wind_spd is not None:
            wind_txt = f"{wind_spd} km/h"
            if wind_dir:
                wind_txt = f"{wind_dir} {wind_txt}"
        else:
            wind_txt = "--"
        self._set_stat(self._wind_lbl, wind_txt)

        # Location / source
        src_parts = []
        if station:
            src_parts.append(station)
        if provider:
            src_parts.append(f"via {provider}")
        self._loc_label.setText(" · ".join(src_parts) if src_parts else "Current Weather")

        # BOM attribution
        if provider == "BOM":
            self._source_label.setText("Data courtesy of the Australian Bureau of Meteorology (bom.gov.au)")
        else:
            self._source_label.setText("")

        # Forecast steps
        # Clear old forecast widgets
        while self._forecast_row.count():
            item = self._forecast_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for step in forecast[:4]:
            w = ForecastStep(step.get("time", ""), step.get("temp", 0), unit)
            self._forecast_row.addWidget(w)

        self.adjustSize()

    # ── Drag to move ──────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = QPoint()
