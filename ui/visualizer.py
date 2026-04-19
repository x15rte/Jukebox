"""Piano keyboard highlight (active pitches) and timeline (note bars, measure lines, playhead)."""

from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal as Signal
from PyQt6.QtGui import (
    QPainter,
    QBrush,
    QColor,
    QPen,
    QPixmap,
    QFont,
    QMouseEvent,
    QResizeEvent,
)
from typing import List, Optional
from models import Note
from core import TempoMap
from logger_core import jukebox_logger
import theme


class PianoWidget(QWidget):
    """Draws a keyboard strip; highlights keys for pitches in active_pitches. A0–C8 (21–108), 52 white keys."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(80)
        self.setMinimumWidth(500)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.active_pitches = set()
        self.min_pitch = 21  # A0
        self.max_pitch = 108  # C8
        self.white_keys_count = 52
        self.black_keys = {1, 3, 6, 8, 10}  # Semitones that are black keys (mod 12)

    def set_pitch_active(self, pitch: int, active: bool):
        if active:
            self.active_pitches.add(pitch)
        else:
            self.active_pitches.discard(pitch)

    def set_active_pitches(self, pitches) -> None:
        """Replace active pitches from an iterable of MIDI note numbers."""
        self.active_pitches = set(pitches)
        self.update()

    def clear(self):
        self.active_pitches.clear()
        self.update()

    def paintEvent(self, a0) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]  # noqa: N802
        """Draw white keys first, then black keys on top."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        key_width = width / self.white_keys_count
        black_key_width = key_width * 0.65
        black_key_height = height * 0.6

        t = theme.get_dark_cyber_theme()

        white_brush = QBrush(t.piano.white_key)
        black_brush = QBrush(t.piano.black_key)
        active_brush = QBrush(t.piano.active_key)

        white_idx = 0
        white_key_rects = {}

        for p in range(self.min_pitch, self.max_pitch + 1):
            if (p % 12) in self.black_keys:
                continue
            x = white_idx * key_width
            rect = QRectF(x, 0, key_width, height)
            white_key_rects[p] = rect

            brush = active_brush if p in self.active_pitches else white_brush
            painter.setBrush(brush)
            painter.setPen(QPen(t.piano.white_key_border, 1))
            painter.drawRect(rect)
            white_idx += 1

        for p in range(self.min_pitch, self.max_pitch + 1):
            if (p % 12) not in self.black_keys:
                continue
            prev_white = p - 1
            if prev_white not in white_key_rects:
                continue

            ref_rect = white_key_rects[prev_white]
            x = ref_rect.right() - (black_key_width / 2)
            rect = QRectF(x, 0, black_key_width, black_key_height)

            brush = active_brush if p in self.active_pitches else black_brush
            painter.setBrush(brush)
            painter.setPen(QPen(t.piano.black_key_highlight, 1))
            painter.drawRect(rect)

        # Label a few reference keys (e.g., C3–C5) along the bottom edge.
        painter.setPen(QPen(QColor(80, 80, 90)))
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        for p, rect in white_key_rects.items():
            # MIDI note names: C n
            if p % 12 == 0 and 36 <= p <= 72:  # C2–C5
                octave = (p // 12) - 1
                painter.drawText(
                    rect.adjusted(0, rect.height() - 16, 0, -2),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                    f"C{octave}",
                )


class TimelineWidget(QWidget):
    """Horizontal timeline: note bars (left=blue-gray, right=gold, unknown=gray), measure lines, playhead. Draggable to seek."""

    seek_requested = Signal(float)
    scrub_position_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.notes = []
        self.total_duration = 1.0
        self.current_time = 0.0
        self.is_dragging = False
        self.pixels_per_second = 50  # Zoom: width = duration * this
        self.tempo_map = None
        self._cached_boundaries = (
            None  # Measure (start, end) times; avoid recompute in paint.
        )

        t = theme.get_dark_cyber_theme()

        self.bg_color = t.visualizer.background
        self.left_hand_color = t.visualizer.left_hand
        self.right_hand_color = t.visualizer.right_hand
        self.unknown_color = t.visualizer.unknown
        self.cursor_color = t.visualizer.cursor
        self.measure_line_color = t.visualizer.measure_line

        # Cached background pixmap (notes + measure lines) to avoid redrawing
        # the entire roll every paint; only rebuilt when size or data changes.
        self._cached_background: QPixmap | None = None

    def set_data(
        self, notes: List[Note], duration: float, tempo_map: TempoMap | None = None
    ):
        """Set notes and duration; cache measure boundaries from tempo_map for paint."""
        self.notes = notes
        self.total_duration = max(duration, 0.1)
        self.tempo_map = tempo_map
        self._cached_boundaries = None

        if self.tempo_map:
            try:
                self._cached_boundaries = self.tempo_map.get_measure_boundaries(
                    self.total_duration
                )
            except Exception as e:
                jukebox_logger.debug(f"Failed to cache tempo measure boundaries: {e}")
                self._cached_boundaries = None

        new_width = int(self.total_duration * self.pixels_per_second)
        new_width = max(new_width, 800)
        self.setFixedWidth(new_width)
        self.current_time = 0.0
        self._cached_background = None
        self.update()

    def set_position(self, time: float):
        if not self.is_dragging:
            self.current_time = time
            self.update()

    def resizeEvent(self, a0: QResizeEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]  # noqa: N802
        # Any size change invalidates the cached pixmap.
        self._cached_background = None
        super().resizeEvent(a0)

    def mousePressEvent(self, a0: QMouseEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]  # noqa: N802
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            self._handle_mouse_input(a0.position().x())

    def mouseMoveEvent(self, a0: QMouseEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]  # noqa: N802
        if self.is_dragging and a0 is not None:
            self._handle_mouse_input(a0.position().x())

    def mouseReleaseEvent(self, a0: QMouseEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]  # noqa: N802
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
            self.seek_requested.emit(self.current_time)

    def _handle_mouse_input(self, x):
        ratio = max(0.0, min(1.0, x / self.width()))
        self.current_time = ratio * self.total_duration
        self.scrub_position_changed.emit(self.current_time)
        self.update()

    def _ensure_background(self):
        """Rebuild the cached background pixmap if needed."""
        if (
            self._cached_background is not None
            and self._cached_background.size() == self.size()
        ):
            return

        if self.width() <= 0 or self.height() <= 0:
            self._cached_background = None
            return

        self._cached_background = QPixmap(self.size())
        self._cached_background.fill(self.bg_color)

        painter = QPainter(self._cached_background)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Measure lines.
        if self._cached_boundaries:
            painter.setPen(QPen(self.measure_line_color, 1))
            for start_t, end_t in self._cached_boundaries:
                x = (start_t / self.total_duration) * w
                painter.drawLine(QPointF(x, 0), QPointF(x, h))

        # Note rectangles.
        if self.notes:
            min_p = 21
            max_p = 108
            range_p = max_p - min_p

            painter.setPen(Qt.PenStyle.NoPen)

            for note in self.notes:
                nx = (note.start_time / self.total_duration) * w
                nw = (note.duration / self.total_duration) * w
                nw = max(2.0, nw)

                ny_ratio = 1.0 - ((note.pitch - min_p) / range_p)
                ny = ny_ratio * (h - 10) + 5
                nh = 8

                if note.hand == "left":
                    painter.setBrush(QBrush(self.left_hand_color))
                elif note.hand == "right":
                    painter.setBrush(QBrush(self.right_hand_color))
                else:
                    painter.setBrush(QBrush(self.unknown_color))

                painter.drawRect(QRectF(nx, ny, nw, nh))

        painter.end()

    def paintEvent(self, a0):  # type: ignore[override]  # noqa: N802
        self._ensure_background()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._cached_background is not None:
            painter.drawPixmap(0, 0, self._cached_background)
        else:
            painter.fillRect(self.rect(), self.bg_color)

        w = self.width()
        h = self.height()

        cx = (self.current_time / self.total_duration) * w
        painter.setPen(QPen(self.cursor_color, 1))
        painter.drawLine(QPointF(cx, 0), QPointF(cx, h))
