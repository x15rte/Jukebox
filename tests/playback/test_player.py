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
