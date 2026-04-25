from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from types import ModuleType
import sys


@dataclass(frozen=True)
class _KeyValue:
    name: str

    def __str__(self) -> str:
        return f"Key.{self.name}"

    __repr__ = __str__


class _KeyNamespace:
    _aliases = {"control": "ctrl"}
    _known_keys = {
        "alt",
        "backspace",
        "ctrl",
        "delete",
        "down",
        "end",
        "enter",
        "esc",
        "home",
        "insert",
        "left",
        "page_down",
        "page_up",
        "right",
        "shift",
        "space",
        "tab",
        "up",
        *(f"f{i}" for i in range(1, 25)),
        "num_lock",
    }

    def __init__(self) -> None:
        self._cache: dict[str, _KeyValue] = {}

    def __getattr__(self, name: str) -> _KeyValue:
        canonical = self._aliases.get(name, name)
        if canonical not in self._known_keys:
            raise AttributeError(name)
        key = self._cache.get(canonical)
        if key is None:
            key = _KeyValue(canonical)
            self._cache[canonical] = key
        return key


@dataclass(frozen=True)
class _KeyCodeValue:
    char: str | None = None
    vk: int | None = None

    def __str__(self) -> str:
        if self.char is not None:
            return self.char
        return f"KeyCode(vk={self.vk})"

    __repr__ = __str__


class _KeyCode:
    @staticmethod
    def from_char(char: str) -> _KeyCodeValue:
        return _KeyCodeValue(char=char)

    @staticmethod
    def from_vk(vk: int) -> _KeyCodeValue:
        return _KeyCodeValue(vk=vk)


class _Controller:
    def pressed(self, *_mods):
        return nullcontext()

    def press(self, _key) -> None:
        return None

    def release(self, _key) -> None:
        return None

    def tap(self, key) -> None:
        self.press(key)
        self.release(key)


class _Listener:
    def __init__(self, on_press=None):
        self.on_press = on_press

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


def install() -> None:
    keyboard_module = ModuleType("pynput.keyboard")
    setattr(keyboard_module, "Key", _KeyNamespace())
    setattr(keyboard_module, "KeyCode", _KeyCode)
    setattr(keyboard_module, "Controller", _Controller)
    setattr(keyboard_module, "Listener", _Listener)

    pynput_module = ModuleType("pynput")
    setattr(pynput_module, "__path__", [])
    setattr(pynput_module, "keyboard", keyboard_module)

    sys.modules["pynput"] = pynput_module
    sys.modules["pynput.keyboard"] = keyboard_module
