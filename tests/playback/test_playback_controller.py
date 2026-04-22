from typing import Any, cast

from playback.playback_controller import PlaybackController
from tests.helpers.fakes import FakeBackend, FakeSignal, FakeThread

PlaybackController = cast(Any, PlaybackController)


class FakePlayer:
    def __init__(self, events, backend, config, total_duration):
        self.events = events
        self.backend = backend
        self.config = config
        self.total_duration = total_duration
        self.playback_finished = FakeSignal()
        self.status_updated = FakeSignal()
        self.progress_updated = FakeSignal()
        self.visualizer_updated = FakeSignal()
        self.stopped = False
        self.paused_toggles = 0
        self.seek_calls = []

    def moveToThread(self, thread):
        self.thread = thread

    def play(self):
        return None

    def stop(self):
        self.stopped = True

    def toggle_pause(self):
        self.paused_toggles += 1

    def seek(self, target):
        self.seek_calls.append(target)


def test_controller_start_and_state_transitions(monkeypatch):
    ctrl = PlaybackController()
    backend = FakeBackend()

    monkeypatch.setattr("playback.playback_controller.create_backend", lambda *a, **k: backend)
    monkeypatch.setattr("playback.playback_controller.QThread", FakeThread)
    monkeypatch.setattr("playback.playback_controller.Player", FakePlayer)

    ctrl.start([], {}, 1.0, "key", False, False)
    assert ctrl.state == "playing"
    assert ctrl.is_running

    ctrl.toggle_pause()
    assert ctrl.state == "paused"
    ctrl.toggle_pause()
    assert ctrl.state == "playing"

    ctrl.seek(0.5)
    player = cast(Any, ctrl.player)
    assert player.seek_calls[-1] == 0.5

    ctrl.stop()
    player = cast(Any, ctrl.player)
    assert player.stopped is True


def test_controller_finishes_and_cleans_up(monkeypatch):
    ctrl = PlaybackController()
    backend = FakeBackend()

    monkeypatch.setattr("playback.playback_controller.create_backend", lambda *a, **k: backend)
    monkeypatch.setattr("playback.playback_controller.QThread", FakeThread)
    monkeypatch.setattr("playback.playback_controller.Player", FakePlayer)

    ctrl.start([], {}, 1.0, "key", False, False)
    player = ctrl.player
    assert player is not None

    ctrl._on_playback_finished_internal()
    assert ctrl.state == "stopped"
    assert ctrl.player is None
