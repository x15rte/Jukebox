"""Windows high-resolution timer utilities.

Provides set_timer_resolution, restore_timer_resolution, precise_sleep, and has_high_res_timer.
All functions are no-ops on non-Windows platforms.
"""

from __future__ import annotations

import sys
import time
import threading
from typing import Optional

from logger_core import jukebox_logger

_timer_resolution_lock = threading.Lock()

_winmm = None
if sys.platform == "win32":
    try:
        import ctypes

        _winmm = ctypes.windll.winmm
    except (OSError, AttributeError, ImportError):
        _winmm = None

_timer_resolution_refs: int = 0
_timer_resolution_ms: int = 1


def set_timer_resolution(ms: int = 1) -> None:
    """Request higher system timer resolution on Windows; no-op on other platforms."""
    global _timer_resolution_refs, _timer_resolution_ms
    if _winmm:
        with _timer_resolution_lock:
            if _timer_resolution_refs == 0:
                try:
                    _timer_resolution_ms = ms
                    _winmm.timeBeginPeriod(ms)
                except Exception as e:
                    jukebox_logger.debug(f"timeBeginPeriod failed: {e}")
                    return  # Don't increment refs on failure
            _timer_resolution_refs += 1

def restore_timer_resolution(ms: int = 1) -> None:
    """Restore timer resolution on Windows; no-op on other platforms."""
    global _timer_resolution_refs, _timer_resolution_ms
    if _winmm:
        with _timer_resolution_lock:
            if _timer_resolution_refs > 0:
                _timer_resolution_refs -= 1
                if _timer_resolution_refs == 0:
                    try:
                        _winmm.timeEndPeriod(_timer_resolution_ms)
                    except Exception as e:
                        jukebox_logger.debug(f"timeEndPeriod failed: {e}")


def precise_sleep(seconds: float, stop_event: Optional[threading.Event] = None, pause_event: Optional[threading.Event] = None) -> None:
    """Sleep for approximately *seconds*; uses busy-wait for the last ~2 ms for accuracy.
    If stop_event is provided, the sleep is interruptible via stop_event.set().
    If pause_event is provided, the coarse sleep also checks pause_event between iterations.
    """
    if seconds <= 0:
        return
    deadline = time.perf_counter() + seconds
    if seconds > 0.002:
        if stop_event is not None:
            while (not stop_event.is_set()) and (not pause_event or not pause_event.is_set()) and time.perf_counter() < deadline - 0.002:
                remaining = deadline - 0.002 - time.perf_counter()
                wait = max(0.001, min(0.05, remaining))
                stop_event.wait(wait)
        elif pause_event is not None:
            while not pause_event.is_set() and time.perf_counter() < deadline - 0.002:
                remaining = deadline - 0.002 - time.perf_counter()
                wait = max(0.001, min(0.05, remaining))
                pause_event.wait(wait)
        else:
            time.sleep(seconds - 0.002)
    while time.perf_counter() < deadline:
        if stop_event is not None and stop_event.is_set():
            break
        if pause_event is not None and pause_event.is_set():
            break
        time.sleep(0)


def has_high_res_timer() -> bool:
    """True if high-resolution timer APIs are available (Windows)."""
    return _winmm is not None
