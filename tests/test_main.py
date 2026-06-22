from pathlib import Path
from types import ModuleType
from typing import Any, cast
import runpy
import sys
import os

import main as app_main

app_main = cast(Any, app_main)


def test_main_wires_app_icon_window_and_exec(monkeypatch, tmp_path):
    events = []

    class FakeApp:
        def __init__(self, _argv):
            events.append("app_init")

        def setWindowIcon(self, _icon):
            events.append("app_icon")

        def exec(self):
            events.append("app_exec")
            return 7

    class FakeWindow:
        def __init__(self, app_version=""):
            events.append(("window_init", app_version))

        def setWindowIcon(self, _icon):
            events.append("window_icon")

        def show(self):
            events.append("window_show")

    class FakeIcon:
        def __init__(self, _path):
            events.append("icon_create")

        def __bool__(self):
            return True

    monkeypatch.setattr(app_main, "QApplication", FakeApp)
    monkeypatch.setattr(app_main, "MainWindow", FakeWindow)
    monkeypatch.setattr(app_main, "QIcon", FakeIcon)
    monkeypatch.setattr(app_main, "get_version", lambda: "vX")
    monkeypatch.setattr(app_main, "APP_ID", "jukebox.id")
    monkeypatch.setattr(app_main, "set_app_user_model_id", lambda app_id: events.append(("app_id", app_id)))
    monkeypatch.setattr(app_main.theme, "apply_global_palette", lambda app: events.append("palette"))
    monkeypatch.setattr(app_main, "_resource_dir", lambda: tmp_path)
    monkeypatch.setattr(app_main.sys, "exit", lambda code: events.append(("exit", code)))

    (tmp_path / "icon.ico").write_text("x", encoding="utf-8")
    app_main.main()

    assert ("app_id", "jukebox.id") in events
    assert "icon_create" in events
    assert "app_icon" in events
    assert "window_icon" in events
    assert "window_show" in events
    assert ("exit", 7) in events


def _shared_mem_test(monkeypatch, tmp_path, scenario, expected_events):
    """Run shared-memory scenario and verify events."""
    events = []

    class FakeApp:
        def __init__(self, _argv):
            events.append("app_init")
        def setWindowIcon(self, _icon):
            events.append("app_icon")
        def exec(self):
            return 0

    class FakeWindow:
        def __init__(self, app_version=""):
            events.append("window_init")
        def setWindowIcon(self, _icon):
            events.append("window_icon")
        def show(self):
            events.append("show")

    class FakeSharedMem:
        class SharedMemoryError:
            AlreadyExists = 0
            NoError = 1
            PermissionDenied = 2
        class AccessMode:
            ReadOnly = 0
        def __init__(self, key):
            self._key = key
            self._attached = False
            self._call_count = 0
            self._scenario = scenario
        def create(self, size):
            self._call_count += 1
            if self._scenario in ("already_exists", "already_exists_kill_fails"):
                return False
            if self._scenario == "already_exists_reclaim_fails":
                return self._call_count > 2
            if self._scenario == "other_error":
                return False
            self._attached = True
            return True
        def error(self):
            if self._scenario == "other_error":
                return self.SharedMemoryError.PermissionDenied
            return self.SharedMemoryError.AlreadyExists
        def attach(self, mode):
            if self._scenario in ("already_exists", "already_exists_kill_fails"):
                self._attached = True
                return True
            return False
        def constData(self):
            if not hasattr(self, "_voidptr"):
                self._voidptr = type("VoidPtr", (), {"asstring": lambda self, sz: b"\xab\x00\x00\x00"})()
            return self._voidptr
        def detach(self):
            self._attached = False
            return True
        def isAttached(self):
            return self._attached
        def data(self):
            return None if self._scenario == "attached_data_none" else bytearray(4)

    monkeypatch.setattr(app_main, "QSharedMemory", FakeSharedMem)
    monkeypatch.setattr(app_main, "QApplication", FakeApp)
    monkeypatch.setattr(app_main, "MainWindow", FakeWindow)
    monkeypatch.setattr(app_main, "QIcon", lambda p: object())
    monkeypatch.setattr(app_main, "_resource_dir", lambda: tmp_path)
    monkeypatch.setattr(app_main.theme, "apply_global_palette", lambda _app: None)
    monkeypatch.setattr(app_main, "set_app_user_model_id", lambda _id: events.append("app_id"))
    monkeypatch.setattr(app_main.sys, "exit", lambda _code: events.append("exit"))
    monkeypatch.setattr(app_main, "os", type("OsMock", (), {"getpid": os.getpid, "kill": lambda *a: (_ for _ in ()).throw(ProcessLookupError()) if scenario == "already_exists_kill_fails" else None})())

    app_main.main()

    for ev in expected_events:
        assert ev in events, f"Expected {ev!r} not in {events}"


def test_main_shared_mem_already_exists_kill_fails(monkeypatch, tmp_path):
    """Shared memory AlreadyExists, os.kill raises, reclaim succeeds."""
    _shared_mem_test(monkeypatch, tmp_path, "already_exists_kill_fails", [
        "app_id", "app_init", "window_init", "show",
    ])


def test_main_shared_mem_already_exists_process_alive(monkeypatch, tmp_path):
    """Shared memory AlreadyExists with live process exits early."""
    _shared_mem_test(monkeypatch, tmp_path, "already_exists", [])


def test_main_shared_mem_already_exists_reclaim_fails(monkeypatch, tmp_path):
    """Shared memory AlreadyExists, reclaim fails, continues anyway."""
    _shared_mem_test(monkeypatch, tmp_path, "already_exists_reclaim_fails", [
        "app_id", "app_init", "window_init", "show",
    ])


def test_main_shared_mem_other_error(monkeypatch, tmp_path):
    """Shared memory non-AlreadyExists error continues without guard."""
    _shared_mem_test(monkeypatch, tmp_path, "other_error", [
        "app_id", "app_init", "window_init", "show",
    ])


def test_main_shared_mem_first_try_success(monkeypatch, tmp_path):
    """Shared memory created on first try; writes PID."""
    _shared_mem_test(monkeypatch, tmp_path, "first_try_success", [
        "app_id", "app_init", "window_init", "show", "exit",
    ])


def test_main_shared_mem_attached_data_none(monkeypatch, tmp_path):
    """Shared memory attached but data() returns None; skips PID write."""
    _shared_mem_test(monkeypatch, tmp_path, "attached_data_none", [
        "app_id", "app_init", "window_init", "show", "exit",
    ])


def test_main_without_icon_path(monkeypatch, tmp_path):
    events = []

    class FakeApp:
        def __init__(self, _argv):
            return None

        def setWindowIcon(self, _icon):
            events.append("app_icon")

        def exec(self):
            return 0

    class FakeWindow:
        def __init__(self, app_version=""):
            return None

        def setWindowIcon(self, _icon):
            events.append("window_icon")

        def show(self):
            events.append("show")

    monkeypatch.setattr(app_main, "QApplication", FakeApp)
    monkeypatch.setattr(app_main, "MainWindow", FakeWindow)
    monkeypatch.setattr(app_main, "QIcon", lambda p: object())
    monkeypatch.setattr(app_main, "_resource_dir", lambda: tmp_path)
    monkeypatch.setattr(app_main.theme, "apply_global_palette", lambda _app: None)
    monkeypatch.setattr(app_main, "set_app_user_model_id", lambda _id: None)
    monkeypatch.setattr(app_main.sys, "exit", lambda _code: None)

    app_main.main()

    assert "show" in events
    assert "app_icon" not in events
    assert "window_icon" not in events


def test_main_module_name_guard_invokes_main(monkeypatch, tmp_path):
    events = []

    class FakeApp:
        def __init__(self, _argv):
            events.append("app_init")

        def setWindowIcon(self, _icon):
            events.append("app_icon")

        def exec(self):
            events.append("app_exec")
            return 0

    class FakeWindow:
        def __init__(self, app_version=""):
            events.append(("window_init", app_version))

        def setWindowIcon(self, _icon):
            events.append("window_icon")

        def show(self):
            events.append("show")

    class FakeIcon:
        def __init__(self, _path):
            events.append("icon_create")

        def __bool__(self):
            return True

    fake_main_window = cast(Any, ModuleType("main_window"))
    fake_main_window.MainWindow = FakeWindow
    fake_main_window.APP_ID = "jukebox.id"

    fake_version = cast(Any, ModuleType("version"))
    fake_version.get_version = lambda: "vX"
    fake_version._resource_dir = lambda: tmp_path

    fake_platform_utils = cast(Any, ModuleType("platform_utils"))
    fake_platform_utils.set_app_user_model_id = lambda app_id: events.append(("app_id", app_id))

    fake_theme = cast(Any, ModuleType("theme"))
    fake_theme.apply_global_palette = lambda _app: events.append("palette")

    fake_qt_widgets = cast(Any, ModuleType("PyQt6.QtWidgets"))
    fake_qt_widgets.QApplication = FakeApp

    fake_qt_gui = cast(Any, ModuleType("PyQt6.QtGui"))
    fake_qt_gui.QIcon = FakeIcon

    original_modules = {
        "main_window": sys.modules.get("main_window"),
        "version": sys.modules.get("version"),
        "platform_utils": sys.modules.get("platform_utils"),
        "theme": sys.modules.get("theme"),
        "PyQt6.QtWidgets": sys.modules.get("PyQt6.QtWidgets"),
        "PyQt6.QtGui": sys.modules.get("PyQt6.QtGui"),
    }

    monkeypatch.setattr(sys, "exit", lambda code: events.append(("exit", code)))
    monkeypatch.setitem(sys.modules, "main_window", fake_main_window)
    monkeypatch.setitem(sys.modules, "version", fake_version)
    monkeypatch.setitem(sys.modules, "platform_utils", fake_platform_utils)
    monkeypatch.setitem(sys.modules, "theme", fake_theme)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", fake_qt_widgets)
    monkeypatch.setitem(sys.modules, "PyQt6.QtGui", fake_qt_gui)

    try:
        runpy.run_path(str((Path(__file__).resolve().parent.parent / "main.py")), run_name="__main__")
    finally:
        for name, mod in original_modules.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    assert ("app_id", "jukebox.id") in events
    assert "show" in events
    assert ("exit", 0) in events
