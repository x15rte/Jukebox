"""Roblox MIDI Connect protocol encoder.

Encodes MIDI note/velocity/pedal into sequences of numpad key presses.
Protocol: *multiply* prefix, then 4 base-12 digits via numpad keys.

The encoding tables, VK codes, and protocol constants below are defined by
the game client and **must not** be changed.
"""

import math
import threading
import time
import platform
import ctypes
from typing import Tuple

import sys
from logger_core import jukebox_logger

_batch_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Game-defined protocol constants  (DO NOT MODIFY)
# ---------------------------------------------------------------------------

ENCODED_KEYS = [
    "numpad0",
    "numpad1",
    "numpad2",
    "numpad3",
    "numpad4",
    "numpad5",
    "numpad6",
    "numpad7",
    "numpad8",
    "numpad9",
    "subtract",
    "add",
]

PEDAL_SENTINEL = 143

# Numpad scan codes (hardware level, matching original RMC project)
_SCAN_CODES = {
    "multiply": 0x37,
    "numpad0": 0x52,
    "numpad1": 0x4F,
    "numpad2": 0x50,
    "numpad3": 0x51,
    "numpad4": 0x4B,
    "numpad5": 0x4C,
    "numpad6": 0x4D,
    "numpad7": 0x47,
    "numpad8": 0x48,
    "numpad9": 0x49,
    "subtract": 0x4A,
    "add": 0x4E,
}

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_platform = platform.system()
if _platform == "Darwin":
    from native import post_macos_key_event as _pmke
else:
    _pmke = None
_numlock_ensured = False
_numlock_lock = threading.Lock()


def reset_batched_sendinput() -> None:
    """Re-enable batched SendInput if it was disabled due to a prior failure.

    Call this between playback sessions so a one-off SendInput failure does not
    permanently degrade to per-key fallback.
    """
    global _use_batched_sendinput
    with _batch_lock:
        if _platform == "Windows" and _use_pydirectinput and not _use_batched_sendinput:
            _use_batched_sendinput = True



# ---------------------------------------------------------------------------
# Batched SendInput (scan codes) — sends one full RMC frame in 1 kernel call
# Falls back to pydirectinput per-key on Windows.
# ---------------------------------------------------------------------------

_KEYEVENTF_SCANCODE = 0x0008
_KEYEVENTF_KEYUP = 0x0002
_INPUT_KEYBOARD = 1

_use_batched_sendinput = False
_use_pydirectinput = False


def _get_windll():
    return getattr(ctypes, "windll", None)


def is_using_pydirectinput() -> bool:
    """Return True if pydirectinput is available and in use for numpad input."""
    return _use_pydirectinput


def is_using_pynput() -> bool:
    """Return True if pynput is available for non-Windows numpad output."""
    return _keyboard is not None and all(
        name in _precomputed_keys for name in ("multiply", *ENCODED_KEYS)
    )


if _platform == "Windows":
    try:
        import pydirectinput

        pydirectinput.PAUSE = 0
        for _name, _sc in _SCAN_CODES.items():
            pydirectinput.KEYBOARD_MAPPING[_name] = _sc
        _use_pydirectinput = True

        # Pre-allocate a reusable INPUT array for 5 key taps (10 events)
        # Uses pydirectinput's own ctypes structures for binary compatibility
        _frame_inputs = (pydirectinput.Input * 10)()
        _frame_extra = ctypes.c_ulong(0)
        _frame_extra_ptr = ctypes.pointer(_frame_extra)
        for _i in range(10):
            _frame_inputs[_i].type = ctypes.c_ulong(_INPUT_KEYBOARD)
            _frame_inputs[_i].ii.ki.wVk = 0
            _frame_inputs[_i].ii.ki.time = 0
            _frame_inputs[_i].ii.ki.dwExtraInfo = _frame_extra_ptr
        for _i in range(5):
            _frame_inputs[_i * 2].ii.ki.dwFlags = _KEYEVENTF_SCANCODE
            _frame_inputs[_i * 2 + 1].ii.ki.dwFlags = (
                _KEYEVENTF_SCANCODE | _KEYEVENTF_KEYUP
            )
        _frame_sizeof = ctypes.sizeof(pydirectinput.Input)
        _use_batched_sendinput = True
    except Exception:
        _use_pydirectinput = False

if _platform != "Windows":
    pydirectinput = None  # type: ignore[assignment]

# pynput transport for Linux/other non-Windows, non-macOS platforms.
_kb = None
_keyboard = None
_precomputed_keys: dict = {}

if _platform not in ("Windows", "Darwin"):
    try:
        from pynput import keyboard as _kb_mod

        _kb = _kb_mod
        _keyboard = _kb.Controller()
    except ImportError:
        pass

VK_CODES = {
    "Windows": {
        "numpad0": 0x60,
        "numpad1": 0x61,
        "numpad2": 0x62,
        "numpad3": 0x63,
        "numpad4": 0x64,
        "numpad5": 0x65,
        "numpad6": 0x66,
        "numpad7": 0x67,
        "numpad8": 0x68,
        "numpad9": 0x69,
        "subtract": 0x6D,
        "add": 0x6B,
        "multiply": 0x6A,
    },
    "Linux": {
        "numpad0": 0xFFB0,
        "numpad1": 0xFFB1,
        "numpad2": 0xFFB2,
        "numpad3": 0xFFB3,
        "numpad4": 0xFFB4,
        "numpad5": 0xFFB5,
        "numpad6": 0xFFB6,
        "numpad7": 0xFFB7,
        "numpad8": 0xFFB8,
        "numpad9": 0xFFB9,
        "subtract": 0xFFAD,
        "add": 0xFFAB,
        "multiply": 0xFFAA,
    },
    "Darwin": {
        "numpad0": 0x52,
        "numpad1": 0x53,
        "numpad2": 0x54,
        "numpad3": 0x55,
        "numpad4": 0x56,
        "numpad5": 0x57,
        "numpad6": 0x58,
        "numpad7": 0x59,
        "numpad8": 0x5B,
        "numpad9": 0x5C,
        "subtract": 0x4E,
        "add": 0x45,
        "multiply": 0x43,
    },
}
_platform_map = VK_CODES.get(_platform, {})
if _kb is not None:
    _precomputed_keys = {
        name: _kb.KeyCode.from_vk(vk) for name, vk in _platform_map.items()
    }

# Scan code lookup table for fast path
_ENCODED_SCAN = [_SCAN_CODES[k] for k in ENCODED_KEYS]
_MULTIPLY_SCAN = _SCAN_CODES["multiply"]


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def ensure_numlock_on() -> None:
    """Activate NumLock once per session (Windows only)."""
    global _numlock_ensured
    if _numlock_ensured:
        return
    with _numlock_lock:
        if _numlock_ensured:
            return
        if _platform != "Windows":
            return
        try:
            windll = _get_windll()
            if windll is None or windll.user32.GetKeyState(0x90) & 1:
                _numlock_ensured = True
                return
            if _use_pydirectinput:
                try:
                    pydirectinput.keyDown("numlock", _pause=False)  # type: ignore[reportPossiblyUnboundVariable]
                    pydirectinput.keyUp("numlock", _pause=False)  # type: ignore[reportPossiblyUnboundVariable]
                    _numlock_ensured = True
                except Exception as e:
                    jukebox_logger.warning(f"Failed to ensure NumLock state: {e}")
        except Exception as e:
            jukebox_logger.debug(f"Failed to ensure NumLock state: {e}")  # debug is appropriate — best-effort

def _tap_key(name: str) -> None:
    """Press and release a single numpad key with the platform transport."""
    if _platform == "Windows":
        if not _use_pydirectinput:
            jukebox_logger.warning(
                f"pydirectinput is unavailable; cannot send numpad key '{name}'."
            )
            return
        try:
            pydirectinput.keyDown(name, _pause=False)  # type: ignore[reportPossiblyUnboundVariable]
        except Exception as e:
            jukebox_logger.warning(f"pydirectinput key send failed for '{name}': {e}", exc_info=True)
            return
        try:
            pydirectinput.keyUp(name, _pause=False)  # type: ignore[reportPossiblyUnboundVariable]
        except Exception as e:
            jukebox_logger.warning(f"pydirectinput keyUp failed for '{name}': {e}", exc_info=True)
        return

    if _platform == "Darwin":
        vk = _platform_map.get(name)
        if vk is not None and _pmke is not None:
            try:
                if not _pmke(vk, True, 0):
                    jukebox_logger.warning(f"macOS CGEvent keyDown failed for '{name}'")
                if not _pmke(vk, False, 0):
                    jukebox_logger.warning(f"macOS CGEvent keyUp failed for '{name}'")
            except Exception as e:
                jukebox_logger.warning(
                    f"macOS CGEvent key send failed for '{name}': {e}",
                    exc_info=True,
                )
        return

    kc = _precomputed_keys.get(name)
    if kc is None:
        jukebox_logger.warning(f"Cannot send key '{name}': key not found in precomputed mappings")
        return
    kb = _keyboard
    if kb is None:
        jukebox_logger.warning(f"Cannot send key '{name}': pynput keyboard controller not available")
        return
    try:
        kb.press(kc)
        kb.release(kc)
    except Exception as e:
        jukebox_logger.warning(
            f"pynput key send failed for '{name}': {e}",
            exc_info=True,
        )


def _send_key_up(scancode: int) -> None:
    """Send a single KEYUP INPUT event via SendInput."""
    if _platform != "Windows" or not _use_pydirectinput:
        return
    windll = _get_windll()
    if windll is None:
        return
    up = (pydirectinput.Input * 1)()  # type: ignore[union-attr]
    up[0].type = ctypes.c_ulong(_INPUT_KEYBOARD)
    up[0].ii.ki.wVk = 0
    up[0].ii.ki.wScan = scancode
    up[0].ii.ki.dwFlags = _KEYEVENTF_SCANCODE | _KEYEVENTF_KEYUP
    up[0].ii.ki.time = 0
    sent = windll.user32.SendInput(1, up, ctypes.sizeof(pydirectinput.Input))  # type: ignore[union-attr]
    if sent != 1:
        jukebox_logger.warning(f"SendInput KEYUP for scancode {scancode:#x} returned {sent}")

def _send_key_down(scancode: int) -> None:
    """Send a single KEYDOWN INPUT event via SendInput."""
    if _platform != "Windows" or not _use_pydirectinput:
        return
    windll = _get_windll()
    if windll is None:
        return
    down = (pydirectinput.Input * 1)()  # type: ignore[union-attr]
    down[0].type = ctypes.c_ulong(_INPUT_KEYBOARD)
    down[0].ii.ki.wVk = 0
    down[0].ii.ki.wScan = scancode
    down[0].ii.ki.dwFlags = _KEYEVENTF_SCANCODE
    down[0].ii.ki.time = 0
    sent = windll.user32.SendInput(1, down, ctypes.sizeof(pydirectinput.Input))  # type: ignore[union-attr]
    if sent != 1:
        jukebox_logger.warning(f"SendInput KEYDOWN for scancode {scancode:#x} returned {sent}")


def _send_frame_batched(sc0, sc1, sc2, sc3, sc4) -> bool:
    """Send 5 key taps as 10 INPUT events in a single SendInput call."""
    if not _use_batched_sendinput:
        return False
    windll = _get_windll()
    if windll is None:
        return False
    _frame_inputs[0].ii.ki.wScan = sc0
    _frame_inputs[0].ii.ki.dwFlags = _KEYEVENTF_SCANCODE
    _frame_inputs[1].ii.ki.wScan = sc0
    _frame_inputs[1].ii.ki.dwFlags = _KEYEVENTF_SCANCODE | _KEYEVENTF_KEYUP
    _frame_inputs[2].ii.ki.wScan = sc1
    _frame_inputs[2].ii.ki.dwFlags = _KEYEVENTF_SCANCODE
    _frame_inputs[3].ii.ki.wScan = sc1
    _frame_inputs[3].ii.ki.dwFlags = _KEYEVENTF_SCANCODE | _KEYEVENTF_KEYUP
    _frame_inputs[4].ii.ki.wScan = sc2
    _frame_inputs[4].ii.ki.dwFlags = _KEYEVENTF_SCANCODE
    _frame_inputs[5].ii.ki.wScan = sc2
    _frame_inputs[5].ii.ki.dwFlags = _KEYEVENTF_SCANCODE | _KEYEVENTF_KEYUP
    _frame_inputs[6].ii.ki.wScan = sc3
    _frame_inputs[6].ii.ki.dwFlags = _KEYEVENTF_SCANCODE
    _frame_inputs[7].ii.ki.wScan = sc3
    _frame_inputs[7].ii.ki.dwFlags = _KEYEVENTF_SCANCODE | _KEYEVENTF_KEYUP
    _frame_inputs[8].ii.ki.wScan = sc4
    _frame_inputs[8].ii.ki.dwFlags = _KEYEVENTF_SCANCODE
    _frame_inputs[9].ii.ki.wScan = sc4
    _frame_inputs[9].ii.ki.dwFlags = _KEYEVENTF_SCANCODE | _KEYEVENTF_KEYUP
    result = windll.user32.SendInput(10, _frame_inputs, _frame_sizeof)
    if result == 10:
        return True
    if result > 0:
        scs = [sc0, sc1, sc2, sc3, sc4]
        fully_sent = result // 2
        if result % 2 == 1:  # KEYDOWN sent but KEYUP not sent for this key
            _send_key_up(scs[fully_sent])
            fully_sent += 1
        for i in range(fully_sent, 5):
            _send_key_down(scs[i])
            _send_key_up(scs[i])
        return True  # handled partial success
    return False


# ---------------------------------------------------------------------------
# Protocol message encoding / sending
# ---------------------------------------------------------------------------


def encode_and_send_message(
    a: int, b: int, c: int, d: int, inter_key_delay: float = 0
) -> None:
    """Send one RMC protocol frame: multiply prefix followed by 4 encoded digits."""
    global _use_batched_sendinput
    with _batch_lock:
        ensure_numlock_on()
        if _use_batched_sendinput and inter_key_delay <= 0:
            ok = _send_frame_batched(
                _MULTIPLY_SCAN,
                _ENCODED_SCAN[max(0, min(11, a))],
                _ENCODED_SCAN[max(0, min(11, b))],
                _ENCODED_SCAN[max(0, min(11, c))],
                _ENCODED_SCAN[max(0, min(11, d))],
            )
            if ok:
                return
        _tap_key("multiply")
        for val in (a, b, c, d):
            if inter_key_delay > 0:
                time.sleep(inter_key_delay)
            _tap_key(ENCODED_KEYS[max(0, min(11, val))])



def _encode_note_components(
    note: int, velocity: int, is_note_off: bool
) -> Tuple[int, int, int, int]:
    """Encode note + velocity into four base-12 values."""
    note = max(0, min(127, note))
    octave = math.floor(note / 12)
    note_in_octave = math.floor(note % 12)
    if is_note_off:
        return octave, note_in_octave, 0, 0
    velocity = max(0, min(127, velocity))
    return octave, note_in_octave, math.floor(velocity / 12), math.floor(velocity % 12)


def send_note_message(note: int, velocity: int, is_note_off: bool) -> None:
    """Encode a note event and send it as a single RMC message."""
    a, b, c, d = _encode_note_components(note, velocity, is_note_off)
    encode_and_send_message(a, b, c, d)


def send_pedal(value: int) -> None:
    """Encode a sustain pedal value (CC 64) and send it as a single RMC message."""
    value = max(0, min(127, value))
    a = math.floor(PEDAL_SENTINEL / 12)
    b = math.floor(PEDAL_SENTINEL % 12)
    c = math.floor(value / 12)
    d = math.floor(value % 12)
    encode_and_send_message(a, b, c, d)

