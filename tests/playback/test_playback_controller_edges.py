from typing import Any, cast

from playback.playback_controller import PlaybackController
from tests.helpers.fakes import FakeBackend, FakePlaybackPlayer, FakeThread

PlaybackController = cast(Any, PlaybackController)


def _setup(monkeypatch):
    ctrl = PlaybackController()
    backend = FakeBackend()
    monkeypatch.setattr("playback.playback_controller.create_backend", lambda *a, **k: backend)
    monkeypatch.setattr("playback.playback_controller.QThread", FakeThread)
    monkeypatch.setattr("playback.playback_controller.Player", FakePlaybackPlayer)
    return ctrl


def test_start_ignored_while_stopping(monkeypatch):
    ctrl = _setup(monkeypatch)
    logs = []

    ctrl._stopping = True
    ctrl.start([], {}, 1.0, "key", False, False, log_message=logs.append)

    assert ctrl.player is None
    assert any("still stopping" in m for m in logs)


def test_stop_and_wait_with_timeout(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False, False)

    thread = ctrl._thread
    player = ctrl.player
    assert thread is not None and player is not None

    ctrl.stop_and_wait(timeout_ms=123)

    player_impl = cast(Any, player)
    thread_impl = cast(Any, thread)
    assert player_impl.stop_calls == 1
    assert thread_impl.wait_calls[-1] == 123
    assert ctrl._stopping is False


def test_stop_and_wait_without_timeout(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False, False)

    thread = ctrl._thread
    player = ctrl.player
    assert thread is not None and player is not None

    ctrl.stop_and_wait()

    player_impl = cast(Any, player)
    thread_impl = cast(Any, thread)
    assert player_impl.stop_calls == 1
    assert thread_impl.wait_calls[-1] is None
    assert ctrl._stopping is False


def test_stop_and_wait_without_player_or_thread_is_safe(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.stop_and_wait(timeout_ms=10)
    assert ctrl._stopping is False


def test_total_duration_prefers_player_value(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 2.5, "key", False, False)
    assert ctrl.total_duration == 2.5


def test_total_duration_falls_back_when_player_missing(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 3.25, "key", False, False)
    ctrl._player = None
    assert ctrl.total_duration == 3.25


def test_set_state_noop_and_toggle_pause_without_player(monkeypatch):
    ctrl = _setup(monkeypatch)
    emitted = []
    ctrl.state_changed.connect(lambda s: emitted.append(s))

    ctrl._set_state("stopped")
    assert emitted == []

    ctrl.toggle_pause()
    assert ctrl.state == "stopped"


def test_stop_noop_when_not_running(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False, False)
    player = ctrl.player
    thread = ctrl._thread
    assert player is not None and thread is not None

    thread_impl = cast(Any, thread)
    thread_impl._running = False
    ctrl.stop()

    player_impl = cast(Any, player)
    assert player_impl.stop_calls == 0


def test_start_ignored_while_running(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False, False)

    logs = []
    first_player = ctrl.player
    ctrl.start([], {}, 1.0, "key", False, False, log_message=logs.append)

    assert ctrl.player is first_player
    assert any("still stopping" in m for m in logs)


def test_on_playback_finished_is_noop_if_already_cleaned(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl._player = None
    ctrl._thread = None
    ctrl._backend = None

    ctrl._on_playback_finished_internal()

    assert ctrl.state == "stopped"


def test_start_finish_then_start_again_uses_clean_state(monkeypatch):
    ctrl = _setup(monkeypatch)

    ctrl.start([], {}, 1.0, "key", False, False)
    first_player = ctrl.player
    first_thread = ctrl._thread
    assert first_player is not None and first_thread is not None

    ctrl._on_playback_finished_internal()
    ctrl.start([], {}, 2.0, "key", False, False)

    assert ctrl.state == "playing"
    assert ctrl.player is not None
    assert ctrl.player is not first_player
    assert ctrl._thread is not None
    assert ctrl._thread is not first_thread
    assert ctrl.total_duration == 2.0


def test_start_stop_and_wait_then_restart_succeeds(monkeypatch):
    ctrl = _setup(monkeypatch)

    ctrl.start([], {}, 1.0, "key", False, False)
    first_player = ctrl.player
    first_thread = ctrl._thread
    assert first_player is not None and first_thread is not None

    ctrl.stop_and_wait(timeout_ms=50)
    ctrl._on_playback_finished_internal()
    ctrl.start([], {}, 1.5, "key", False, False)

    assert ctrl.player is not None
    assert ctrl.player is not first_player
    assert ctrl._thread is not None
    assert ctrl._thread is not first_thread
    assert ctrl.state == "playing"
