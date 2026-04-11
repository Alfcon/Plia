"""
Plia Voice Indicator — shows the Plia logo with an animated speaking mouth
when the voice assistant is active.

States:
  - Hidden          : voice assistant idle
  - Listening       : wake word detected, pulsing glow ring around logo
  - Speaking        : AI is responding, robot mouth animates open/close
"""

import os
import math
from PySide6.QtWidgets import QWidget, QGraphicsOpacityEffect
from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    QPoint, QRect, QSize, Property
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPixmap,
    QRadialGradient, QPainterPath, QFont
)

# Path to the logo image (icon only, no text)
_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")
LOGO_PATH   = os.path.join(_ASSETS_DIR, "logo_128.png")

# Robot mouth position within a 128x128 logo image
# The robot face is roughly centred at (64, 52) in a 128px image
# Mouth centre is approximately at 60% down the face
_MOUTH_CX_RATIO = 0.500   # horizontal centre of mouth (fraction of widget width)
_MOUTH_CY_RATIO = 0.490   # vertical centre of mouth (fraction of widget height)
_MOUTH_W_RATIO  = 0.130   # mouth width as fraction of widget width
_MOUTH_H_BASE   = 0.018   # mouth height (closed) as fraction of widget height
_MOUTH_H_OPEN   = 0.065   # mouth height (fully open) as fraction of widget height


class VoiceIndicator(QWidget):
    """
    Plia logo indicator that animates the robot's mouth when speaking.
    Replaces the old plain-circle indicator.
    """

    # --- States ---
    STATE_HIDDEN    = 0
    STATE_LISTENING = 1
    STATE_SPEAKING  = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.Tool |
            Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self._state         = self.STATE_HIDDEN
        self._pulse         = 0.0     # 0..1 glow ring pulse
        self._mouth_open    = 0.0     # 0..1 mouth openness
        self._mouth_dir     = 1       # +1 opening, -1 closing
        self._logo_pixmap   = None

        self._load_logo()
        self._setup_animations()
        self.setFixedSize(160, 185)
        self.hide()

    # ── Logo ─────────────────────────────────────────────────────────────────

    def _load_logo(self):
        """Load the Plia logo pixmap."""
        if os.path.exists(LOGO_PATH):
            self._logo_pixmap = QPixmap(LOGO_PATH).scaled(
                128, 128,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
        else:
            self._logo_pixmap = None

    # ── Animations ───────────────────────────────────────────────────────────

    def _setup_animations(self):
        """Set up opacity fade, pulse glow, and mouth animation."""
        # Opacity for fade in/out
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(0.0)

        self._fade_in = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_in.setDuration(300)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutCubic)

        self._fade_out = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_out.setDuration(300)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.InCubic)
        self._fade_out.finished.connect(self._on_fade_out_done)

        # Pulse glow ring (listening state)
        self._pulse_anim = QPropertyAnimation(self, b"pulseValue")
        self._pulse_anim.setDuration(1400)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.setEasingCurve(QEasingCurve.InOutSine)

        # Mouth animation timer (speaking state)
        self._mouth_timer = QTimer(self)
        self._mouth_timer.setInterval(60)   # ~16fps mouth movement
        self._mouth_timer.timeout.connect(self._step_mouth)

        # Text label timer
        self._label_text = "Listening..."

    # ── Qt Property for pulse animation ──────────────────────────────────────

    def _get_pulse(self):
        return self._pulse

    def _set_pulse(self, v):
        self._pulse = v
        self.update()

    pulseValue = Property(float, _get_pulse, _set_pulse)

    # ── Mouth animation logic ─────────────────────────────────────────────────

    def _step_mouth(self):
        """Advance the mouth open/close cycle."""
        speed = 0.12
        self._mouth_open += speed * self._mouth_dir
        if self._mouth_open >= 1.0:
            self._mouth_open = 1.0
            self._mouth_dir = -1
        elif self._mouth_open <= 0.0:
            self._mouth_open = 0.0
            self._mouth_dir = 1
        self.update()

    # ── Public API ────────────────────────────────────────────────────────────

    def show_listening(self):
        """Show pulsing glow — wake word detected, waiting for command."""
        if self._state == self.STATE_LISTENING:
            return
        self._state      = self.STATE_LISTENING
        self._label_text = "Listening..."
        self._mouth_timer.stop()
        self._pulse_anim.start()
        self._position_window()
        self.show()
        self._fade_in.start()

    def show_speaking(self):
        """Switch to speaking animation — AI is responding."""
        if self._state == self.STATE_HIDDEN:
            self.show()
            self._fade_in.start()
        self._state      = self.STATE_SPEAKING
        self._label_text = "Speaking..."
        self._pulse_anim.stop()
        self._mouth_open = 0.0
        self._mouth_dir  = 1
        self._mouth_timer.start()
        self._position_window()
        self.update()

    def hide_listening(self, delay_ms: int = 500):
        """Hide with optional delay."""
        if self._state == self.STATE_HIDDEN:
            return
        if delay_ms > 0:
            QTimer.singleShot(delay_ms, self._do_hide)
        else:
            self._do_hide()

    def _do_hide(self):
        if self._state == self.STATE_HIDDEN:
            return
        self._state = self.STATE_HIDDEN
        self._pulse_anim.stop()
        self._mouth_timer.stop()
        self._fade_out.start()

    def _on_fade_out_done(self):
        self.hide()
        self._pulse     = 0.0
        self._mouth_open = 0.0

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        if self._state == self.STATE_HIDDEN:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        w = self.width()
        h = self.height()
        logo_size = 128
        logo_x = (w - logo_size) // 2
        logo_y = 10

        # 1. Pulsing glow ring (listening state)
        if self._state == self.STATE_LISTENING:
            self._draw_glow(painter, logo_x, logo_y, logo_size)

        # 2. Logo
        if self._logo_pixmap:
            painter.drawPixmap(logo_x, logo_y, self._logo_pixmap)
        else:
            # Fallback circle if logo missing
            painter.setBrush(QBrush(QColor(26, 53, 96)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(logo_x, logo_y, logo_size, logo_size)

        # 3. Animated mouth overlay
        self._draw_mouth(painter, logo_x, logo_y, logo_size)

        # 4. Status label below logo
        self._draw_label(painter, w, logo_y + logo_size + 6, h)

    def _draw_glow(self, painter, lx, ly, ls):
        """Draw animated pulsing cyan glow ring around the logo."""
        cx = lx + ls // 2
        cy = ly + ls // 2
        base_r = ls // 2 + 4
        pulse_r = base_r + int(self._pulse * 22)
        alpha   = int(200 * (1.0 - self._pulse))

        # Outer pulse ring
        color = QColor(51, 181, 229, alpha)
        painter.setPen(QPen(color, 3))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPoint(cx, cy), pulse_r, pulse_r)

        # Inner steady ring
        inner_color = QColor(51, 181, 229, 160)
        painter.setPen(QPen(inner_color, 2))
        painter.drawEllipse(QPoint(cx, cy), base_r, base_r)

    def _draw_mouth(self, painter, lx, ly, ls):
        """Draw an animated mouth over the robot face."""
        # Mouth centre in widget coordinates
        cx = lx + int(ls * _MOUTH_CX_RATIO)
        cy = ly + int(ls * _MOUTH_CY_RATIO)
        mw = int(ls * _MOUTH_W_RATIO)   # half-width of mouth

        # Interpolate height between closed and open
        mh_closed = int(ls * _MOUTH_H_BASE)
        mh_open   = int(ls * _MOUTH_H_OPEN)
        mh = mh_closed + int((mh_open - mh_closed) * self._mouth_open)
        mh = max(mh, 2)

        # Draw a dark background patch to hide the existing printed mouth
        patch_w = mw * 2 + 6
        patch_h = mh_open + 8
        patch_color = QColor(20, 50, 90, 230)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(patch_color))
        painter.drawRoundedRect(
            cx - patch_w // 2,
            cy - patch_h // 2,
            patch_w, patch_h,
            4, 4
        )

        if self._state == self.STATE_SPEAKING and self._mouth_open > 0.02:
            # Draw open mouth — dark ellipse with teeth/glow effect
            # Outer lip
            lip_color = QColor(0, 200, 255, 240)
            painter.setPen(QPen(lip_color, 2))
            painter.setBrush(QBrush(QColor(10, 20, 40, 255)))
            painter.drawEllipse(cx - mw, cy - mh, mw * 2, mh * 2)

            # Inner glow (sound waves suggestion)
            if self._mouth_open > 0.3:
                glow = QColor(0, 220, 255, int(180 * self._mouth_open))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(glow))
                inner_w = int(mw * 0.6 * self._mouth_open)
                inner_h = int(mh * 0.5 * self._mouth_open)
                if inner_w > 1 and inner_h > 1:
                    painter.drawEllipse(
                        cx - inner_w, cy - inner_h,
                        inner_w * 2, inner_h * 2
                    )
        else:
            # Draw closed smile
            smile_color = QColor(0, 200, 255, 220)
            painter.setPen(QPen(smile_color, 2, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            path = QPainterPath()
            path.moveTo(cx - mw, cy - 1)
            path.quadTo(cx, cy + mh_closed + 3, cx + mw, cy - 1)
            painter.drawPath(path)

    def _draw_label(self, painter, w, y, h):
        """Draw the status text below the logo."""
        painter.setPen(QColor(51, 181, 229, 230))
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
        painter.drawText(
            QRect(0, y, w, h - y),
            Qt.AlignHCenter | Qt.AlignTop,
            self._label_text
        )

    # ── Position ──────────────────────────────────────────────────────────────

    def _position_window(self):
        if not self.parent():
            return
        pr = self.parent().rect()
        x  = (pr.width()  - self.width())  // 2
        y  = (pr.height() - self.height()) // 2 - 60
        self.move(x, y)

    def showEvent(self, event):
        super().showEvent(event)
        self._position_window()


class EmbeddedVoiceWidget(QWidget):
    """
    Permanent dashboard logo widget with animated speaking mouth.
    Sits inline in the layout (not a floating window).

    States:
      IDLE      — logo shown with closed smile, no animation
      LISTENING — pulsing cyan glow ring
      SPEAKING  — animated open/close mouth
    """

    STATE_IDLE      = 0
    STATE_LISTENING = 1
    STATE_SPEAKING  = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state      = self.STATE_IDLE
        self._pulse      = 0.0
        self._mouth_open = 0.0
        self._mouth_dir  = 1
        self._logo_pixmap = None
        self._label_text  = ""

        self.setFixedSize(140, 160)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._load_logo()
        self._setup_animations()

    # ── Logo ─────────────────────────────────────────────────────────────────

    def _load_logo(self):
        if os.path.exists(LOGO_PATH):
            self._logo_pixmap = QPixmap(LOGO_PATH).scaled(
                110, 110,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )

    # ── Animations ───────────────────────────────────────────────────────────

    def _setup_animations(self):
        self._pulse_anim = QPropertyAnimation(self, b"pulseValue")
        self._pulse_anim.setDuration(1400)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.setEasingCurve(QEasingCurve.InOutSine)

        self._mouth_timer = QTimer(self)
        self._mouth_timer.setInterval(60)
        self._mouth_timer.timeout.connect(self._step_mouth)

    def _get_pulse(self):
        return self._pulse

    def _set_pulse(self, v):
        self._pulse = v
        self.update()

    pulseValue = Property(float, _get_pulse, _set_pulse)

    def _step_mouth(self):
        speed = 0.12
        self._mouth_open += speed * self._mouth_dir
        if self._mouth_open >= 1.0:
            self._mouth_open = 1.0
            self._mouth_dir  = -1
        elif self._mouth_open <= 0.0:
            self._mouth_open = 0.0
            self._mouth_dir  = 1
        self.update()

    # ── Public API ────────────────────────────────────────────────────────────

    def show_listening(self):
        self._state      = self.STATE_LISTENING
        self._label_text = "Listening..."
        self._mouth_timer.stop()
        self._pulse_anim.start()
        self.update()

    def show_speaking(self):
        self._state      = self.STATE_SPEAKING
        self._label_text = "Speaking..."
        self._pulse_anim.stop()
        self._mouth_open = 0.0
        self._mouth_dir  = 1
        self._mouth_timer.start()
        self.update()

    def show_idle(self):
        self._state      = self.STATE_IDLE
        self._label_text = ""
        self._pulse_anim.stop()
        self._mouth_timer.stop()
        self._pulse      = 0.0
        self._mouth_open = 0.0
        self.update()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        w = self.width()
        logo_size = 110
        logo_x = (w - logo_size) // 2
        logo_y = 10

        # 1. Glow ring (listening)
        if self._state == self.STATE_LISTENING:
            self._draw_glow(painter, logo_x, logo_y, logo_size)

        # 2. Logo
        if self._logo_pixmap:
            painter.drawPixmap(logo_x, logo_y, self._logo_pixmap)
        else:
            painter.setBrush(QBrush(QColor(26, 53, 96)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(logo_x, logo_y, logo_size, logo_size)

        # 3. Mouth overlay (all states — idle shows closed smile)
        self._draw_mouth(painter, logo_x, logo_y, logo_size)

        # 4. Status label
        if self._label_text:
            painter.setPen(QColor(51, 181, 229, 230))
            painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
            painter.drawText(
                QRect(0, logo_y + logo_size + 4, w, 20),
                Qt.AlignHCenter | Qt.AlignVCenter,
                self._label_text
            )

    def _draw_glow(self, painter, lx, ly, ls):
        cx = lx + ls // 2
        cy = ly + ls // 2
        base_r = ls // 2 + 4
        pulse_r = base_r + int(self._pulse * 20)
        alpha   = int(200 * (1.0 - self._pulse))

        painter.setPen(QPen(QColor(51, 181, 229, alpha), 3))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPoint(cx, cy), pulse_r, pulse_r)

        painter.setPen(QPen(QColor(51, 181, 229, 160), 2))
        painter.drawEllipse(QPoint(cx, cy), base_r, base_r)

    def _draw_mouth(self, painter, lx, ly, ls):
        cx = lx + int(ls * _MOUTH_CX_RATIO)
        cy = ly + int(ls * _MOUTH_CY_RATIO)
        mw = int(ls * _MOUTH_W_RATIO)

        mh_closed = int(ls * _MOUTH_H_BASE)
        mh_open   = int(ls * _MOUTH_H_OPEN)
        mh = mh_closed + int((mh_open - mh_closed) * self._mouth_open)
        mh = max(mh, 2)

        # Dark patch to cover printed mouth on PNG
        patch_w = mw * 2 + 6
        patch_h = mh_open + 8
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(20, 50, 90, 230)))
        painter.drawRoundedRect(
            cx - patch_w // 2, cy - patch_h // 2,
            patch_w, patch_h, 4, 4
        )

        if self._state == self.STATE_SPEAKING and self._mouth_open > 0.02:
            painter.setPen(QPen(QColor(0, 200, 255, 240), 2))
            painter.setBrush(QBrush(QColor(10, 20, 40, 255)))
            painter.drawEllipse(cx - mw, cy - mh, mw * 2, mh * 2)
            if self._mouth_open > 0.3:
                glow = QColor(0, 220, 255, int(180 * self._mouth_open))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(glow))
                iw = int(mw * 0.6 * self._mouth_open)
                ih = int(mh * 0.5 * self._mouth_open)
                if iw > 1 and ih > 1:
                    painter.drawEllipse(cx - iw, cy - ih, iw * 2, ih * 2)
        else:
            # Closed smile (idle or listening)
            painter.setPen(QPen(QColor(0, 200, 255, 220), 2,
                                Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            path = QPainterPath()
            path.moveTo(cx - mw, cy - 1)
            path.quadTo(cx, cy + mh_closed + 3, cx + mw, cy - 1)
            painter.drawPath(path)
