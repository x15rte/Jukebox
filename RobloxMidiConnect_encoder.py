import math
import platform
import ctypes
from typing import Tuple

from pynput import keyboard as kb


keyboard = kb.Controller()
encoded_keys = [
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


vk_keycodes = {
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

CURRENT_PLATFORM = platform.system()
_numlock_checked = False


def _is_numlock_on_windows() -> bool:
    state = ctypes.windll.user32.GetKeyState(0x90)
    return bool(state & 1)


def ensure_numlock_on() -> None:
    global _numlock_checked
    if _numlock_checked:
        return
    _numlock_checked = True

    if CURRENT_PLATFORM != "Windows":
        return

    try:
        if not _is_numlock_on_windows():
            keyboard.tap(kb.Key.num_lock)
    except Exception:
        pass


def _send_key(numpad_key_name: str) -> None:
    platform_map = vk_keycodes.get(CURRENT_PLATFORM)
    if not platform_map:
        return
    vk_code = platform_map.get(numpad_key_name)
    if vk_code is None:
        return
    try:
        keyboard.tap(kb.KeyCode.from_vk(vk_code))
    except Exception:
        pass


def encode_and_send_message(a: int, b: int, c: int, d: int) -> None:
    ensure_numlock_on()

    _send_key("multiply")

    for value in (a, b, c, d):
        if not (0 <= value < 12):
            value = max(0, min(11, value))
        key_name = encoded_keys[value]
        _send_key(key_name)


def _encode_note_components(note: int, velocity: int, is_note_off: bool) -> Tuple[int, int, int, int]:
    octave_no = math.floor(note / 12)
    note_no = math.floor(note % 12)

    if is_note_off:
        v1 = 0
        v2 = 0
    else:
        velocity = max(0, min(127, velocity))
        v1 = math.floor(velocity / 12)
        v2 = math.floor(velocity % 12)

    return octave_no, note_no, v1, v2


def send_note_message(note: int, velocity: int, is_note_off: bool) -> None:
    a, b, c, d = _encode_note_components(note, velocity, is_note_off)
    encode_and_send_message(a, b, c, d)


PEDAL_SENTINEL = 143


def send_pedal(value: int) -> None:
    value = max(0, min(127, value))
    control = PEDAL_SENTINEL
    a = math.floor(control / 12)
    b = math.floor(control % 12)
    c = math.floor(value / 12)
    d = math.floor(value % 12)
    encode_and_send_message(a, b, c, d)


def process_mido_message(msg) -> None:
    msg_type = getattr(msg, "type", None)
    if msg_type == "clock":
        return

    if msg_type in ("note_on", "note_off"):
        note = getattr(msg, "note", None)
        velocity = getattr(msg, "velocity", 0)
        if note is None:
            return

        is_off = msg_type == "note_off" or (msg_type == "note_on" and velocity == 0)
        send_note_message(note, velocity, is_off)
        return

    if msg_type == "control_change":
        control = getattr(msg, "control", None)
        value = getattr(msg, "value", 0)
        if control == 64:
            send_pedal(value)

