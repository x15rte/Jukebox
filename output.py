"""Unified output backends for Roblox piano playback.

Two concrete backends share the same interface:
  * **KeyboardBackend** — emits pynput key presses (for direct keyboard mode).
    On macOS (Darwin) uses CGEvent for layout-independent key codes when available.
  * **NumpadBackend** — emits RMC numpad protocol messages.
"""

import sys
import time
import traceback
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional, Set, Tuple

from pynput.keyboard import Key, Controller

from models import KeyState
from core import KeyMapper
import RobloxMidiConnect_encoder as rmc
from logger_core import jukebox_logger
from platform_utils import (
    get_macos_vk_for_key,
    get_macos_vk_for_modifier,
    post_macos_key_event,
    MACOS_CGFLAG_SHIFT,
    MACOS_CGFLAG_CONTROL,
    MACOS_CGFLAG_ALT,
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

    @abstractmethod
    def shutdown(self) -> None:
        """Release every active note and pedal.  Must be idempotent."""
        ...


# ---------------------------------------------------------------------------
# Keyboard backend
# ---------------------------------------------------------------------------

class KeyboardBackend(OutputBackend):
    """Translates note/pedal events into pynput keyboard actions.
    On macOS, uses CGEvent when the "Use pynput (Mac)" option is unchecked; otherwise pynput.
    """

    def __init__(self, use_88_key_layout: bool = False,
                 macos_use_pynput: bool = False,
                 log_message: Optional[Callable[[str], None]] = None):
        self._kb = Controller()
        self._mapper = KeyMapper(use_88_key_layout=use_88_key_layout)
        self._states: Dict[str, KeyState] = {}
        self._pedal_down = False
        self._log = log_message or jukebox_logger.info

        use_cgevent = sys.platform == "darwin" and not macos_use_pynput
        self._use_macos_cgevent = bool(use_cgevent)
        # (shift, alt, ctrl) logical state for CGEvent flags.
        # Refcount so we only release a modifier when no key still needs it.
        self._macos_modifiers: Tuple[bool, bool, bool] = (False, False, False)
        self._macos_modifier_refcount: Tuple[int, int, int] = (0, 0, 0)

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
        return self._states[key_char]

    def _log_exception(self, context: str, exc: Exception) -> None:
        """Log exception with traceback for easier diagnosis."""
        if self._log is not None:
            self._log(f"{context}: {exc}\n{traceback.format_exc()}")

    # -- notes --

    def _note_on_macos_cgevent(self, data: Dict, base_key: str, modifiers: List) -> bool:
        vk = get_macos_vk_for_key(base_key)
        if vk is None:
            return False
        state = self._state_for(base_key)
        was_down = state.is_physically_down
        is_sustained = state.is_sustained and not state.is_active
        state.press()

        shift_rc, alt_rc, ctrl_rc = self._macos_modifier_refcount
        for mod in modifiers:
            mod_vk = get_macos_vk_for_modifier(mod)
            if mod_vk is None:
                continue
            shift, alt, ctrl = self._macos_modifiers
            if mod in (Key.shift,) or getattr(mod, "name", None) == "shift":
                shift_rc += 1
                if not shift:
                    post_macos_key_event(mod_vk, True, self._macos_flags())
                    self._macos_modifiers = (True, alt, ctrl)
            elif mod in (Key.ctrl, Key.control) or getattr(mod, "name", None) in ("ctrl", "control"):
                ctrl_rc += 1
                if not ctrl:
                    post_macos_key_event(mod_vk, True, self._macos_flags())
                    self._macos_modifiers = (shift, alt, True)
            elif mod == Key.alt or getattr(mod, "name", None) == "alt":
                alt_rc += 1
                if not alt:
                    post_macos_key_event(mod_vk, True, self._macos_flags())
                    self._macos_modifiers = (shift, True, ctrl)
        self._macos_modifier_refcount = (shift_rc, alt_rc, ctrl_rc)

        flags = self._macos_flags()
        if is_sustained:
            post_macos_key_event(vk, False, flags)
            time.sleep(0.001)
        if not was_down or is_sustained:
            post_macos_key_event(vk, True, flags)
        return True

    def _note_off_macos_cgevent(self, data: Dict, base_key: str, modifiers: List) -> bool:
        vk = get_macos_vk_for_key(base_key)
        if vk is None:
            return False
        state = self._states.get(base_key)
        if not state:
            return True
        state.release()
        flags = self._macos_flags()
        post_macos_key_event(vk, False, flags)
        shift_rc, alt_rc, ctrl_rc = self._macos_modifier_refcount
        for mod in modifiers:
            mod_vk = get_macos_vk_for_modifier(mod)
            if mod_vk is None:
                continue
            shift, alt, ctrl = self._macos_modifiers
            if mod in (Key.shift,) or getattr(mod, "name", None) == "shift":
                shift_rc = max(0, shift_rc - 1)
                if shift and shift_rc == 0:
                    post_macos_key_event(mod_vk, False, flags)
                    self._macos_modifiers = (False, alt, ctrl)
            elif mod in (Key.ctrl, Key.control) or getattr(mod, "name", None) in ("ctrl", "control"):
                ctrl_rc = max(0, ctrl_rc - 1)
                if ctrl and ctrl_rc == 0:
                    post_macos_key_event(mod_vk, False, flags)
                    self._macos_modifiers = (shift, alt, False)
            elif mod == Key.alt or getattr(mod, "name", None) == "alt":
                alt_rc = max(0, alt_rc - 1)
                if alt and alt_rc == 0:
                    post_macos_key_event(mod_vk, False, flags)
                    self._macos_modifiers = (shift, False, ctrl)
        self._macos_modifier_refcount = (shift_rc, alt_rc, ctrl_rc)
        return True

    def note_on(self, pitch: int, velocity: int) -> None:
        data = self._mapper.get_key_data(pitch)
        if not data:
            return
        base_key = data["key"]
        modifiers = data["modifiers"]

        if self._use_macos_cgevent and self._note_on_macos_cgevent(data, base_key, modifiers):
            return

        state = self._state_for(base_key)
        was_down = state.is_physically_down
        is_sustained = state.is_sustained and not state.is_active
        state.press()
        try:
            with self._kb.pressed(*modifiers):
                if is_sustained:
                    self._kb.release(base_key)
                    time.sleep(0.001)
                    self._kb.press(base_key)
                elif not was_down:
                    self._kb.press(base_key)
        except Exception as e:
            self._log_exception("KeyboardBackend note_on error", e)

    def note_off(self, pitch: int) -> None:
        data = self._mapper.get_key_data(pitch)
        if not data:
            return
        base_key = data["key"]
        modifiers = data["modifiers"]

        if self._use_macos_cgevent and self._note_off_macos_cgevent(data, base_key, modifiers):
            return

        state = self._states.get(base_key)
        if not state:
            return
        state.release()
        try:
            self._kb.release(base_key)
        except Exception as e:
            self._log_exception("KeyboardBackend note_off error", e)

    # -- pedal --

    def pedal_on(self) -> None:
        if self._pedal_down:
            return
        self._pedal_down = True
        if self._use_macos_cgevent:
            space_vk = get_macos_vk_for_key(Key.space)
            if space_vk is not None and post_macos_key_event(space_vk, True, 0):
                return
        try:
            self._kb.press(Key.space)
        except Exception as e:
            self._log_exception("KeyboardBackend pedal_on error", e)

    def pedal_off(self) -> None:
        if not self._pedal_down:
            return
        self._pedal_down = False
        if self._use_macos_cgevent:
            space_vk = get_macos_vk_for_key(Key.space)
            if space_vk is not None and post_macos_key_event(space_vk, False, 0):
                return
        try:
            self._kb.release(Key.space)
        except Exception as e:
            self._log_exception("KeyboardBackend pedal_off error", e)

    # -- shutdown --

    def shutdown(self) -> None:
        if self._use_macos_cgevent:
            flags = self._macos_flags()
            for key_char, state in self._states.items():
                if state.is_active or state.is_sustained:
                    vk = get_macos_vk_for_key(key_char)
                    if vk is not None:
                        post_macos_key_event(vk, False, flags)
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

        for key_char, state in self._states.items():
            if state.is_active or state.is_sustained:
                try:
                    self._kb.release(key_char)
                except Exception as e:
                    self._log_exception("KeyboardBackend shutdown note release error", e)
                state.release()

        if self._pedal_down:
            self._pedal_down = False
            try:
                self._kb.release(Key.space)
            except Exception as e:
                self._log_exception("KeyboardBackend shutdown pedal release error", e)

        for mod in (Key.shift, Key.ctrl, Key.alt):
            try:
                self._kb.release(mod)
            except Exception as e:
                self._log_exception("KeyboardBackend shutdown modifier release error", e)


# ---------------------------------------------------------------------------
# Numpad (RMC) backend
# ---------------------------------------------------------------------------

class NumpadBackend(OutputBackend):
    """Translates note/pedal events into Roblox MIDI Connect numpad messages."""

    def __init__(self, inter_message_delay: float = 0.0,
                 log_message: Optional[Callable[[str], None]] = None):
        self._delay = inter_message_delay
        self._active_notes: Set[int] = set()
        self._pedal_down = False
        # Fall back to central logger if no callback is provided.
        self._log = log_message or jukebox_logger.info

    def _post_delay(self):
        if self._delay > 0:
            time.sleep(self._delay)

    # -- notes --

    def note_on(self, pitch: int, velocity: int) -> None:
        rmc.send_note_message(pitch, velocity, is_note_off=False)
        self._active_notes.add(pitch)
        self._post_delay()

    def note_off(self, pitch: int) -> None:
        rmc.send_note_message(pitch, velocity=0, is_note_off=True)
        self._active_notes.discard(pitch)
        self._post_delay()

    # -- pedal --

    def pedal_on(self) -> None:
        if not self._pedal_down:
            self._pedal_down = True
            rmc.send_pedal(127)
            self._post_delay()

    def pedal_off(self) -> None:
        if self._pedal_down:
            self._pedal_down = False
            rmc.send_pedal(0)
            self._post_delay()

    # -- shutdown --

    def shutdown(self) -> None:
        for pitch in list(self._active_notes):
            rmc.send_note_message(pitch, velocity=0, is_note_off=True)
            self._post_delay()
        self._active_notes.clear()

        if self._pedal_down:
            self._pedal_down = False
            rmc.send_pedal(0)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_backend(output_mode: str, use_88_key_layout: bool = False,
                   inter_message_delay: float = 0.0,
                   macos_use_pynput: bool = False,
                   log_message: Optional[Callable[[str], None]] = None) -> OutputBackend:
    """Return the appropriate backend for *output_mode* (``'key'`` or ``'midi_numpad'``).
    On macOS, *macos_use_pynput* True forces pynput for both KEY and Numpad; False uses CGEvent.
    """
    effective_log = log_message or jukebox_logger.info
    if output_mode == 'midi_numpad':
        if sys.platform == "darwin":
            rmc.set_macos_cgevent(not macos_use_pynput)
        elif not rmc.is_using_pydirectinput():
            effective_log("PyDirectInput is not in use; falling back to pynput for numpad input.")
        return NumpadBackend(inter_message_delay=inter_message_delay,
                             log_message=effective_log)
    return KeyboardBackend(use_88_key_layout=use_88_key_layout,
                           macos_use_pynput=macos_use_pynput,
                           log_message=effective_log)
