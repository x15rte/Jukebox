from typing import Any, cast

from playback.playback_controller import PlaybackController
from tests.helpers.fakes import FakeBackend, FakePlaybackPlayer, FakeThread

PlaybackController = cast(Any, PlaybackController)


def test_controller_start_and_state_transitions(monkeypatch):
    ctrl = PlaybackController()
    backend = FakeBackend()

    monkeypatch.setattr("playback.playback_controller.create_backend", lambda *a, **k: backend)
    monkeypatch.setattr("playback.playback_controller.QThread", FakeThread)
    monkeypatch.setattr("playback.playback_controller.Player", FakePlaybackPlayer)

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
    monkeypatch.setattr("playback.playback_controller.Player", FakePlaybackPlayer)

    ctrl.start([], {}, 1.0, "key", False, False)
    player = ctrl.player
    assert player is not None

    ctrl._on_playback_finished_internal()
    assert ctrl.state == "stopped"
    assert ctrl.player is None
