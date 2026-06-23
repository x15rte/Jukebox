"""Unified output backends for Roblox piano playback.

Two concrete backends share the same interface:
  * **KeyboardBackend** — emits keyboard presses (for direct keyboard mode).
    On macOS (Darwin) uses CGEvent for layout-independent key codes when available.
    On Windows uses pydirectinput with explicit scan codes.
  * **NumpadBackend** — emits RMC numpad protocol messages.
"""

import ctypes
import sys
import time
import traceback
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from pynput.keyboard import Key, KeyCode, Controller

from models import KeyState
from core import KeyMapper
from . import RobloxMidiConnect_encoder as rmc
from logger_core import jukebox_logger
from native import (
    get_macos_vk_for_key,
    get_macos_vk_for_modifier,
    post_macos_key_event,
    MACOS_CGFLAG_SHIFT,
    MACOS_CGFLAG_CONTROL,
    MACOS_CGFLAG_ALT,
)


class OutputBackendError(RuntimeError):
    """Base class for output backend failures that should be visible to users."""


class OutputBackendUnavailableError(OutputBackendError):
    """Raised when an output backend cannot be initialized on this platform."""


class OutputBackendSendError(OutputBackendError):
    """Raised when an output backend fails while sending input."""


_KEYEVENTF_SCANCODE = 0x0008
_KEYEVENTF_KEYUP = 0x0002
_INPUT_KEYBOARD = 1

_WINDOWS_KEY_SCAN_CODES: Dict[str, int] = {
    "1": 0x02,
    "2": 0x03,
    "3": 0x04,
    "4": 0x05,
    "5": 0x06,
    "6": 0x07,
    "7": 0x08,
    "8": 0x09,
    "9": 0x0A,
    "0": 0x0B,
    "q": 0x10,
    "w": 0x11,
    "e": 0x12,
    "r": 0x13,
    "t": 0x14,
    "y": 0x15,
    "u": 0x16,
    "i": 0x17,
    "o": 0x18,
    "p": 0x19,
    "a": 0x1E,
    "s": 0x1F,
    "d": 0x20,
    "f": 0x21,
    "g": 0x22,
    "h": 0x23,
    "j": 0x24,
    "k": 0x25,
    "l": 0x26,
    "z": 0x2C,
    "x": 0x2D,
    "c": 0x2E,
    "v": 0x2F,
    "b": 0x30,
    "n": 0x31,
    "m": 0x32,
    "space": 0x39,
    "shiftleft": 0x2A,
    "ctrlleft": 0x1D,
    "altleft": 0x38,
}


def _get_windll() -> Any:
    return getattr(ctypes, "windll", None)


class _WindowsPydirectInputTransport:
    """Windows KEY-mode transport using batched scan-code SendInput calls."""

    def __init__(self) -> None:
        try:
            import pydirectinput as pdi_mod
        except Exception as exc:
            raise OutputBackendUnavailableError(
                "Windows KEY mode requires pydirectinput. Install the Windows "
                "requirements and restart Jukebox."
            ) from exc

        try:
            pdi_mod.PAUSE = 0
            pdi_mod.FAILSAFE = False
            mapping = pdi_mod.KEYBOARD_MAPPING
            for key_name, scan_code in _WINDOWS_KEY_SCAN_CODES.items():
                mapping[key_name] = scan_code
        except Exception as exc:
            raise OutputBackendUnavailableError(
                "Windows KEY mode could not configure pydirectinput scan-code mapping."
            ) from exc

        try:
            self._input_type = pdi_mod.Input
            self._input_sizeof = ctypes.sizeof(self._input_type)
            self._capacity = max(1, len(_WINDOWS_KEY_SCAN_CODES))
            self._inputs = (self._input_type * self._capacity)()
            self._extra = ctypes.c_ulong(0)
            self._extra_ptr = ctypes.pointer(self._extra)
            for i in range(self._capacity):
                self._inputs[i].type = ctypes.c_ulong(_INPUT_KEYBOARD)
                self._inputs[i].ii.ki.wVk = 0
                self._inputs[i].ii.ki.wScan = 0
                self._inputs[i].ii.ki.dwFlags = _KEYEVENTF_SCANCODE
                self._inputs[i].ii.ki.time = 0
                self._inputs[i].ii.ki.dwExtraInfo = self._extra_ptr

            windll = _get_windll()
            if windll is None:
                raise AttributeError("ctypes.windll.user32.SendInput is unavailable")
            self._send_input = windll.user32.SendInput
        except Exception as exc:
            raise OutputBackendUnavailableError(
                "Windows KEY mode could not initialize SendInput scan-code transport."
            ) from exc

        self._pdi = pdi_mod

    @property
    def pydirectinput(self) -> Any:
        return self._pdi

    def key_down(self, key_name: str) -> None:
        self.send_batch([(key_name, True)])

    def key_up(self, key_name: str) -> None:
        self.send_batch([(key_name, False)])

    def send_batch(self, actions: List[Tuple[str, bool]]) -> None:
        for key_name, _is_down in actions:
            if key_name not in _WINDOWS_KEY_SCAN_CODES:
                raise OutputBackendSendError(
                    f"Windows KEY mode has no scan code registered for '{key_name}'."
                )

        for start in range(0, len(actions), self._capacity):
            self._send_chunk(actions[start : start + self._capacity])

    def _send_chunk(self, actions: List[Tuple[str, bool]]) -> None:
        for i, (key_name, is_down) in enumerate(actions):
            scan_code = _WINDOWS_KEY_SCAN_CODES[key_name]
            key_input = self._inputs[i].ii.ki
            key_input.wScan = scan_code
            key_input.dwFlags = _KEYEVENTF_SCANCODE
            if not is_down:
                key_input.dwFlags |= _KEYEVENTF_KEYUP

        count = len(actions)
        try:
            sent = self._send_input(count, self._inputs, self._input_sizeof)
        except Exception as exc:
            raise OutputBackendSendError(
                f"Windows KEY mode SendInput failed: {exc}"
            ) from exc
        if sent != count:
            raise OutputBackendSendError(
                f"Windows KEY mode SendInput sent {sent} of {count} input events."
            )


class OutputBackend(ABC):
    """Abstract base for all output backends."""

    @abstractmethod
    def note_on(self, pitch: int, velocity: int) -> None: ...

    @abstractmethod
    def note_off(self, pitch: int) -> None: ...

    @abstractmethod
    def pedal_on(self) -> None: ...

    @abstractmethod
    def pedal_off(self) -> None: ...

    def execute_batch(self, events: List[Any]) -> None:
        """Execute a same-timeslice event batch.

        Default behavior preserves historical ordering semantics.
        """
        pedals = [e for e in events if e.action == "pedal"]
        releases = [e for e in events if e.action == "release"]
        presses = [e for e in events if e.action == "press"]

        for e in pedals:
            if e.key_char == "down":
                self.pedal_on()
            else:
                self.pedal_off()

        for e in releases:
            if e.pitch is not None:
                self.note_off(e.pitch)

        for e in presses:
            if e.pitch is not None:
                self.note_on(e.pitch, e.velocity)

    @abstractmethod
    def shutdown(self) -> None:
        """Release every active note and pedal.  Must be idempotent."""
        ...


# ---------------------------------------------------------------------------
# Keyboard backend
# ---------------------------------------------------------------------------


class KeyboardBackend(OutputBackend):
    """Translates note/pedal events into key output.

    Transport selection:
    - macOS: CGEvent
    - Windows: pydirectinput scan-code transport
    - Linux/other platforms: pynput
    """

    def __init__(
        self,
        use_88_key_layout: bool = False,
        log_message: Optional[Callable[[str], None]] = None,
    ):
        self._mapper = KeyMapper(use_88_key_layout=use_88_key_layout)
        self._states: Dict[str, KeyState] = {}
        self._active_pitches: Dict[str, Set[int]] = {}
        self._pedal_down = False
        self._log = log_message or jukebox_logger.info

        self._kb: Optional[Controller] = None
        self._pdi: Any = None
        self._windows_transport: Optional[_WindowsPydirectInputTransport] = None

        self._use_macos_cgevent = sys.platform == "darwin"
        self._use_pydirectinput = False

        self._macos_modifiers: Tuple[bool, bool, bool] = (False, False, False)
        self._macos_modifier_refcount: Tuple[int, int, int] = (0, 0, 0)

        if not self._use_macos_cgevent and sys.platform == "win32":
            self._windows_transport = _WindowsPydirectInputTransport()
            self._pdi = self._windows_transport.pydirectinput
            self._use_pydirectinput = True
            self._log("KEY mode: using pydirectinput scan-code transport on Windows.")
        elif not self._use_macos_cgevent:
            self._kb = Controller()

    def _macos_flags(self) -> int:
        f = 0
        if self._macos_modifiers[0]:
            f |= MACOS_CGFLAG_SHIFT
        if self._macos_modifiers[1]:
            f |= MACOS_CGFLAG_ALT
        if self._macos_modifiers[2]:
            f |= MACOS_CGFLAG_CONTROL
        return f

    def _state_for(self, key_char: str) -> KeyState:
        if key_char not in self._states:
            self._states[key_char] = KeyState(key_char)
            self._active_pitches[key_char] = set()
        return self._states[key_char]

    def _modifier_name(self, mod) -> Optional[str]:
        name = getattr(mod, "name", None)
        if mod in (Key.shift,) or name in ("shift", "shift_r"):
            return "shiftleft"
        if mod in (Key.ctrl,) or name in ("ctrl", "control", "ctrl_r"):
            return "ctrlleft"
        if mod == Key.alt or name in ("alt", "alt_r"):
            return "altleft"
        return None

    def _pdi_key_down(self, key_name: str) -> None:
        if self._windows_transport is not None:
            self._windows_transport.key_down(key_name)
            return

    def _pdi_key_up(self, key_name: str) -> None:
        if self._windows_transport is not None:
            self._windows_transport.key_up(key_name)
            return

    def _release_key_if_unused(self, base_key: str) -> None:
        if not self._active_pitches.get(base_key):
            state = self._states.get(base_key)
            if state:
                state.release()
            if self._use_pydirectinput and self._pdi is not None:
                self._pdi_key_up(base_key)
            elif self._kb is not None:
                try:
                    self._kb.release(KeyCode.from_vk(ord(base_key)))
                except Exception as e:
                    self._log_exception(
                        "KeyboardBackend _release_key_if_unused error", e
                    )
            self._active_pitches.pop(base_key, None)
            self._states.pop(base_key, None)

    def _log_exception(self, context: str, exc: Exception) -> None:
        self._log(f"{context}: {exc}\n{traceback.format_exc()}")

    def note_on(self, pitch: int, velocity: int) -> None:
        if velocity == 0:
            self.note_off(pitch)
            return
        data = self._mapper.get_key_data(pitch)
        if not data:
            return

        base_key = data["key"]
        modifiers = data["modifiers"]
        was_active = bool(self._active_pitches.get(base_key))

        if self._use_macos_cgevent:
            vk = get_macos_vk_for_key(base_key)
            if vk is None:
                return
            if was_active:
                # Release key first so CGEvent registers a new key-down event
                post_macos_key_event(vk, False, self._macos_flags())
                time.sleep(0.001)
            state = self._state_for(base_key)
            state.press()
            self._active_pitches.setdefault(base_key, set()).add(pitch)
            shift_rc, alt_rc, ctrl_rc = self._macos_modifier_refcount
            for mod in modifiers:
                mod_vk = get_macos_vk_for_modifier(mod)
                if mod_vk is None:
                    continue
                if mod in (Key.shift,) or getattr(mod, "name", None) == "shift":
                    shift_rc += 1
                    if shift_rc == 1:
                        post_macos_key_event(mod_vk, True, self._macos_flags())
                        self._macos_modifiers = (
                            True,
                            self._macos_modifiers[1],
                            self._macos_modifiers[2],
                        )
                elif mod in (Key.ctrl,) or getattr(mod, "name", None) in (
                    "ctrl",
                    "control",
                ):
                    ctrl_rc += 1
                    if ctrl_rc == 1:
                        post_macos_key_event(mod_vk, True, self._macos_flags())
                        self._macos_modifiers = (
                            self._macos_modifiers[0],
                            self._macos_modifiers[1],
                            True,
                        )
                elif mod == Key.alt or getattr(mod, "name", None) == "alt":
                    alt_rc += 1
                    if alt_rc == 1:
                        post_macos_key_event(mod_vk, True, self._macos_flags())
                        self._macos_modifiers = (
                            self._macos_modifiers[0],
                            True,
                            self._macos_modifiers[2],
                        )
            self._macos_modifier_refcount = (shift_rc, alt_rc, ctrl_rc)
            post_macos_key_event(vk, True, self._macos_flags())
            return

        state = self._state_for(base_key)
        state.press()
        self._active_pitches.setdefault(base_key, set()).add(pitch)

        if self._windows_transport is not None:
            if was_active:
                # Release key first so the new key-down event registers.
                # No delay needed — individual SendInput calls are queued in order.
                self._windows_transport.key_up(base_key)
            modifier_names = [
                mod_name
                for mod in modifiers
                if (mod_name := self._modifier_name(mod)) is not None
            ]
            # Send each event separately (press modifiers, press key, release modifiers)
            # so the game's input polling can observe the intermediate modifier-held state.
            for mod_name in modifier_names:
                self._windows_transport.send_batch([(mod_name, True)])
            self._windows_transport.send_batch([(base_key, True)])
            for mod_name in reversed(modifier_names):
                self._windows_transport.send_batch([(mod_name, False)])
            return


        try:
            if self._kb is not None:
                if was_active:
                    # Release key first so OS/pynput registers a new key-down event
                    self._kb.release(KeyCode.from_vk(ord(base_key)))
                    time.sleep(0.001)
                with self._kb.pressed(*modifiers):
                    self._kb.press(KeyCode.from_vk(ord(base_key)))
        except Exception as e:
            self._log_exception("KeyboardBackend note_on error", e)

    def note_off(self, pitch: int) -> None:
        data = self._mapper.get_key_data(pitch)
        if not data:
            return

        base_key = data["key"]
        modifiers = data["modifiers"]

        active = self._active_pitches.get(base_key)
        if active:
            active.discard(pitch)

        if self._use_macos_cgevent:
            shift_rc, alt_rc, ctrl_rc = self._macos_modifier_refcount
            for mod in modifiers:
                mod_vk = get_macos_vk_for_modifier(mod)
                if mod_vk is None:
                    continue
                if mod in (Key.shift,) or getattr(mod, "name", None) == "shift":
                    shift_rc = max(0, shift_rc - 1)
                    if shift_rc == 0 and self._macos_modifiers[0]:
                        self._macos_modifiers = (
                            False,
                            self._macos_modifiers[1],
                            self._macos_modifiers[2],
                        )
                        post_macos_key_event(mod_vk, False, self._macos_flags())
                elif mod in (Key.ctrl,) or getattr(mod, "name", None) in (
                    "ctrl",
                    "control",
                ):
                    ctrl_rc = max(0, ctrl_rc - 1)
                    if ctrl_rc == 0 and self._macos_modifiers[2]:
                        self._macos_modifiers = (
                            self._macos_modifiers[0],
                            self._macos_modifiers[1],
                            False,
                        )
                        post_macos_key_event(mod_vk, False, self._macos_flags())
                elif mod == Key.alt or getattr(mod, "name", None) == "alt":
                    alt_rc = max(0, alt_rc - 1)
                    if alt_rc == 0 and self._macos_modifiers[1]:
                        self._macos_modifiers = (
                            self._macos_modifiers[0],
                            False,
                            self._macos_modifiers[2],
                        )
                        post_macos_key_event(mod_vk, False, self._macos_flags())
            self._macos_modifier_refcount = (shift_rc, alt_rc, ctrl_rc)

            if not self._active_pitches.get(base_key):
                state = self._states.get(base_key)
                vk = get_macos_vk_for_key(base_key)
                if state:
                    state.release()
                if vk is not None:
                    post_macos_key_event(vk, False, self._macos_flags())
                self._active_pitches.pop(base_key, None)
                self._states.pop(base_key, None)
            return

        self._release_key_if_unused(base_key)

    def pedal_on(self) -> None:
        if self._pedal_down:
            return
        self._pedal_down = True

        if self._use_macos_cgevent:
            space_vk = get_macos_vk_for_key(Key.space)
            if space_vk is not None and post_macos_key_event(space_vk, True, 0):
                return

        try:
            if self._use_pydirectinput and self._pdi is not None:
                self._pdi_key_down("space")
            elif self._kb is not None:
                self._kb.press(Key.space)
        except Exception as e:
            if self._use_pydirectinput:
                raise
            self._log_exception("KeyboardBackend pedal_on error", e)

    def pedal_off(self) -> None:
        if not self._pedal_down:
            return
        self._pedal_down = False

        for key_char in list(self._active_pitches.keys()):
            if not self._active_pitches[key_char]:
                if self._use_macos_cgevent:
                    state = self._states.get(key_char)
                    if state:
                        state.release()
                    vk = get_macos_vk_for_key(key_char)
                    if vk is not None:
                        post_macos_key_event(vk, False, 0)
                    self._active_pitches.pop(key_char, None)
                    self._states.pop(key_char, None)
                else:
                    self._release_key_if_unused(key_char)

        if self._use_macos_cgevent:
            space_vk = get_macos_vk_for_key(Key.space)
            if space_vk is not None and post_macos_key_event(space_vk, False, 0):
                return

        try:
            if self._use_pydirectinput and self._pdi is not None:
                self._pdi_key_up("space")
            elif self._kb is not None:
                self._kb.release(Key.space)
        except Exception as e:
            if self._use_pydirectinput:
                raise
            self._log_exception("KeyboardBackend pedal_off error", e)

    def execute_batch(self, events: List[Any]) -> None:
        if not events:
            return

        if self._windows_transport is not None:
            pedals = [e for e in events if e.action == "pedal"]
            releases = [e for e in events if e.action == "release"]
            presses = [e for e in events if e.action == "press"]

            for e in pedals:
                if e.key_char == "down":
                    self.pedal_on()
                else:
                    self.pedal_off()

            for e in releases:
                if e.pitch is not None:
                    self.note_off(e.pitch)

            # No batch-level delay needed — each note_on/note_off sends individual
            # SendInput calls, so the OS input queue guarantees correct ordering.

            for e in presses:
                if e.pitch is not None:
                    self.note_on(e.pitch, e.velocity)
            return

        super().execute_batch(events)

    def shutdown(self) -> None:
        if self._use_macos_cgevent:
            flags = self._macos_flags()
            for key_char in list(self._active_pitches.keys()):
                vk = get_macos_vk_for_key(key_char)
                if vk is not None:
                    post_macos_key_event(vk, False, flags)
            self._active_pitches.clear()
            for state in self._states.values():
                state.release()
            if self._pedal_down:
                space_vk = get_macos_vk_for_key(Key.space)
                if space_vk is not None:
                    post_macos_key_event(space_vk, False, 0)
                self._pedal_down = False
            shift_vk = get_macos_vk_for_modifier(Key.shift)
            ctrl_vk = get_macos_vk_for_modifier(Key.ctrl)
            alt_vk = get_macos_vk_for_modifier(Key.alt)
            if self._macos_modifiers[0] and shift_vk is not None:
                post_macos_key_event(shift_vk, False, 0)
            if self._macos_modifiers[1] and alt_vk is not None:
                post_macos_key_event(alt_vk, False, 0)
            if self._macos_modifiers[2] and ctrl_vk is not None:
                post_macos_key_event(ctrl_vk, False, 0)
            self._macos_modifiers = (False, False, False)
            self._macos_modifier_refcount = (0, 0, 0)
            return

        if self._windows_transport is not None:
            batch = [(key_char, False) for key_char in self._active_pitches.keys()]
            if self._pedal_down:
                batch.append(("space", False))
            batch.extend(
                (mod_name, False)
                for mod_name in ("shiftleft", "ctrlleft", "altleft")
            )
            try:
                self._windows_transport.send_batch(batch)
            except Exception as e:
                self._log_exception("KeyboardBackend shutdown release error", e)
            self._active_pitches.clear()
            for state in self._states.values():
                state.release()
            self._pedal_down = False
        else:
            for key_char in list(self._active_pitches.keys()):
                try:
                    if self._use_pydirectinput and self._pdi is not None:
                        self._pdi_key_up(key_char)
                    elif self._kb is not None:
                        self._kb.release(KeyCode.from_vk(ord(key_char)))
                except Exception as e:
                    self._log_exception("KeyboardBackend shutdown note release error", e)

            self._active_pitches.clear()
            for state in self._states.values():
                state.release()

            if self._pedal_down:
                self._pedal_down = False
                try:
                    if self._use_pydirectinput and self._pdi is not None:
                        self._pdi_key_up("space")
                    elif self._kb is not None:
                        self._kb.release(Key.space)
                except Exception as e:
                    self._log_exception(
                        "KeyboardBackend shutdown pedal release error", e
                    )

            if self._use_pydirectinput and self._pdi is not None:
                for mod in ("shiftleft", "ctrlleft", "altleft"):
                    try:
                        self._pdi_key_up(mod)
                    except Exception as e:
                        self._log_exception(
                            "KeyboardBackend shutdown modifier release error", e
                        )
            elif self._kb is not None:
                for mod in (Key.shift, Key.ctrl, Key.alt):
                    try:
                        self._kb.release(mod)
                    except Exception as e:
                        self._log_exception(
                            "KeyboardBackend shutdown modifier release error", e
                        )


# ---------------------------------------------------------------------------
# Numpad (RMC) backend
# ---------------------------------------------------------------------------


class NumpadBackend(OutputBackend):
    """Translates note/pedal events into Roblox MIDI Connect numpad messages."""

    def __init__(
        self,
        inter_message_delay: float = 0.0,
        log_message: Optional[Callable[[str], None]] = None,
    ):
        self._delay = inter_message_delay
        self._active_notes: Set[int] = set()
        self._pedal_down = False
        # Fall back to central logger if no callback is provided.
        self._log = log_message or jukebox_logger.info

    def _post_delay(self):
        if self._delay > 0:
            time.sleep(self._delay)

    def _log_exception(self, context: str, exc: Exception) -> None:
        """Log exception with traceback for easier diagnosis."""
        if self._log is not None:
            self._log(f"{context}: {exc}\n{traceback.format_exc()}")

    # -- notes --

    def note_on(self, pitch: int, velocity: int) -> None:
        if velocity == 0:
            self.note_off(pitch)
            return
        try:
            rmc.send_note_message(pitch, velocity, is_note_off=False)
            self._active_notes.add(pitch)
        except Exception as e:
            self._log_exception("NumpadBackend note_on error", e)
        self._post_delay()

    def note_off(self, pitch: int) -> None:
        try:
            rmc.send_note_message(pitch, velocity=0, is_note_off=True)
            self._active_notes.discard(pitch)
        except Exception as e:
            self._log_exception("NumpadBackend note_off error", e)
        self._post_delay()

    # -- pedal --

    def pedal_on(self) -> None:
        if not self._pedal_down:
            try:
                self._pedal_down = True
                rmc.send_pedal(127)
            except Exception as e:
                self._log_exception("NumpadBackend pedal_on error", e)
            self._post_delay()

    def pedal_off(self) -> None:
        if self._pedal_down:
            try:
                self._pedal_down = False
                rmc.send_pedal(0)
            except Exception as e:
                self._log_exception("NumpadBackend pedal_off error", e)
            self._post_delay()

    # -- shutdown --

    def shutdown(self) -> None:
        for pitch in list(self._active_notes):
            try:
                rmc.send_note_message(pitch, velocity=0, is_note_off=True)
            except Exception as e:
                self._log_exception("NumpadBackend shutdown note release error", e)
            self._post_delay()
        self._active_notes.clear()

        if self._pedal_down:
            try:
                self._pedal_down = False
                rmc.send_pedal(0)
            except Exception as e:
                self._log_exception("NumpadBackend shutdown pedal release error", e)
            self._post_delay()

        rmc.reset_batched_sendinput()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_backend(
    output_mode: str,
    use_88_key_layout: bool = False,
    inter_message_delay: float = 0.0,
    log_message: Optional[Callable[[str], None]] = None,
) -> OutputBackend:
    """Return the appropriate backend for *output_mode* (``'key'`` or ``'midi_numpad'``)."""
    effective_log = log_message or jukebox_logger.info
    if output_mode == "midi_numpad":
        if sys.platform == "win32" and not rmc.is_using_pydirectinput():
            raise OutputBackendUnavailableError(
                "Windows MIDI Numpad mode requires pydirectinput. Install the "
                "Windows requirements and restart Jukebox."
            )
        if sys.platform.startswith("linux") and not rmc.is_using_pynput():
            raise OutputBackendUnavailableError(
                "Linux MIDI Numpad mode requires pynput. Install the runtime "
                "requirements and restart Jukebox."
            )
        return NumpadBackend(
            inter_message_delay=inter_message_delay, log_message=effective_log
        )
    return KeyboardBackend(
        use_88_key_layout=use_88_key_layout,
        log_message=effective_log,
    )
