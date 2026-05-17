"""
gui/tabs/dashboard.py

P.L.I.A. Dashboard Tab — Iron Man HUD style.

Layout
------
  ┌─────────────────────────────────────────────────────┐
  │  ◆ P.L.I.A.   ● ONLINE            HH:MM:SS — Day   │  ← top bar
  ├───────────┬─────────────────────────────────────────┤
  │  Plia     │  COMMUNICATION LOG                      │
  │  Logo     │                                         │
  │           │  [scrolling monospace log,              │
  │  ───────  │   stretches to fill the panel]          │
  │  SYSTEM   │                                         │
  │  MONITOR  │                                         │
  │           │                                         │
  │           │  [__input__________]            [SEND]  │
  └───────────┴─────────────────────────────────────────┘
"""

from __future__ import annotations

import datetime
import traceback

import psutil

from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QLineEdit, QSizePolicy, QScrollBar,
)
from PySide6.QtCore import (
    Qt, QTimer, QThread, QObject, Signal, QRectF,
)
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QTextCharFormat,
    QTextCursor,
)


# ── GPU monitoring ────────────────────────────────────────────
try:
    import pynvml
    pynvml.nvmlInit()
    _GPU_OK = True
except Exception:
    _GPU_OK = False

# ── Colour palette (matches plia2.py C_* constants) ───────────
C_BG          = "#0a0a0f"
C_PANEL       = "#0d0d18"
C_BORDER      = "#1a3a5c"
C_ACCENT      = "#00b4d8"
C_ACCENT2     = "#0077b6"
C_TEXT        = "#c8dce8"
C_TEXT_DIM    = "#4a6a80"
C_WARN        = "#f4a261"
C_ERROR       = "#e63946"
C_SUCCESS     = "#2ec4b6"
C_GOLD        = "#ffd60a"
C_ARC_BLUE    = "#48cae4"
C_ARC_GLOW    = "#90e0ef"
C_REACTOR     = "#00b4d8"
C_GPU         = "#4fc3f7"



# ══════════════════════════════════════════════════════════════
#  SYSTEM MONITOR PANEL (bar-based, matches plia2.py look)
# ══════════════════════════════════════════════════════════════
class _BarRow(QWidget):
    """Single metric row: label | progress bar | percentage."""

    def __init__(self, name: str, accent: QColor, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(22)
        self._pct    = 0.0
        self._accent = accent

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(4)

        self._name_lbl = QLabel(f"{name}:")
        self._name_lbl.setFixedWidth(38)
        self._name_lbl.setFont(QFont("Consolas", 8))
        self._name_lbl.setStyleSheet(f"color: {C_TEXT_DIM};")
        lay.addWidget(self._name_lbl)

        self._bar = _MiniBar(accent)
        self._bar.setFixedSize(110, 12)
        lay.addWidget(self._bar)

        self._pct_lbl = QLabel("--")
        self._pct_lbl.setFixedWidth(36)
        self._pct_lbl.setFont(QFont("Consolas", 8))
        self._pct_lbl.setStyleSheet(f"color: {C_TEXT};")
        lay.addWidget(self._pct_lbl)

    def set_value(self, pct: float, override_color: QColor | None = None) -> None:
        self._pct = max(0.0, min(100.0, pct))
        color = override_color or self._color_for(pct)
        self._bar.set_value(self._pct, color)
        self._pct_lbl.setText(f"{pct:.0f}%")
        self._pct_lbl.setStyleSheet(
            f"color: {color.name()}; font-family: Consolas; font-size: 8pt;"
        )

    @staticmethod
    def _color_for(pct: float) -> QColor:
        if pct >= 90:
            return QColor("#ef5350")
        if pct >= 70:
            return QColor("#ffb74d")
        if pct >= 50:
            return QColor("#fff176")
        return QColor(C_ACCENT)


class _MiniBar(QWidget):
    """Thin coloured progress bar without Qt's built-in QProgressBar styling."""

    def __init__(self, default_color: QColor, parent=None) -> None:
        super().__init__(parent)
        self._pct   = 0.0
        self._color = default_color

    def set_value(self, pct: float, color: QColor) -> None:
        self._pct   = pct
        self._color = color
        self.update()

    def paintEvent(self, _event) -> None:          # noqa: N802
        p = QPainter(self)
        w, h = self.width(), self.height()

        # Dark background
        p.fillRect(0, 0, w, h, QColor("#0a0a12"))
        # Filled portion
        filled = int(w * self._pct / 100)
        if filled > 0:
            p.fillRect(0, 0, filled, h, self._color)
        # Border
        pen = QPen(QColor(C_BORDER))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(0, 0, w - 1, h - 1)
        p.end()


class _MonitorWorker(QObject):
    """Collect psutil / pynvml stats off the UI thread."""
    stats_ready = Signal(dict)

    def collect(self) -> None:                     # noqa: D102
        try:
            data: dict = {}
            data["cpu"]  = psutil.cpu_percent(interval=None)
            mem          = psutil.virtual_memory()
            data["ram"]  = mem.percent
            disk         = psutil.disk_usage("/")
            data["disk"] = disk.percent
            boot         = datetime.datetime.fromtimestamp(psutil.boot_time())
            up           = datetime.datetime.now() - boot
            d, h, m      = (up.days,
                            up.seconds // 3600,
                            (up.seconds % 3600) // 60)
            data["uptime"] = f"Uptime: {d}d {h}h {m}m"

            if _GPU_OK:
                try:
                    handle         = pynvml.nvmlDeviceGetHandleByIndex(0)
                    util           = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    mi             = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    data["gpu"]    = float(util.gpu)
                    data["vram"]   = (mi.used / mi.total) * 100 if mi.total else 0.0
                    data["vram_gb"] = (
                        f"{mi.used / 1024**3:.1f} / {mi.total / 1024**3:.1f} GB"
                    )
                except Exception:
                    data["gpu"] = data["vram"] = None
            else:
                data["gpu"] = data["vram"] = None

            self.stats_ready.emit(data)
        except Exception:
            pass


class SystemMonitorPanel(QFrame):
    """
    Left-panel system monitor with CPU / RAM / DISK / GPU / VRAM bars.
    Mirrors plia2.py's SystemMonitorPanel, rebuilt for PySide6.
    Updates every 2 seconds via a background QThread.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background: {C_PANEL}; border: none;")
        self._build()
        self._start_worker()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)

        hdr = QLabel("SYSTEM MONITOR")
        hdr.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C_ACCENT};")
        hdr.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(hdr)

        gpu_color = QColor(C_GPU)

        self._cpu_row  = _BarRow("CPU",  QColor(C_ACCENT))
        self._ram_row  = _BarRow("RAM",  QColor(C_ACCENT))
        self._disk_row = _BarRow("DISK", QColor(C_ACCENT))
        self._gpu_row  = _BarRow("GPU",  gpu_color)
        self._vram_row = _BarRow("VRAM", gpu_color)

        for row in (self._cpu_row, self._ram_row, self._disk_row,
                    self._gpu_row, self._vram_row):
            lay.addWidget(row)

        self._vram_detail = QLabel("")
        self._vram_detail.setFont(QFont("Consolas", 7))
        self._vram_detail.setStyleSheet(f"color: {C_GPU};")
        self._vram_detail.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._vram_detail)

        if not _GPU_OK:
            self._vram_detail.setText("nvidia-ml-py not found")
            self._vram_detail.setStyleSheet(f"color: {C_TEXT_DIM};")

        self._uptime_lbl = QLabel("Uptime: --")
        self._uptime_lbl.setFont(QFont("Consolas", 7))
        self._uptime_lbl.setStyleSheet(f"color: {C_TEXT_DIM};")
        self._uptime_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._uptime_lbl)

    def _start_worker(self) -> None:
        self._thread = QThread(self)
        self._thread.setObjectName("SystemMonitor")
        self._worker = _MonitorWorker()
        self._worker.moveToThread(self._thread)
        self._worker.stats_ready.connect(self._on_stats)
        self._thread.start()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._worker.collect)
        self._timer.start(2000)
        QTimer.singleShot(200, self._worker.collect)

    def _on_stats(self, data: dict) -> None:
        self._cpu_row.set_value(data.get("cpu", 0))
        self._ram_row.set_value(data.get("ram", 0))
        self._disk_row.set_value(data.get("disk", 0))
        self._uptime_lbl.setText(data.get("uptime", "Uptime: --"))

        gpu  = data.get("gpu")
        vram = data.get("vram")
        gpu_color = QColor(C_GPU)

        if gpu is not None:
            self._gpu_row.set_value(gpu,  self._usage_color(gpu,  gpu_color))
            self._vram_row.set_value(vram, self._usage_color(vram, gpu_color))
            self._vram_detail.setText(data.get("vram_gb", ""))
            self._vram_detail.setStyleSheet(
                f"color: {self._usage_color(vram or 0, gpu_color).name()};"
            )
        else:
            self._gpu_row.set_value(0, gpu_color)
            self._vram_row.set_value(0, gpu_color)
            if _GPU_OK:
                self._vram_detail.setText("GPU read error")
                self._vram_detail.setStyleSheet(f"color: {C_ERROR};")

    @staticmethod
    def _usage_color(pct: float, base: QColor) -> QColor:
        if pct >= 90:
            return QColor("#ef5350")
        if pct >= 70:
            return QColor("#ffb74d")
        if pct >= 50:
            return QColor("#fff176")
        return base

    def cleanup(self) -> None:
        self._timer.stop()
        self._thread.quit()
        self._thread.wait()


# ══════════════════════════════════════════════════════════════
#  COMMUNICATION LOG (QTextEdit with colour-tagged output)
# ══════════════════════════════════════════════════════════════
class CommunicationLog(QTextEdit):
    """
    Read-only log widget that mirrors plia2.py's ScrolledText conversation area.
    Supports four colour tags: 'system', 'user', 'plia', 'error'.
    """

    _TAG_COLORS = {
        "system":  C_TEXT_DIM,
        "user":    C_GOLD,
        "plia":    C_ACCENT,
        "error":   C_ERROR,
        "success": C_SUCCESS,
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Consolas", 10))
        self.setStyleSheet(f"""
            QTextEdit {{
                background-color: #080814;
                color: {C_TEXT};
                border: none;
                padding: 8px;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {C_BORDER};
                border-radius: 3px;
            }}
        """)

    def append_message(self, text: str, tag: str = "system") -> None:
        """Append a timestamped, colour-coded line."""
        color    = self._TAG_COLORS.get(tag, C_TEXT)
        ts       = datetime.datetime.now().strftime("%H:%M:%S")

        cursor   = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Timestamp (always dimmed)
        fmt_ts   = QTextCharFormat()
        fmt_ts.setForeground(QColor(C_TEXT_DIM))
        cursor.setCharFormat(fmt_ts)
        cursor.insertText(f"[{ts}] ")

        # Message body (colour-tagged)
        fmt_msg  = QTextCharFormat()
        fmt_msg.setForeground(QColor(color))
        cursor.setCharFormat(fmt_msg)
        cursor.insertText(f"{text}\n")

        self.setTextCursor(cursor)
        self.ensureCursorVisible()


# ══════════════════════════════════════════════════════════════
#  DASHBOARD VIEW  (main QWidget registered as a tab)
# ══════════════════════════════════════════════════════════════
_BTN_STYLE = f"""
    QPushButton {{
        background: #111122;
        color: {C_TEXT};
        border: 1px solid {C_BORDER};
        border-radius: 3px;
        font-family: Consolas;
        font-size: 9pt;
        padding: 3px 6px;
        text-align: left;
    }}
    QPushButton:hover {{
        background: {C_ACCENT2};
        color: white;
        border-color: {C_ACCENT};
    }}
    QPushButton:pressed {{
        background: {C_ACCENT};
    }}
"""

_SEND_STYLE = f"""
    QPushButton {{
        background: {C_ACCENT2};
        color: white;
        border: none;
        border-radius: 3px;
        font-family: Consolas;
        font-size: 9pt;
        font-weight: bold;
        padding: 4px 14px;
    }}
    QPushButton:hover  {{ background: {C_ACCENT}; }}
    QPushButton:pressed {{ background: #005f8a; }}
"""

_INPUT_STYLE = f"""
    QLineEdit {{
        background: #0a0a16;
        color: {C_TEXT};
        border: 1px solid {C_BORDER};
        border-radius: 3px;
        font-family: Consolas;
        font-size: 11pt;
        padding: 2px 6px;
    }}
    QLineEdit:focus {{
        border-color: {C_ACCENT};
    }}
"""


class DashboardView(QWidget):
    """
    Main dashboard tab — P.L.I.A. HUD style.

    Signals
    -------
    navigate_to(str) : emitted with objectName of the target tab so that
                       app.py can call switchTo() appropriately.
    """

    navigate_to = Signal(str)

    # ── Construction ──────────────────────────────────────────
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dashboardInterface")
        self.setStyleSheet(f"background: {C_BG};")

        self._build_ui()
        self._start_clock()
        self._post_init_messages()

    # ── UI construction ───────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_top_bar())

        # Thin separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {C_BORDER}; border: none;")
        root.addWidget(sep)

        # Main content area
        content = QHBoxLayout()
        content.setContentsMargins(5, 5, 5, 5)
        content.setSpacing(5)
        content.addWidget(self._build_left_panel(), 0)
        content.addWidget(self._build_right_panel(), 1)
        root.addLayout(content)

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(40)
        bar.setStyleSheet("background: #060610; border: none;")

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(15, 4, 15, 4)
        lay.setSpacing(20)

        title = QLabel("◆ P.L.I.A.")
        title.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C_ACCENT};")
        lay.addWidget(title)

        self._status_lbl = QLabel("● ONLINE")
        self._status_lbl.setFont(QFont("Consolas", 10))
        self._status_lbl.setStyleSheet(f"color: {C_SUCCESS};")
        lay.addWidget(self._status_lbl)

        lay.addStretch()

        self._clock_lbl = QLabel("")
        self._clock_lbl.setFont(QFont("Consolas", 10))
        self._clock_lbl.setStyleSheet(f"color: {C_TEXT_DIM};")
        lay.addWidget(self._clock_lbl)

        return bar

    def _build_left_panel(self) -> QFrame:
        panel = QFrame()
        panel.setFixedWidth(225)
        panel.setStyleSheet(f"background: {C_PANEL}; border: none;")

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 5, 0, 5)
        lay.setSpacing(0)

        # Plia logo (lip-syncs with TTS speaking state)
        from gui.components.plia_logo import PliaLogoWidget
        self.reactor = PliaLogoWidget(size=190)
        lay.addWidget(self.reactor, 0, Qt.AlignmentFlag.AlignHCenter)

        lay.addWidget(self._hsep())

        # System monitor bars
        self.sys_monitor = SystemMonitorPanel()
        lay.addWidget(self.sys_monitor)

        lay.addStretch()

        return panel

    def _build_right_panel(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet(f"background: {C_BG}; border: none;")

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Header bar ────────────────────────────────────────
        hdr = QFrame()
        hdr.setFixedHeight(28)
        hdr.setStyleSheet("background: #060610; border: none;")
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(10, 0, 10, 0)
        lbl = QLabel("COMMUNICATION LOG")
        lbl.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {C_TEXT_DIM};")
        hdr_lay.addWidget(lbl)
        hdr_lay.addStretch()
        lay.addWidget(hdr)

        # ── Live-agent result cards ──────────────────────────────────────
        from PySide6.QtWidgets import QVBoxLayout as _QVBox
        self._agent_cards_box = QWidget()
        self._agent_cards_layout = _QVBox(self._agent_cards_box)
        self._agent_cards_layout.setContentsMargins(0, 0, 0, 0)
        self._agent_cards_layout.setSpacing(6)
        lay.addWidget(self._agent_cards_box)

        # ── Communication log ────────────────────────────────
        self.log = CommunicationLog()
        self.log.setMinimumHeight(120)
        lay.addWidget(self.log, 1)   # stretch to fill all space above input bar

        # ── Input area ───────────────────────────────────────
        input_frame = QFrame()
        input_frame.setFixedHeight(52)
        input_frame.setStyleSheet(f"background: {C_PANEL}; border: none;")
        inp_lay = QHBoxLayout(input_frame)
        inp_lay.setContentsMargins(8, 6, 8, 6)
        inp_lay.setSpacing(4)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command…")
        self._input.setStyleSheet(_INPUT_STYLE)
        self._input.returnPressed.connect(self._on_send)
        inp_lay.addWidget(self._input, 1)

        send_btn = QPushButton("SEND")
        send_btn.setStyleSheet(_SEND_STYLE)
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.clicked.connect(self._on_send)
        inp_lay.addWidget(send_btn)

        lay.addWidget(input_frame)

        return panel

    # ── Helpers ───────────────────────────────────────────────
    @staticmethod
    def _hsep() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {C_BORDER}; border: none;")
        return sep

    # ── Clock ─────────────────────────────────────────────────
    def _start_clock(self) -> None:
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._tick_clock()

    def _tick_clock(self) -> None:
        now = datetime.datetime.now().strftime("%I:%M:%S %p  —  %A, %b %d")
        self._clock_lbl.setText(now)

    # ── Startup log messages ──────────────────────────────────
    def _post_init_messages(self) -> None:
        self.log.append_message("P.L.I.A. initialized. All systems nominal.")

        try:
            import psutil as _ps
            ps_status = "Online"
        except ImportError:
            ps_status = "OFF — pip install psutil"

        gpu_status = "Online" if _GPU_OK else "OFF — pip install nvidia-ml-py"

        self.log.append_message(
            f"System Monitor: {ps_status}  |  GPU Monitor: {gpu_status}"
        )
        self.log.append_message(
            "Type any command, question, or task below — same capabilities "
            "as voice. 'status' for an instant system readout."
        )
        self.log.append_message("System is ready.", "success")

    # ── Quick-action button handlers ──────────────────────────
    def _cmd_status(self) -> None:
        try:
            cpu  = psutil.cpu_percent(interval=None)
            mem  = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            msg  = (f"System Status — CPU: {cpu:.1f}%  "
                    f"RAM: {mem.percent:.1f}%  "
                    f"Disk: {disk.percent:.1f}%")
            if _GPU_OK:
                try:
                    h    = pynvml.nvmlDeviceGetHandleByIndex(0)
                    util = pynvml.nvmlDeviceGetUtilizationRates(h)
                    mi   = pynvml.nvmlDeviceGetMemoryInfo(h)
                    msg += (f"  GPU: {util.gpu}%  "
                            f"VRAM: {mi.used/1024**3:.1f}/"
                            f"{mi.total/1024**3:.1f} GB")
                except Exception:
                    msg += "  GPU: read error"
            self.log.append_message(msg, "success")
        except Exception as exc:
            self.log.append_message(f"Status error: {exc}", "error")

    # ── Input send handler ────────────────────────────────────
    def _on_send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.log.append_message(f"► {text}", "user")

        # "status" stays a local fast-path — instant CPU/RAM/GPU readout
        # without a round-trip through the LLM.
        cmd = text.lower()
        if cmd in ("status", "system status"):
            self._cmd_status()
            return

        # Everything else goes through the full voice-assistant pipeline:
        # plugin reload, agent creation wizard, web search, weather,
        # planner intents, smart-home, file reading, desktop automation,
        # and LLM chat as the final fallback — same set of capabilities
        # the wake-word path exposes.
        try:
            from core.voice_assistant import voice_assistant
            voice_assistant._on_speech(text)
        except Exception as exc:
            self.log.append_message(f"Dispatch error: {exc}", "error")

    # ── Public helpers (called by app.py voice signals) ───────
    def set_status_online(self) -> None:
        self._status_lbl.setText("● ONLINE")
        self._status_lbl.setStyleSheet(f"color: {C_SUCCESS};")

    def set_status_listening(self) -> None:
        self._status_lbl.setText("● LISTENING")
        self._status_lbl.setStyleSheet(f"color: {C_ACCENT};")

    def set_status_processing(self) -> None:
        self._status_lbl.setText("● PROCESSING")
        self._status_lbl.setStyleSheet(f"color: {C_GOLD};")

    def add_system_message(self, text: str, tag: str = "system") -> None:
        """Allow external callers to inject messages into the log."""
        self.log.append_message(text, tag)

    def add_agent_card(self, payload: dict) -> None:
        """Add a live-agent result card to the right panel. Newest on top,
        capped at 5 visible cards."""
        from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel

        card = QFrame()
        card.setObjectName("agentResultCard")
        ok = payload.get("success", True)
        border = "#4caf50" if ok else "#ef5350"
        card.setStyleSheet(
            f"QFrame#agentResultCard {{ border: 1px solid {border};"
            f" border-radius: 6px; background: rgba(255,255,255,0.04); }}"
        )
        col = QVBoxLayout(card)
        col.setContentsMargins(8, 6, 8, 6)
        col.setSpacing(2)

        header = QLabel(f"{payload.get('icon', '🤖')}  {payload.get('title', 'Agent')}")
        header.setStyleSheet("font-weight: 600;")
        col.addWidget(header)

        summary = QLabel(payload.get("summary", ""))
        summary.setWordWrap(True)
        col.addWidget(summary)

        from core.agent_reporting import _item_label
        for item in payload.get("items", []):
            row = QLabel(f"  • {_item_label(item)}")
            row.setStyleSheet("color: #9aa0aa;")
            col.addWidget(row)

        self._agent_cards_layout.insertWidget(0, card)

        # cap at 5 visible cards
        while self._agent_cards_layout.count() > 5:
            old = self._agent_cards_layout.takeAt(self._agent_cards_layout.count() - 1)
            w = old.widget()
            if w is not None:
                w.deleteLater()

    # ── Cleanup ───────────────────────────────────────────────
    def closeEvent(self, event) -> None:           # noqa: N802
        if hasattr(self, "sys_monitor"):
            try:
                self.sys_monitor.cleanup()
            except Exception:
                pass
        super().closeEvent(event)
