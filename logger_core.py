"""Central logging utility for Jukebox.

Provides:
- A process-wide logger instance with standard Python `logging`.
- Optional rotating file output (enabled/disabled by the GUI).
- One or more GUI callbacks invoked for every log entry (level + message),
  intended to be bridged into Qt signals.
- Configurable log level (e.g. DEBUG, INFO, WARNING, ERROR, CRITICAL).

This module is intentionally free of any Qt imports so it can be reused
in headless / CLI contexts.
"""

import logging
import os
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, List, Optional

# Callback signature: (level: str, message: str) -> None
LogCallback = Callable[[str, str], None]

_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


LOG_FILENAME = "log.txt"

class JukeboxLogger:
    """Thin wrapper around ``logging.Logger`` with GUI callbacks and level control.

    State queries (thread-safe):
    - :attr:`is_file_logging_enabled`
    - :attr:`current_level_name`
    - :attr:`callback_count`
    """

    def __init__(self, logger_name: str = "jukebox") -> None:
        self._logger = logging.getLogger(logger_name)
        self._logger.setLevel(logging.INFO)
        # Avoid propagating to the root logger unless the host app wants that.
        self._logger.propagate = False

        # Basic stderr handler for non-GUI / debug runs.
        if not self._logger.handlers:
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(logging.Formatter(_FORMAT))
            # Handle Unicode characters that may not be representable in the
            # active console code page (e.g. cp437 on Windows).
            try:
                if hasattr(sys.stderr, 'reconfigure'):
                    sys.stderr.reconfigure(errors='replace')  # type: ignore[attr-defined]
            except (OSError, ValueError):
                pass
            self._logger.addHandler(stream_handler)

        self._lock = threading.Lock()
        self._file_handler: Optional[RotatingFileHandler] = None
        self._gui_callbacks: List[LogCallback] = []

    # ------------------------------------------------------------------
    # Representation & state queries (thread-safe)
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        with self._lock:
            level = logging.getLevelName(self._logger.level)
            cb_count = len(self._gui_callbacks)
            file_on = self._file_handler is not None
        return (
            f"JukeboxLogger(level={level}, "
            f"callbacks={cb_count}, "
            f"file_logging={'on' if file_on else 'off'})"
        )

    @property
    def is_file_logging_enabled(self) -> bool:
        with self._lock:
            return self._file_handler is not None

    @property
    def current_level_name(self) -> str:
        with self._lock:
            return logging.getLevelName(self._logger.level)

    @property
    def callback_count(self) -> int:
        with self._lock:
            return len(self._gui_callbacks)

    # ------------------------------------------------------------------
    # GUI integration (multi-callback)
    # ------------------------------------------------------------------

    def set_gui_callback(self, callback: Optional[LogCallback]) -> None:
        """Set the single GUI callback (replaces any existing).

        For multiple listeners use :meth:`add_gui_callback`.
        """
        with self._lock:
            self._gui_callbacks = [callback] if callback else []

    def clear_gui_callbacks(self) -> None:
        """Remove all registered GUI callbacks."""
        with self._lock:
            self._gui_callbacks.clear()

    def add_gui_callback(self, callback: LogCallback) -> None:
        """Register an additional callback for every log entry.

        Idempotent per callback identity — adding the same object twice
        is a no-op.
        """
        with self._lock:
            if callback not in self._gui_callbacks:
                self._gui_callbacks.append(callback)

    def remove_gui_callback(self, callback: LogCallback) -> None:
        """Unregister a previously added callback.

        Silently ignored if *callback* was not registered.
        """
        with self._lock:
            if callback in self._gui_callbacks:
                self._gui_callbacks.remove(callback)

    def set_level(self, level_name: str) -> None:
        """Set the minimum log level (e.g. ``'DEBUG'``, ``'INFO'``, ``'WARNING'``,
        ``'ERROR'``, ``'CRITICAL'``).

        Unknown level names silently fall back to ``INFO``.
        """
        name = level_name.upper()
        level = _LEVELS.get(name, logging.INFO)
        with self._lock:
            self._logger.setLevel(level)

    # ------------------------------------------------------------------
    # File logging (with rotation)
    # ------------------------------------------------------------------

    def enable_file_logging(
        self,
        path: str | Path,
        max_bytes: int = 5 * 1024 * 1024,
        backup_count: int = 2,
    ) -> None:
        """Enable rotating file logging to *path*.

        If a file handler is already active for the same *path*, this is a no-op.
        """
        abs_path = Path(path).resolve()
        # Directory creation outside the lock to avoid blocking on I/O
        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        except OSError:
            pass

        # Quick check outside lock, then double-check with lock
        with self._lock:
            if (
                self._file_handler is not None
                and self._file_handler.baseFilename == str(abs_path)
                and self._file_handler.maxBytes == max_bytes
                and self._file_handler.backupCount == backup_count
                and hasattr(self._file_handler, 'stream')
                and self._file_handler.stream is not None
                and not self._file_handler.stream.closed
            ):
                return
            # Remember the old handler for disposal outside the lock
            old_handler = self._file_handler
            self._file_handler = None

        try:
            handler = RotatingFileHandler(
                abs_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
        except (OSError, PermissionError) as e:
            self._logger.warning("Could not enable file logging: %s", e)
            with self._lock:
                if self._file_handler is None:
                    self._file_handler = old_handler
                elif old_handler is not None:  # pragma: no cover
                    # Another thread set a handler while we were creating ours.
                    # Dispose old_handler since it's no longer tracked.
                    self._logger.removeHandler(old_handler)
                    try:
                        old_handler.close()
                    except Exception as ce:
                        self._logger.debug("Error closing previous file handler: %s", ce)
            return

        with self._lock:
            if self._file_handler is not None:
                # Another thread set a handler while we were creating ours
                if old_handler is not None:  # pragma: no cover
                    self._logger.removeHandler(old_handler)
                    try:
                        old_handler.close()
                    except Exception as e:
                        self._logger.debug("Error closing previous file handler: %s", e)
                handler.close()  # pragma: no cover
                return  # pragma: no cover
            handler.setFormatter(logging.Formatter(_FORMAT))
            self._logger.addHandler(handler)
            self._file_handler = handler

        # Dispose old handler outside the lock
        if old_handler is not None:
            self._logger.removeHandler(old_handler)
            try:
                old_handler.close()
            except Exception as e:
                self._logger.debug("Error closing previous file handler: %s", e)

    def disable_file_logging(self) -> None:
        """Disable file logging and close the current file handler, if any."""
        with self._lock:
            if self._file_handler is None:
                return
            self._logger.removeHandler(self._file_handler)
            try:
                self._file_handler.close()
            except Exception as e:
                self._logger.debug("Error closing file handler: %s", e)
            self._file_handler = None

    # ------------------------------------------------------------------
    # Core logging API
    # ------------------------------------------------------------------

    def log(self, level: str, message: str, exc_info: bool = False) -> None:
        """Log *message* at the given *level* and notify all GUI callbacks.

        If *exc_info* is ``True`` and an exception is currently being handled
        (i.e. inside an ``except`` block), the traceback is appended to the
        GUI callback message.  If *exc_info* is ``True`` but no exception is
        active, the traceback is silently omitted.

        .. note::
            Callbacks registered via add_gui_callback are stored indefinitely.
            For dynamically-created callbacks (lambdas, bound methods), caller
            MUST call remove_gui_callback when the callback is no longer needed
            to prevent reference leaks.
        """
        lvl_name = level.upper()
        lvl = _LEVELS.get(lvl_name, logging.INFO)

        with self._lock:
            if not self._logger.isEnabledFor(lvl):
                return
            callbacks = list(self._gui_callbacks) if self._gui_callbacks else []

        self._logger.log(lvl, message, exc_info=exc_info)

        if not callbacks:
            return

        if exc_info and sys.exc_info()[0] is not None:
            full_message = message + "\n" + traceback.format_exc()
        else:
            full_message = message

        for cb in callbacks:
            try:
                cb(lvl_name, full_message)
            except Exception:
                self._logger.debug("Error in GUI log callback", exc_info=True)

    def info(self, message: str, exc_info: bool = False) -> None:
        """Log at INFO level."""
        self.log("INFO", message, exc_info=exc_info)

    def warning(self, message: str, exc_info: bool = False) -> None:
        """Log at WARNING level."""
        self.log("WARNING", message, exc_info=exc_info)

    def error(self, message: str, exc_info: bool = False) -> None:
        """Log at ERROR level."""
        self.log("ERROR", message, exc_info=exc_info)

    def debug(self, message: str, exc_info: bool = False) -> None:
        """Log at DEBUG level."""
        self.log("DEBUG", message, exc_info=exc_info)

# Global singleton used throughout the project.
jukebox_logger = JukeboxLogger()

