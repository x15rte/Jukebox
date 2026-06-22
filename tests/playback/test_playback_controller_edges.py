# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false

from typing import Any, cast
import pytest

from playback.playback_controller import PlaybackController
from tests.helpers.fakes import FakeBackend, FakePlaybackPlayer, FakeThread

PlaybackController = cast(Any, PlaybackController)


def _setup(monkeypatch):
    ctrl = PlaybackController()
    backend = FakeBackend()
    monkeypatch.setattr("playback.playback_controller.create_backend", lambda *a, **k: backend)
    monkeypatch.setattr("playback.playback_controller.QThread", FakeThread)
    monkeypatch.setattr("playback.playback_controller.Player", FakePlaybackPlayer)
    # Fire deferred timers immediately, but first simulate thread completion
    # since FakeThread.quit() doesn't set _running=False (matching real QThread).
    def _fake_timer(ms, cb):
        if ms > 0 and ctrl._thread is not None:
            ctrl._thread._running = False  # type: ignore[attr-defined]
        cb()
    monkeypatch.setattr("playback.playback_controller.QTimer.singleShot", _fake_timer)
    return ctrl


def test_start_applies_seek_offset(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl._seek_offset = 5.0
    ctrl.start([], {}, 10.0, "key", False)
    assert ctrl.player is not None
    assert ctrl.player.config.get("start_offset") == 5.0
    assert ctrl._seek_offset == 0.0


def test_seek_stores_offset_when_not_running(monkeypatch):
    ctrl = PlaybackController()
    ctrl.seek(3.0)
    assert ctrl._seek_offset == 3.0
    assert ctrl._player is None


def test_start_ignored_while_stopping(monkeypatch):
    ctrl = _setup(monkeypatch)
    logs = []

    ctrl._stopping = True
    ctrl.start([], {}, 1.0, "key", False, log_message=logs.append)

    assert ctrl.player is None
    assert any("still stopping" in m for m in logs)


def test_stop_and_wait_with_timeout(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False)

    thread = ctrl._thread
    player = ctrl.player
    assert thread is not None and player is not None

    ctrl.stop_and_wait(timeout_ms=123)

    player_impl = cast(Any, player)
    assert player_impl.stop_calls == 1
    assert ctrl.state == "stopped"
    assert ctrl.player is None
    assert ctrl._thread is None
    assert ctrl._stopping is False


def test_stop_and_wait_without_timeout(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False)

    thread = ctrl._thread
    player = ctrl.player
    assert thread is not None and player is not None

    ctrl.stop_and_wait()

    player_impl = cast(Any, player)
    assert player_impl.stop_calls == 1
    assert ctrl.state == "stopped"
    assert ctrl.player is None
    assert ctrl._thread is None
    assert ctrl._stopping is False


def test_stop_and_wait_without_player_or_thread_is_safe(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.stop_and_wait(timeout_ms=10)
    assert ctrl._stopping is False


def test_total_duration_prefers_player_value(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 2.5, "key", False)
    assert ctrl.total_duration == 2.5


def test_total_duration_falls_back_when_player_missing(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 3.25, "key", False)
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


def test_stop_always_calls_player_stop(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False)
    player = ctrl.player
    thread = ctrl._thread
    assert player is not None and thread is not None

    thread_impl = cast(Any, thread)
    thread_impl._running = False
    ctrl.stop()

    player_impl = cast(Any, player)
    assert player_impl.stop_calls == 1


def test_start_ignored_while_running(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False)

    logs = []
    first_player = ctrl.player
    ctrl.start([], {}, 1.0, "key", False, log_message=logs.append)

    assert ctrl.player is first_player
    assert any("already running" in m for m in logs)


def test_on_playback_finished_is_noop_if_already_cleaned(monkeypatch):
    ctrl = _setup(monkeypatch)
    ctrl._player = None
    ctrl._thread = None
    ctrl._backend = None

    ctrl._on_playback_finished_internal()

    assert ctrl.state == "stopped"


def test_start_finish_then_start_again_uses_clean_state(monkeypatch):
    ctrl = _setup(monkeypatch)

    ctrl.start([], {}, 1.0, "key", False)
    first_player = ctrl.player
    first_thread = ctrl._thread
    assert first_player is not None and first_thread is not None

    monkeypatch.setattr(ctrl, "sender", lambda: first_player)
    ctrl._on_playback_finished_internal()
    ctrl.start([], {}, 2.0, "key", False)

    assert ctrl.state == "playing"
    assert ctrl.player is not None
    assert ctrl.player is not first_player
    assert ctrl._thread is not None
    assert ctrl._thread is not first_thread
    assert ctrl.total_duration == 2.0


def test_start_stop_and_wait_then_restart_succeeds(monkeypatch):
    ctrl = _setup(monkeypatch)

    ctrl.start([], {}, 1.0, "key", False)
    first_player = ctrl.player
    first_thread = ctrl._thread
    assert first_player is not None and first_thread is not None

    ctrl.stop_and_wait(timeout_ms=50)
    monkeypatch.setattr(ctrl, "sender", lambda: first_player)
    ctrl._on_playback_finished_internal()
    ctrl.start([], {}, 1.5, "key", False)

    assert ctrl.player is not None
    assert ctrl.player is not first_player
    assert ctrl._thread is not None
    assert ctrl._thread is not first_thread
    assert ctrl.state == "playing"

def test_start_thread_failure_shuts_down_backend(monkeypatch):
    """Exception from thread.start() shuts down backend and re-raises."""
    ctrl = PlaybackController()
    backend = FakeBackend()
    monkeypatch.setattr(
        "playback.playback_controller.create_backend",
        lambda *a, **k: backend,
    )
    monkeypatch.setattr("playback.playback_controller.Player", FakePlaybackPlayer)

    class FailingThread(FakeThread):
        def start(self):
            raise RuntimeError("thread start failure")

    monkeypatch.setattr("playback.playback_controller.QThread", FailingThread)

    with pytest.raises(RuntimeError, match="thread start failure"):
        ctrl.start([], {}, 1.0, "key", False)
    assert ("shutdown", None) in backend.calls
    assert ctrl.state == "stopped"  # _set_state("playing") was never reached


def test_stop_and_wait_blocking_basic(monkeypatch):
    """stop_and_wait_blocking stops and cleans up playback."""
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False)
    result = ctrl.stop_and_wait_blocking()
    assert result is True
    assert ctrl.state == "stopped"
    assert ctrl.player is None
    assert ctrl._stopping is False


def test_stop_and_wait_blocking_timeout(monkeypatch):
    """stop_and_wait_blocking returns False when thread.wait times out."""
    ctrl = PlaybackController()
    backend = FakeBackend()
    thread = FakeThread()
    monkeypatch.setattr(
        "playback.playback_controller.create_backend",
        lambda *a, **k: backend,
    )
    monkeypatch.setattr("playback.playback_controller.QThread", lambda: thread)
    monkeypatch.setattr("playback.playback_controller.Player", FakePlaybackPlayer)

    warnings = []
    monkeypatch.setattr(
        "playback.playback_controller.jukebox_logger.warning", warnings.append
    )

    orig_wait = thread.wait

    def timeout_wait(timeout=None):
        orig_wait(timeout)
        return False

    thread.wait = timeout_wait

    ctrl.start([], {}, 1.0, "key", False)
    result = ctrl.stop_and_wait_blocking(timeout_ms=100)
    assert result is False
    assert ctrl._stopping is False
    assert any("did not finish" in w for w in warnings)


def test_stop_and_wait_blocking_no_playback(monkeypatch):
    """stop_and_wait_blocking when no playback started returns True."""
    ctrl = PlaybackController()
    result = ctrl.stop_and_wait_blocking()
    assert result is True


def test_stop_and_wait_cleanup_none_timeout(monkeypatch):
    """_stop_and_wait_cleanup sets default timeout when timeout is None."""
    ctrl = PlaybackController()
    thread = FakeThread()
    thread.start()
    ctrl._thread = thread
    ctrl._stopping = True
    monkeypatch.setattr(
        "playback.playback_controller.QTimer.singleShot",
        lambda ms, cb: None,
    )
    ctrl._stop_and_wait_cleanup(thread, None)
    # timeout_ms was None → 30000 → thread running → retry timer scheduled (no-op)
    assert ctrl._stopping is True  # still waiting, retry scheduled


def test_stop_and_wait_cleanup_none_thread(monkeypatch):
    """_stop_and_wait_cleanup with None thread sets _stopping=False."""
    ctrl = PlaybackController()
    ctrl._stopping = True
    monkeypatch.setattr(
        "playback.playback_controller.QTimer.singleShot",
        lambda ms, cb: None,
    )
    ctrl._stop_and_wait_cleanup(None, 5000)
    assert ctrl._stopping is False


def test_stop_and_wait_cleanup_timeout_expired(monkeypatch):
    """_stop_and_wait_cleanup warns and clears _stopping on timeout."""
    ctrl = PlaybackController()
    thread = FakeThread()
    thread.start()
    ctrl._thread = thread
    ctrl._stopping = True
    warnings = []
    monkeypatch.setattr(
        "playback.playback_controller.jukebox_logger.warning", warnings.append
    )
    monkeypatch.setattr(
        "playback.playback_controller.QTimer.singleShot",
        lambda ms, cb: None,
    )
    ctrl._stop_and_wait_cleanup(thread, 0)
    assert ctrl._stopping is False
    assert any("did not finish" in w for w in warnings)


def test_finish_cleanup_schedules_retry_when_thread_running(monkeypatch):
    """_finish_cleanup schedules a retry when thread is still running."""
    ctrl = PlaybackController()
    thread = FakeThread()
    thread.start()
    ctrl._thread = thread
    timer_calls = []
    monkeypatch.setattr(
        "playback.playback_controller.QTimer.singleShot",
        lambda ms, cb: timer_calls.append((ms, cb)),
    )
    ctrl._finish_cleanup(thread)
    assert len(timer_calls) == 1
    assert timer_calls[0][0] == 100


def test_finish_cleanup_stale_thread(monkeypatch):
    """_finish_cleanup cleans up a thread different from the current one."""
    ctrl = PlaybackController()
    thread_a = FakeThread()
    thread_a._running = False
    thread_b = FakeThread()
    ctrl._thread = thread_b

    ctrl._finish_cleanup(thread_a)
    assert thread_a.quit_called
    assert 1000 in thread_a.wait_calls
    assert ctrl._thread is thread_b  # current thread unchanged


def test_finish_cleanup_stale_thread_none(monkeypatch):
    """_finish_cleanup stale path handles None thread."""
    ctrl = PlaybackController()
    thread_b = FakeThread()
    ctrl._thread = thread_b

    ctrl._finish_cleanup(None)
    assert ctrl._thread is thread_b


def test_finish_cleanup_signal_disconnect_exception(monkeypatch):
    """_finish_cleanup handles TypeError from playback_finished.disconnect."""
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False)

    def raising_disconnect(fn=None):
        raise TypeError("signal not connected")

    ctrl._player.playback_finished.disconnect = raising_disconnect

    ctrl._finish_cleanup(ctrl._thread)
    assert ctrl.player is None
    assert ctrl.state == "stopped"


def test_finish_cleanup_blanket_disconnect_exception(monkeypatch):
    """_finish_cleanup handles TypeError from blanket signal disconnects."""
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False)

    def raising_disconnect(fn=None):
        raise TypeError("signal not connected")

    ctrl._player.status_updated.disconnect = raising_disconnect
    ctrl._player.progress_updated.disconnect = raising_disconnect

    ctrl._finish_cleanup(ctrl._thread)
    assert ctrl.player is None
    assert ctrl.state == "stopped"


def test_toggle_pause_when_state_stopped(monkeypatch):
    """toggle_pause is no-op when state is stopped but player exists."""
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False)
    assert ctrl._player is not None
    ctrl._set_state("stopped")
    ctrl.toggle_pause()
    assert ctrl.state == "stopped"


def test_toggle_pause_when_player_ignores_toggle(monkeypatch):
    """toggle_pause is no-op when player.toggle_pause doesn't change state."""
    ctrl = _setup(monkeypatch)
    ctrl.start([], {}, 1.0, "key", False)
    pause_event = ctrl._player.pause_event
    was_paused = pause_event.is_set()
    monkeypatch.setattr(ctrl._player, "toggle_pause", lambda: None)
    ctrl.toggle_pause()
    assert pause_event.is_set() == was_paused
    assert ctrl.state == "playing"
