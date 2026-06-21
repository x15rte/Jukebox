from typing import Any, cast

from playback.playback_controller import PlaybackController
from output import OutputBackendUnavailableError
from tests.helpers.fakes import FakeBackend, FakePlaybackPlayer, FakeThread

PlaybackController = cast(Any, PlaybackController)


def test_controller_start_and_state_transitions(monkeypatch):
    ctrl = PlaybackController()
    backend = FakeBackend()

    monkeypatch.setattr("playback.playback_controller.create_backend", lambda *a, **k: backend)
    monkeypatch.setattr("playback.playback_controller.QThread", FakeThread)
    monkeypatch.setattr("playback.playback_controller.Player", FakePlaybackPlayer)

    assert ctrl.start([], {}, 1.0, "key", False) is True
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
    thread = FakeThread()
    monkeypatch.setattr("playback.playback_controller.QThread", lambda: thread)
    monkeypatch.setattr("playback.playback_controller.Player", FakePlaybackPlayer)
    monkeypatch.setattr("playback.playback_controller.QTimer.singleShot", lambda _ms, cb: cb())

    assert ctrl.start([], {}, 1.0, "key", False) is True
    player = ctrl.player
    assert player is not None

    monkeypatch.setattr(ctrl, "sender", lambda: player)
    # FakeThread.quit() doesn't set _running=False (matching real QThread),
    # so simulate the thread finishing via wait() before triggering cleanup.
    thread.wait(0)
    ctrl._on_playback_finished_internal()
    assert ctrl.state == "stopped"
    assert ctrl.player is None

def test_controller_start_backend_unavailable_returns_false(monkeypatch):
    ctrl = PlaybackController()
    logs = []

    def unavailable(*_args, **_kwargs):
        raise OutputBackendUnavailableError("pydirectinput missing")

    monkeypatch.setattr("playback.playback_controller.create_backend", unavailable)
    monkeypatch.setattr("playback.playback_controller.QThread", FakeThread)
    monkeypatch.setattr("playback.playback_controller.Player", FakePlaybackPlayer)

    assert (
        ctrl.start([], {}, 1.0, "key", False, log_message=logs.append)
        is False
    )
    assert ctrl.state == "stopped"
    assert ctrl.player is None
    assert ctrl._thread is None
    assert any("Playback could not start" in m for m in logs)
