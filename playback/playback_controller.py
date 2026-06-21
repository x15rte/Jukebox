"""Playback controller: wraps Player, backend, and QThread.

Keeps threading and backend wiring out of the MainWindow so the UI only needs
to deal with high-level playback commands and signals.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, List, Optional, Callable

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal as Signal

from models import KeyEvent
from .player import Player
from logger_core import jukebox_logger
from output import OutputBackend, OutputBackendUnavailableError, create_backend


PlaybackState = str  # "stopped" | "playing" | "paused"


class PlaybackController(QObject):
    """High-level controller for a single playback run.

    Responsibilities:
    - Own a Player instance, its QThread, and the OutputBackend.
    - Expose Qt signals mirroring Player's signals so that the UI does not need
      to manage threads directly.
    """

    status_updated = Signal(str)
    progress_updated = Signal(float)
    playback_finished = Signal()
    visualizer_updated = Signal(list)
    state_changed = Signal(str)  # emits PlaybackState

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._player: Optional[Player] = None
        self._backend: Optional[OutputBackend] = None
        self._total_duration: float = 0.0
        self._state: PlaybackState = "stopped"
        # True while a stop has been requested but the worker thread has not
        # yet fully finished. Used to avoid starting a new run in the brief
        # window where the previous one is still shutting down.
        self._stopping: bool = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def player(self) -> Optional[Player]:
        """Expose the underlying Player for read-only status checks."""
        return self._player

    @property
    def total_duration(self) -> float:
        """Return the total duration of the current playback run."""
        if self._player is not None:
            return self._player.total_duration
        return self._total_duration

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    @property
    def state(self) -> PlaybackState:
        return self._state

    def _set_state(self, state: PlaybackState) -> None:
        if state == self._state:
            return
        self._state = state
        self.state_changed.emit(state)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(
        self,
        compiled_events: List[KeyEvent],
        config: Mapping[str, Any],
        total_duration: float,
        output_mode: str,
        use_88_key_layout: bool,
        log_message: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """Start playback with the given events and configuration.

        This method is intended to be called from the GUI thread.
        """
        # If a previous playback is still running or in the process of
        # stopping, avoid starting a second overlapping run. This keeps the
        # threading model simple and mirrors the user's expectation that
        # "Stop" fully completes before a new "Play" starts.
        if self._stopping:
            if log_message is not None:
                log_message(
                    "Playback is still stopping; please wait a moment before starting again."
                )
            return False
        if self.is_running:
            if log_message is not None:
                log_message("Playback is already running.")
            return False

        self._total_duration = total_duration

        # Small inter-message delay for midi_numpad spreads RMC bursts so the game
        # can process input smoothly (avoids stutter from back-to-back frames).
        inter_message_delay = 0.001 if output_mode == "midi_numpad" else 0.0
        try:
            backend = create_backend(
                output_mode,
                use_88_key_layout,
                inter_message_delay=inter_message_delay,
                log_message=log_message,
            )
        except (OutputBackendUnavailableError, ValueError) as e:
            message = f"Playback could not start: {e}"
            if log_message is not None:
                log_message(message)
            self._backend = None
            return False
        self._backend = backend

        thread = QThread()
        player = Player(compiled_events, backend, config, total_duration)
        player.moveToThread(thread)

        thread.started.connect(player.play)
        player.playback_finished.connect(self._on_playback_finished_internal)
        player.status_updated.connect(self.status_updated)
        player.progress_updated.connect(self.progress_updated)
        player.visualizer_updated.connect(self.visualizer_updated)

        self._thread = thread
        self._player = player
        try:
            thread.start()
            self._set_state("playing")
        except Exception:
            backend.shutdown()
            raise
        return True

    def stop(self) -> None:
        """Request playback stop; returns immediately."""
        if self._player is not None:
            self._stopping = True
            self._player.stop()
        # _finish_cleanup transitions to "stopped" — not called here.
        # The state remains "playing" or "paused" until the thread finishes.

    def stop_and_wait(self, timeout_ms: Optional[int] = 5000) -> None:
        """Request playback stop and wait for the worker thread to finish (non-blocking retry)."""
        thread = self._thread
        if self._player is not None:
            self._stopping = True
            self._player.stop()
        if thread is not None and thread.isRunning():
            # Player doesn't run a Qt event loop, so quit() would be a no-op.
            # The thread exits when play() returns after stop_event is set.
            QTimer.singleShot(100, lambda: self._stop_and_wait_cleanup(thread, timeout_ms))
        else:
            self._stopping = False

    def _stop_and_wait_cleanup(self, thread: Optional[QThread], timeout_ms: Optional[int]) -> None:
        """Retry loop for stop_and_wait; avoids blocking the GUI thread."""
        if timeout_ms is None:
            timeout_ms = 30000
        if thread is None:
            self._stopping = False
            return
        if thread.isRunning():
            if timeout_ms <= 0:
                jukebox_logger.warning(
                    "Playback thread did not finish within timeout — continuing"
                )
                self._stopping = False
                return
            remaining = timeout_ms - 100
            QTimer.singleShot(100, lambda: self._stop_and_wait_cleanup(thread, remaining))
        else:
            self._finish_cleanup(thread)

    def stop_and_wait_blocking(self, timeout_ms: int = 5000) -> bool:
        """Request stop and block until the worker thread finishes (or timeout).

        This blocks the calling thread — use in closeEvent where the app is
        shutting down and we need the thread to actually finish before we
        return. Returns True if the thread finished, False on timeout.
        """
        thread = self._thread
        if self._player is not None:
            self._stopping = True
            self._player.stop()
        if thread is not None and thread.isRunning():
            # Despite the thread not having its own event loop during play(),
            # after play() returns QThread.run() calls exec(), starting a real
            # event loop. Call quit() first so the event loop exits before wait().
            thread.quit()
            ok = thread.wait(timeout_ms)
            if not ok:
                jukebox_logger.warning(
                    f"Playback thread did not finish within {timeout_ms}ms timeout"
                )
                self._stopping = False
                return ok
        self._finish_cleanup(thread)
        return True

    def _finish_cleanup(self, thread: Optional[QThread]) -> None:
        if thread is not None and thread.isRunning():
            # Still running — retry in 100ms
            QTimer.singleShot(100, lambda: self._finish_cleanup(thread))
            return
        # Ensure we haven't moved on to a new thread since the timer was scheduled
        if self._thread is not thread:
            # Thread was replaced by a new playback — still clean up the old one.
            if thread is not None:
                thread.quit()
                thread.wait(1000)
                try:
                    thread.deleteLater()
                except AttributeError:
                    pass
            return
        old_player = self._player
        old_thread = self._thread
        if old_player is not None:
            # Disconnect playback_finished specifically (PlaybackController connects via start()).
            try:
                old_player.playback_finished.disconnect(self._on_playback_finished_internal)
            except (TypeError, AttributeError):
                pass
            # Blanket-disconnect the remaining signals. These are connected by MainWindow,
            # which expects them to be removed when the Player object is discarded.
            for sig_name in ("status_updated", "progress_updated", "visualizer_updated"):
                try:
                    getattr(old_player, sig_name).disconnect()
                except (TypeError, AttributeError):
                    pass
        self._player = None
        self._backend = None
        self._thread = None
        if old_thread is not None:
            old_thread.quit()  # Safety quit — thread's event loop may or may not be running.
            old_thread.wait(1000)
            try:
                old_thread.deleteLater()
            except AttributeError:
                pass
        self._stopping = False
        self._set_state("stopped")
        self.playback_finished.emit()

    def toggle_pause(self) -> None:
        """Toggle pause/resume if a player is active."""
        if self._player is None:
            return
        # Don't toggle if playback has naturally ended (all events consumed)
        # but stop_event hasn't been set yet (race window before playback_finished).
        if self.state != "playing" and self.state != "paused":
            return
        was_paused = self._player.pause_event.is_set()
        self._player.toggle_pause()
        now_paused = self._player.pause_event.is_set()
        if was_paused == now_paused:
            return  # Player ignored the toggle (e.g., already stopped)
        # Re-check state — playback may have finished while we were toggling
        if self._player is not None and not self._player.stop_event.is_set():
            self._set_state("paused" if now_paused else "playing")

    def seek(self, target_time: float) -> None:
        """Seek to a given time in seconds if a player is active."""
        if self._player is not None:
            self._player.seek(target_time)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _on_playback_finished_internal(self) -> None:
        """Handle Player completion: clean up thread/backend and emit signal."""
        if self._player is None or self.sender() is not self._player:
            return  # Stale signal from a previous Player, or already cleaned up.

        thread = self._thread
        if thread is not None and thread.isRunning():
            thread.quit()  # Safety quit — thread's event loop may or may not be running.
            # Don't block — use a timer to check completion later
            QTimer.singleShot(100, lambda: self._finish_cleanup(thread))
        else:
            self._finish_cleanup(thread)

