import importlib

import native.timer_utils as tu


def test_set_and_restore_timer_resolution_no_winmm(monkeypatch):
    monkeypatch.setattr(tu, "_winmm", None)
    tu.set_timer_resolution(1)
    tu.restore_timer_resolution(1)


def test_set_timer_resolution_handles_exception(monkeypatch):
    class W:
        def timeBeginPeriod(self, _ms):
            raise RuntimeError("x")

    monkeypatch.setattr(tu, "_winmm", W())
    tu.set_timer_resolution(2)


def test_restore_timer_resolution_handles_exception(monkeypatch):
    class W:
        def timeEndPeriod(self, _ms):
            raise RuntimeError("x")

    monkeypatch.setattr(tu, "_winmm", W())
    tu.restore_timer_resolution(2)


def test_precise_sleep_non_positive_returns_immediately():
    tu.precise_sleep(0)
    tu.precise_sleep(-1)


def test_precise_sleep_paths(monkeypatch):
    seq = [0.0, 0.001, 0.002, 0.0035, 0.005]
    sleeps = []

    monkeypatch.setattr(tu.time, "perf_counter", lambda: seq.pop(0) if seq else 0.01)
    monkeypatch.setattr(tu.time, "sleep", lambda s: sleeps.append(s))

    tu.precise_sleep(0.003)
    if not (sleeps and sleeps[0] == 0.001):
        raise AssertionError("Assertion failed")


def test_has_high_res_timer_reflects_winmm(monkeypatch):
    monkeypatch.setattr(tu, "_winmm", object())
    if not (tu.has_high_res_timer() is True):
        raise AssertionError("Assertion failed")
    monkeypatch.setattr(tu, "_winmm", None)
    if not (tu.has_high_res_timer() is False):
        raise AssertionError("Assertion failed")


def test_import_sets_winmm_none_on_ctypes_failure(monkeypatch):
    import builtins

    real_import = builtins.__import__

    class CtypesBroken:
        class Windll:
            @property
            def winmm(self):
                raise OSError("nope")

        windll = Windll()

    def fake_import(name, *args, **kwargs):
        if name == "ctypes":
            return CtypesBroken
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(tu.sys, "platform", "win32")
    monkeypatch.setattr(builtins, "__import__", fake_import)

    mod = importlib.reload(tu)
    try:
        if not (mod._winmm is None):
            raise AssertionError("Assertion failed")
    finally:
        importlib.reload(mod)
