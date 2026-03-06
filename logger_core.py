"""Central logging utility for Jukebox.

Provides:
- A process-wide logger instance with standard Python `logging`.
- Optional rotating file output (enabled/disabled by the GUI).
- One or more GUI callbacks invoked for every log entry (level + message),
  intended to be bridged into Qt signals.
- Configurable log level (e.g. DEBUG, INFO, WARNING).

This module is intentionally free of any Qt imports so it can be reused
in headless / CLI contexts.
"""

from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from typing import Callable, List, Optional

# Callback signature: (level: str, message: str) -> None
LogCallback = Callable[[str, str], None]


class _JukeboxLogger:
    """Thin wrapper around `logging.Logger` with GUI callbacks and level control."""

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
        self._gui_callbacks: List[LogCallback] = []

    # ------------------------------------------------------------------
    # GUI integration (multi-callback)
    # ------------------------------------------------------------------
    def set_gui_callback(self, callback: Optional[LogCallback]) -> None:
        """Set the single GUI callback (replaces any existing). For multiple listeners use add_gui_callback."""
        with self._lock:
            self._gui_callbacks = [callback] if callback else []

    def add_gui_callback(self, callback: LogCallback) -> None:
        """Register an additional callback for every log entry. Idempotent per callback identity."""
        with self._lock:
            if callback not in self._gui_callbacks:
                self._gui_callbacks.append(callback)

    def remove_gui_callback(self, callback: LogCallback) -> None:
        """Unregister a previously added callback."""
        with self._lock:
            if callback in self._gui_callbacks:
                self._gui_callbacks.remove(callback)

    def set_level(self, level_name: str) -> None:
        """Set the minimum log level (e.g. 'DEBUG', 'INFO', 'WARNING', 'ERROR')."""
        name = level_name.upper()
        level = getattr(logging, name, logging.INFO)
        self._logger.setLevel(level)

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
                except Exception as e:
                    self._logger.debug("Error closing previous file handler: %s", e)
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
            except Exception as e:
                self._logger.debug("Error closing file handler: %s", e)
            self._file_handler = None

    # ------------------------------------------------------------------
    # Core logging API
    # ------------------------------------------------------------------
    def log(self, level: str, message: str, exc_info: bool = False) -> None:
        """Log *message* at the given *level* and notify all GUI callbacks. If exc_info is True, append exception traceback."""
        lvl_name = level.upper()
        lvl = getattr(logging, lvl_name, logging.INFO)
        if exc_info:
            self._logger.exception(message)
        else:
            self._logger.log(lvl, message)

        if exc_info:
            import traceback
            full_message = message + "\n" + traceback.format_exc()
        else:
            full_message = message
        # Only push to GUI callbacks when this level is enabled (same as terminal/file).
        if self._logger.isEnabledFor(lvl):
            with self._lock:
                callbacks = list(self._gui_callbacks)
            for cb in callbacks:
                try:
                    cb(lvl_name, full_message)
                except Exception:
                    self._logger.debug("Error in GUI log callback", exc_info=True)

    def info(self, message: str) -> None:
        self.log("INFO", message)

    def warning(self, message: str) -> None:
        self.log("WARNING", message)

    def error(self, message: str, exc_info: bool = False) -> None:
        self.log("ERROR", message, exc_info=exc_info)

    def debug(self, message: str) -> None:
        self.log("DEBUG", message)


# Global singleton used throughout the project.
jukebox_logger = _JukeboxLogger()

