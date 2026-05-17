"""
plia_logo.py — Animated Plia logo with mouth lip-sync.

Draws ``gui/assets/logo_base.png`` as the base portrait, then overlays one
of the mouth frames (closed / small / medium / wide / o) on top. Each
mouth PNG is a full-frame transparent image pre-aligned to the logo so
no per-frame positioning is needed — drawing them at the same rect as
the logo lines them up correctly.

The widget self-subscribes to ``core.tts.tts.signals``: while the TTS
engine is speaking, a QTimer cycles through the mouth frames at ~8 FPS
to give the impression of talking; when speaking finishes (or the
widget hasn't been told otherwise) it shows ``mouth_closed``.

Drop-in replacement for ``ArcReactorWidget`` — same constructor
signature (``size=190``) and fixed-size layout behaviour.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, QRect, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


# Order of frames cycled through while speaking. Repeating "medium" between
# the wider shapes gives a smoother, less jittery talking motion.
_SPEAKING_CYCLE: List[str] = [
    "mouth_small",
    "mouth_medium",
    "mouth_wide",
    "mouth_medium",
    "mouth_o",
    "mouth_medium",
]


class PliaLogoWidget(QWidget):
    """Logo with animated mouth + expanding sonar ring driven by TTS state."""

    FRAME_INTERVAL_MS = 120     # ~8 FPS mouth cycle
    PULSE_INTERVAL_MS = 33      # ~30 FPS ring redraws
    RING_PERIOD_SEC = 1.4       # how long one ring takes to fully expand
    RING_COUNT = 2              # how many staggered rings on-screen at once
    RING_COLOR = QColor(51, 181, 229)  # cyan, matches the app accent

    # Logo occupies this fraction of the widget so the rings have somewhere
    # to expand into. Increasing the value shrinks the breathing room.
    LOGO_INSET_FRAC = 0.84

    def __init__(self, parent: Optional[QWidget] = None, size: int = 190) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._size = size
        logo_size = int(size * self.LOGO_INSET_FRAC)
        self._logo_rect = QRect(
            (size - logo_size) // 2, (size - logo_size) // 2,
            logo_size, logo_size,
        )
        self._logo: Optional[QPixmap] = self._load("logo_base", logo_size)
        self._mouths = {
            name: self._load(name, logo_size)
            for name in ("mouth_closed", "mouth_small", "mouth_medium",
                         "mouth_wide", "mouth_o")
        }

        self._speaking = False
        self._frame_index = 0
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(self.FRAME_INTERVAL_MS)
        self._anim_timer.timeout.connect(self._advance_frame)

        # Drives the expanding ring redraws while speaking.
        self._pulse_start: Optional[float] = None
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(self.PULSE_INTERVAL_MS)
        self._pulse_timer.timeout.connect(self.update)

        # Subscribe to the global TTS signals. Done in the constructor so
        # any caller just dropping this widget in gets lip-sync for free.
        try:
            from core.tts import tts
            tts.signals.speaking_started.connect(self._on_speaking_started)
            tts.signals.speaking_finished.connect(self._on_speaking_finished)
        except Exception as exc:
            # TTS may not be available in unit tests / headless mode.
            print(f"[PliaLogoWidget] could not subscribe to tts signals: {exc}")

    # ── public API ────────────────────────────────────────────────────────
    def set_speaking(self, speaking: bool) -> None:
        """Manual hook for callers that want to drive the mouth without
        the TTS engine (e.g. previews, audio playback from other sources)."""
        if speaking:
            self._on_speaking_started()
        else:
            self._on_speaking_finished()

    # ── speaking-state handlers ───────────────────────────────────────────
    def _on_speaking_started(self) -> None:
        self._speaking = True
        self._frame_index = 0
        self._pulse_start = time.monotonic()
        if not self._anim_timer.isActive():
            self._anim_timer.start()
        if not self._pulse_timer.isActive():
            self._pulse_timer.start()
        self.update()

    def _on_speaking_finished(self) -> None:
        self._speaking = False
        self._anim_timer.stop()
        self._pulse_timer.stop()
        self._pulse_start = None
        self.update()

    def _advance_frame(self) -> None:
        self._frame_index = (self._frame_index + 1) % len(_SPEAKING_CYCLE)
        self.update()

    # ── painting ──────────────────────────────────────────────────────────
    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Rings render behind the logo so they look like they're emanating
        # from it, not painted on top.
        if self._speaking and self._pulse_start is not None:
            self._draw_pulse_rings(p)

        if self._logo is not None:
            p.drawPixmap(self._logo_rect, self._logo)
        mouth = self._current_mouth()
        if mouth is not None:
            p.drawPixmap(self._logo_rect, mouth)
        p.end()

    def _draw_pulse_rings(self, p: QPainter) -> None:
        """Draw N staggered concentric outlines expanding from the logo
        edge outward to the widget edge, fading as they grow."""
        cx = self._size / 2.0
        cy = self._size / 2.0
        # Start radius: roughly the logo's visible edge.
        start_r = self._logo_rect.width() / 2.0 * 0.95
        # End radius: just inside the widget bounds so the ring isn't clipped.
        end_r = self._size / 2.0 - 1.0
        if end_r <= start_r:
            return

        elapsed = time.monotonic() - (self._pulse_start or time.monotonic())
        for i in range(self.RING_COUNT):
            offset = i / float(self.RING_COUNT)
            phase = ((elapsed / self.RING_PERIOD_SEC) + offset) % 1.0
            radius = start_r + (end_r - start_r) * phase
            # Fade out as the ring expands; also fade in slightly at birth
            # so it doesn't pop into existence sharply.
            fade_in = min(1.0, phase * 6.0)
            alpha = int(220 * (1.0 - phase) * fade_in)
            if alpha <= 0:
                continue
            color = QColor(self.RING_COLOR)
            color.setAlpha(alpha)
            pen = QPen(color)
            pen.setWidthF(2.0)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - radius, cy - radius,
                                 radius * 2, radius * 2))

    def _current_mouth(self) -> Optional[QPixmap]:
        if not self._speaking:
            return self._mouths.get("mouth_closed")
        name = _SPEAKING_CYCLE[self._frame_index]
        return self._mouths.get(name)

    # ── helpers ───────────────────────────────────────────────────────────
    @staticmethod
    def _load(stem: str, size: int) -> Optional[QPixmap]:
        path = _ASSETS_DIR / f"{stem}.png"
        if not path.exists():
            print(f"[PliaLogoWidget] asset missing: {path}")
            return None
        pix = QPixmap(str(path))
        if pix.isNull():
            print(f"[PliaLogoWidget] could not load asset: {path}")
            return None
        return pix.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
