"""Platform-specific utilities and capability detection.

Centralizes Windows-only code (high-resolution timer, app user model ID)
and reports capabilities at startup for logging/UI.
"""

from __future__ import annotations

import logging
import shutil
import subprocess  # nosec B404: used with fixed args only; not user-controlled
import sys
import time
from typing import Any, Dict, Optional

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
# macOS Accessibility (for keyboard injection; Darwin only)
# ---------------------------------------------------------------------------

def is_macos_accessibility_trusted() -> bool:
    """Return True if the current process is trusted for Accessibility on macOS (Darwin).
    Returns True on non-Darwin or on any failure so we do not block the user."""
    if sys.platform != "darwin":
        return True
    try:
        import ctypes
        app_services = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        fn = app_services.AXIsProcessTrustedWithOptions
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = ctypes.c_bool
        return bool(fn(None))
    except Exception as e:
        _log.debug("AXIsProcessTrustedWithOptions check failed: %s", e)
        return True


def open_macos_accessibility_preferences() -> None:
    """Open System Settings to Privacy & Security → Accessibility on macOS (Darwin). No-op on other platforms."""
    if sys.platform != "darwin":
        return
    try:
        open_path = shutil.which("open") or "/usr/bin/open"
        subprocess.run(  # nosec B603 B607: fixed args, executable from shutil.which; not user-controlled
            [open_path, "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
            check=False,
            timeout=5,
        )
    except Exception as e:
        _log.debug("Failed to open Accessibility preferences: %s", e)


# ---------------------------------------------------------------------------
# macOS CGEvent key injection (Darwin only; aligns with miditoqwerty-rs)
# ---------------------------------------------------------------------------

# Virtual key codes for keys used by KeyMapper; same as miditoqwerty-rs KEYCODES mac field.
# See https://github.com/ArijanJ/miditoqwerty-rs/blob/main/src/keycodes/mod.rs
_MACOS_VK: Dict[str, int] = {}
if sys.platform == "darwin":
    _MACOS_VK = {
        "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "5": 0x17, "6": 0x16,
        "7": 0x1A, "8": 0x1C, "9": 0x19, "0": 0x1D,
        "q": 0x0C, "w": 0x0D, "e": 0x0E, "r": 0x0F, "t": 0x11, "y": 0x10,
        "u": 0x20, "i": 0x22, "o": 0x1F, "p": 0x23,
        "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "g": 0x05, "h": 0x04,
        "j": 0x26, "k": 0x28, "l": 0x25,
        "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "n": 0x2D, "m": 0x2E,
        "space": 0x31,
        "shift": 0x38, "ctrl": 0x3B, "control": 0x3B, "alt": 0x3A,
    }

# CGEventFlags (Carbon.HIToolbox)
MACOS_CGFLAG_SHIFT = 0x00000100
MACOS_CGFLAG_CONTROL = 0x00000400
MACOS_CGFLAG_ALT = 0x00080000

_kCGEventSourceStateHIDSystemState = 1
_kCGHIDEventTap = 0

_macos_cgevent_ready = False
_macos_app_services = None
_macos_core_foundation = None


def _init_macos_cgevent() -> bool:
    """Load ApplicationServices and CoreFoundation for CGEvent; return True if ready."""
    global _macos_cgevent_ready, _macos_app_services, _macos_core_foundation
    if sys.platform != "darwin":
        return False
    if _macos_cgevent_ready:
        return _macos_app_services is not None
    try:
        _macos_app_services = __import__("ctypes").CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        _macos_core_foundation = __import__("ctypes").CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        # CGEventSourceRef CGEventSourceCreate(cgEventSourceStateID stateID);
        _macos_app_services.CGEventSourceCreate.argtypes = [__import__("ctypes").c_uint32]
        _macos_app_services.CGEventSourceCreate.restype = __import__("ctypes").c_void_p
        # CGEventRef CGEventCreateKeyboardEvent(CGEventSourceRef source, CGKeyCode keyCode, bool keyDown);
        _macos_app_services.CGEventCreateKeyboardEvent.argtypes = [
            __import__("ctypes").c_void_p,
            __import__("ctypes").c_uint16,
            __import__("ctypes").c_uint8,
        ]
        _macos_app_services.CGEventCreateKeyboardEvent.restype = __import__("ctypes").c_void_p
        # void CGEventSetFlags(CGEventRef event, CGEventFlags flags);
        _macos_app_services.CGEventSetFlags.argtypes = [
            __import__("ctypes").c_void_p,
            __import__("ctypes").c_uint64,
        ]
        _macos_app_services.CGEventSetFlags.restype = None
        # void CGEventPost(CGEventTapLocation tap, CGEventRef event);
        _macos_app_services.CGEventPost.argtypes = [
            __import__("ctypes").c_uint32,
            __import__("ctypes").c_void_p,
        ]
        _macos_app_services.CGEventPost.restype = None
        # void CFRelease(CFTypeRef cf);
        _macos_core_foundation.CFRelease.argtypes = [__import__("ctypes").c_void_p]
        _macos_core_foundation.CFRelease.restype = None
        _macos_cgevent_ready = True
        return True
    except Exception as e:
        _log.debug("macOS CGEvent init failed: %s", e)
        _macos_cgevent_ready = True
        _macos_app_services = None
        return False


def get_macos_vk_for_key(base_key: Any) -> Optional[int]:
    """Return macOS virtual key code for a key used by KeyMapper (single char or Key-like). None if not on Darwin or unknown."""
    if sys.platform != "darwin" or not _MACOS_VK:
        return None
    if isinstance(base_key, str) and len(base_key) == 1:
        return _MACOS_VK.get(base_key.lower())
    # pynput Key enum: treat by name
    key_name = getattr(base_key, "name", None) if hasattr(base_key, "name") else None
    if key_name:
        n = key_name.lower()
        if n in ("space", "shift", "ctrl", "control", "alt"):
            return _MACOS_VK.get(n) or _MACOS_VK.get("control" if n == "ctrl" else n)
    return None


def get_macos_vk_for_modifier(mod_key: Any) -> Optional[int]:
    """Return macOS VK for a modifier (Key.shift -> 0x38, etc.). None if not Darwin or unknown."""
    if sys.platform != "darwin" or not _MACOS_VK:
        return None
    name = getattr(mod_key, "name", None) if hasattr(mod_key, "name") else None
    if name:
        n = name.lower()
        return _MACOS_VK.get(n) or (_MACOS_VK.get("control") if n == "ctrl" else None)
    return None


def post_macos_key_event(key_code: int, key_down: bool, flags: int = 0) -> bool:
    """Post a single keyboard event via CGEvent on macOS. Returns True on success. No-op on non-Darwin."""
    if sys.platform != "darwin":
        return False
    if not _init_macos_cgevent() or _macos_app_services is None or _macos_core_foundation is None:
        return False
    try:
        source = _macos_app_services.CGEventSourceCreate(_kCGEventSourceStateHIDSystemState)
        if not source:
            return False
        event = _macos_app_services.CGEventCreateKeyboardEvent(
            source, key_code, 1 if key_down else 0
        )
        if not event:
            _macos_core_foundation.CFRelease(source)
            return False
        _macos_app_services.CGEventSetFlags(event, flags)
        _macos_app_services.CGEventPost(_kCGHIDEventTap, event)
        _macos_core_foundation.CFRelease(event)
        _macos_core_foundation.CFRelease(source)
        return True
    except Exception as e:
        _log.debug("post_macos_key_event failed: %s", e)
        return False


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
