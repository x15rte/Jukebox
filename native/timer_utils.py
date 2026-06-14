"""Windows high-resolution timer utilities.

Provides set_timer_resolution, restore_timer_resolution, precise_sleep, and has_high_res_timer.
All functions are no-ops on non-Windows platforms.
"""

from __future__ import annotations

import sys
import sys
import time

from logger_core import jukebox_logger

_winmm = None
if sys.platform == "win32":
    try:
        import ctypes

        _winmm = ctypes.windll.winmm
    except (OSError, AttributeError, ImportError):
        _winmm = None


def set_timer_resolution(ms: int = 1) -> None:
    """Request higher system timer resolution on Windows; no-op on other platforms."""
    if _winmm:
        try:
            _winmm.timeBeginPeriod(ms)
        except Exception as e:
            jukebox_logger.debug(f"timeBeginPeriod failed: {e}")


def restore_timer_resolution(ms: int = 1) -> None:
    """Restore timer resolution on Windows; no-op on other platforms."""
    if _winmm:
        try:
            _winmm.timeEndPeriod(ms)
        except Exception as e:
            jukebox_logger.debug(f"timeEndPeriod failed: {e}")


def precise_sleep(seconds: float) -> None:
    """Sleep for approximately *seconds*; uses busy-wait for the last ~2 ms for accuracy."""
    if seconds <= 0:
        return
    deadline = time.perf_counter() + seconds
    if seconds > 0.002:
        time.sleep(seconds - 0.002)
    while time.perf_counter() < deadline:
        pass


def has_high_res_timer() -> bool:
    """True if high-resolution timer APIs are available (Windows)."""
    return _winmm is not None
