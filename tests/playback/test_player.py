from typing import Any, cast

from models import KeyEvent
from playback.player import Player
from tests.helpers.fakes import FakeBackend, FakeEvent

Player = cast(Any, Player)


class Recorder:
    def __init__(self):
        self.values = []

    def emit(self, value):
        self.values.append(value)


def test_execute_batch_updates_visualizer_state():
    backend = FakeBackend()
    p = Player([], backend, {}, 1.0)
    rec = Recorder()
    p.visualizer_updated = cast(Any, rec)
    p._active_pitches = {60}

    p._execute_batch(
        cast(
            list[KeyEvent],
            [
                FakeEvent(0.0, 4, "release", pitch=60),
                FakeEvent(0.0, 2, "press", pitch=64),
            ],
        )
    )

    assert backend.calls[0][0] == "execute_batch"
    assert set(rec.values[-1]) == {64}


def test_seek_updates_event_index_and_progress():
    backend = FakeBackend()
    events = [
        FakeEvent(0.1, 2, "press", pitch=60),
        FakeEvent(0.5, 2, "press", pitch=62),
    ]
    p = Player(cast(list[KeyEvent], events), backend, {}, 1.0)
    rec = Recorder()
    p.progress_updated = cast(Any, rec)

    p.seek(0.5)
    assert p.event_index == 1
    assert rec.values[-1] == 0.5


def test_toggle_pause_sets_and_clears_pause_event(monkeypatch):
    backend = FakeBackend()
    p = Player([], backend, {}, 1.0)
    monkeypatch.setattr("playback.player.time.perf_counter", lambda: 10.0)

    p.toggle_pause()
    assert p.pause_event.is_set()

    p.toggle_pause()
    assert not p.pause_event.is_set()


def test_play_reports_shutdown_error(monkeypatch):
    class BadShutdownBackend(FakeBackend):
        def shutdown(self):
            raise RuntimeError("shutdown boom")

    class FinishedRecorder:
        def __init__(self):
            self.count = 0

        def emit(self):
            self.count += 1

    backend = BadShutdownBackend()
    p = Player([], backend, {}, 1.0)
    statuses = Recorder()
    finished = FinishedRecorder()
    p.status_updated = cast(Any, statuses)
    p.playback_finished = cast(Any, finished)
    monkeypatch.setattr(p, "_run_loop", lambda: None)

    p.play()

    assert any("shutdown boom" in value for value in statuses.values)
    assert finished.count == 1


def test_execute_batch_same_batch_press_release_tracks_state():
    """A pitch pressed AND released in the same batch is added to _active_pitches.

    The backend processes release → press, so the key ends up pressed.
    _active_pitches must reflect that state for correct pause/resume restoration.
    """
    backend = FakeBackend()
    p = Player([], backend, {}, 1.0)
    rec = Recorder()
    p.visualizer_updated = cast(Any, rec)

    # Both press and release of the same pitch in one batch
    p._execute_batch(
        cast(
            list[KeyEvent],
            [
                FakeEvent(0.0, 4, "release", pitch=60),  # release first (higher priority)
                FakeEvent(0.0, 2, "press", pitch=60),    # press second
            ],
        )
    )

    # After the batch, pitch should be in _active_pitches (backend pressed it)
    assert 60 in p._active_pitches
    # Visualizer was updated
    assert rec.values
    assert 60 in set(rec.values[-1])


def test_toggle_pause_returns_early_when_stopped():
    """toggle_pause returns immediately if stop_event is already set (line 633)."""
    backend = FakeBackend()
    p = Player([], backend, {}, 1.0)
    p.stop_event.set()
    p.toggle_pause()
    assert not p.pause_event.is_set()
    assert not p._pending_pause


def test_toggle_pause_confirmed_accumulates_paused_time(monkeypatch):
    """When _pause_confirmed is True, pause duration is added to total_paused_time (line 639)."""
    backend = FakeBackend()
    p = Player([], backend, {}, 1.0)
    p.pause_event.set()
    p._pause_confirmed = True
    p._pause_ts = 5.0
    monkeypatch.setattr("playback.player.time.perf_counter", lambda: 7.0)
    p.toggle_pause()
    assert p.total_paused_time == 2.0  # 7.0 - 5.0
    assert not p._pause_confirmed


def test_toggle_pause_stop_before_pause_lock(monkeypatch):
    """If stop() is called between _pause_ts assignment and _pause_lock,
    toggle_pause returns without setting _pending_pause or pause_event (line 649)."""
    backend = FakeBackend()
    p = Player([], backend, {}, 1.0)

    called = False

    def _perf():
        nonlocal called
        if not called:
            called = True
            p.stop_event.set()
        return 10.0

    monkeypatch.setattr("playback.player.time.perf_counter", _perf)
    p.toggle_pause()
    assert not p._pending_pause
    assert not p.pause_event.is_set()


def test_release_all_notes_releases_active_pitches():
    """_release_all_notes sends note_off for each active pitch (line 718)."""
    backend = FakeBackend()
    p = Player([], backend, {}, 1.0)
    p._active_pitches = {60, 64}
    p._pitch_velocities = {60: 100, 64: 90}
    p._release_all_notes()
    assert ("note_off", 60) in backend.calls
    assert ("note_off", 64) in backend.calls
    assert not p._active_pitches
    assert not p._pitch_velocities


def test_restore_backend_state_from_paused_pitches():
    """_restore_backend_state with _paused_pitches re-presses from paused set (lines 726-731)."""
    backend = FakeBackend()
    p = Player([], backend, {}, 1.0)
    p._paused_pitches = {60, 67}
    p._pitch_velocities = {60: 100, 67: 95}
    rec = Recorder()
    p.visualizer_updated = cast(Any, rec)

    p._restore_backend_state()

    assert ("note_on", (60, 100)) in backend.calls
    assert ("note_on", (67, 95)) in backend.calls
    assert p._active_pitches == {60, 67}
    assert p._paused_pitches is None
    assert set(rec.values[-1]) == {60, 67}


def test_restore_backend_state_from_active_pitches():
    """_restore_backend_state without _paused_pitches re-presses _active_pitches (lines 734-735)."""
    backend = FakeBackend()
    p = Player([], backend, {}, 1.0)
    p._paused_pitches = None
    p._active_pitches = {64}
    p._pitch_velocities = {64: 90}

    p._restore_backend_state()

    assert ("note_on", (64, 90)) in backend.calls


def test_restore_backend_state_restores_pedal():
    """_restore_backend_state calls pedal_on when _paused_pedal is True (lines 739-742)."""
    backend = FakeBackend()
    p = Player([], backend, {}, total_duration=1.0)
    p._paused_pitches = {60}
    p._paused_pedal = True
    p._pitch_velocities[60] = 95

    p._restore_backend_state()

    assert ("pedal_on", None) in backend.calls
    assert p._pedal_down is True
    assert p._paused_pedal is False


def test_restore_backend_state_default_velocity():
    """_restore_backend_state uses velocity 100 when pitch not in _pitch_velocities (lines 727/734)."""
    backend = FakeBackend()
    p = Player([], backend, {}, 1.0)
    p._paused_pitches = None
    p._active_pitches = {72}
    # No entry in _pitch_velocities for pitch 72

    p._restore_backend_state()

    assert ("note_on", (72, 100)) in backend.calls


def test_reconcile_active_pitches_tracks_press_and_release():
    """_reconcile_active_pitches computes held pitches from past events (lines 700-704, 709-711).

    Note: _pitch_velocities keeps entries for all pressed pitches (the velocity
    is needed if the note is later re-pressed after seek/resume), even if the
    pitch has been released from _active_pitches.
    """
    backend = FakeBackend()
    events = [
        FakeEvent(0.1, 2, "press", pitch=60, velocity=100),
        FakeEvent(0.2, 2, "press", pitch=64, velocity=90),
        FakeEvent(0.3, 4, "release", pitch=60),
    ]
    p = Player(cast(list[KeyEvent], events), backend, {}, 1.0)
    p.event_index = 3  # all events "processed"
    rec = Recorder()
    p.visualizer_updated = cast(Any, rec)

    p._reconcile_active_pitches()

    # 60 was pressed then released, 64 is still held
    assert p._active_pitches == {64}
    # _pitch_velocities retains velocity for ALL pressed pitches
    assert p._pitch_velocities == {60: 100, 64: 90}
    assert set(rec.values[-1]) == {64}
