"""Central logging utility for Jukebox.

Provides:
- A process-wide logger instance with standard Python `logging`.
- Optional rotating file output (enabled/disabled by the GUI).
- An optional GUI callback that will be invoked for every log entry
  (level + message), intended to be bridged into Qt signals.

This module is intentionally free of any Qt imports so it can be reused
in headless / CLI contexts.
"""

from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from typing import Callable, Optional


class _JukeboxLogger:
    """Thin wrapper around `logging.Logger` with GUI callback support."""

    def __init__(self) -> None:
        self._logger = logging.getLogger("jukebox")
        self._logger.setLevel(logging.INFO)
        # Avoid propagating to the root logger unless the host app wants that.
        self._logger.propagate = False

        # Basic stderr handler for non-GUI / debug runs.
        if not self._logger.handlers:
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            )
            self._logger.addHandler(stream_handler)

        self._lock = threading.Lock()
        self._file_handler: Optional[RotatingFileHandler] = None
        # Callback signature: (level: str, message: str) -> None
        self._gui_callback: Optional[Callable[[str, str], None]] = None

    # ------------------------------------------------------------------
    # GUI integration
    # ------------------------------------------------------------------
    def set_gui_callback(self, callback: Optional[Callable[[str, str], None]]) -> None:
        """Register a callback invoked for every log entry.

        The callback is expected to be cheap and non-blocking; the GUI
        should usually bridge this into a Qt signal so that any actual
        widget updates run on the main thread.
        """
        with self._lock:
            self._gui_callback = callback

    # ------------------------------------------------------------------
    # File logging (with rotation)
    # ------------------------------------------------------------------
    def enable_file_logging(
        self,
        path: str,
        max_bytes: int = 5 * 1024 * 1024,
        backup_count: int = 3,
    ) -> None:
        """Enable rotating file logging to *path*.

        Subsequent calls with the same parameters are cheap; changing the
        path or rotation settings will recreate the handler.
        """
        abs_path = os.path.abspath(path)
        with self._lock:
            if (
                self._file_handler is not None
                and os.path.abspath(self._file_handler.baseFilename) == abs_path
                and getattr(self._file_handler, "maxBytes", None) == max_bytes
                and getattr(self._file_handler, "backupCount", None) == backup_count
            ):
                return

            if self._file_handler is not None:
                self._logger.removeHandler(self._file_handler)
                try:
                    self._file_handler.close()
                except Exception:
                    pass
                self._file_handler = None

            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            handler = RotatingFileHandler(
                abs_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
            )
            handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            )
            self._logger.addHandler(handler)
            self._file_handler = handler

    def disable_file_logging(self) -> None:
        """Disable file logging and close the current file handler, if any."""
        with self._lock:
            if self._file_handler is None:
                return
            self._logger.removeHandler(self._file_handler)
            try:
                self._file_handler.close()
            except Exception:
                pass
            self._file_handler = None

    # ------------------------------------------------------------------
    # Core logging API
    # ------------------------------------------------------------------
    def log(self, level: str, message: str) -> None:
        """Log *message* at the given *level* and notify GUI callback."""
        lvl_name = level.upper()
        lvl = getattr(logging, lvl_name, logging.INFO)
        self._logger.log(lvl, message)

        # Notify GUI (if any) without holding the lock during the callback.
        with self._lock:
            callback = self._gui_callback
        if callback is not None:
            try:
                callback(lvl_name, message)
            except Exception:
                # Avoid recursive logging here; swallow GUI callback errors.
                self._logger.debug("Error in GUI log callback", exc_info=True)

    def info(self, message: str) -> None:
        self.log("INFO", message)

    def warning(self, message: str) -> None:
        self.log("WARNING", message)

    def error(self, message: str) -> None:
        self.log("ERROR", message)


# Global singleton used throughout the project.
jukebox_logger = _JukeboxLogger()

