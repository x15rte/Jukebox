"""Unified output backends for Roblox piano playback.

Two concrete backends share the same interface:
  * **KeyboardBackend** — emits keyboard presses (for direct keyboard mode).
    On macOS (Darwin) uses CGEvent for layout-independent key codes when available.
    On Windows uses pydirectinput with explicit scan codes.
  * **NumpadBackend** — emits RMC numpad protocol messages.
"""

import ctypes
import sys
import threading
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
    _init_macos_cgevent,
    get_macos_vk_for_key,
    get_macos_vk_for_modifier,
    post_macos_key_event,
    MACOS_CGFLAG_SHIFT,
    MACOS_CGFLAG_CONTROL,
    MACOS_CGFLAG_ALT,
)



def _post_macos_key_event(vk: int, down: bool, flags: int) -> bool:
    """Wrap native post_macos_key_event with failure logging. Resolves at call time for test compatibility."""
    func = globals().get('post_macos_key_event')
    if func is None:
        return False
    if not func(vk, down, flags):
        jukebox_logger.warning(
            f"macOS key event failed: vk={vk}, down={down}, flags={flags}"
        )
        return False
    return True


class OutputBackendError(RuntimeError):
    """Base class for output backend failures that should be visible to users."""


class OutputBackendUnavailableError(OutputBackendError):
    """Raised when an output backend cannot be initialized on this platform."""


class OutputBackendSendError(OutputBackendError):
    """Raised when an output backend fails while sending input."""


_KEYEVENTF_SCANCODE = 0x0008
_KEYEVENTF_KEYUP = 0x0002
_INPUT_KEYBOARD = 1
_WINDOWS_KEY_REPRESS_DELAY = 0.001

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
        self._lock: threading.Lock = threading.Lock()

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

        chunks_sent = 0
        for start in range(0, len(actions), self._capacity):
            try:
                self._send_chunk(actions[start : start + self._capacity])
                chunks_sent += 1
            except OutputBackendSendError as e:
                jukebox_logger.error(
                    f"SendInput batch failed after {chunks_sent} chunks "
                    f"({start//self._capacity}/{ (len(actions)-1)//self._capacity + 1}): {e}"
                )
                raise

    def _send_chunk(self, actions: List[Tuple[str, bool]]) -> None:
        if len(actions) > self._capacity:
            raise ValueError(f"_send_chunk capacity {self._capacity} < {len(actions)}")
        with self._lock:
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
            try:
                if e.key_char == "down":
                    self.pedal_on()
                else:
                    self.pedal_off()
            except Exception as ex:
                if isinstance(ex, OutputBackendError):
                    raise
                self._log_exception("execute_batch pedal", ex)

        for e in releases:
            pitch = getattr(e, 'pitch', None)
            if pitch is not None:
                try:
                    self.note_off(pitch)
                except Exception as ex:
                    if isinstance(ex, OutputBackendError):
                        raise
                    self._log_exception("execute_batch note_off", ex)

        for e in presses:
            pitch = getattr(e, 'pitch', None)
            if pitch is not None:
                try:
                    self.note_on(pitch, getattr(e, 'velocity', 100))
                except Exception as ex:
                    if isinstance(ex, OutputBackendError):
                        raise
                    self._log_exception("execute_batch note_on", ex)

    @abstractmethod
    def shutdown(self) -> None:
        """Release every active note and pedal.  Must be idempotent."""
        ...

    def _log_exception(self, context: str, exc: Exception) -> None:
        """Log exception with traceback for easier diagnosis."""
        jukebox_logger.error(f"{context}: {exc}\n{traceback.format_exc()}")


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
        self._lock: threading.RLock = threading.RLock()
        self._states: Dict[str, KeyState] = {}
        self._active_pitches: Dict[str, Set[int]] = {}
        self._pedal_down = False
        self._held_modifiers: Dict[str, List[str]] = {}
        self._held_modifier_keys: Dict[str, List[Any]] = {}
        self._log = log_message or jukebox_logger.info
        self._Key = Key

        self._kb: Optional[Controller] = None
        self._pdi = None
        self._windows_transport: Optional[_WindowsPydirectInputTransport] = None

        self._use_macos_cgevent = sys.platform == "darwin"
        if self._use_macos_cgevent and not _init_macos_cgevent():
            self._use_macos_cgevent = False
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
        with self._lock:
            if key_char not in self._states:
                self._states[key_char] = KeyState(key_char)
                self._active_pitches[key_char] = set()
            return self._states[key_char]

    def _modifier_name(self, mod) -> Optional[str]:
        name = getattr(mod, "name", None)
        if mod in (self._Key.shift,) or name in ("shift", "shift_r"):
            return "shiftleft"
        if mod in (self._Key.ctrl,) or name in ("ctrl", "control", "ctrl_r"):
            return "ctrlleft"
        if mod == self._Key.alt or name in ("alt", "alt_r"):
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
        # RLock is re-entrant (same thread can re-acquire), so holding it across OS I/O
        # calls is safe from a deadlock perspective. This is intentional — the lock
        # serializes note_on/note_off/pedal operations within this backend instance.
        with self._lock:
            if not self._active_pitches.get(base_key):
                state = self._states.get(base_key)
                if state:
                    state.release()
                released = False
                if self._use_pydirectinput and self._pdi is not None:
                    try:
                        self._pdi_key_up(base_key)
                        released = True
                    except Exception as e:
                        self._log_exception(
                            "KeyboardBackend _release_key_if_unused error", e
                        )
                elif self._kb is not None:
                    try:
                        self._kb.release(base_key)
                        released = True
                    except Exception as e:
                        self._log_exception(
                            "KeyboardBackend _release_key_if_unused error", e
                        )
                if released:
                    # Release tracked modifier names for this key (Windows pydirectinput)
                    mod_names = self._held_modifiers.pop(base_key, [])
                    if mod_names and self._windows_transport is not None:
                        for mod_name in reversed(mod_names):
                            self._pdi_key_up(mod_name)
                    # Release tracked modifier Key objects for this key (pynput)
                    mod_keys = self._held_modifier_keys.pop(base_key, [])
                    if mod_keys and self._kb is not None:
                        for mod_key in mod_keys:
                            try:
                                self._kb.release(mod_key)
                            except Exception as e:
                                self._log_exception(
                                    "KeyboardBackend modifier release error", e
                                )
                    self._active_pitches.pop(base_key, None)
                    self._states.pop(base_key, None)

    def _log_exception(self, context: str, exc: Exception) -> None:
        jukebox_logger.error(f"{context}: {exc}\n{traceback.format_exc()}")

    def _windows_key_repress_delay(self) -> None:
        time.sleep(_WINDOWS_KEY_REPRESS_DELAY)

    def note_on(self, pitch: int, velocity: int) -> None:
        if velocity == 0:
            self.note_off(pitch)
            return
        try:
            data = self._mapper.get_key_data(pitch)
            if not data:
                return

            base_key = data["key"]
            modifiers = data["modifiers"]

            if self._use_macos_cgevent:  # pragma: no cover
                with self._lock:
                    was_active = bool(self._active_pitches.get(base_key))
                    vk = get_macos_vk_for_key(base_key)
                    if vk is None:
                        return
                    shift_rc, alt_rc, ctrl_rc = self._macos_modifier_refcount
                    orig_shift_rc, orig_alt_rc, orig_ctrl_rc = shift_rc, alt_rc, ctrl_rc
                    macos_modifiers = self._macos_modifiers
                    original_modifiers = macos_modifiers  # for rollback
                    committed = False
                    for mod in modifiers:
                        mod_vk = get_macos_vk_for_modifier(mod)
                        if mod_vk is None:
                            continue
                        if mod in (self._Key.shift,) or getattr(mod, "name", None) == "shift":
                            if not _post_macos_key_event(mod_vk, True, self._macos_flags()):
                                jukebox_logger.warning(
                                    f"macOS: failed to post shift key event for {base_key}"
                                )
                                # Rollback: release modifiers already pressed
                                if committed:
                                    for rmod in reversed(modifiers[:modifiers.index(mod)]):
                                        rvk = get_macos_vk_for_modifier(rmod)
                                        if rvk is not None:
                                            _post_macos_key_event(rvk, False, self._macos_flags())
                                self._macos_modifiers = original_modifiers
                                return
                            shift_rc += 1
                            if shift_rc == 1:
                                macos_modifiers = (True, macos_modifiers[1], macos_modifiers[2])
                                self._macos_modifiers = macos_modifiers  # commit immediately
                                committed = True
                        elif mod in (self._Key.ctrl,) or getattr(mod, "name", None) in (
                            "ctrl",
                            "control",
                        ):
                            if not _post_macos_key_event(mod_vk, True, self._macos_flags()):
                                jukebox_logger.warning(
                                    f"macOS: failed to post ctrl key event for {base_key}"
                                )
                                if committed:
                                    for rmod in reversed(modifiers[:modifiers.index(mod)]):
                                        rvk = get_macos_vk_for_modifier(rmod)
                                        if rvk is not None:
                                            _post_macos_key_event(rvk, False, self._macos_flags())
                                self._macos_modifiers = original_modifiers
                                return
                            ctrl_rc += 1
                            if ctrl_rc == 1:
                                macos_modifiers = (macos_modifiers[0], macos_modifiers[1], True)
                                self._macos_modifiers = macos_modifiers
                                committed = True
                        elif mod == self._Key.alt or getattr(mod, "name", None) == "alt":
                            if not _post_macos_key_event(mod_vk, True, self._macos_flags()):
                                jukebox_logger.warning(
                                    f"macOS: failed to post alt key event for {base_key}"
                                )
                                if committed:
                                    for rmod in reversed(modifiers[:modifiers.index(mod)]):
                                        rvk = get_macos_vk_for_modifier(rmod)
                                        if rvk is not None:
                                            _post_macos_key_event(rvk, False, self._macos_flags())
                                self._macos_modifiers = original_modifiers
                                return
                            alt_rc += 1
                            if alt_rc == 1:
                                macos_modifiers = (macos_modifiers[0], True, macos_modifiers[2])
                                self._macos_modifiers = macos_modifiers
                                committed = True
                    self._macos_modifiers = macos_modifiers
                    self._macos_modifier_refcount = (shift_rc, alt_rc, ctrl_rc)
                    # State updates only after all CGEvent calls succeed
                    state = self._state_for(base_key)
                    state.press()
                    self._active_pitches.setdefault(base_key, set()).add(pitch)
                    # Build map of modifier → whether it was newly pressed (refcount was 0)
                    modifier_newly_pressed: dict[Any, bool] = {}
                    for m in modifiers:
                        if m in (self._Key.shift,) or getattr(m, "name", None) == "shift":
                            modifier_newly_pressed[m] = (orig_shift_rc == 0)
                        elif m in (self._Key.ctrl,) or getattr(m, "name", None) in ("ctrl", "control"):
                            modifier_newly_pressed[m] = (orig_ctrl_rc == 0)
                        elif m == self._Key.alt or getattr(m, "name", None) == "alt":
                            modifier_newly_pressed[m] = (orig_alt_rc == 0)

                    # Compute CGEvent flags for the new pitch only (not global modifier state)
                    new_flags = 0
                    for mod in modifiers:
                        if mod in (self._Key.shift,) or getattr(mod, "name", None) == "shift":
                            new_flags |= MACOS_CGFLAG_SHIFT
                        elif mod in (self._Key.ctrl,) or getattr(mod, "name", None) in ("ctrl", "control",):
                            new_flags |= MACOS_CGFLAG_CONTROL
                        elif mod == self._Key.alt or getattr(mod, "name", None) == "alt":
                            new_flags |= MACOS_CGFLAG_ALT
                        else:
                            jukebox_logger.debug(
                                f"Unknown macOS modifier for {base_key}: {mod}"
                            )
                    if was_active:
                        if not _post_macos_key_event(vk, False, self._macos_flags()):
                            jukebox_logger.warning(
                                f"macOS key release failed for {base_key}, skipping re-press"
                            )
                            # Rollback: restore modifier state fully
                            self._macos_modifiers = original_modifiers
                            self._macos_modifier_refcount = (orig_shift_rc, orig_alt_rc, orig_ctrl_rc)
                            # Release only modifiers that were newly pressed by this note_on
                            for rmod in reversed(modifiers):
                                if modifier_newly_pressed.get(rmod, False):
                                    rvk = get_macos_vk_for_modifier(rmod)
                                    if rvk is not None:
                                        _post_macos_key_event(rvk, False, self._macos_flags())
                            self._active_pitches[base_key].discard(pitch)
                            if not self._active_pitches[base_key]:
                                self._active_pitches.pop(base_key, None)
                            self._states.pop(base_key, None)
                        else:
                            time.sleep(_WINDOWS_KEY_REPRESS_DELAY)
                            if not _post_macos_key_event(vk, True, new_flags):
                                jukebox_logger.warning(
                                    f"macOS key re-press failed for {base_key}"
                                )
                                self._active_pitches[base_key].discard(pitch)
                                if not self._active_pitches[base_key]:
                                    self._active_pitches.pop(base_key, None)
                                self._states.pop(base_key, None)
                                # Restore state first so _macos_flags() excludes the modifiers being released
                                self._macos_modifier_refcount = (orig_shift_rc, orig_alt_rc, orig_ctrl_rc)
                                self._macos_modifiers = original_modifiers
                                # Release only modifiers that were newly pressed by this note_on
                                for rmod in reversed(modifiers):
                                    if modifier_newly_pressed.get(rmod, False):
                                        rvk = get_macos_vk_for_modifier(rmod)
                                        if rvk is not None:
                                            _post_macos_key_event(rvk, False, self._macos_flags())
                    else:
                        # First press — send the base key down
                        if not _post_macos_key_event(vk, True, new_flags):
                            jukebox_logger.warning(
                                f"macOS key press failed for {base_key}"
                            )
                            # Rollback: restore modifier state fully
                            self._macos_modifiers = original_modifiers
                            self._macos_modifier_refcount = (orig_shift_rc, orig_alt_rc, orig_ctrl_rc)
                            # Release only modifiers that were newly pressed by this note_on
                            for rmod in reversed(modifiers):
                                if modifier_newly_pressed.get(rmod, False):
                                    rvk = get_macos_vk_for_modifier(rmod)
                                    if rvk is not None:
                                        _post_macos_key_event(rvk, False, self._macos_flags())
                            self._active_pitches[base_key].discard(pitch)
                            if not self._active_pitches[base_key]:
                                self._active_pitches.pop(base_key, None)
                            self._states.pop(base_key, None)
                return
            if self._windows_transport is not None:
                with self._lock:
                    was_active = bool(self._active_pitches.get(base_key))
                    modifier_names = [
                        mod_name
                        for mod in modifiers
                        if (mod_name := self._modifier_name(mod)) is not None
                    ]
                    batch: List[Tuple[str, bool]] = [
                        (mod_name, True) for mod_name in modifier_names
                    ]
                    old_mods = []
                    stale_mods = []
                    if was_active:
                        old_mods = self._held_modifiers.pop(base_key, [])
                        stale_mods = [m for m in old_mods if m not in modifier_names]
                        try:
                            if stale_mods:
                                self._windows_transport.send_batch(
                                    [(m, False) for m in reversed(stale_mods)]
                                )
                            self._windows_transport.send_batch([(base_key, False)])
                        except OutputBackendSendError:
                            # State is now unknown: clear tracking so _release_key_if_unused won't try
                            # to release modifiers that may not actually be held.
                            self._held_modifiers.pop(base_key, None)
                            return
                        self._windows_key_repress_delay()
                    batch.append((base_key, True))
                    # Keep modifiers held — release them on note_off via _release_key_if_unused
                    try:
                        self._windows_transport.send_batch(batch)
                    except OutputBackendSendError:
                        # Modifier downs were already sent — try to release them
                        for mod_name in reversed(modifier_names):
                            try:
                                self._windows_transport.send_batch([(mod_name, False)])
                            except OutputBackendSendError:
                                pass
                        # Re-press stale modifiers that were released before the failure
                        if stale_mods:
                            try:
                                self._windows_transport.send_batch(
                                    [(m, True) for m in stale_mods]
                                )
                            except OutputBackendSendError:
                                pass
                        # State is now unknown: clear tracking so _release_key_if_unused won't try
                        # to release modifiers that may not actually be held.
                        self._held_modifiers.pop(base_key, None)
                        self._active_pitches.pop(base_key, None)
                        return
                    self._held_modifiers[base_key] = modifier_names
                    state = self._state_for(base_key)
                    state.press()
                    self._active_pitches.setdefault(base_key, set()).add(pitch)
                return

            try:
                if self._kb is not None:
                    with self._lock:
                        was_active = bool(self._active_pitches.get(base_key))
                        old_mod_keys = self._held_modifier_keys.pop(base_key, []) if was_active else []
                    if was_active:
                        stale_mod_keys = [m for m in old_mod_keys if m not in modifiers]
                        for mod_key in stale_mod_keys:
                            try:
                                self._kb.release(mod_key)
                            except Exception:
                                pass
                        self._kb.release(base_key)
                    try:
                        # Keep modifiers held — store for release in note_off
                        mod_keys: List[Any] = []
                        for mod in modifiers:
                            mod_name = self._modifier_name(mod)
                            if mod_name:
                                self._kb.press(mod)
                                mod_keys.append(mod)
                        self._kb.press(base_key)
                        with self._lock:
                            self._held_modifier_keys[base_key] = mod_keys
                    except Exception as e:
                        # Release any modifiers that were already pressed before the error
                        for mod in reversed(mod_keys):
                            try:
                                self._kb.release(mod)
                            except Exception:
                                pass
                        if was_active:
                            try:
                                self._kb.press(base_key)
                            except Exception:
                                pass
                        self._log_exception("KeyboardBackend note_on error", e)
                        return
                    with self._lock:
                        state = self._state_for(base_key)
                        state.press()
                        self._active_pitches.setdefault(base_key, set()).add(pitch)
            except Exception as e:
                self._log_exception("KeyboardBackend note_on error", e)
        except OutputBackendError:
            raise
        except Exception as e:
            self._log_exception("KeyboardBackend note_on error", e)

    def note_off(self, pitch: int) -> None:
        try:
            data = self._mapper.get_key_data(pitch)
            if not data:
                return

            base_key = data["key"]
            modifiers = data["modifiers"]

            with self._lock:
                active = self._active_pitches.get(base_key)
                if active:
                    active.discard(pitch)

                if self._use_macos_cgevent:  # pragma: no cover
                    # Release base key BEFORE modifiers so game sees the note-off
                    # before the modifier changes reset the octave mapping.
                    if not self._pedal_down and not self._active_pitches.get(base_key):
                        state = self._states.get(base_key)
                        vk = get_macos_vk_for_key(base_key)
                        if state:
                            state.release()
                        if vk is not None:
                            if _post_macos_key_event(vk, False, self._macos_flags()):
                                self._active_pitches.pop(base_key, None)
                                self._states.pop(base_key, None)

                    shift_rc, alt_rc, ctrl_rc = self._macos_modifier_refcount
                    for mod in modifiers:
                        if mod in (self._Key.shift,) or getattr(mod, "name", None) == "shift":
                            shift_rc = max(0, shift_rc - 1)
                            if shift_rc == 0 and self._macos_modifiers[0]:
                                mod_vk = get_macos_vk_for_modifier(mod)
                                if mod_vk is not None:
                                    if _post_macos_key_event(mod_vk, False, self._macos_flags()):
                                        self._macos_modifiers = (False, self._macos_modifiers[1], self._macos_modifiers[2])
                        elif mod in (self._Key.ctrl,) or getattr(mod, "name", None) in ("ctrl", "control"):
                            ctrl_rc = max(0, ctrl_rc - 1)
                            if ctrl_rc == 0 and self._macos_modifiers[2]:
                                mod_vk = get_macos_vk_for_modifier(mod)
                                if mod_vk is not None:
                                    if _post_macos_key_event(mod_vk, False, self._macos_flags()):
                                        self._macos_modifiers = (self._macos_modifiers[0], self._macos_modifiers[1], False)
                        elif mod == self._Key.alt or getattr(mod, "name", None) == "alt":
                            alt_rc = max(0, alt_rc - 1)
                            if alt_rc == 0 and self._macos_modifiers[1]:
                                mod_vk = get_macos_vk_for_modifier(mod)
                                if mod_vk is not None:
                                    if _post_macos_key_event(mod_vk, False, self._macos_flags()):
                                        self._macos_modifiers = (self._macos_modifiers[0], False, self._macos_modifiers[2])
                    self._macos_modifier_refcount = (shift_rc, alt_rc, ctrl_rc)
                else:
                    if not self._pedal_down:
                        self._release_key_if_unused(base_key)
        except OutputBackendError:
            raise
        except Exception as e:
            self._log_exception("KeyboardBackend note_off error", e)

    def pedal_on(self) -> None:
        if self._use_macos_cgevent:  # pragma: no cover
            with self._lock:
                if self._pedal_down:
                    return
                space_vk = get_macos_vk_for_key(self._Key.space)
                if space_vk is not None and _post_macos_key_event(space_vk, True, 0):
                    self._pedal_down = True
            return
        with self._lock:
            if self._pedal_down:
                return
        try:
            if self._use_pydirectinput and self._pdi is not None:
                self._pdi_key_down("space")
                with self._lock:
                    self._pedal_down = True
            elif self._kb is not None:
                self._kb.press(self._Key.space)
                with self._lock:
                    self._pedal_down = True
        except Exception as e:
            if self._use_pydirectinput:
                raise
            self._log_exception("KeyboardBackend pedal_on error", e)

    def pedal_off(self) -> None:
        # Clean up active pitches under lock (runs before macOS CGEvent to ensure cleanup)
        with self._lock:
            if not self._pedal_down:
                return
            for key_char in list(self._active_pitches.keys()):
                if not self._active_pitches[key_char]:
                    if self._use_macos_cgevent:  # pragma: no cover
                        state = self._states.get(key_char)
                        if state:
                            state.release()
                        vk = get_macos_vk_for_key(key_char)
                        if vk is not None:
                            _post_macos_key_event(vk, False, self._macos_flags())
                        self._active_pitches.pop(key_char, None)
                        self._states.pop(key_char, None)
                    else:
                        self._release_key_if_unused(key_char)

        # Then handle the pedal space key release
        if self._use_macos_cgevent:  # pragma: no cover
            space_vk = get_macos_vk_for_key(self._Key.space)
            if space_vk is not None and _post_macos_key_event(space_vk, False, 0):
                with self._lock:
                    self._pedal_down = False
                return

        try:
            if self._use_pydirectinput and self._pdi is not None:
                self._pdi_key_up("space")
            elif self._kb is not None:
                self._kb.release(self._Key.space)
        except Exception as e:
            if self._use_pydirectinput:
                raise
            self._log_exception("KeyboardBackend pedal_off error", e)
        finally:
            with self._lock:
                self._pedal_down = False

    # Note: release-then-press of the same base key in one batch skips the
    # per-key repress delay because the release clears _active_pitches before
    # the press checks was_active. Acceptable for sub-millisecond trills.
    def execute_batch(self, events: List[Any]) -> None:
        if not events:
            return
        super().execute_batch(events)

    def shutdown(self) -> None:
        with self._lock:
            if self._use_macos_cgevent:  # pragma: no cover
                flags = self._macos_flags()
                for key_char in list(self._active_pitches.keys()):
                    vk = get_macos_vk_for_key(key_char)
                    if vk is not None:
                        _post_macos_key_event(vk, False, flags)
                self._active_pitches.clear()
                for state in self._states.values():
                    state.release()
                if self._pedal_down:
                    space_vk = get_macos_vk_for_key(self._Key.space)
                    if space_vk is not None:
                        _post_macos_key_event(space_vk, False, 0)
                    self._pedal_down = False
                shift_needed = self._macos_modifiers[0]
                alt_needed = self._macos_modifiers[1]
                ctrl_needed = self._macos_modifiers[2]

                # Clear state first to prevent _macos_flags() from including them
                self._macos_modifiers = (False, False, False)
                self._macos_modifier_refcount = (0, 0, 0)

                shift_vk = get_macos_vk_for_modifier(self._Key.shift)
                ctrl_vk = get_macos_vk_for_modifier(self._Key.ctrl)
                alt_vk = get_macos_vk_for_modifier(self._Key.alt)

                # Release with flags for modifiers still held at time of release.
                # Track remaining state so each release excludes already-released modifiers.
                still_shift = shift_needed
                still_alt = alt_needed
                still_ctrl = ctrl_needed

                if still_shift and shift_vk is not None:
                    _post_macos_key_event(shift_vk, False,
                        (MACOS_CGFLAG_ALT if still_alt else 0) | (MACOS_CGFLAG_CONTROL if still_ctrl else 0))
                    still_shift = False
                if still_alt and alt_vk is not None:
                    _post_macos_key_event(alt_vk, False,
                        (MACOS_CGFLAG_SHIFT if still_shift else 0) | (MACOS_CGFLAG_CONTROL if still_ctrl else 0))
                    still_alt = False
                if still_ctrl and ctrl_vk is not None:
                    _post_macos_key_event(ctrl_vk, False,
                        (MACOS_CGFLAG_SHIFT if still_shift else 0) | (MACOS_CGFLAG_ALT if still_alt else 0))
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
                            self._kb.release(key_char)
                    except Exception as e:
                        self._log_exception("KeyboardBackend shutdown note release error", e)

                self._active_pitches.clear()
                for state in self._states.values():
                    state.release()

                if self._pedal_down:
                    try:
                        if self._use_pydirectinput and self._pdi is not None:
                            self._pdi_key_up("space")
                        elif self._kb is not None:
                            self._kb.release(self._Key.space)
                        self._pedal_down = False
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
                    for mod in (self._Key.shift, self._Key.ctrl, self._Key.alt):
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
        self._lock: threading.RLock = threading.RLock()
        # Fall back to central logger if no callback is provided.
        self._log = log_message or jukebox_logger.info

    def _post_delay(self):
        if self._delay > 0:
            time.sleep(self._delay)

    def _log_exception(self, context: str, exc: Exception) -> None:
        """Log exception with traceback for easier diagnosis."""
        jukebox_logger.error(f"{context}: {exc}\n{traceback.format_exc()}")

    # -- notes --

    def note_on(self, pitch: int, velocity: int) -> None:
        if velocity == 0:
            self.note_off(pitch)
            return
        if not 0 <= pitch <= 127:
            return
        with self._lock:
            self._active_notes.add(pitch)
        try:
            rmc.send_note_message(pitch, velocity, is_note_off=False)
            self._post_delay()
        except Exception as e:
            self._log_exception("NumpadBackend note_on error", e)

    def note_off(self, pitch: int) -> None:
        if not 0 <= pitch <= 127:
            return
        with self._lock:
            self._active_notes.discard(pitch)
        try:
            rmc.send_note_message(pitch, velocity=0, is_note_off=True)
            self._post_delay()
        except Exception as e:
            self._log_exception("NumpadBackend note_off error", e)

    # -- pedal --

    def pedal_on(self) -> None:
        with self._lock:
            if self._pedal_down:
                return
        try:
            rmc.send_pedal(127)
            self._post_delay()
            with self._lock:
                self._pedal_down = True
        except Exception as e:
            self._log_exception("NumpadBackend pedal_on error", e)

    def pedal_off(self) -> None:
        with self._lock:
            if not self._pedal_down:
                return
        try:
            rmc.send_pedal(0)
            self._post_delay()
            with self._lock:
                self._pedal_down = False
        except Exception as e:
            self._log_exception("NumpadBackend pedal_off error", e)

    # -- shutdown --

    def shutdown(self) -> None:
        with self._lock:
            for pitch in list(self._active_notes):
                try:
                    rmc.send_note_message(pitch, velocity=0, is_note_off=True)
                except Exception as e:
                    self._log_exception("NumpadBackend shutdown note release error", e)
                self._post_delay()
            self._active_notes.clear()
            if self._pedal_down:
                try:
                    rmc.send_pedal(0)
                    self._pedal_down = False
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
        if sys.platform == "darwin" and not _init_macos_cgevent():
            raise OutputBackendUnavailableError(
                "macOS Accessibility not granted for CGEvent"
            )
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
    if output_mode == "key":
        return KeyboardBackend(
            use_88_key_layout=use_88_key_layout,
            log_message=effective_log,
        )
    raise ValueError(f"Unknown output mode: {output_mode!r}")
