from typing import Any, cast

from pynput.keyboard import Key

from tests.helpers.fakes import FakeListener
from ui.hotkey_manager import HotkeyManager, parse_hotkey_string

parse_hotkey_string = cast(Any, parse_hotkey_string)


def _patch_listener(monkeypatch):
    monkeypatch.setattr("ui.hotkey_manager.keyboard.Listener", FakeListener)


def test_parse_hotkey_string_defaults_and_char():
    assert parse_hotkey_string(None) == Key.f6
    key = cast(Any, parse_hotkey_string("x"))
    assert hasattr(key, "char") and key.char == "x"


def test_hotkey_manager_binding_and_toggle(monkeypatch):
    _patch_listener(monkeypatch)

    mgr = HotkeyManager()
    captured = {"toggle": 0, "bound": None}
    mgr.toggle_requested.connect(lambda: captured.__setitem__("toggle", captured["toggle"] + 1))
    mgr.bound_updated.connect(lambda s: captured.__setitem__("bound", s))

    mgr.start_binding()
    mgr.on_press(Key.f7)
    assert captured["bound"] == "f7"

    mgr.current_key = Key.f8
    mgr.on_press(Key.f8)
    assert captured["toggle"] == 1


def test_parse_hotkey_string_invalid_char_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(
        "ui.hotkey_manager.KeyCode.from_char",
        lambda _c: (_ for _ in ()).throw(ValueError("bad char")),
    )
    assert parse_hotkey_string("x") == Key.f6


def test_parse_hotkey_string_multi_char_falls_back_to_default():
    assert parse_hotkey_string("xx") == Key.f6


def test_format_key_string_prefers_key_char(monkeypatch):
    class CharKey:
        char = "z"

    _patch_listener(monkeypatch)
    mgr = HotkeyManager()

    assert mgr.format_key_string(CharKey()) == "z"


def test_stop_with_no_listener_noop(monkeypatch):
    _patch_listener(monkeypatch)
    mgr = HotkeyManager()
    mgr.listener = None

    mgr.stop()
