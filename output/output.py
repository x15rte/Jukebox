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
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from pynput.keyboard import Key, Controller

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
    - macOS: CGEvent (default) or pynput (when explicitly requested)
    - Windows: pydirectinput when available, otherwise pynput
    - Other platforms: pynput
    """

    def __init__(
        self,
        use_88_key_layout: bool = False,
        macos_use_pynput: bool = False,
        log_message: Optional[Callable[[str], None]] = None,
    ):
        self._mapper = KeyMapper(use_88_key_layout=use_88_key_layout)
        self._states: Dict[str, KeyState] = {}
        self._active_pitches: Dict[str, Set[int]] = {}
        self._pedal_down = False
        self._log = log_message or jukebox_logger.info

        self._kb: Optional[Controller] = None
        self._pdi = None

        use_cgevent = sys.platform == "darwin" and not macos_use_pynput
        self._use_macos_cgevent = bool(use_cgevent)
        self._use_pydirectinput = False

        self._macos_modifiers: Tuple[bool, bool, bool] = (False, False, False)
        self._macos_modifier_refcount: Tuple[int, int, int] = (0, 0, 0)

        if not self._use_macos_cgevent and sys.platform == "win32":
            try:
                import pydirectinput as pdi_mod

                pdi_mod.PAUSE = 0
                pdi_mod.FAILSAFE = False
                self._pdi = pdi_mod
                self._use_pydirectinput = True
                self._log("KEY mode: using pydirectinput on Windows.")
            except Exception:
                self._kb = Controller()
                self._log(
                    "KEY mode: pydirectinput unavailable, falling back to pynput."
                )
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
        if mod in (Key.shift,) or name == "shift":
            return "shiftleft"
        if mod in (Key.ctrl,) or name in ("ctrl", "control"):
            return "ctrlleft"
        if mod == Key.alt or name == "alt":
            return "altleft"
        return None

    def _pdi_key_down(self, key_name: str) -> None:
        if self._pdi is None:
            return
        try:
            self._pdi.keyDown(key_name, _pause=False)
        except TypeError:
            self._pdi.keyDown(key_name)

    def _pdi_key_up(self, key_name: str) -> None:
        if self._pdi is None:
            return
        try:
            self._pdi.keyUp(key_name, _pause=False)
        except TypeError:
            self._pdi.keyUp(key_name)

    def _release_key_if_unused(self, base_key: str) -> None:
        if not self._active_pitches.get(base_key):
            state = self._states.get(base_key)
            if state:
                state.release()
            try:
                if self._use_pydirectinput and self._pdi is not None:
                    self._pdi_key_up(base_key)
                elif self._kb is not None:
                    self._kb.release(base_key)
            except Exception as e:
                self._log_exception("KeyboardBackend _release_key_if_unused error", e)
            self._active_pitches.pop(base_key, None)
            self._states.pop(base_key, None)

    def _log_exception(self, context: str, exc: Exception) -> None:
        if self._log is not None:
            self._log(f"{context}: {exc}\n{traceback.format_exc()}")

    def note_on(self, pitch: int, velocity: int) -> None:
        data = self._mapper.get_key_data(pitch)
        if not data:
            return

        base_key = data["key"]
        modifiers = data["modifiers"]

        if self._use_macos_cgevent:
            vk = get_macos_vk_for_key(base_key)
            if vk is None:
                return
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

        try:
            if self._use_pydirectinput and self._pdi is not None:
                pressed_modifiers: List[str] = []
                try:
                    for mod in modifiers:
                        mod_name = self._modifier_name(mod)
                        if mod_name is None:
                            continue
                        self._pdi_key_down(mod_name)
                        pressed_modifiers.append(mod_name)
                    self._pdi_key_down(base_key)
                finally:
                    for mod_name in reversed(pressed_modifiers):
                        self._pdi_key_up(mod_name)
            elif self._kb is not None:
                with self._kb.pressed(*modifiers):
                    self._kb.press(base_key)
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
                self._pdi.keyDown("space")
            elif self._kb is not None:
                self._kb.press(Key.space)
        except Exception as e:
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
                self._pdi.keyUp("space")
            elif self._kb is not None:
                self._kb.release(Key.space)
        except Exception as e:
            self._log_exception("KeyboardBackend pedal_off error", e)

    def execute_batch(self, events: List[Any]) -> None:
        if not events:
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

        for key_char in list(self._active_pitches.keys()):
            try:
                if self._use_pydirectinput and self._pdi is not None:
                    self._pdi_key_up(key_char)
                elif self._kb is not None:
                    self._kb.release(key_char)
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
                self._log_exception("KeyboardBackend shutdown pedal release error", e)

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
    macos_use_pynput: bool = False,
    log_message: Optional[Callable[[str], None]] = None,
) -> OutputBackend:
    """Return the appropriate backend for *output_mode* (``'key'`` or ``'midi_numpad'``).
    On macOS, *macos_use_pynput* True forces pynput for both KEY and Numpad; False uses CGEvent.
    """
    effective_log = log_message or jukebox_logger.info
    if output_mode == "midi_numpad":
        if sys.platform == "darwin":
            rmc.set_macos_cgevent(not macos_use_pynput)
        elif not rmc.is_using_pydirectinput():
            effective_log(
                "PyDirectInput is not in use; falling back to pynput for numpad input."
            )
        return NumpadBackend(
            inter_message_delay=inter_message_delay, log_message=effective_log
        )
    return KeyboardBackend(
        use_88_key_layout=use_88_key_layout,
        macos_use_pynput=macos_use_pynput,
        log_message=effective_log,
    )
