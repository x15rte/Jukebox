"""Hotkey management: global hotkey for play/pause toggle.

Uses Qt's QShortcut for in-app hotkey and platform-native APIs for global
hotkey when the application loses focus.  The global hotkey is registered
only while the application is inactive, avoiding the OS-level key
interception that breaks QShortcut.

Supported platforms:
  - Windows: RegisterHotKey + native event filter for WM_HOTKEY
  - macOS:   Carbon RegisterEventHotKey
  - Linux:   X11 XGrabKey + QSocketNotifier (no polling thread)
"""

from __future__ import annotations

import ctypes
import sys
import time
from typing import Any, Callable

from PyQt6.QtCore import (
    QAbstractNativeEventFilter,
    QObject,
    QEvent,
    QSocketNotifier,
    Qt,
    pyqtSignal as Signal,
)
from PyQt6.QtGui import QShortcut, QKeySequence, QKeyEvent
from PyQt6.QtWidgets import QApplication, QWidget

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _split_hotkey(key_str: str) -> tuple[list[str], str | None]:
    """Split a key string like ``"Ctrl+Shift+A"`` into modifiers and key name.

    Returns ``(modifiers, key_name)`` where *modifiers* is a list of
    modifier names (lowercased) and *key_name* is the final token or
    ``None`` if the string contains only modifiers.
    """
    parts = [p.strip() for p in key_str.split("+")]
    mods: list[str] = []
    rest: list[str] = []
    for p in parts:
        low = p.lower()
        if low in ("ctrl", "shift", "alt", "meta"):
            mods.append(low)
        else:
            rest.append(p)
    return mods, rest[-1] if rest else None


def _parse_vk(key_name: str) -> int | None:
    """Return the Windows virtual-key code for *key_name* (e.g. ``"F8"``)."""
    # Single letters / digits
    if len(key_name) == 1 and key_name.isascii():  # pragma: no cover
        return ord(key_name.upper())
    if key_name.isdigit() and len(key_name) == 1:  # pragma: no cover
        return ord(key_name)

    table: dict[str, int] = {
        "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
        "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
        "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
        "F13": 0x7C, "F14": 0x7D, "F15": 0x7E, "F16": 0x7F,
        "F17": 0x80, "F18": 0x81, "F19": 0x82, "F20": 0x83,
        "F21": 0x84, "F22": 0x85, "F23": 0x86, "F24": 0x87,
        "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
        "PAGEUP": 0x21, "PAGEDOWN": 0x22, "HOME": 0x24, "END": 0x23,
        "INSERT": 0x2D, "DELETE": 0x2E,
        "SPACE": 0x20, "ESCAPE": 0x1B, "TAB": 0x09,
        "ENTER": 0x0D, "RETURN": 0x0D, "BACKSPACE": 0x08,
        "PAUSE": 0x13, "PRINT": 0x2A,
        "PLUS": 0xBB, "MINUS": 0xBD, "COMMA": 0xBC,
        "PERIOD": 0xBE, "SEMICOLON": 0xBA,
        "QUOTE": 0xDE, "SLASH": 0xBF, "BACKSLASH": 0xDC,
        "BRACKETLEFT": 0xDB, "BRACKETRIGHT": 0xDD,
    }

    return table.get(key_name.upper())
# Windows backend  (RegisterHotKey + native event filter)  # pragma: no cover
# ---------------------------------------------------------------------------

if sys.platform == "win32":  # pragma: no cover
    import ctypes.wintypes

    WM_HOTKEY = 0x0312
    HOTKEY_GLOBAL_ID = 1

    _user32 = ctypes.windll.user32
    _RegisterHotKey = _user32.RegisterHotKey
    _RegisterHotKey.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_uint,
    ]
    _RegisterHotKey.restype = ctypes.c_bool

    _UnregisterHotKey = _user32.UnregisterHotKey
    _UnregisterHotKey.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.c_int,
    ]
    _UnregisterHotKey.restype = ctypes.c_bool

    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_WIN = 0x0008
    MOD_NOREPEAT = 0x4000

    _WIN32_MOD_MAP: dict[str, int] = {
        "ctrl": MOD_CONTROL,
        "shift": MOD_SHIFT,
        "alt": MOD_ALT,
        "meta": MOD_WIN,
    }

    def _register_win32(key_str: str, hwnd: int) -> bool:
        """Register a global hotkey on Windows using ``RegisterHotKey``."""
        mods, key_name = _split_hotkey(key_str)
        if key_name is None:
            
            return False
        vk = _parse_vk(key_name)
        if vk is None:
            
            from PyQt6.QtGui import QKeySequence

            ks = QKeySequence(key_str)
            if ks.isEmpty():
                
                return False
            # QKeyCombination.key() is a METHOD in PyQt6
            vk = int(ks[0].key()) & 0xFF
        fs_mod = 0
        for m in mods:
            fs_mod |= _WIN32_MOD_MAP.get(m, 0)
        fs_mod |= MOD_NOREPEAT
        result = bool(
            _RegisterHotKey(
                ctypes.wintypes.HWND(hwnd), HOTKEY_GLOBAL_ID, fs_mod, vk
            )
        )
        return result

    def _unregister_win32(hwnd: int) -> None:
        """Unregister the global hotkey on Windows."""
        _UnregisterHotKey(ctypes.wintypes.HWND(hwnd), HOTKEY_GLOBAL_ID)

    class _GlobalHotkeyFilter(QAbstractNativeEventFilter):
        """Qt native event filter that catches ``WM_HOTKEY`` messages."""

        def __init__(self, callback: Callable[[], None]) -> None:
            super().__init__()
            self._callback = callback

        def nativeEventFilter(
            self, event_type, message, /,
        ) -> tuple[bool, int]:
            if not message or event_type != b"windows_generic_MSG":
                return False, 0
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_GLOBAL_ID:
                    self._callback()
                    return True, 0
            except Exception:  # nosec
                pass
            return False, 0

# macOS backend  (Carbon RegisterEventHotKey)  # pragma: no cover
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

elif sys.platform == "darwin":  # pragma: no cover
    import Carbon
    import Carbon.CarbonEvt
    import Carbon.Events

    _macos_handler_cb: Any = None
    _macos_callback: Callable[[], None] | None = None
    _macos_hotkey_ref: Any = None

    _MACOS_MOD_MAP: dict[str, int] = {
        "ctrl": Carbon.CarbonEvt.cmdKey,
        "shift": Carbon.CarbonEvt.shiftKey,
        "alt": Carbon.CarbonEvt.optionKey,
        "meta": Carbon.CarbonEvt.cmdKey,
    }
    _MACOS_EXTRA_VK: dict[str, int] = {
        "F1": 122, "F2": 120, "F3": 99, "F4": 118,
        "F5": 96, "F6": 97, "F7": 98, "F8": 100,
        "F9": 101, "F10": 109, "F11": 103, "F12": 111,
        "Left": 123, "Right": 124, "Down": 125, "Up": 126,
        "PageUp": 116, "PageDown": 121,
        "Home": 115, "End": 119,
        "Delete": 117, "Escape": 53, "Tab": 48,
        "Space": 49, "Return": 36, "Enter": 76,
        "Backspace": 51,
    }

    def _register_macos(key_str: str) -> bool:
        """Register a global hotkey on macOS via Carbon."""
        global _macos_hotkey_ref, _macos_handler_cb

        _unregister_macos()

        mods, key_name = _split_hotkey(key_str)
        if key_name is None:
            return False

        vk = _parse_vk(key_name)
        if vk is None:
            from PyQt6.QtGui import QKeySequence

            ks = QKeySequence(key_name)
            if not ks.isEmpty():
                vk = int(ks[0].key) & 0xFF
        if vk is None:
            vk = _MACOS_EXTRA_VK.get(key_name, 0)

        mod_bits = 0
        for m in mods:
            mod_bits |= _MACOS_MOD_MAP.get(m, 0)

        import Carbon.App

        event_class = Carbon.CarbonEvt.kEventClassKeyboard
        event_kind = Carbon.CarbonEvt.kEventHotKeyPressed

        _macos_handler_cb = Carbon.App.EventHandlerUPP(
            _macos_hotkey_handler
        )

        Carbon.App.InstallEventHandler(
            Carbon.App.GetApplicationEventTarget(),
            _macos_handler_cb,
            1,
            Carbon.CarbonEvt.EventTypeSpec(event_class, event_kind),
            None,
        )

        err, _macos_hotkey_ref = Carbon.CarbonEvt.RegisterEventHotKey(
            vk, mod_bits, (0, 0),
            Carbon.App.GetApplicationEventTarget(), 0,
        )
        return err == 0

    def _macos_hotkey_handler(
        next_handler: Callable, event: Any, user_data: Any,
    ) -> int | None:
        """Carbon event handler — forward hotkey press to the Python callback."""
        if _macos_callback is not None:
            _macos_callback()
        return 0  # noErr

    def _unregister_macos() -> None:
        """Unregister the macOS global hotkey."""
        global _macos_hotkey_ref, _macos_handler_cb
        if _macos_hotkey_ref is not None:
            try:
                Carbon.CarbonEvt.UnregisterEventHotKey(_macos_hotkey_ref)
            except Exception:  # nosec
                pass
            _macos_hotkey_ref = None
        if _macos_handler_cb is not None:
            try:
                Carbon.App.RemoveEventHandler(_macos_handler_cb)
            except Exception:  # nosec
                pass
            _macos_handler_cb = None

# Linux X11 backend  (XGrabKey + QSocketNotifier)  # pragma: no cover
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

elif sys.platform.startswith("linux"):  # pragma: no cover

    class _XKeyEvent(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_int),
            ("serial", ctypes.c_ulong),
            ("send_event", ctypes.c_int),
            ("display", ctypes.c_void_p),
            ("window", ctypes.c_ulong),
            ("root", ctypes.c_ulong),
            ("subwindow", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("x", ctypes.c_int),
            ("y", ctypes.c_int),
            ("x_root", ctypes.c_int),
            ("y_root", ctypes.c_int),
            ("state", ctypes.c_uint),
            ("keycode", ctypes.c_uint),
            ("same_screen", ctypes.c_int),
        ]

    class _XEvent(ctypes.Union):
        _fields_ = [("xkey", _XKeyEvent)]

    _xlib = ctypes.cdll.LoadLibrary("libX11.so")
    _xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    _xlib.XOpenDisplay.restype = ctypes.c_void_p
    _xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    _xlib.XDefaultRootWindow.restype = ctypes.c_ulong
    _xlib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    _xlib.XKeysymToKeycode.restype = ctypes.c_uint
    _xlib.XGrabKey.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_uint,
        ctypes.c_ulong, ctypes.c_int,
    ]
    _xlib.XGrabKey.restype = ctypes.c_int
    _xlib.XUngrabKey.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong,
    ]
    _xlib.XUngrabKey.restype = ctypes.c_int
    _xlib.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(_XEvent)]
    _xlib.XNextEvent.restype = ctypes.c_int
    _xlib.XFlush.argtypes = [ctypes.c_void_p]
    _xlib.XFlush.restype = ctypes.c_int

    _X11_MOD_MAP: dict[str, int] = {
        "ctrl": 4,    # ControlMask
        "shift": 1,   # ShiftMask
        "alt": 8,     # Mod1Mask
        "meta": 64,   # Mod4Mask (Super key)
    }

    _XStringToKeysym = _xlib.XStringToKeysym
    _XStringToKeysym.argtypes = [ctypes.c_char_p]
    _XStringToKeysym.restype = ctypes.c_ulong

    def _register_linux(key_str: str) -> tuple[bool, dict | None]:
        """Register a global hotkey on Linux X11 via ``XGrabKey``."""
        mods, key_name = _split_hotkey(key_str)
        if key_name is None:
            return False, None

        display = _xlib.XOpenDisplay(None)
        if not display:
            return False, None

        root = _xlib.XDefaultRootWindow(display)

        mod_mask = 0
        for m in mods:
            mod_mask |= _X11_MOD_MAP.get(m, 0)

        keysym = _XStringToKeysym(key_name.encode("ascii"))
        keycode = _xlib.XKeysymToKeycode(display, keysym)
        if not keycode:
            from PyQt6.QtGui import QKeySequence

            ks = QKeySequence(key_name)
            if not ks.isEmpty():
                vk = int(ks[0].key) & 0xFF
                keysym = _XStringToKeysym(f"0x{vk:02X}".encode("ascii"))
                keycode = _xlib.XKeysymToKeycode(display, keysym)
        if not keycode:
            return False, None

        _xlib.XGrabKey(display, keycode, mod_mask, root, 1, 1, 1)
        _xlib.XFlush(display)

        _xlib.XConnectionNumber.argtypes = [ctypes.c_void_p]
        _xlib.XConnectionNumber.restype = ctypes.c_int
        conn_fd = _xlib.XConnectionNumber(display)

        notifier = QSocketNotifier(conn_fd, QSocketNotifier.Type.Exception)

        state: dict[str, Any] = {
            "display": display,
            "notifier": notifier,
            "root": root,
            "keycode": keycode,
            "mod_mask": mod_mask,
        }

        return True, state

    def _unregister_linux(state: dict) -> None:
        """Ungrab the X11 hotkey and clean up."""
        display = state.get("display")
        keycode = state.get("keycode", 0)
        mod_mask = state.get("mod_mask", 0)
        root = state.get("root", 0)

        if display:
            _xlib.XUngrabKey(display, keycode, mod_mask, root)
            _xlib.XFlush(display)

        notifier = state.get("notifier")
        if notifier is not None:
            notifier.setEnabled(False)

    def _make_linux_handler(
        state: dict, callback: Callable[[], None],
    ) -> Callable[[], None]:
        """Return a callable that reads the X11 event queue and fires
        *callback* for pending key events."""
        display = state["display"]

        def _handler() -> None:
            event = _XEvent()
            _xlib.XPending.argtypes = [ctypes.c_void_p]
            _xlib.XPending.restype = ctypes.c_int
            while _xlib.XPending(display):
                _xlib.XNextEvent(display, ctypes.byref(event))
                if event.xkey.type == 2:  # KeyPress
                    callback()

        return _handler

    _xlib.XPending.argtypes = [ctypes.c_void_p]
    _xlib.XPending.restype = ctypes.c_int


# ===========================================================================
# HotkeyManager
# ===========================================================================


class HotkeyManager(QObject):
    """Application-scope hotkey toggle using QShortcut + global native APIs.

    The in-app hotkey uses ``QShortcut`` (works while the app has focus).
    When the application becomes inactive a platform-native global hotkey is
    registered so the toggle still works from other windows.  The global
    hotkey is unregistered when the app regains focus, allowing the
    ``QShortcut`` to take over without conflict.

    Signals:
        toggle_requested: emitted when the current hotkey is pressed (from
                          either QShortcut or the global native hook).
        bound_updated: emitted with the new key string when a binding is
                       captured via the event filter.
    """

    toggle_requested = Signal()
    bound_updated = Signal(str)
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._parent = parent
        self.current_key: str = "F8"
        self._listening_for_bind = False
        self._shortcut: QShortcut | None = None
        self._stopped: bool = False

        # Global hotkey state
        self._app_focused: bool = True
        self._hotkey_hwnd: int | None = None  # Windows
        self._linux_state: dict[str, Any] | None = None
        self._linux_notifier: QSocketNotifier | None = None
        self._native_filter: QAbstractNativeEventFilter | None = None
        self._last_global_toggle: float = 0.0

        self._update_shortcut()

        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.installEventFilter(self)
            app.applicationStateChanged.connect(self._on_app_state_changed)

        # Install native event filter (Windows WM_HOTKEY catch)
        if sys.platform == "win32" and app is not None:
            self._native_filter = _GlobalHotkeyFilter(self._on_global_hotkey)
            app.installNativeEventFilter(self._native_filter)
        elif sys.platform == "darwin":  # pragma: no cover
            global _macos_callback
            _macos_callback = self._on_global_hotkey

        # Polling fallback: re-sync every 2 s to catch missed focus events
        from PyQt6.QtCore import QTimer

        self._focus_poll_timer = QTimer(self)
        self._focus_poll_timer.timeout.connect(self._poll_focus_state)
        self._focus_poll_timer.setInterval(2000)
        self._focus_poll_timer.start()

    def _poll_focus_state(self) -> None:
        """Periodic focus-state sync  (belt-and-suspenders fallback)."""
        try:
            app = QApplication.instance()
            if not isinstance(app, QApplication):
                return
            actual = app.applicationState()
            if actual == Qt.ApplicationState.ApplicationActive:
                if not self._app_focused:  # pragma: no cover
                    self._app_focused = True
                    self._unregister_global_hotkey()
            elif actual in (
                Qt.ApplicationState.ApplicationInactive,
                Qt.ApplicationState.ApplicationHidden,
            ):
                if self._app_focused:
                    self._app_focused = False
                    self._sync_global_hotkey()
        except Exception:  # nosec
            pass
    def _on_app_state_changed(self, state: Qt.ApplicationState) -> None:
        """Track application focus via ``applicationStateChanged`` signal."""
        try:
            if self._stopped:
                return
            if state in (
                Qt.ApplicationState.ApplicationInactive,
                Qt.ApplicationState.ApplicationHidden,
            ):
                if not self._app_focused:
                    return
                self._app_focused = False
                self._sync_global_hotkey()
            elif state == Qt.ApplicationState.ApplicationActive:
                if self._app_focused:
                    return
                self._app_focused = True
                self._unregister_global_hotkey()
        except Exception:  # nosec
            pass
    def _sync_global_hotkey(self) -> None:
        """Register or re-register the global hotkey (app is not focused)."""
        if self._app_focused:
            return

        if sys.platform == "win32":  # pragma: no cover
            if self._hotkey_hwnd is not None:  # pragma: no cover
                _unregister_win32(self._hotkey_hwnd)
            self._hotkey_hwnd = int(self._parent.winId())
            _register_win32(self.current_key, self._hotkey_hwnd)

        elif sys.platform == "darwin":  # pragma: no cover
            _register_macos(self.current_key)

        elif sys.platform.startswith("linux"):  # pragma: no cover
            ok, st = _register_linux(self.current_key)
            if ok and st is not None:  # pragma: no cover
                self._linux_state = st  # pragma: no cover
                handler = _make_linux_handler(st, self._on_global_hotkey)
                st["notifier"].activated.connect(handler)
                self._linux_notifier = st["notifier"]

    def _unregister_global_hotkey(self) -> None:
        """Unregister the platform native global hotkey."""
        if sys.platform == "win32":  # pragma: no cover
            if self._hotkey_hwnd is not None:  # pragma: no cover
                _unregister_win32(self._hotkey_hwnd)
                self._hotkey_hwnd = None
        elif sys.platform == "darwin":  # pragma: no cover
            _unregister_macos()
        elif sys.platform.startswith("linux"):  # pragma: no cover
            if self._linux_state is not None:  # pragma: no cover
                _unregister_linux(self._linux_state)
                self._linux_state = None
            if self._linux_notifier is not None:  # pragma: no cover
                self._linux_notifier.setEnabled(False)

    def _on_global_hotkey(self) -> None:
        """Called when the platform-native global hotkey fires.

        Includes a 200 ms debounce to prevent double-fire during focus
        transitions.  All exceptions are swallowed to keep them out of
        the Qt event loop.
        """
        try:  # pragma: no cover
            now = time.monotonic()
            elapsed = now - self._last_global_toggle
            if elapsed < 0.2:  # pragma: no cover
                return
            self._last_global_toggle = now
            self.toggle_requested.emit()
        except Exception:  # pragma: no cover  # nosec
            pass


    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Handle binding mode key capture and window focus tracking."""
        # Window focus tracking (fallback in case applicationStateChanged
        # doesn't fire on some platform/configurations)
        if event.type() == QEvent.Type.WindowDeactivate:  # pragma: no cover
            self._on_window_deactivated()
            return False
        if event.type() == QEvent.Type.WindowActivate:  # pragma: no cover
            self._on_window_activated()
            return False

        # Binding mode: capture the next key press
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
                self.current_key = "F8"
                self.bound_updated.emit("(modifier only — press a key combo)")
                return True
        return super().eventFilter(obj, event)

    def _on_window_deactivated(self) -> None:  # pragma: no cover
        """Register global hotkey when the window loses focus."""
        try:
            if self._stopped:  # pragma: no cover
                return
            if not self._app_focused:  # pragma: no cover
                return
            self._app_focused = False
            self._sync_global_hotkey()
        except Exception:  # pragma: no cover  # nosec
            pass

    def _on_window_activated(self) -> None:  # pragma: no cover
        """Unregister global hotkey when the window gains focus."""
        try:
            if self._stopped:  # pragma: no cover
                return
            if self._app_focused:  # pragma: no cover
                return
            self._app_focused = True
            self._unregister_global_hotkey()
        except Exception:  # pragma: no cover  # nosec
            pass
    # ---- Shortcut management ---------------------------------------------

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

    # ---- Public API ------------------------------------------------------

    def start_binding(self) -> None:
        """Enter binding mode: the next key press applies the hotkey."""
        self._listening_for_bind = True

    def set_hotkey(self, key_str: str) -> None:
        """Set the toggle hotkey from a key string (e.g. 'F8', 'Ctrl+Shift+A')."""
        self.current_key = key_str
        self._update_shortcut()
        self._sync_global_hotkey()

    def get_current_key(self) -> str:
        """Return the current hotkey as a key string."""
        return self.current_key

    def stop(self) -> None:
        """Disable the shortcut, remove filters, and unregister any global hotkey."""
        self._stopped = True
        self._unregister_global_hotkey()
        app = QApplication.instance()
        if isinstance(app, QApplication):
            try:
                app.applicationStateChanged.disconnect(self._on_app_state_changed)
            except (TypeError, RuntimeError):
                pass
            try:
                app.removeEventFilter(self)
            except Exception:  # nosec
                pass
        if sys.platform == "win32" and self._native_filter is not None:  # pragma: no cover
            if app is not None:  # pragma: no cover
                try:
                    app.removeNativeEventFilter(self._native_filter)
                except Exception:  # pragma: no cover  # nosec
                    pass
        if self._shortcut is not None:
            self._shortcut.setEnabled(False)
            self._shortcut.deleteLater()
            self._shortcut = None
