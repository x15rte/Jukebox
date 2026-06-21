"""macOS CGEvent key injection and Accessibility helpers (Darwin only).

All functions are no-ops on non-Darwin platforms.
"""

from __future__ import annotations
import threading
import shutil
import subprocess  # nosec B404: fixed args only
import sys
from typing import Any, Dict, Optional

from logger_core import jukebox_logger
from pynput.keyboard import Key, KeyCode

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
        jukebox_logger.debug(f"AXIsProcessTrustedWithOptions check failed: {e}")
        return False

def open_macos_accessibility_preferences() -> None:
    """Open System Settings to Privacy & Security -> Accessibility on macOS (Darwin). No-op on other platforms."""
    if sys.platform != "darwin":
        return
    try:
        open_path = shutil.which("open") or "/usr/bin/open"
        subprocess.run(  # nosec B603 B607: fixed args, executable from shutil.which; not user-controlled
            [
                open_path,
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            ],
            check=False,
            timeout=5,
        )
    except Exception as e:
        jukebox_logger.debug(f"Failed to open Accessibility preferences: {e}")


# ---------------------------------------------------------------------------
# macOS CGEvent key injection (Darwin only; aligns with miditoqwerty-rs)
# ---------------------------------------------------------------------------

_MACOS_VK: Dict[str, int] = {}
if sys.platform == "darwin":
    _MACOS_VK = {
        "1": 0x12,
        "2": 0x13,
        "3": 0x14,
        "4": 0x15,
        "5": 0x17,
        "6": 0x16,
        "7": 0x1A,
        "8": 0x1C,
        "9": 0x19,
        "0": 0x1D,
        "q": 0x0C,
        "w": 0x0D,
        "e": 0x0E,
        "r": 0x0F,
        "t": 0x11,
        "y": 0x10,
        "u": 0x20,
        "i": 0x22,
        "o": 0x1F,
        "p": 0x23,
        "a": 0x00,
        "s": 0x01,
        "d": 0x02,
        "f": 0x03,
        "g": 0x05,
        "h": 0x04,
        "j": 0x26,
        "k": 0x28,
        "l": 0x25,
        "z": 0x06,
        "x": 0x07,
        "c": 0x08,
        "v": 0x09,
        "b": 0x0B,
        "n": 0x2D,
        "m": 0x2E,
        "space": 0x31,
        "shift": 0x38,
        "ctrl": 0x3B,
        "control": 0x3B,
        "alt": 0x3A,
    }

# CGEventFlags (CoreGraphics kCGEventFlagMask*)
MACOS_CGFLAG_SHIFT = 0x00020000      # kCGEventFlagMaskShift
MACOS_CGFLAG_CONTROL = 0x00040000    # kCGEventFlagMaskControl
MACOS_CGFLAG_ALT = 0x00080000        # kCGEventFlagMaskAlternate


_kCGEventSourceStateHIDSystemState = 1
_kCGHIDEventTap = 0

_macos_cgevent_init_attempted = False
_macos_app_services = None
_macos_core_foundation = None
_init_lock = threading.Lock()


def _init_macos_cgevent() -> bool:
    """Load ApplicationServices and CoreFoundation for CGEvent; return True if ready."""
    global _macos_cgevent_init_attempted, _macos_app_services, _macos_core_foundation
    if sys.platform != "darwin":
        return False
    with _init_lock:
        if _macos_cgevent_init_attempted:
            return _macos_app_services is not None
        try:
            import ctypes
            import ctypes.util

            _macos_core_foundation = ctypes.cdll.LoadLibrary(
                ctypes.util.find_library("CoreFoundation")
            )
            if _macos_core_foundation is None:
                jukebox_logger.warning("macOS CGEvent: Could not load CoreFoundation")
                _macos_cgevent_init_attempted = True
                return False

            _macos_app_services = ctypes.cdll.LoadLibrary(
                ctypes.util.find_library("ApplicationServices")
            )
            if _macos_app_services is None:
                jukebox_logger.warning("macOS CGEvent: Could not load ApplicationServices")
                _macos_core_foundation = None
                _macos_cgevent_init_attempted = True
                return False

            # CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
            _macos_app_services.CGEventSourceCreate.restype = ctypes.c_void_p
            _macos_app_services.CGEventSourceCreate.argtypes = [ctypes.c_int32]

            # CGEventCreateKeyboardEvent(source, keycode, keydown)
            _macos_app_services.CGEventCreateKeyboardEvent.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint16,
                ctypes.c_uint8,
            ]
            _macos_app_services.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p

            # CGEventSetFlags(event, flags)
            _macos_app_services.CGEventSetFlags.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint64,
            ]
            _macos_app_services.CGEventSetFlags.restype = None

            # CGEventPost(tap, event)
            _macos_app_services.CGEventPost.argtypes = [
                ctypes.c_uint32,
                ctypes.c_void_p,
            ]
            _macos_app_services.CGEventPost.restype = ctypes.c_int32

            # CFRelease(object)
            _macos_core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
            _macos_core_foundation.CFRelease.restype = None

            _macos_cgevent_init_attempted = True
            return True
        except Exception as e:
            jukebox_logger.warning(f"macOS CGEvent init failed: {e}")
            _macos_cgevent_init_attempted = True
            _macos_core_foundation = None
            return False

def get_macos_vk_for_key(base_key: Any) -> Optional[int]:
    """Return macOS virtual key code for a key used by KeyMapper (single char or Key-like). None if not on Darwin or unknown."""
    if not _MACOS_VK:
        return None
    if hasattr(base_key, "name"):
        n = base_key.name
    elif isinstance(base_key, Key) and hasattr(base_key, "value") and isinstance(base_key.value, KeyCode):
        n = base_key.value.char or base_key.value.vk
    else:
        n = base_key
    if isinstance(n, int):
        # n is already a macOS VK code from pynput KeyCode.vk
        return n
    if not isinstance(n, str):
        return None
    n = n.lower()
    vk = _MACOS_VK.get(n)
    return vk if vk is not None else _MACOS_VK.get("control" if n == "ctrl" else n)


def get_macos_vk_for_modifier(mod_key: Any) -> Optional[int]:
    """Return macOS VK for a modifier (Key.shift -> 0x38, etc.). None if not Darwin or unknown."""
    if not _MACOS_VK:
        return None
    if hasattr(mod_key, "name"):
        n = mod_key.name
    elif isinstance(mod_key, Key) and hasattr(mod_key, "value") and isinstance(mod_key.value, KeyCode):
        n = mod_key.value.char or mod_key.value.vk
    else:
        n = mod_key
    if isinstance(n, int):
        # n is already a macOS VK code from pynput KeyCode.vk
        return n
    if not isinstance(n, str):
        return None
    n = n.lower()
    vk = _MACOS_VK.get(n)
    return vk if vk is not None else (_MACOS_VK.get("control") if n == "ctrl" else None)

def post_macos_key_event(key_code: int, key_down: bool, flags: int = 0) -> bool:
    """Post a single keyboard event via CGEvent on macOS. Returns True on success. No-op on non-Darwin."""
    if sys.platform != "darwin":
        return False
    if (
        not _init_macos_cgevent()
        or _macos_app_services is None
        or _macos_core_foundation is None
    ):
        return False
    source: Optional[int] = None
    event: Optional[int] = None
    try:
        source = _macos_app_services.CGEventSourceCreate(
            _kCGEventSourceStateHIDSystemState
        )
        if not source:
            return False
        event = _macos_app_services.CGEventCreateKeyboardEvent(
            source, key_code, 1 if key_down else 0
        )
        if not event:
            return False
        _macos_app_services.CGEventSetFlags(event, flags)
        result = _macos_app_services.CGEventPost(_kCGHIDEventTap, event)
        return result == 0
    except Exception as e:
        jukebox_logger.debug(f"post_macos_key_event failed: {e}")
        return False
    finally:
        if event:
            try:
                _macos_core_foundation.CFRelease(event)
            except Exception:
                pass
        if source:
            try:
                _macos_core_foundation.CFRelease(source)
            except Exception:
                pass
