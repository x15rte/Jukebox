"""Hotkey management: global key listener for play/pause toggle."""

from __future__ import annotations

from pynput import keyboard
from pynput.keyboard import Key, KeyCode
from PyQt6.QtCore import QObject, pyqtSignal as Signal

from logger_core import jukebox_logger


def parse_hotkey_string(s: str | None) -> Key | KeyCode:
    """Parse config string to pynput Key or KeyCode (special key name or single char); default Key.f8."""
    if not s or not isinstance(s, str):
        return Key.f8
    s = s.strip().lower()
    special = getattr(Key, s, None)
    if special is not None:
        return special
    if len(s) == 1:
        try:
            return KeyCode.from_char(s)
        except Exception:
            jukebox_logger.debug(f"Invalid hotkey character '{s}', using default F8.")
            return Key.f8
    return Key.f8


class HotkeyManager(QObject):
    """Global hotkey listener: current_key triggers toggle; start_binding() captures next key and emits bound_updated."""

    toggle_requested = Signal()
    bound_updated = Signal(str)

    def __init__(self):
        super().__init__()
        self.current_key = Key.f8
        self.listener = None
        self.listening_for_bind = False
        self._start_listener()

    def _start_listener(self):
        self.listener = keyboard.Listener(on_press=self.on_press)
        self.listener.start()

    def format_key_string(self, key):
        if hasattr(key, "char") and key.char:
            return key.char
        return str(key).replace("Key.", "")

    def on_press(self, key):
        if self.listening_for_bind:
            self.current_key = key
            self.listening_for_bind = False
            self.bound_updated.emit(self.format_key_string(key))
            return
        if key == self.current_key:
            self.toggle_requested.emit()

    def start_binding(self):
        self.listening_for_bind = True

    def stop(self):
        """Stop the pynput listener. Call during application shutdown."""
        if self.listener is not None:
            self.listener.stop()
