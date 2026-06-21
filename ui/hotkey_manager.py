"""Hotkey management: global hotkey for play/pause toggle via Qt QShortcut.

Uses Qt's QShortcut for the toggle hotkey (no global hooks, no AV false positives).
Binding mode captures the next key press via a QApplication event filter.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QEvent, Qt, pyqtSignal as Signal
from PyQt6.QtGui import QShortcut, QKeySequence, QKeyEvent
from PyQt6.QtWidgets import QApplication, QWidget



class HotkeyManager(QObject):
    """Application-scope hotkey toggle using QShortcut.

    Signals:
        toggle_requested: emitted when the current hotkey is pressed.
        bound_updated: emitted with the new key string when a binding is captured.
    """

    toggle_requested = Signal()
    bound_updated = Signal(str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._parent = parent
        self.current_key: str = "F8"
        self._listening_for_bind = False
        self._shortcut: QShortcut | None = None
        self._update_shortcut()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Capture key press during binding mode."""
        if self._listening_for_bind and event.type() == QEvent.Type.KeyPress:
            ke: QKeyEvent = event  # type: ignore[assignment]
            if ke.isAutoRepeat():
                return False
            key = ke.key()
            mods = ke.modifiers()
            ks = QKeySequence(int(key) | mods.value)
            key_str = ks.toString(QKeySequence.SequenceFormat.NativeText)
            if key_str:
                self._listening_for_bind = False
                self.current_key = key_str
                self._update_shortcut()
                self.bound_updated.emit(key_str)
                return True
            else:
                self._listening_for_bind = False
                # Modifier-only keys (Ctrl, Shift, Alt) cannot be used as hotkeys.
                self.current_key = "F8"  # keep previous
                self.bound_updated.emit("(modifier only — press a key combo)")
                return True
        return super().eventFilter(obj, event)

    def _update_shortcut(self) -> None:
        """Replace the QShortcut with one for the current key."""
        if self._shortcut is not None:
            self._shortcut.setEnabled(False)
            self._shortcut.deleteLater()
        ks = QKeySequence(self.current_key)
        self._shortcut = QShortcut(ks, self._parent)
        self._shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._shortcut.activated.connect(self.toggle_requested.emit)

    @staticmethod
    def format_key_string(key_str: str) -> str:
        """Return the key string as-is (already display-ready from QKeySequence)."""
        return key_str

    def start_binding(self) -> None:
        """Enter binding mode: the next key press applies the hotkey."""
        self._listening_for_bind = True

    def set_hotkey(self, key_str: str) -> None:
        """Set the toggle hotkey from a key string (e.g. 'F8', 'Ctrl+Shift+A')."""
        self.current_key = key_str
        self._update_shortcut()

    def get_current_key(self) -> str:
        """Return the current hotkey as a key string."""
        return self.current_key
    def stop(self) -> None:
        """Disable the shortcut and remove event filter. Called during shutdown."""
        app = QApplication.instance()
        if self._shortcut is not None:
            self._shortcut.setEnabled(False)
            self._shortcut.deleteLater()
            self._shortcut = None
        if app is not None:
            app.removeEventFilter(self)
