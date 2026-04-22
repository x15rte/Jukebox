from typing import Any, cast

from models import KeyEvent
import playback.player as pmod
from tests.helpers.fakes import FakeBackend, FakeEvent, FakeSignal, RecorderBackend

pmod = cast(Any, pmod)


def test_loop_body_handles_pending_shutdown(monkeypatch):
    backend = FakeBackend()
    p = pmod.Player([], backend, {}, total_duration=0.1)
    p._pending_shutdown = True

    times = iter([0.0, 0.5])
    monkeypatch.setattr(pmod.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(pmod.time, "sleep", lambda _s: None)

    p._loop_body()

    shutdown_calls = [c for c in backend.calls if c[0] == "shutdown"]
    if not (shutdown_calls):
        raise AssertionError("Assertion failed")


def test_loop_body_pause_branch_runs_shutdown_once(monkeypatch):
    backend = FakeBackend()
    p = pmod.Player([], backend, {}, total_duration=10.0)
    p.pause_event.set()
    p._pending_pause = True
    p._active_pitches = {60}
    vis = FakeSignal()
    p.visualizer_updated = cast(Any, vis)

    calls = {"sleep": 0}

    def _sleep(_s):
        calls["sleep"] += 1
        p.stop_event.set()

    monkeypatch.setattr(pmod.time, "sleep", _sleep)

    p._loop_body()

    shutdown_calls = [c for c in backend.calls if c[0] == "shutdown"]
    if not (shutdown_calls):
        raise AssertionError("Assertion failed")
    if not (vis.emitted[-1] == ([],)):
        raise AssertionError("Assertion failed")


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
    monkeypatch.setattr(pmod, "precise_sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(pmod.time, "sleep", lambda _s: None)

    p._loop_body()

    if not (sleeps and sleeps[0] > 0):
        raise AssertionError("Assertion failed")
    if not (backend.calls[0][0] == "execute_batch"):
        raise AssertionError("Assertion failed")
    if not (len(backend.calls[0][1]) == 2):
        raise AssertionError("Assertion failed")


def test_loop_body_emits_progress_periodically(monkeypatch):
    backend = FakeBackend()
    events = [FakeEvent(0.0, 2, "press", pitch=60)]
    p = pmod.Player(cast(list[KeyEvent], events), backend, {}, total_duration=1.0)
    p.start_time = 0.0

    progress = FakeSignal()
    p.progress_updated = cast(Any, progress)

    perf = iter([0.0, 0.05, 0.05, 0.10, 0.10])

    monkeypatch.setattr(pmod.time, "perf_counter", lambda: next(perf))
    monkeypatch.setattr(pmod, "precise_sleep", lambda _s: None)

    orig_execute = p._execute_batch

    def _exec(events):
        orig_execute(events)
        p.stop_event.set()

    p._execute_batch = cast(Any, _exec)

    p._loop_body()

    if not (progress.emitted):
        raise AssertionError("Assertion failed")


def test_countdown_stops_early_when_stop_event_set(monkeypatch):
    p = pmod.Player([], FakeBackend(), {}, 1.0)
    status = FakeSignal()
    p.status_updated = cast(Any, status)

    def _sleep(_s):
        p.stop_event.set()

    monkeypatch.setattr(pmod.time, "sleep", _sleep)
    p._countdown()

    if not (status.emitted[0] == ("Get ready...",)):
        raise AssertionError("Assertion failed")
    if not (any(e == ("3...",) for e in status.emitted)):
        raise AssertionError("Assertion failed")


def test_play_respects_start_offset_event_index(monkeypatch):
    backend = FakeBackend()
    events = [FakeEvent(0.1, 2, "press", pitch=60), FakeEvent(0.9, 2, "press", pitch=62)]
    p = pmod.Player(cast(list[KeyEvent], events), backend, {"countdown": False, "start_offset": 0.5}, 1.0)

    monkeypatch.setattr(pmod.time, "perf_counter", lambda: 10.0)
    monkeypatch.setattr(p, "_run_loop", lambda: None)

    p.play()

    if not (p.event_index == 1):
        raise AssertionError("Assertion failed")


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
    monkeypatch.setattr(pmod, "precise_sleep", lambda _s: None)
    monkeypatch.setattr(pmod.time, "sleep", lambda _s: None)

    p.play()

    if not (backend.calls == [
        ("pedal_on",),
        ("note_on", 60, 95),
        ("note_on", 64, 100),
        ("pedal_off",),
        ("note_off", 60),
        ("note_off", 64),
        ("shutdown",),
    ]):
        raise AssertionError("Assertion failed")


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
    monkeypatch.setattr(pmod, "precise_sleep", lambda _s: None)
    monkeypatch.setattr(pmod.time, "sleep", lambda _s: None)

    p.play()

    if not (backend.calls[:3] == [
        ("note_on", 60, 90),
        ("note_off", 60),
        ("note_on", 67, 110),
    ]):
        raise AssertionError("Assertion failed")
