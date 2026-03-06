"""Platform-specific utilities and capability detection.

Centralizes Windows-only code (high-resolution timer, app user model ID)
and reports capabilities at startup for logging/UI.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any, Dict

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Windows high-resolution timer (used by player)
# ---------------------------------------------------------------------------

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
            # Best-effort: avoid breaking playback if timer API fails (e.g. driver issue).
            _log.debug("timeBeginPeriod failed: %s", e)


def restore_timer_resolution(ms: int = 1) -> None:
    """Restore timer resolution on Windows; no-op on other platforms."""
    if _winmm:
        try:
            _winmm.timeEndPeriod(ms)
        except Exception as e:
            # Best-effort: avoid breaking playback if timer API fails.
            _log.debug("timeEndPeriod failed: %s", e)


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


# ---------------------------------------------------------------------------
# Windows app user model ID (for taskbar icon grouping)
# ---------------------------------------------------------------------------

def set_app_user_model_id(app_id: str) -> None:
    """Set the application user model ID on Windows so the taskbar groups the icon correctly. No-op on other platforms."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (OSError, AttributeError, ImportError):
        pass


# ---------------------------------------------------------------------------
# Capability detection for startup logging
# ---------------------------------------------------------------------------

def get_capabilities() -> Dict[str, Any]:
    """Return a small dict of runtime capabilities (timer, pydirectinput) for logging or UI."""
    caps: Dict[str, Any] = {
        "high_res_timer": has_high_res_timer(),
        "platform": sys.platform,
    }
    if sys.platform == "win32":
        try:
            import RobloxMidiConnect_encoder as rmc
            caps["pydirectinput"] = rmc.is_using_pydirectinput()
        except Exception:
            caps["pydirectinput"] = False
    else:
        caps["pydirectinput"] = False
    return caps
