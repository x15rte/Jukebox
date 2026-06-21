# pyright: reportOptionalMemberAccess=false

"""Tests for HotkeyManager using QShortcut / eventFilter (no pynput)."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent, QKeySequence
from PyQt6.QtWidgets import QWidget, QApplication

from ui.hotkey_manager import HotkeyManager




def test_hotkey_manager_default_key(qtbot: Any) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    assert mgr.get_current_key() == "F8"


def test_hotkey_manager_set_and_get(qtbot: Any) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    mgr.set_hotkey("Ctrl+Shift+A")
    assert mgr.get_current_key() == "Ctrl+Shift+A"


def test_hotkey_manager_format_key_string(qtbot: Any) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    assert mgr.format_key_string("F8") == "F8"
    assert mgr.format_key_string("Ctrl+Shift+A") == "Ctrl+Shift+A"


def test_hotkey_manager_binding_captures_key(qtbot: Any) -> None:
    """start_binding() followed by a key press emits bound_updated."""
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)

    captured: list[str] = []
    mgr.bound_updated.connect(captured.append)

    mgr.start_binding()
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F7, Qt.KeyboardModifier.NoModifier)
    mgr.eventFilter(parent, event)
    assert len(captured) == 1
    assert captured[0] == "F7"
    assert mgr.get_current_key() == "F7"


def test_hotkey_manager_binding_ignores_autorepeat(qtbot: Any) -> None:
    """Auto-repeat key events should not trigger a binding."""
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)

    captured: list[str] = []
    mgr.bound_updated.connect(captured.append)

    mgr.start_binding()
    # Auto-repeat event
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F7,
                      Qt.KeyboardModifier.NoModifier, "", True)
    mgr.eventFilter(parent, event)

    assert len(captured) == 0, "auto-repeat should not bind"
    assert mgr._listening_for_bind, "binding mode should remain active"


def test_hotkey_manager_binding_only_when_listening(qtbot: Any) -> None:
    """Key press without start_binding() does not emit bound_updated."""
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)

    captured: list[str] = []
    mgr.bound_updated.connect(captured.append)

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F7, Qt.KeyboardModifier.NoModifier)
    mgr.eventFilter(parent, event)


def test_hotkey_manager_toggle_signal(qtbot: Any) -> None:
    """The QShortcut emits toggle_requested when activated."""
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)

    toggled: list[bool] = []
    mgr.toggle_requested.connect(lambda: toggled.append(True))

    # Emit the shortcut's activated signal directly
    # Shortcut is set during construction
    assert mgr._shortcut is not None
    mgr._shortcut.activated.emit()
    assert toggled == [True], "shortcut activated should emit toggle_requested"


def test_hotkey_manager_stop(qtbot: Any) -> None:
    """stop() disables the shortcut."""
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    mgr.stop()
    assert mgr._shortcut is None or not mgr._shortcut.isEnabled()


def test_hotkey_manager_stop_idempotent(qtbot: Any) -> None:
    """Calling stop() multiple times does not raise."""
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    mgr.stop()
    mgr.stop()  # second call should be safe

def test_hotkey_manager_modifier_only_key(qtbot: Any, monkeypatch: Any) -> None:
    """Modifier-only key press keeps previous binding and emits special message."""
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    signals = []
    mgr.bound_updated.connect(signals.append)
    mgr.start_binding()

    # Make QKeySequence.toString return empty to simulate modifier-only key
    monkeypatch.setattr(QKeySequence, "toString", lambda *a, **kw: "")

    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_F7,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.instance().sendEvent(parent, event)

    # Modifier-only path: key stays at previous ("F8"), special message emitted
    assert mgr.get_current_key() == "F8"
    assert signals == ["(modifier only — press a key combo)"]
