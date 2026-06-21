# pyright: reportAttributeAccessIssue=false

from typing import Any, cast

from models import KeyEvent
import playback.player as pmod
from tests.helpers.fakes import FakeBackend, FakeEvent, FakeSignal, RecorderBackend

pmod = cast(Any, pmod)

def test_loop_body_handles_seek_pending(monkeypatch):
    backend = FakeBackend()
    p = pmod.Player([], backend, {}, total_duration=0.1)
    p._seek_pending = True

    times = iter([0.0, 0.5])
    monkeypatch.setattr(pmod.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(pmod.time, "sleep", lambda _s: None)

    p._loop_body()

    # Seek no longer calls backend.shutdown(); _release_all_notes() releases notes instead.
    shutdown_calls = [c for c in backend.calls if c[0] == "shutdown"]
    assert not shutdown_calls


def test_loop_body_pause_branch_releases_held_notes(monkeypatch):
    backend = FakeBackend()
    p = pmod.Player([], backend, {}, total_duration=10.0)
    p.pause_event.set()
    p._pending_pause = True
    p._active_pitches = {60}
    vis = FakeSignal()
    p.visualizer_updated = cast(Any, vis)

    # Mock stop_event.wait to set stop_event on first call (replaces old time.sleep mock)
    original_wait = p.stop_event.wait
    def _mock_wait(timeout=None):
        p.stop_event.set()
        return True
    p.stop_event.wait = _mock_wait  # type: ignore[assignment]

    p._loop_body()

    note_off_calls = [c for c in backend.calls if c[0] == "note_off"]
    assert note_off_calls == [("note_off", 60)]
    assert vis.emitted[-1] == ([],)


def test_loop_body_waits_with_precise_sleep_and_batches(monkeypatch):
    backend = FakeBackend()
    events = [
        FakeEvent(0.2, 2, "press", pitch=60),
        FakeEvent(0.2004, 4, "release", pitch=60),
        FakeEvent(0.3, 2, "press", pitch=61),
    ]
    p = pmod.Player(cast(list[KeyEvent], events), backend, {}, total_duration=1.0)
    p.start_time = 0.0
    p.total_paused_time = 0.0

    perf = iter([0.0, 0.2005, 0.2005, 2.0])
    sleeps = []

    monkeypatch.setattr(pmod.time, "perf_counter", lambda: next(perf, 3.0))
    monkeypatch.setattr(pmod, "precise_sleep", lambda s, _e=None, _p=None: sleeps.append(s))
    monkeypatch.setattr(pmod.time, "sleep", lambda _s: None)

    p._loop_body()

    assert sleeps and sleeps[0] > 0
    assert backend.calls[0][0] == "execute_batch"
    assert len(backend.calls[0][1]) == 2


def test_loop_body_emits_progress_periodically(monkeypatch):
    backend = FakeBackend()
    events = [FakeEvent(0.0, 2, "press", pitch=60)]
    p = pmod.Player(cast(list[KeyEvent], events), backend, {}, total_duration=1.0)
    p.start_time = 0.0

    progress = FakeSignal()
    p.progress_updated = cast(Any, progress)

    perf = iter([0.1, 0.1, 0.1, 0.1, 0.1])

    monkeypatch.setattr(pmod.time, "perf_counter", lambda: next(perf))
    monkeypatch.setattr(pmod, "precise_sleep", lambda _s, _e=None, _p=None: None)

    orig_execute = p._execute_batch

    def _exec(events):
        orig_execute(events)
        p.stop_event.set()

    p._execute_batch = cast(Any, _exec)

    p._loop_body()

    assert progress.emitted


def test_countdown_stops_early_when_stop_event_set(monkeypatch):
    p = pmod.Player([], FakeBackend(), {}, 1.0)
    status = FakeSignal()
    p.status_updated = cast(Any, status)

    # Mock stop_event.wait to set stop_event on first call (fast replacement for old time.sleep mock)
    def _mock_wait(timeout=None):
        p.stop_event.set()
        return True
    p.stop_event.wait = _mock_wait  # type: ignore[assignment]

    p._countdown()

    assert status.emitted[0] == ("Get ready...",)
    assert any(e == ("3...",) for e in status.emitted)


def test_play_respects_start_offset_event_index(monkeypatch):
    backend = FakeBackend()
    events = [FakeEvent(0.1, 2, "press", pitch=60), FakeEvent(0.9, 2, "press", pitch=62)]
    p = pmod.Player(cast(list[KeyEvent], events), backend, {"countdown": False, "start_offset": 0.5}, 1.0)

    monkeypatch.setattr(pmod.time, "perf_counter", lambda: 10.0)
    monkeypatch.setattr(p, "_run_loop", lambda: None)

    p.play()

    assert p.event_index == 1


def test_player_golden_sequence_chord_with_pedal(monkeypatch):
    backend = RecorderBackend()
    events = [
        FakeEvent(0.0, 1, "pedal", key_char="down"),
        FakeEvent(0.0, 2, "press", pitch=60, velocity=95),
        FakeEvent(0.0, 2, "press", pitch=64, velocity=100),
        FakeEvent(0.5, 0, "pedal", key_char="up"),
        FakeEvent(0.5, 4, "release", pitch=60, velocity=0),
        FakeEvent(0.5, 4, "release", pitch=64, velocity=0),
    ]

    p = pmod.Player(cast(list[KeyEvent], events), backend, {"countdown": False}, total_duration=0.6)

    perf = iter([0.0, 0.0, 0.034, 0.5, 0.068, 0.8])

    monkeypatch.setattr(pmod.sys, "getswitchinterval", lambda: 0.01)
    monkeypatch.setattr(pmod.sys, "setswitchinterval", lambda _v: None)
    monkeypatch.setattr(pmod, "set_timer_resolution", lambda _v: None)
    monkeypatch.setattr(pmod, "restore_timer_resolution", lambda _v: None)
    monkeypatch.setattr(pmod.time, "perf_counter", lambda: next(perf))
    monkeypatch.setattr(pmod, "precise_sleep", lambda _s, _e=None, _p=None: None)
    monkeypatch.setattr(pmod.time, "sleep", lambda _s: None)

    p.play()

    assert [c for c in backend.calls if c[0] != "execute_batch"] == [
        ("pedal_on",),
        ("note_on", 60, 95),
        ("note_on", 64, 100),
        ("pedal_off",),
        ("note_off", 60),
        ("note_off", 64),
        ("shutdown",),
    ]


def test_player_golden_sequence_same_time_release_before_press(monkeypatch):
    backend = RecorderBackend()
    events = [
        FakeEvent(0.0, 2, "press", pitch=60, velocity=90),
        FakeEvent(0.3, 4, "release", pitch=60, velocity=0),
        FakeEvent(0.3, 2, "press", pitch=67, velocity=110),
    ]

    p = pmod.Player(cast(list[KeyEvent], events), backend, {"countdown": False}, total_duration=0.4)

    perf = iter([0.0, 0.0, 0.04, 0.3, 0.08, 0.6])

    monkeypatch.setattr(pmod.sys, "getswitchinterval", lambda: 0.01)
    monkeypatch.setattr(pmod.sys, "setswitchinterval", lambda _v: None)
    monkeypatch.setattr(pmod, "set_timer_resolution", lambda _v: None)
    monkeypatch.setattr(pmod, "restore_timer_resolution", lambda _v: None)
    monkeypatch.setattr(pmod.time, "perf_counter", lambda: next(perf))
    monkeypatch.setattr(pmod, "precise_sleep", lambda _s, _e=None, _p=None: None)
    monkeypatch.setattr(pmod.time, "sleep", lambda _s: None)

    p.play()

    individual = [c for c in backend.calls if c[0] != "execute_batch"]
    assert individual[:3] == [
        ("note_on", 60, 90),
        ("note_off", 60),
        ("note_on", 67, 110),
    ]


def test_countdown_pause_returns_early(monkeypatch):
    """_countdown returns early when pause_event is set (lines 681-682)."""
    p = pmod.Player([], FakeBackend(), {}, 1.0)
    status = FakeSignal()
    p.status_updated = cast(Any, status)
    p.pause_event.set()
    monkeypatch.setattr(pmod.time, "sleep", lambda _s: None)

    p._countdown()

    assert any(e == ("Paused.",) for e in status.emitted)


def test_loop_body_pause_continues_after_wait(monkeypatch):
    """When pause branch stop_event.wait returns False, loop continues (line 785)."""
    backend = FakeBackend()
    p = pmod.Player([], backend, {}, total_duration=10.0)
    p.pause_event.set()
    p._pending_pause = False

    wait_results = iter([False, True])

    def mock_wait(timeout=None):
        try:
            rv = next(wait_results)
            if rv:
                p.stop_event.set()
            return rv
        except StopIteration:
            return True

    p.stop_event.wait = mock_wait  # type: ignore[assignment]

    p._loop_body()


def test_loop_body_past_end_stop_event_returns(monkeypatch):
    """past_end branch: stop_event.wait(0.005) returning True triggers return (line 793)."""
    backend = FakeBackend()
    p = pmod.Player([], backend, {}, total_duration=1.0)

    monkeypatch.setattr(pmod.time, "perf_counter", lambda: 0.0)

    wait_results = iter([True])

    def mock_wait(timeout=None):
        rv = next(wait_results, True)
        if rv:
            p.stop_event.set()
        return rv

    p.stop_event.wait = mock_wait  # type: ignore[assignment]

    p._loop_body()


def test_loop_body_past_end_pause_continues(monkeypatch):
    """past_end branch: pause set during wait triggers continue (line 795)."""
    backend = FakeBackend()
    p = pmod.Player([], backend, {}, total_duration=1.0)
    # pause_event NOT set initially — set inside the wait mock

    monkeypatch.setattr(pmod.time, "perf_counter", lambda: 0.0)

    # Track whether pause was set during the wait
    pause_was_set_in_wait = False

    # First call (past_end wait with timeout=0.005): set pause, return False
    # Second call (pause branch after continue): return False → continue
    # Third call: stop
    waits_for_795 = iter([False, False, True])

    def mock_for_795(timeout=None):
        nonlocal pause_was_set_in_wait
        rv = next(waits_for_795)
        if rv:
            p.stop_event.set()
        if timeout == 0.005 and not rv:
            # Simulate pause being requested during the wait
            p.pause_event.set()
            pause_was_set_in_wait = True
        return rv

    p.stop_event.wait = mock_for_795  # type: ignore[assignment]

    p._loop_body()

    assert pause_was_set_in_wait, "mock should have set pause_event"
    assert p.pause_event.is_set(), "pause_event should be set after the loop"
def test_loop_body_seek_pending_paused_saves_pitches(monkeypatch):
    """Seek while paused saves reconciled pitches for later restore (lines 764-765)."""
    backend = FakeBackend()
    events = [
        FakeEvent(0.1, 2, "press", pitch=60, velocity=100),
        FakeEvent(0.2, 4, "release", pitch=60),
    ]
    p = pmod.Player(cast(list[KeyEvent], events), backend, {}, total_duration=1.0)
    p.pause_event.set()
    p._seek_pending = True
    p.event_index = 1  # so _reconcile sees the press event (pitch 60 still held)

    perf = iter([0.0, 0.0, 0.3])
    monkeypatch.setattr(pmod.time, "perf_counter", lambda: next(perf))
    monkeypatch.setattr(pmod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(pmod, "precise_sleep", lambda _s, _e=None, _p=None: None)

    # Let the loop exit after processing seek_pending
    def mock_wait(timeout=None):
        p.stop_event.set()
        return True

    p.stop_event.wait = mock_wait  # type: ignore[assignment]

    p._loop_body()

    # seek_pending branch with pause set should save reconciled pitches
    assert p._paused_pitches is not None
    assert set(p._paused_pitches) == {60}


def test_loop_body_was_paused_restores_state(monkeypatch):
    """After pause→resume, was_paused block restores notes (lines 800-811)."""
    backend = FakeBackend()
    events = [
        FakeEvent(0.1, 2, "press", pitch=60, velocity=100),
        FakeEvent(0.5, 4, "release", pitch=60),
    ]
    p = pmod.Player(cast(list[KeyEvent], events), backend, {}, total_duration=1.0)
    p._active_pitches = {60}
    p._pitch_velocities = {60: 100}
    vis = FakeSignal()
    p.visualizer_updated = cast(Any, vis)

    monkeypatch.setattr(pmod.time, "perf_counter", lambda: 0.0)
    monkeypatch.setattr(pmod, "precise_sleep", lambda _s, _e=None, _p=None: None)
    monkeypatch.setattr(pmod.time, "sleep", lambda _s: None)

    # Step 1: enter pause branch to set was_paused = True
    p.pause_event.set()
    p._pending_pause = True

    wait_idx = 0

    def mock_wait(timeout=None):
        nonlocal wait_idx
        wait_idx += 1
        if wait_idx == 1 and timeout == 0.05:
            # First call: in pause branch — clear pause_event so next iteration
            # enters was_paused block instead of pause branch again
            p.pause_event.clear()
            return False
        # Subsequent calls: stop
        p.stop_event.set()
        return True

    p.stop_event.wait = mock_wait  # type: ignore[assignment]

    p._loop_body()

    # After was_paused block, _restore_backend_state should have re-pressed pitch 60
    assert ("note_on", (60, 100)) in backend.calls


def test_loop_body_was_paused_discards_past_releases(monkeypatch):
    """was_paused block discards releases that passed during pause (lines 802-809)."""
    backend = FakeBackend()
    events = [
        FakeEvent(0.1, 2, "press", pitch=60, velocity=100),
        FakeEvent(0.5, 4, "release", pitch=60),
        FakeEvent(0.7, 2, "press", pitch=67, velocity=90),
    ]
    p = pmod.Player(cast(list[KeyEvent], events), backend, {}, total_duration=1.0)
    # Both pitches held when pause happens → will be saved to _paused_pitches
    p._active_pitches = {60, 67}
    p._pitch_velocities = {60: 100, 67: 90}
    vis = FakeSignal()
    p.visualizer_updated = cast(Any, vis)

    # perf_counter: iteration 1 (pause) needs 1 call, iteration 2 (was_paused) needs 2 calls.
    # Use 0.0 for pause-iteration (pt=0.0), 0.8 for was_paused-iteration (pt=0.8 past release).
    perf = iter([0.0, 0.8, 0.8, 2.0])
    monkeypatch.setattr(pmod.time, "perf_counter", lambda: next(perf, 2.0))
    monkeypatch.setattr(pmod, "precise_sleep", lambda _s, _e=None, _p=None: None)
    monkeypatch.setattr(pmod.time, "sleep", lambda _s: None)

    # Step 1: start with pause set to trigger was_paused = True
    p.pause_event.set()
    p._pending_pause = True

    wait_idx = 0

    def mock_wait(timeout=None):
        nonlocal wait_idx
        wait_idx += 1
        if wait_idx == 1 and timeout == 0.05:
            p.pause_event.clear()
            return False
        p.stop_event.set()
        return True

    p.stop_event.wait = mock_wait  # type: ignore[assignment]

    p._loop_body()

    # Pitch 60 was released during pause (at 0.5, pt=0.8), so it should have
    # been discarded from _paused_pitches. Pitch 67 (no release) should be restored.
    restore_calls = [c for c in backend.calls if c[0] == "note_on"]
    note_on_pitches = {c[1][0] for c in restore_calls}
    assert 67 in note_on_pitches, "pitch 67 should be restored (no release during pause)"
    assert 60 not in note_on_pitches, "pitch 60 should have been discarded (released during pause)"

def test_loop_body_pause_after_sleep_continues(monkeypatch):
    """After precise_sleep, if pause_event is set, the loop continues (line 819)."""
    backend = FakeBackend()
    events = [
        FakeEvent(0.1, 2, "press", pitch=60),
    ]
    p = pmod.Player(cast(list[KeyEvent], events), backend, {}, total_duration=1.0)
    p.start_time = 0.0
    p.total_paused_time = 0.0

    perf = iter([0.0, 0.0, 0.0])
    sleeps = []

    def _mock_sleep(s, _e=None, _p=None):
        sleeps.append(s)
        p.pause_event.set()  # set pause during sleep

    monkeypatch.setattr(pmod.time, "perf_counter", lambda: next(perf, 2.0))
    monkeypatch.setattr(pmod, "precise_sleep", _mock_sleep)

    # Stop the loop after the continue
    def mock_wait(timeout=None):
        p.stop_event.set()
        return True

    p.stop_event.wait = mock_wait  # type: ignore[assignment]

    p._loop_body()

    # The pause branch will be hit after the continue; verify it ran
    assert sleeps


def test_loop_body_seek_version_changed_after_sleep(monkeypatch):
    """Seek during sleep causes seek_version mismatch → continue (line 826)."""
    backend = FakeBackend()
    events = [
        FakeEvent(0.1, 2, "press", pitch=60),
    ]
    p = pmod.Player(cast(list[KeyEvent], events), backend, {}, total_duration=1.0)
    p.start_time = 0.0
    p.total_paused_time = 0.0

    sleep_count = 0

    def _mock_sleep(s, _e=None, _p=None):
        nonlocal sleep_count
        sleep_count += 1
        p._seek_version += 1  # simulate seek happening during sleep
        if sleep_count >= 3:
            p.stop_event.set()

    monkeypatch.setattr(pmod.time, "perf_counter", lambda: 0.0)
    monkeypatch.setattr(pmod, "precise_sleep", _mock_sleep)

    p._loop_body()

    # The seek version changed during sleep, so the continue at line 826
    # was hit repeatedly. No batch should have been executed.
    execute_calls = [c for c in backend.calls if c[0] == "execute_batch"]
    assert not execute_calls


def test_loop_body_seek_version_changed_during_batch(monkeypatch):
    """_seek_version changed during batch collection causes continue (line 836)."""
    backend = FakeBackend()
    events = [
        FakeEvent(0.1, 2, "press", pitch=60),
    ]
    p = pmod.Player(cast(list[KeyEvent], events), backend, {}, total_duration=1.0)
    p.start_time = 0.0
    p.total_paused_time = 0.0

    monkeypatch.setattr(pmod.time, "perf_counter", lambda: 0.0)
    monkeypatch.setattr(pmod, "precise_sleep", lambda _s, _e=None, _p=None: None)

    # Mock stop_event.wait to eventually exit the loop
    def mock_wait(timeout=None):
        p.stop_event.set()
        return True

    p.stop_event.wait = mock_wait  # type: ignore[assignment]

    # Wrap _state_lock in a BumpLock that increments _seek_version on the
    # second release within the loop (which is the batch section's lock exit).
    class BumpLock:
        def __init__(self, real_lock):
            self._lock = real_lock
            self._release_count = 0
        def acquire(self, blocking=True, timeout=-1):
            return self._lock.acquire(blocking, timeout)
        def release(self):
            self._release_count += 1
            if self._release_count == 2:
                p._seek_version += 1
            self._lock.release()
        def __enter__(self):
            self.acquire()
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            self.release()
            return False

    p._state_lock = BumpLock(p._state_lock)

    p._loop_body()

    # The _seek_version was bumped after batch collection, so line 834
    # detected the mismatch and continued at line 836. No batch executed.
    execute_calls = [c for c in backend.calls if c[0] == "execute_batch"]
    assert not execute_calls


