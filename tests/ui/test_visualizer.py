from types import SimpleNamespace
from typing import Any, cast

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPixmap, QResizeEvent

from tests.helpers.builders import make_note
from ui import visualizer
from ui.visualizer import PianoWidget, TimelineWidget

visualizer = cast(Any, visualizer)
PianoWidget = cast(Any, PianoWidget)
TimelineWidget = cast(Any, TimelineWidget)


class FakePainter:
    class RenderHint:
        Antialiasing = 1

    instances = []

    def __init__(self, _target):
        self.calls = []
        FakePainter.instances.append(self)

    def setRenderHint(self, *_a, **_k):
        self.calls.append(("hint",))

    def scale(self, *_a, **_k):
        self.calls.append(("scale",))

    def setBrush(self, *_a, **_k):
        self.calls.append(("brush",))

    def setPen(self, *_a, **_k):
        self.calls.append(("pen",))

    def drawRect(self, *_a, **_k):
        self.calls.append(("rect",))

    def drawText(self, *_a, **_k):
        self.calls.append(("text",))

    def drawLine(self, *_a, **_k):
        self.calls.append(("line",))

    def drawPixmap(self, *_a, **_k):
        self.calls.append(("pixmap",))

    def fillRect(self, *_a, **_k):
        self.calls.append(("fill",))

    def setFont(self, *_a, **_k):
        self.calls.append(("font",))

    def end(self):
        self.calls.append(("end",))


def _flatten_calls():
    out = []
    for inst in FakePainter.instances:
        out.extend(inst.calls)
    return out


def test_piano_active_pitch_mutators(qtbot):
    w = PianoWidget()
    qtbot.addWidget(w)

    w.active_pitches.add(60)
    assert 60 in w.active_pitches

    w.active_pitches.discard(60)
    assert 60 not in w.active_pitches

    w.set_active_pitches([61, 62])
    assert w.active_pitches == {61, 62}

    w.clear()
    assert w.active_pitches == set()


def test_piano_paint_event_draws_rects_and_labels(qtbot, monkeypatch):
    FakePainter.instances = []
    monkeypatch.setattr(visualizer, "QPainter", FakePainter)

    w = PianoWidget()
    qtbot.addWidget(w)
    w.resize(520, 80)
    w.set_active_pitches([24, 25])

    w.paintEvent(None)

    calls = _flatten_calls()
    assert ("rect",) in calls
    assert ("text",) in calls


def test_piano_paint_event_black_key_without_prev_white_branch(qtbot, monkeypatch):
    FakePainter.instances = []
    monkeypatch.setattr(visualizer, "QPainter", FakePainter)

    w = PianoWidget()
    qtbot.addWidget(w)
    w.min_pitch = 22
    w.max_pitch = 22

    w.paintEvent(None)

    calls = _flatten_calls()
    assert ("rect",) not in calls


def test_timeline_set_data_caches_boundaries_and_min_width(qtbot):
    tw = TimelineWidget()
    qtbot.addWidget(tw)

    args = []

    class Tempo:
        def get_measure_boundaries(self, d):
            args.append(d)
            return [(0.0, 1.0)]

    tw.pixels_per_second = 10
    tw.set_data([make_note(1, 60, 0.0, 0.1)], duration=0.05, tempo_map=cast(Any, Tempo()))

    assert args == [0.1]
    assert tw.total_duration == 0.1
    assert tw._cached_boundaries == [(0.0, 1.0)]
    assert tw.width() == 800
    assert tw.current_time == 0.0


def test_timeline_set_data_boundary_exception_logs_debug(qtbot, monkeypatch):
    tw = TimelineWidget()
    qtbot.addWidget(tw)

    logs = []
    monkeypatch.setattr(visualizer.jukebox_logger, "debug", lambda m: logs.append(m))

    class Tempo:
        def get_measure_boundaries(self, _d):
            raise RuntimeError("bad")

    tw.set_data([], duration=1.0, tempo_map=cast(Any, Tempo()))
    assert tw._cached_boundaries is None
    assert logs and "Failed to cache tempo measure boundaries" in logs[0]


def test_timeline_set_position_respects_dragging(qtbot):
    tw = TimelineWidget()
    qtbot.addWidget(tw)
    tw.set_data([], 5.0)  # Set a duration that accommodates test times

    tw.is_dragging = False
    tw.set_position(1.5)
    assert tw.current_time == 1.5

    tw.is_dragging = True
    tw.set_position(2.5)
    assert tw.current_time == 1.5


def test_timeline_mouse_events_emit_scrub_and_seek(qtbot):
    tw = TimelineWidget()
    qtbot.addWidget(tw)
    tw.resize(100, 80)
    tw.total_duration = 10.0

    scrub = []
    seek = []
    tw.scrub_position_changed.connect(lambda t: scrub.append(t))
    tw.seek_requested.connect(lambda t: seek.append(t))

    def ev(btn, x):
        return SimpleNamespace(
            button=lambda: btn,
            position=lambda: SimpleNamespace(x=lambda: x),
        )

    tw.mousePressEvent(cast(Any, ev(Qt.MouseButton.LeftButton, 50)))
    assert tw.is_dragging is True

    tw.mouseMoveEvent(cast(Any, ev(Qt.MouseButton.LeftButton, 80)))
    tw.mouseMoveEvent(cast(Any, None))

    tw.mouseReleaseEvent(cast(Any, ev(Qt.MouseButton.LeftButton, 80)))
    assert tw.is_dragging is False

    tw.mousePressEvent(cast(Any, ev(Qt.MouseButton.RightButton, 10)))
    assert tw.is_dragging is False

    assert scrub
    assert seek and seek[-1] == tw.current_time


def test_timeline_handle_mouse_input_clamps_ratio(qtbot):
    tw = TimelineWidget()
    qtbot.addWidget(tw)
    tw.resize(100, 60)
    tw.total_duration = 10.0

    tw._handle_mouse_input(-50)
    assert tw.current_time == 0.0

    tw._handle_mouse_input(500)
    assert tw.current_time == 10.0


def test_timeline_handle_mouse_input_zero_width(qtbot):
    """_handle_mouse_input early-returns when widget width <= 0."""
    tw = TimelineWidget()
    qtbot.addWidget(tw)
    tw.resize(0, 60)
    tw.total_duration = 10.0
    tw._handle_mouse_input(50)
    assert tw.current_time == 0.0  # unchanged


def test_timeline_ensure_background_draws_lines_notes_and_cache_return(
    qtbot, monkeypatch
):
    FakePainter.instances = []
    monkeypatch.setattr(visualizer, "QPainter", FakePainter)

    tw = TimelineWidget()
    qtbot.addWidget(tw)
    tw.resize(300, 100)
    tw.total_duration = 10.0
    tw._cached_boundaries = [(1.0, 2.0)]
    tw.notes = [
        make_note(1, 40, 0.0, 0.2, hand="left"),
        make_note(2, 60, 1.0, 0.3, hand="right"),
        make_note(3, 70, 2.0, 0.4, hand="unknown"),
    ]

    tw._ensure_background()
    first = tw._cached_background
    tw._ensure_background()

    assert first is not None
    assert tw._cached_background is first
    calls = _flatten_calls()
    assert ("line",) in calls
    assert ("rect",) in calls


def test_timeline_ensure_background_zero_size_clears_cache(qtbot, monkeypatch):
    tw = TimelineWidget()
    qtbot.addWidget(tw)
    tw._cached_background = QPixmap(10, 10)

    monkeypatch.setattr(TimelineWidget, "width", lambda self: 0)
    monkeypatch.setattr(TimelineWidget, "height", lambda self: 0)

    tw._ensure_background()
    assert tw._cached_background is None


def test_timeline_paint_event_with_and_without_cached_background(qtbot, monkeypatch):
    FakePainter.instances = []
    monkeypatch.setattr(visualizer, "QPainter", FakePainter)

    tw = TimelineWidget()
    qtbot.addWidget(tw)
    tw.resize(200, 80)
    tw.total_duration = 5.0
    tw.current_time = 2.5

    tw._cached_background = QPixmap(tw.size())
    tw.paintEvent(None)

    monkeypatch.setattr(tw, "_ensure_background", lambda: setattr(tw, "_cached_background", None))
    tw.paintEvent(None)

    calls = _flatten_calls()
    assert ("pixmap",) in calls
    assert ("fill",) in calls
    assert ("line",) in calls


def test_timeline_resize_event_invalidates_background_cache(qtbot):
    tw = TimelineWidget()
    qtbot.addWidget(tw)
    tw._cached_background = QPixmap(10, 10)

    tw.resizeEvent(QResizeEvent(QSize(220, 80), QSize(200, 80)))
    assert tw._cached_background is None
