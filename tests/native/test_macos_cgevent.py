import importlib
from typing import Any, cast

import native.macos_cgevent as mc

mc = cast(Any, mc)


def _fresh_module():
    return cast(Any, importlib.reload(mc))


def test_macos_vk_initialized_on_darwin_import(monkeypatch):
    import builtins

    mod = cast(Any, _fresh_module())
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    real_import = builtins.__import__

    def imp(name, *args, **kwargs):
        if name == "native.macos_cgevent":
            fresh = real_import(name, *args, **kwargs)
            return importlib.reload(fresh)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", imp)
    fresh_mod = __import__("native.macos_cgevent", fromlist=["*"])
    assert fresh_mod._MACOS_VK


def test_accessibility_trusted_non_darwin(monkeypatch):
    mod = cast(Any, _fresh_module())
    monkeypatch.setattr(mod.sys, "platform", "win32")
    assert mod.is_macos_accessibility_trusted() is True


def test_accessibility_trusted_darwin_success_and_failure(monkeypatch):
    mod = cast(Any, _fresh_module())
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    class Fn:
        def __init__(self, out=True):
            self.argtypes = None
            self.restype = None
            self._out = out

        def __call__(self, _opts):
            return self._out

    class AppServices:
        def __init__(self):
            self.AXIsProcessTrustedWithOptions = Fn(True)

    class CtypesOK:
        c_void_p = object
        c_bool = bool

        @staticmethod
        def CDLL(_p):
            return AppServices()

    import builtins

    real_import = builtins.__import__

    def imp_ok(name, *args, **kwargs):
        if name == "ctypes":
            return CtypesOK
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", imp_ok)
    assert mod.is_macos_accessibility_trusted() is True

    def imp_fail(name, *args, **kwargs):
        if name == "ctypes":
            raise ImportError("no ctypes")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", imp_fail)
    assert mod.is_macos_accessibility_trusted() is True


def test_open_accessibility_preferences_paths(monkeypatch):
    mod = cast(Any, _fresh_module())
    monkeypatch.setattr(mod.sys, "platform", "linux")
    mod.open_macos_accessibility_preferences()

    monkeypatch.setattr(mod.sys, "platform", "darwin")
    calls = []
    monkeypatch.setattr(mod.shutil, "which", lambda _n: None)
    monkeypatch.setattr(mod.subprocess, "run", lambda args, **k: calls.append((args, k)))

    mod.open_macos_accessibility_preferences()
    assert calls
    assert calls[0][0][0] == "/usr/bin/open"

    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("x")),
    )
    mod.open_macos_accessibility_preferences()


def test_init_macos_cgevent_non_darwin(monkeypatch):
    mod = cast(Any, _fresh_module())
    monkeypatch.setattr(mod.sys, "platform", "win32")
    assert mod._init_macos_cgevent() is False


def test_init_macos_cgevent_success_and_cached(monkeypatch):
    mod = cast(Any, _fresh_module())
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    class Fn:
        def __init__(self):
            self.argtypes = None
            self.restype = None

        def __call__(self, *_a):
            return 1

    class Ctypes:
        c_uint32 = int
        c_void_p = int
        c_uint16 = int
        c_uint8 = int
        c_uint64 = int

        @staticmethod
        def CDLL(_p):
            return type(
                "Lib",
                (),
                {
                    "CGEventSourceCreate": Fn(),
                    "CGEventCreateKeyboardEvent": Fn(),
                    "CGEventSetFlags": Fn(),
                    "CGEventPost": Fn(),
                    "CFRelease": Fn(),
                },
            )()

    import builtins

    real_import = builtins.__import__

    def imp_ok(name, *args, **kwargs):
        if name == "ctypes":
            return Ctypes
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", imp_ok)

    assert mod._init_macos_cgevent() is True
    assert mod._init_macos_cgevent() is True


def test_init_macos_cgevent_failure(monkeypatch):
    mod = cast(Any, _fresh_module())
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    import builtins

    real_import = builtins.__import__

    def imp_fail(name, *args, **kwargs):
        if name == "ctypes":
            raise ImportError("no ctypes")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", imp_fail)
    assert mod._init_macos_cgevent() is False


def test_get_macos_vk_for_key_and_modifier_paths(monkeypatch):
    mod = cast(Any, _fresh_module())

    monkeypatch.setattr(mod.sys, "platform", "win32")
    assert mod.get_macos_vk_for_key("a") is None
    assert mod.get_macos_vk_for_modifier(type("K", (), {"name": "shift"})()) is None

    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod, "_MACOS_VK", {"a": 1, "space": 2, "control": 3, "shift": 4})

    assert mod.get_macos_vk_for_key("A") == 1
    assert mod.get_macos_vk_for_key(type("K", (), {"name": "space"})()) == 2
    assert mod.get_macos_vk_for_key(type("K", (), {"name": "ctrl"})()) == 3
    assert mod.get_macos_vk_for_key(type("K", (), {"name": "zzz"})()) is None

    assert mod.get_macos_vk_for_modifier(type("K", (), {"name": "shift"})()) == 4
    assert mod.get_macos_vk_for_modifier(type("K", (), {"name": "ctrl"})()) == 3
    assert mod.get_macos_vk_for_modifier(type("K", (), {"name": "zzz"})()) is None
    assert mod.get_macos_vk_for_modifier(object()) is None


def test_post_macos_key_event_non_darwin_and_init_fail(monkeypatch):
    mod = cast(Any, _fresh_module())
    monkeypatch.setattr(mod.sys, "platform", "linux")
    assert mod.post_macos_key_event(10, True, 0) is False

    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod, "_init_macos_cgevent", lambda: False)
    assert mod.post_macos_key_event(10, True, 0) is False


def test_post_macos_key_event_source_or_event_missing(monkeypatch):
    mod = cast(Any, _fresh_module())
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod, "_init_macos_cgevent", lambda: True)

    class Core:
        def __init__(self):
            self.released = []

        def CFRelease(self, obj):
            self.released.append(obj)

    core = Core()

    class AppNoSource:
        def CGEventSourceCreate(self, _s):
            return 0

    mod._macos_app_services = AppNoSource()
    mod._macos_core_foundation = core
    assert mod.post_macos_key_event(12, True, 0) is False

    class AppNoEvent:
        def CGEventSourceCreate(self, _s):
            return 11

        def CGEventCreateKeyboardEvent(self, _src, _kc, _kd):
            return 0

    mod._macos_app_services = AppNoEvent()
    assert mod.post_macos_key_event(12, False, 0) is False
    assert 11 in core.released


def test_post_macos_key_event_success_and_exception(monkeypatch):
    mod = cast(Any, _fresh_module())
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod, "_init_macos_cgevent", lambda: True)

    class Core:
        def __init__(self):
            self.released = []

        def CFRelease(self, obj):
            self.released.append(obj)

    class App:
        def __init__(self):
            self.flags = []
            self.posts = []

        def CGEventSourceCreate(self, _s):
            return 21

        def CGEventCreateKeyboardEvent(self, _src, _kc, _kd):
            return 22

        def CGEventSetFlags(self, _event, flags):
            self.flags.append(flags)

        def CGEventPost(self, tap, event):
            self.posts.append((tap, event))

    app = App()
    core = Core()
    mod._macos_app_services = app
    mod._macos_core_foundation = core

    assert mod.post_macos_key_event(42, True, 123) is True
    assert app.flags == [123]
    assert app.posts
    assert 22 in core.released and 21 in core.released

    class AppBoom(App):
        def CGEventSourceCreate(self, _s):
            raise RuntimeError("boom")

    mod._macos_app_services = AppBoom()
    assert mod.post_macos_key_event(42, False, 0) is False
