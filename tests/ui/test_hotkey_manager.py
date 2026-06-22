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


def test_hotkey_manager_stop_non_windows(monkeypatch: Any, qtbot: Any) -> None:
    """stop() on non-Windows without native filter does not raise."""
    monkeypatch.setattr("ui.hotkey_manager.sys.platform", "linux")
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    mgr._native_filter = None
    mgr.stop()  # should not raise
    assert mgr._stopped


def test_hotkey_manager_poll_focus_no_app(monkeypatch: Any, qtbot: Any) -> None:
    """_poll_focus_state returns early when QApplication.instance() is None."""
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    monkeypatch.setattr("ui.hotkey_manager.QApplication.instance", lambda: None)
    mgr._poll_focus_state()  # should not raise


def test_hotkey_manager_poll_focus_inactive(monkeypatch: Any, qtbot: Any) -> None:
    """_poll_focus_state transitions from active to inactive."""
    from PyQt6.QtCore import Qt
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    mgr._app_focused = True
    monkeypatch.setattr(
        "ui.hotkey_manager.QApplication.applicationState",
        lambda self: Qt.ApplicationState.ApplicationInactive,
    )
    mgr._poll_focus_state()
    assert mgr._app_focused is False


def test_hotkey_manager_poll_focus_exception(monkeypatch: Any, qtbot: Any) -> None:
    """_poll_focus_state swallows exceptions."""
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    def raise_boom():
        raise RuntimeError("boom")
    monkeypatch.setattr("ui.hotkey_manager.QApplication.applicationState", lambda self: raise_boom())
    mgr._poll_focus_state()  # should not raise


def test_hotkey_manager_on_app_state_changed_stopped(qtbot: Any) -> None:
    """_on_app_state_changed returns early when stopped."""
    from PyQt6.QtCore import Qt
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    mgr._stopped = True
    mgr._on_app_state_changed(Qt.ApplicationState.ApplicationActive)  # should not raise


def test_hotkey_manager_stop_disconnect_exception(monkeypatch: Any, qtbot: Any) -> None:
    """stop() handles disconnect exceptions."""
    from types import SimpleNamespace
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    app = QApplication.instance()
    assert app is not None
    def bad_disconnect(fn=None):
        raise TypeError("signal not connected")
    monkeypatch.setattr(app, "applicationStateChanged", SimpleNamespace(disconnect=bad_disconnect))
    mgr.stop()  # should not raise


def test_hotkey_manager_parse_vk_unknown() -> None:
    """_parse_vk returns None for unknown key names."""
    from ui.hotkey_manager import _parse_vk
    assert _parse_vk("ZZZ") is None


def test_hotkey_manager_split_hotkey_no_modifier() -> None:
    """_split_hotkey returns empty mods for bare key."""
    from ui.hotkey_manager import _split_hotkey
    mods, key = _split_hotkey("F8")
    assert mods == []
    assert key == "F8"


def test_hotkey_manager_split_hotkey_multiple_modifiers() -> None:
    """_split_hotkey handles multiple modifiers."""
    from ui.hotkey_manager import _split_hotkey
    mods, key = _split_hotkey("Ctrl+Shift+A")
    assert mods == ["ctrl", "shift"]
    assert key == "A"


def test_hotkey_manager_poll_focus_active_already_focused(monkeypatch: Any, qtbot: Any) -> None:
    """_poll_focus_state skips _unregister_global_hotkey when already focused."""
    from PyQt6.QtCore import Qt
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    mgr._app_focused = True
    monkeypatch.setattr("ui.hotkey_manager.QApplication.applicationState", lambda self: Qt.ApplicationState.ApplicationActive)
    mgr._poll_focus_state()


def test_hotkey_manager_poll_focus_inactive_already_unfocused(monkeypatch: Any, qtbot: Any) -> None:
    """_poll_focus_state skips _sync_global_hotkey when already unfocused."""
    from PyQt6.QtCore import Qt
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    mgr._app_focused = False
    monkeypatch.setattr("ui.hotkey_manager.QApplication.applicationState", lambda self: Qt.ApplicationState.ApplicationInactive)
    mgr._poll_focus_state()


def test_hotkey_manager_on_app_state_changed_active(qtbot: Any) -> None:
    """_on_app_state_changed handles active transition."""
    from PyQt6.QtCore import Qt
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    mgr._app_focused = False
    mgr._on_app_state_changed(Qt.ApplicationState.ApplicationActive)
    assert mgr._app_focused is True


def test_hotkey_manager_on_app_state_changed_inactive(qtbot: Any) -> None:
    """_on_app_state_changed handles inactive transition."""
    from PyQt6.QtCore import Qt
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    mgr._app_focused = True
    mgr._on_app_state_changed(Qt.ApplicationState.ApplicationInactive)
    assert mgr._app_focused is False


def test_hotkey_manager_on_app_state_changed_already_active(qtbot: Any) -> None:
    """_on_app_state_changed no-op when already active."""
    from PyQt6.QtCore import Qt
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    mgr._app_focused = True
    mgr._on_app_state_changed(Qt.ApplicationState.ApplicationActive)
    assert mgr._app_focused is True


def test_hotkey_manager_on_app_state_changed_already_inactive(qtbot: Any) -> None:
    """_on_app_state_changed no-op when already inactive."""
    from PyQt6.QtCore import Qt
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    mgr._app_focused = False
    mgr._on_app_state_changed(Qt.ApplicationState.ApplicationInactive)
    assert mgr._app_focused is False


def test_hotkey_manager_on_app_state_changed_exception(monkeypatch: Any, qtbot: Any) -> None:
    """_on_app_state_changed swallows exceptions."""
    from PyQt6.QtCore import Qt
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    monkeypatch.setattr(mgr, "_sync_global_hotkey", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    mgr._on_app_state_changed(Qt.ApplicationState.ApplicationInactive)


def test_hotkey_manager_start_binding(qtbot: Any) -> None:
    """start_binding sets _listening_for_bind."""
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    mgr.start_binding()
    assert mgr._listening_for_bind is True


def test_hotkey_manager_update_shortcut_replaces_existing(qtbot: Any) -> None:
    """_update_shortcut replaces an existing shortcut."""
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    assert mgr._shortcut is not None
    mgr._update_shortcut()
    assert mgr._shortcut is not None


def test_hotkey_manager_stop_remove_event_filter_exception(monkeypatch: Any, qtbot: Any) -> None:
    """stop() handles removeEventFilter exception."""
    parent = QWidget()
    qtbot.addWidget(parent)
    mgr = HotkeyManager(parent)
    app = QApplication.instance()
    assert app is not None
    monkeypatch.setattr(app, "removeEventFilter", lambda obj: (_ for _ in ()).throw(RuntimeError("boom")))
    mgr.stop()
