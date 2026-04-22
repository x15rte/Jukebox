import platform_utils as pu


def test_set_app_user_model_id_noop_on_non_windows(monkeypatch):
    monkeypatch.setattr(pu.sys, "platform", "linux")
    pu.set_app_user_model_id("jukebox.test")


def test_set_app_user_model_id_calls_ctypes_on_windows(monkeypatch):
    monkeypatch.setattr(pu.sys, "platform", "win32")
    called = []

    class Shell32:
        def SetCurrentProcessExplicitAppUserModelID(self, app_id):
            called.append(app_id)

    class Windll:
        shell32 = Shell32()

    class Ctypes:
        windll = Windll()

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "ctypes":
            return Ctypes()
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    pu.set_app_user_model_id("jukebox.test")
    if not (called == ["jukebox.test"]):
        raise AssertionError("Assertion failed")


def test_set_app_user_model_id_swallows_import_error(monkeypatch):
    monkeypatch.setattr(pu.sys, "platform", "win32")
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "ctypes":
            raise ImportError("no ctypes")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    pu.set_app_user_model_id("x")


def test_get_capabilities_windows_and_non_windows(monkeypatch):
    monkeypatch.setattr(pu, "has_high_res_timer", lambda: True)

    monkeypatch.setattr(pu.sys, "platform", "win32")
    monkeypatch.setattr(pu, "_check_pydirectinput", lambda: True)
    caps = pu.get_capabilities()
    if not (caps["platform"] == "win32"):
        raise AssertionError("Assertion failed")
    if not (caps["high_res_timer"] is True):
        raise AssertionError("Assertion failed")
    if not (caps["pydirectinput"] is True):
        raise AssertionError("Assertion failed")
    if not (caps["direct_input"] is True):
        raise AssertionError("Assertion failed")

    monkeypatch.setattr(pu.sys, "platform", "darwin")
    caps2 = pu.get_capabilities()
    if not (caps2["pydirectinput"] is False):
        raise AssertionError("Assertion failed")
    if not (caps2["direct_input"] is False):
        raise AssertionError("Assertion failed")


def test_check_pydirectinput_true_and_exception(monkeypatch):
    import importlib

    class Mod:
        @staticmethod
        def is_using_pydirectinput():
            return 1

    monkeypatch.setattr(importlib, "import_module", lambda name: Mod())
    if not (pu._check_pydirectinput() is True):
        raise AssertionError("Assertion failed")

    monkeypatch.setattr(importlib, "import_module", lambda name: (_ for _ in ()).throw(RuntimeError("boom")))
    if not (pu._check_pydirectinput() is False):
        raise AssertionError("Assertion failed")
