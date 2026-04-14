"""
gui/tabs/dashboard.py

P.L.I.A. Dashboard Tab — Iron Man HUD style.
Replaces the original home-screen dashboard with the futuristic HUD display
seen in plia2.py, ported from Tkinter → PySide6.

Layout
------
  ┌─────────────────────────────────────────────────────┐
  │  ◆ P.L.I.A.   ● ONLINE            HH:MM:SS — Day   │  ← top bar
  ├───────────┬─────────────────────────────────────────┤
  │  Arc      │  COMMUNICATION LOG               [...]  │
  │  Reactor  │                                         │
  │           │  [scrolling monospace log]              │
  │  ───────  │                                         │
  │  SYSTEM   │  ───────────────────────────────────── │
  │  MONITOR  │  ~~~  waveform  ~~~                     │
  │           │  ───────────────────────────────────── │
  │  ───────  │  🎤  🔊  [__input__________]  [SEND]  │
  │  Buttons  │                                         │
  └───────────┴─────────────────────────────────────────┘
"""

from __future__ import annotations

import math
import random
import datetime
import traceback

import psutil

from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QLineEdit, QSizePolicy, QScrollBar,
)
from PySide6.QtCore import (
    Qt, QTimer, QThread, QObject, Signal, QRectF, QPointF,
)
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QTextCharFormat,
    QTextCursor, QPainterPath,
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
#  ARC REACTOR  (animated via QTimer + paintEvent)
# ══════════════════════════════════════════════════════════════
class ArcReactorWidget(QWidget):
    """
    Animated power-core widget that mirrors plia2.py's ArcReactorCanvas.
    Draws concentric rotating rings, triangular spokes, and a pulsing core
    using QPainter — no external assets required.
    """

    def __init__(self, parent: QWidget | None = None, size: int = 190) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

        self._size  = size
        self._cx    = size / 2
        self._cy    = size / 2
        self._angle = 0.0
        self._pulse = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)          # ~30 FPS

    def _tick(self) -> None:
        self._angle = (self._angle + 1.2) % 360
        self._pulse += 0.08
        self.update()

    def paintEvent(self, _event) -> None:          # noqa: N802
        p   = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx, cy = self._cx, self._cy
        ang    = self._angle
        pls    = self._pulse

        # Fill background
        p.fillRect(self.rect(), QColor(C_BG))

        # ── Faint outer glow rings ────────────────────────────
        for i in range(5):
            r     = 80 + i * 2.5
            alpha = max(10, 40 - i * 8)
            pen   = QPen(QColor(0, 20 + alpha, 180, alpha))
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # ── Outer ring ────────────────────────────────────────
        pen = QPen(QColor(C_BORDER))
        pen.setWidthF(2.0)
        p.setPen(pen)
        p.drawEllipse(QRectF(cx - 76, cy - 76, 152, 152))

        # ── 8 rotating outer ticks ────────────────────────────
        pen_acc = QPen(QColor(C_ACCENT))
        pen_acc.setWidthF(2.0)
        p.setPen(pen_acc)
        for i in range(8):
            a  = math.radians(ang + i * 45)
            x1 = cx + 66 * math.cos(a)
            y1 = cy + 66 * math.sin(a)
            x2 = cx + 76 * math.cos(a)
            y2 = cy + 76 * math.sin(a)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # ── Middle ring ───────────────────────────────────────
        pen_acc2 = QPen(QColor(C_ACCENT2))
        pen_acc2.setWidthF(1.0)
        p.setPen(pen_acc2)
        p.drawEllipse(QRectF(cx - 56, cy - 56, 112, 112))

        # ── 6 counter-rotating mid ticks ─────────────────────
        pen_blue = QPen(QColor(C_ARC_BLUE))
        pen_blue.setWidthF(2.0)
        p.setPen(pen_blue)
        for i in range(6):
            a  = math.radians(-ang * 1.5 + i * 60)
            x1 = cx + 48 * math.cos(a)
            y1 = cy + 48 * math.sin(a)
            x2 = cx + 56 * math.cos(a)
            y2 = cy + 56 * math.sin(a)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # ── Inner ring ────────────────────────────────────────
        pen_acc.setWidthF(1.0)
        p.setPen(pen_acc)
        p.drawEllipse(QRectF(cx - 35, cy - 35, 70, 70))

        # ── 3 fast-rotating triangular spokes ────────────────
        pen_glow = QPen(QColor(C_ARC_GLOW))
        pen_glow.setWidthF(1.0)
        p.setPen(pen_glow)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(3):
            a    = math.radians(ang * 2 + i * 120)
            x1   = cx + 28 * math.cos(a)
            y1   = cy + 28 * math.sin(a)
            x2   = cx + 35 * math.cos(a + 0.3)
            y2   = cy + 35 * math.sin(a + 0.3)
            x3   = cx + 35 * math.cos(a - 0.3)
            y3   = cy + 35 * math.sin(a - 0.3)
            path = QPainterPath()
            path.moveTo(x1, y1)
            path.lineTo(x2, y2)
            path.lineTo(x3, y3)
            path.closeSubpath()
            p.drawPath(path)

        # ── Pulsing core ─────────────────────────────────────
        pr = 16 + 4 * math.sin(pls)
        # Dark halo
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 26, 51)))
        p.drawEllipse(QRectF(cx - pr - 7, cy - pr - 7,
                             (pr + 7) * 2, (pr + 7) * 2))
        # Glowing core fill
        p.setBrush(QBrush(QColor(C_REACTOR)))
        pen_glow2 = QPen(QColor(C_ARC_GLOW))
        pen_glow2.setWidthF(2.0)
        p.setPen(pen_glow2)
        p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))
        # Inner highlight
        ir = 5 + 2 * math.sin(pls * 1.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(C_ARC_GLOW)))
        p.drawEllipse(QRectF(cx - ir, cy - ir, ir * 2, ir * 2))

        p.end()


# ══════════════════════════════════════════════════════════════
#  WAVEFORM  (animated sine wave)
# ══════════════════════════════════════════════════════════════
class WaveformWidget(QWidget):
    """
    Audio waveform visualiser that mirrors plia2.py's WaveformCanvas.
    Two layered sine waves rendered with QPainter, animated at ~30 FPS.
    Call set_amplitude(value) to make the waveform spike.
    """

    def __init__(self, parent: QWidget | None = None, height: int = 50) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        self._phase     = 0.0
        self._amplitude = 2.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_amplitude(self, amp: float) -> None:
        self._amplitude = max(2.0, min(25.0, float(amp)))

    def _tick(self) -> None:
        self._phase += 0.15
        if self._amplitude > 2.0:
            self._amplitude *= 0.97
        self.update()

    def paintEvent(self, _event) -> None:          # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(C_BG))

        w   = self.width()
        mid = self.height() / 2
        ph  = self._phase
        amp = self._amplitude

        # Primary wave
        pen1 = QPen(QColor(C_ACCENT))
        pen1.setWidthF(1.5)
        p.setPen(pen1)
        pts: list[QPointF] = []
        for x in range(0, w, 2):
            y = (mid + amp * math.sin(ph + x * 0.04)
                 * math.cos(ph * 0.7 + x * 0.02)
                 + random.uniform(-amp * 0.3, amp * 0.3))
            pts.append(QPointF(x, y))
        if len(pts) >= 2:
            path = QPainterPath()
            path.moveTo(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            p.drawPath(path)

        # Secondary wave (slightly different frequency)
        pen2 = QPen(QColor(C_ACCENT2))
        pen2.setWidthF(1.0)
        p.setPen(pen2)
        pts2: list[QPointF] = []
        for x in range(0, w, 2):
            y = mid + amp * 0.6 * math.sin(ph * 1.3 + x * 0.05 + 1)
            pts2.append(QPointF(x, y))
        if len(pts2) >= 2:
            path2 = QPainterPath()
            path2.moveTo(pts2[0])
            for pt in pts2[1:]:
                path2.lineTo(pt)
            p.drawPath(path2)

        p.end()


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
        lay.setContentsMargins(15, 0, 15, 0)
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

        # Arc reactor
        self.reactor = ArcReactorWidget(size=190)
        lay.addWidget(self.reactor, 0, Qt.AlignmentFlag.AlignHCenter)

        lay.addWidget(self._hsep())

        # System monitor bars
        self.sys_monitor = SystemMonitorPanel()
        lay.addWidget(self.sys_monitor)

        lay.addWidget(self._hsep())

        # Quick-action buttons
        btn_frame = QFrame()
        btn_frame.setStyleSheet(f"background: {C_PANEL}; border: none;")
        btn_lay = QVBoxLayout(btn_frame)
        btn_lay.setContentsMargins(10, 5, 10, 5)
        btn_lay.setSpacing(2)

        actions = [
            ("⚙  Status",   self._cmd_status),
            ("📋  Notes",   self._cmd_notes),
            ("⏰  Remind",  self._cmd_remind),
            ("🔍  Help",    self._cmd_help),
        ]
        for label, callback in actions:
            btn = QPushButton(label)
            btn.setStyleSheet(_BTN_STYLE)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(callback)
            btn_lay.addWidget(btn)

        lay.addWidget(btn_frame)
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

        # ── Communication log ────────────────────────────────
        self.log = CommunicationLog()
        lay.addWidget(self.log, 1)

        # ── Waveform ─────────────────────────────────────────
        self.waveform = WaveformWidget(height=50)
        lay.addWidget(self.waveform)

        # ── Input area ───────────────────────────────────────
        input_frame = QFrame()
        input_frame.setFixedHeight(52)
        input_frame.setStyleSheet(f"background: {C_PANEL}; border: none;")
        inp_lay = QHBoxLayout(input_frame)
        inp_lay.setContentsMargins(8, 6, 8, 6)
        inp_lay.setSpacing(4)

        mic_btn = QPushButton("🎤")
        mic_btn.setFixedSize(36, 36)
        mic_btn.setFont(QFont("Segoe UI Emoji", 14))
        mic_btn.setStyleSheet(f"""
            QPushButton {{
                background: #111122; color: {C_TEXT};
                border: 1px solid {C_BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C_ERROR}; }}
        """)
        mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mic_btn.setToolTip("Voice input (handled by voice assistant)")
        inp_lay.addWidget(mic_btn)

        spk_btn = QPushButton("🔊")
        spk_btn.setFixedSize(36, 36)
        spk_btn.setFont(QFont("Segoe UI Emoji", 12))
        spk_btn.setStyleSheet(f"""
            QPushButton {{
                background: #111122; color: {C_TEXT};
                border: 1px solid {C_BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C_WARN}; }}
        """)
        spk_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        spk_btn.setToolTip("TTS toggle (handled by voice assistant)")
        inp_lay.addWidget(spk_btn)

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
            "Type a command below or use the quick-action buttons on the left."
        )

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

    def _cmd_notes(self) -> None:
        self.log.append_message("► Navigating to Planner (Notes/Tasks)…", "plia")
        self.navigate_to.emit("plannerInterface")

    def _cmd_remind(self) -> None:
        self.log.append_message("► Navigating to Planner (Reminders/Alarms)…", "plia")
        self.navigate_to.emit("plannerInterface")

    def _cmd_help(self) -> None:
        """Display comprehensive help across all program features in the communication log."""
        sections = [
            ("═══════════════════════════════════════════════", "system"),
            ("  P.L.I.A. — HELP & COMMAND REFERENCE", "plia"),
            ("═══════════════════════════════════════════════", "system"),
            ("", "system"),
            ("▶ VOICE ACTIVATION", "success"),
            ("  Say 'Jarvis' to wake the assistant, then speak naturally.", "plia"),
            ("  The wake word can be changed in the Settings tab.", "plia"),
            ("", "system"),
            ("▶ DASHBOARD", "success"),
            ("  Status  — Show live CPU / RAM / Disk / GPU readings", "plia"),
            ("  Notes   — Jump to Planner (tasks and notes)", "plia"),
            ("  Remind  — Jump to Planner (alarms and timers)", "plia"),
            ("  Help    — Show this help panel", "plia"),
            ("  Type a command in the input box below and press SEND.", "plia"),
            ("", "system"),
            ("▶ CHAT TAB", "success"),
            ("  Ask any question or give any task in plain English.", "plia"),
            ("  Streaming responses powered by your local Ollama model.", "plia"),
            ("  Thinking / reasoning steps collapse inline automatically.", "plia"),
            ("  Voice: 'Jarvis, <any question or task>'", "plia"),
            ("", "system"),
            ("▶ WEB SEARCH  (DuckDuckGo)", "success"),
            ("  Type : 'search for Python tutorials'", "plia"),
            ("  Voice: 'Jarvis, internet search on <topic>'", "plia"),
            ("  Voice: 'Jarvis, search the web for <topic>'", "plia"),
            ("  A floating results panel opens with numbered links.", "plia"),
            ("  Navigate : 'Jarvis, next search page'", "plia"),
            ("  Open link: 'Jarvis, open search result 3'", "plia"),
            ("  Close    : 'Jarvis, close search'", "plia"),
            ("", "system"),
            ("▶ WEATHER", "success"),
            ("  Voice: 'Jarvis, what is the weather today?'", "plia"),
            ("  Voice: 'Jarvis, will it rain?'", "plia"),
            ("  A weather overlay appears; close with 'Jarvis, close weather'.", "plia"),
            ("  Set your location in Settings (latitude / longitude).", "plia"),
            ("", "system"),
            ("▶ PLANNER  (Calendar, Tasks, Alarms, Timers)", "success"),
            ("  Voice: 'Jarvis, add buy groceries to my to-do list'", "plia"),
            ("  Voice: 'Jarvis, set a timer for 10 minutes'", "plia"),
            ("  Voice: 'Jarvis, set an alarm for 7 AM'", "plia"),
            ("  Voice: 'Jarvis, add meeting with team on Friday at 2 PM'", "plia"),
            ("  Voice: 'Jarvis, what is on my schedule today?'", "plia"),
            ("  GUI:   Use the Planner tab to manage events manually.", "plia"),
            ("  Sync:  Connect Google or Outlook in the Settings tab.", "plia"),
            ("", "system"),
            ("▶ SMART HOME  (TP-Link Kasa)", "success"),
            ("  Voice: 'Jarvis, turn on the office lights'", "plia"),
            ("  Voice: 'Jarvis, dim the lounge to 40 percent'", "plia"),
            ("  Voice: 'Jarvis, turn off all lights'", "plia"),
            ("  GUI:   Home Automation tab — Refresh to discover devices.", "plia"),
            ("  Setup: Devices must be on the same Wi-Fi network.", "plia"),
            ("", "system"),
            ("▶ ACTIVE AGENTS", "success"),
            ("  Chat : 'Create an agent that monitors my email'", "plia"),
            ("  Chat : 'Run the Python tutor agent'", "plia"),
            ("  Voice: 'Jarvis, refresh active agents'", "plia"),
            ("  Agents tab: Create / Run / Delete custom agents.", "plia"),
            ("  Saved to: %USERPROFILE%\\.plia_ai\\agents\\", "plia"),
            ("  Agents can use OpenAI (key in Settings) or local Ollama.", "plia"),
            ("", "system"),
            ("▶ DESKTOP AGENT  (Windows automation)", "success"),
            ("  Voice: 'Jarvis, open Notepad'", "plia"),
            ("  Voice: 'Jarvis, open Spotify'", "plia"),
            ("  Voice: 'Jarvis, close Discord'", "plia"),
            ("  Supports: launch, close, switch, minimise, maximise apps.", "plia"),
            ("", "system"),
            ("▶ DAILY BRIEFING", "success"),
            ("  Open the Briefing tab for AI-curated news.", "plia"),
            ("  Categories: Technology, Science, Top Stories.", "plia"),
            ("  Fetched via DuckDuckGo — no API key required.", "plia"),
            ("", "system"),
            ("▶ MODEL BROWSER", "success"),
            ("  Browse, download and switch Ollama models from the GUI.", "plia"),
            ("  Set the active model in Settings or config.py.", "plia"),
            ("", "system"),
            ("▶ SETTINGS", "success"),
            ("  Wake word / sensitivity  — change the trigger phrase", "plia"),
            ("  TTS voice               — switch Piper voice model", "plia"),
            ("  Weather location        — set latitude and longitude", "plia"),
            ("  Auto-start voice        — enable or disable on launch", "plia"),
            ("  OpenAI API key          — used by the Agent Builder", "plia"),
            ("  Calendar sync           — connect Google or Outlook", "plia"),
            ("", "system"),
            ("▶ SYSTEM MONITOR", "success"),
            ("  Title bar: live CPU / RAM / GPU VRAM percentages.", "plia"),
            ("  Dashboard panel: detailed bar graphs (left side).", "plia"),
            ("", "system"),
            ("▶ GETTING MORE HELP", "success"),
            ("  Voice       : 'Jarvis, help' or 'Jarvis, what can you do?'", "plia"),
            ("  Dashboard   : type 'help' and press SEND", "plia"),
            ("  README.md   : full documentation in the project folder.", "plia"),
            ("═══════════════════════════════════════════════", "system"),
        ]
        for text, tag in sections:
            self.log.append_message(text, tag)

    def _cmd_settings(self) -> None:
        self.log.append_message("► Navigating to Settings…", "plia")
        self.navigate_to.emit("settingsInterface")

    # ── Input send handler ────────────────────────────────────
    def _on_send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.log.append_message(f"► {text}", "user")
        self.waveform.set_amplitude(15)

        cmd = text.lower()
        if cmd in ("status", "system status"):
            self._cmd_status()
        elif cmd in ("help",):
            self._cmd_help()
        elif cmd.startswith("note") or cmd.startswith("task"):
            self._cmd_notes()
        elif cmd.startswith("remind") or cmd.startswith("alarm"):
            self._cmd_remind()
        elif cmd in ("settings", "setting"):
            self._cmd_settings()
        else:
            self.log.append_message(
                "◄ Command not recognised in dashboard mode. "
                "Switch to the Chat tab to talk to P.L.I.A.",
                "plia",
            )

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

    # ── Cleanup ───────────────────────────────────────────────
    def closeEvent(self, event) -> None:           # noqa: N802
        if hasattr(self, "sys_monitor"):
            try:
                self.sys_monitor.cleanup()
            except Exception:
                pass
        super().closeEvent(event)
