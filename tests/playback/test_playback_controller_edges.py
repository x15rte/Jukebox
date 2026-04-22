from typing import Any, cast

from playback.playback_controller import PlaybackController
from tests.helpers.fakes import FakeBackend, FakeSignal, FakeThread

PlaybackController = cast(Any, PlaybackController)


class _Player:
    def __init__(self, events, backend, config, total_duration):
        self.total_duration = total_duration
        self.playback_finished = FakeSignal()
        self.status_updated = FakeSignal()
        self.progress_updated = FakeSignal()
        self.visualizer_updated = FakeSignal()
        self.stop_calls = 0

    def moveToThread(self, thread):
        self.thread = thread

    def play(self):
        return None

    def stop(self):
        self.stop_calls += 1

    def toggle_pause(self):
        return None

    def seek(self, target):
        return None


def _setup(monkeypatch):
    ctrl = PlaybackController()
    backend = FakeBackend()
    monkeypatch.setattr("playback.playback_controller.create_backend", lambda *a, **k: backend)
    monkeypatch.setattr("playback.playback_controller.QThread", FakeThread)
    monkeypatch.setattr("playback.playback_controller.Player", _Player)
    return ctrl


def test_start_ignored_while_stopping(monkeypatch):
    ctrl = _setup(monkeypatch)
    logs = []

    ctrl._stopping = True
    ctrl.start([], {}, 1.0, "key", False, False, log_message=logs.append)

    if not (ctrl.player is None):
        raise AssertionError("Assertion failed")
    if not (any("still stopping" in m for m in logs)):
        raise AssertionError("Assertion failed")


def test_stop_and_wait_with_timeout(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False, False)

    thread = ctrl._thread
    player = ctrl.player
    if not (thread is not None and player is not None):
        raise AssertionError("Assertion failed")

    ctrl.stop_and_wait(timeout_ms=123)

    player_impl = cast(Any, player)
    thread_impl = cast(Any, thread)
    if not (player_impl.stop_calls == 1):
        raise AssertionError("Assertion failed")
    if not (thread_impl.wait_calls[-1] == 123):
        raise AssertionError("Assertion failed")
    if not (ctrl._stopping is False):
        raise AssertionError("Assertion failed")


def test_stop_and_wait_without_timeout(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False, False)

    thread = ctrl._thread
    player = ctrl.player
    if not (thread is not None and player is not None):
        raise AssertionError("Assertion failed")

    ctrl.stop_and_wait()

    player_impl = cast(Any, player)
    thread_impl = cast(Any, thread)
    if not (player_impl.stop_calls == 1):
        raise AssertionError("Assertion failed")
    if not (thread_impl.wait_calls[-1] is None):
        raise AssertionError("Assertion failed")
    if not (ctrl._stopping is False):
        raise AssertionError("Assertion failed")


def test_stop_and_wait_without_player_or_thread_is_safe(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.stop_and_wait(timeout_ms=10)
    if not (ctrl._stopping is False):
        raise AssertionError("Assertion failed")


def test_total_duration_prefers_player_value(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 2.5, "key", False, False)
    if not (ctrl.total_duration == 2.5):
        raise AssertionError("Assertion failed")


def test_total_duration_falls_back_when_player_missing(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 3.25, "key", False, False)
    ctrl._player = None
    if not (ctrl.total_duration == 3.25):
        raise AssertionError("Assertion failed")


def test_set_state_noop_and_toggle_pause_without_player(monkeypatch):
    ctrl = _setup(monkeypatch)
    emitted = []
    ctrl.state_changed.connect(lambda s: emitted.append(s))

    ctrl._set_state("stopped")
    if not (emitted == []):
        raise AssertionError("Assertion failed")

    ctrl.toggle_pause()
    if not (ctrl.state == "stopped"):
        raise AssertionError("Assertion failed")


def test_stop_noop_when_not_running(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False, False)
    player = ctrl.player
    thread = ctrl._thread
    if not (player is not None and thread is not None):
        raise AssertionError("Assertion failed")

    thread_impl = cast(Any, thread)
    thread_impl._running = False
    ctrl.stop()

    player_impl = cast(Any, player)
    if not (player_impl.stop_calls == 0):
        raise AssertionError("Assertion failed")


def test_start_ignored_while_running(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False, False)

    logs = []
    first_player = ctrl.player
    ctrl.start([], {}, 1.0, "key", False, False, log_message=logs.append)

    if not (ctrl.player is first_player):
        raise AssertionError("Assertion failed")
    if not (any("still stopping" in m for m in logs)):
        raise AssertionError("Assertion failed")


def test_on_playback_finished_is_noop_if_already_cleaned(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl._player = None
    ctrl._thread = None
    ctrl._backend = None

    ctrl._on_playback_finished_internal()

    if not (ctrl.state == "stopped"):
        raise AssertionError("Assertion failed")
