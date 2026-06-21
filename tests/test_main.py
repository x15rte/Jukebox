from pathlib import Path
from types import ModuleType
from typing import Any, cast
import runpy
import sys

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
