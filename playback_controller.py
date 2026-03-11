"""Playback controller: wraps Player, backend, and QThread.

Keeps threading and backend wiring out of the MainWindow so the UI only needs
to deal with high-level playback commands and signals.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal as Signal

from models import KeyEvent
from player import Player
from output import OutputBackend, create_backend


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
        config: Dict[str, Any],
        total_duration: float,
        output_mode: str,
        use_88_key_layout: bool,
        macos_use_pynput: bool,
        log_message: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Start playback with the given events and configuration.

        This method is intended to be called from the GUI thread.
        """
        # If a previous playback is still running or in the process of
        # stopping, avoid starting a second overlapping run. This keeps the
        # threading model simple and mirrors the user's expectation that
        # "Stop" fully completes before a new "Play" starts.
        if self.is_running or self._stopping:
            if log_message is not None:
                log_message("Playback is still stopping; please wait a moment before starting again.")
            return

        self._total_duration = total_duration

        backend = create_backend(
            output_mode,
            use_88_key_layout,
            macos_use_pynput=macos_use_pynput,
            log_message=log_message,
        )
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
        thread.start()
        self._set_state("playing")

    def stop(self) -> None:
        """Request playback stop; returns immediately."""
        if self._player is not None:
            self._stopping = True
            self._player.stop()
        self._set_state("stopped")

    def stop_and_wait(self, timeout_ms: Optional[int] = None) -> None:
        """Request playback stop and wait for the worker thread to finish."""
        if self._player is not None:
            self._stopping = True
            self._player.stop()
        thread = self._thread
        if thread is not None:
            if timeout_ms is not None:
                thread.wait(timeout_ms)
            else:
                thread.wait()

    def toggle_pause(self) -> None:
        """Toggle pause/resume if a player is active."""
        if self._player is None:
            return
        # Optimistically update state based on current controller state;
        # Player will follow via its internal pause_event.
        if self._state == "playing":
            self._player.toggle_pause()
            self._set_state("paused")
        elif self._state == "paused":
            self._player.toggle_pause()
            self._set_state("playing")

    def seek(self, target_time: float) -> None:
        """Seek to a given time in seconds if a player is active."""
        if self._player is not None:
            self._player.seek(target_time)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _on_playback_finished_internal(self) -> None:
        """Handle Player completion: clean up thread/backend and emit signal."""
        self.playback_finished.emit()

        thread = self._thread
        player = self._player
        backend = self._backend

        self._player = None
        self._backend = None
        self._thread = None
        self._stopping = False
        self._set_state("stopped")

        if thread is not None:
            thread.quit()
            thread.wait()

        # Player.shutdown() is called from inside Player.play()'s finally block,
        # so there is nothing left to do here regarding backend.

