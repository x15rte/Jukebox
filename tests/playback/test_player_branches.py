from typing import Any, cast

from models import KeyEvent
import playback.player as pmod
from tests.helpers.builders import make_section
from tests.helpers.fakes import FakeBackend, FakeEvent, FakeSignal

pmod = cast(Any, pmod)


def test_stop_sets_stop_and_clears_pause():
    p = pmod.Player([], FakeBackend(), {}, 1.0)
    p.pause_event.set()
    p.stop()
    assert p.stop_event.is_set()
    assert not p.pause_event.is_set()


def test_seek_while_paused_updates_start_and_pause_ts(monkeypatch):
    p = pmod.Player([FakeEvent(0.1, 2, "press", pitch=60)], FakeBackend(), {}, 1.0)
    prog = FakeSignal()
    p.progress_updated = cast(Any, prog)
    p.pause_event.set()
    monkeypatch.setattr(pmod.time, "perf_counter", lambda: 10.0)

    p.seek(0.1)

    assert p.start_time == 9.9
    assert p._pause_ts == 0.0
    assert prog.emitted[-1] == (0.1,)


def test_countdown_emits_status_and_sleeps(monkeypatch):
    p = pmod.Player([], FakeBackend(), {}, 1.0)
    status = FakeSignal()
    p.status_updated = cast(Any, status)
    waits = []
    orig_wait = p.stop_event.wait
    def fake_wait(timeout=None):
        waits.append(timeout)
        return False  # never set
    p.stop_event.wait = fake_wait

    p._countdown()

    assert status.emitted[0] == ("Get ready...",)
    assert status.emitted[1:] == [("3...",), ("2...",), ("1...",)]
    assert waits == [1, 1, 1]


def test_run_loop_restores_timer_and_switch_interval(monkeypatch):
    p = pmod.Player([], FakeBackend(), {}, 1.0)
    calls = []
    monkeypatch.setattr(pmod.sys, "getswitchinterval", lambda: 0.01)
    monkeypatch.setattr(pmod.sys, "setswitchinterval", lambda v: calls.append(("switch", v)))
    monkeypatch.setattr(pmod, "set_timer_resolution", lambda v: calls.append(("set_timer", v)))
    monkeypatch.setattr(pmod, "restore_timer_resolution", lambda v: calls.append(("restore_timer", v)))
    monkeypatch.setattr(p, "_loop_body", lambda: calls.append(("loop", None)))

    p._run_loop()

    assert calls[0] == ("switch", 0.0005)
    assert ("set_timer", 1) in calls
    assert ("restore_timer", 1) in calls
    assert calls[-1] == ("switch", 0.01)


def test_loop_body_exits_after_total_duration(monkeypatch):
    p = pmod.Player([], FakeBackend(), {}, total_duration=0.1)
    status = FakeSignal()
    p.status_updated = cast(Any, status)

    times = iter([0.0, 0.3])
    monkeypatch.setattr(pmod.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(pmod.time, "sleep", lambda _s: None)

    p._loop_body()

    assert status.emitted[-1] == ("Playback finished.",)


def test_play_calls_shutdown_and_finished_even_on_exception(monkeypatch):
    backend = FakeBackend()
    p = pmod.Player([], backend, {"countdown": False}, 1.0)
    finished = FakeSignal()
    status = FakeSignal()
    p.playback_finished = cast(Any, finished)
    p.status_updated = cast(Any, status)
    monkeypatch.setattr(p, "_run_loop", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    p.play()

    assert backend.calls[-1][0] == "shutdown"
    assert finished.emitted[-1] == ()
    assert status.emitted[-1][0].startswith("Error: boom")


def test_event_compiler_clears_played_set_when_entering_next_section(monkeypatch):
    notes = [
        pmod.Note(1, 60, 90, 0.0, 0.2, hand="right"),
        pmod.Note(2, 60, 90, 1.0, 0.2, hand="right"),
    ]
    sections = [
        make_section(0.0, 0.5, [notes[0]]),
        make_section(0.5, 1.5, [notes[1]]),
    ]

    monkeypatch.setattr(pmod.random, "random", lambda: 0.0)
    monkeypatch.setattr(pmod.EventCompiler, "_mistake_pitch", lambda _p: 61)
    monkeypatch.setattr(pmod.PedalGenerator, "generate_events", lambda *_a, **_k: [])

    events = pmod.EventCompiler.compile(
        notes,
        sections,
        {"enable_mistakes": True, "mistake_chance": 100},
    )

    press_pitches = [e.pitch for e in events if e.action == "press"]
    assert press_pitches == [61, 61]


def test_event_compiler_pushes_generated_pedal_events(monkeypatch):
    notes = [pmod.Note(1, 60, 90, 0.0, 0.2, hand="right")]

    pedal_event = pmod.KeyEvent(0.1, 0, "pedal", "down")
    monkeypatch.setattr(pmod.PedalGenerator, "generate_events", lambda *_a, **_k: [pedal_event])

    events = pmod.EventCompiler.compile(notes, [], {})

    assert any(e.action == "pedal" and e.key_char == "down" for e in events)


def test_mistake_pitch_black_key_returns_none_when_all_candidates_out_of_range(monkeypatch):
    monkeypatch.setattr(pmod.KeyMapper, "is_black_key", lambda _p: True)
    monkeypatch.setattr(pmod.random, "shuffle", lambda _vals: None)

    out = pmod.EventCompiler._mistake_pitch(-100)

    assert out is None


def test_play_stops_after_countdown_when_stop_event_set(monkeypatch):
    backend = FakeBackend()
    p = pmod.Player([], backend, {"countdown": True}, 1.0)
    p.stop_event.set()
    monkeypatch.setattr(p, "_run_loop", lambda: (_ for _ in ()).throw(RuntimeError("should not run")))

    p.play()

    assert backend.calls[-1][0] == "shutdown"


def test_execute_batch_returns_immediately_when_stopped():
    backend = FakeBackend()
    p = pmod.Player([], backend, {}, 1.0)
    p.stop_event.set()

    p._execute_batch([FakeEvent(0.0, 2, "press", pitch=60)])

    assert not backend.calls


def test_execute_batch_ignores_events_without_pitch_values():
    backend = FakeBackend()
    p = pmod.Player([], backend, {}, 1.0)
    vis = FakeSignal()
    p.visualizer_updated = cast(Any, vis)
    p._active_pitches = {60}

    p._execute_batch(
        [
            FakeEvent(0.0, 4, "release", pitch=None),
            FakeEvent(0.0, 2, "press", pitch=None),
        ]
    )

    assert backend.calls and backend.calls[-1][0] == "execute_batch"
    assert not any(c[0] in ("note_on", "note_off") for c in backend.calls), \
        "Pitch-less events should not generate note_on/note_off backend calls"
    assert p._active_pitches == {60}
    assert vis.emitted == []
