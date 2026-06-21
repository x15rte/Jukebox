import importlib
import threading

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
    monkeypatch.setattr(tu, "_timer_resolution_refs", 1)
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
    assert sleeps and sleeps[0] == 0.001


def test_has_high_res_timer_reflects_winmm(monkeypatch):
    monkeypatch.setattr(tu, "_winmm", object())
    assert tu.has_high_res_timer() is True
    monkeypatch.setattr(tu, "_winmm", None)
    assert tu.has_high_res_timer() is False


def test_set_timer_resolution_success_path(monkeypatch):
    """set_timer_resolution with a fake winmm that succeeds."""
    calls = []
    class Winmm:
        def timeBeginPeriod(self, ms):
            calls.append(ms)
    monkeypatch.setattr(tu, "_winmm", Winmm())
    monkeypatch.setattr(tu, "_timer_resolution_refs", 0)
    monkeypatch.setattr(tu, "_timer_resolution_ms", 1)
    tu.set_timer_resolution(2)
    assert calls == [2]


def test_restore_timer_resolution_success_path(monkeypatch):
    """restore_timer_resolution with refs > 0 calls timeEndPeriod."""
    calls = []
    class Winmm:
        def timeEndPeriod(self, ms):
            calls.append(ms)
    monkeypatch.setattr(tu, "_winmm", Winmm())
    monkeypatch.setattr(tu, "_timer_resolution_refs", 1)
    monkeypatch.setattr(tu, "_timer_resolution_ms", 1)
    tu.restore_timer_resolution(1)
    assert calls == [1]


def test_set_timer_resolution_already_active(monkeypatch):
    """When _timer_resolution_refs > 0, set_timer_resolution only increments."""
    monkeypatch.setattr(tu, "_winmm", object())
    monkeypatch.setattr(tu, "_timer_resolution_refs", 2)
    tu.set_timer_resolution(3)
    assert tu._timer_resolution_refs == 3  # 2 + 1


def test_restore_timer_resolution_when_zero(monkeypatch):
    """restore_timer_resolution is no-op when _timer_resolution_refs is 0."""
    monkeypatch.setattr(tu, "_winmm", object())
    monkeypatch.setattr(tu, "_timer_resolution_refs", 0)
    tu.restore_timer_resolution(1)
    assert tu._timer_resolution_refs == 0


_RAMP_STEP = 0.0005


class _RampingClock:
    """Returns increasing perf_counter values."""
    def __init__(self):
        self._t = -0.02
    def __call__(self):
        self._t += _RAMP_STEP
        return self._t


def test_precise_sleep_coarse_loop_stop_event(monkeypatch):
    """precise_sleep coarse loop with stop_event, entering the loop body."""
    monkeypatch.setattr(tu.time, "perf_counter", _RampingClock())
    sleeps = []
    monkeypatch.setattr(tu.time, "sleep", lambda s: sleeps.append(s))
    stop = threading.Event()
    tu.precise_sleep(0.004, stop_event=stop)
    assert sleeps


def test_precise_sleep_coarse_loop_both_events(monkeypatch):
    """precise_sleep coarse loop with both stop and pause events."""
    monkeypatch.setattr(tu.time, "perf_counter", _RampingClock())
    sleeps = []
    monkeypatch.setattr(tu.time, "sleep", lambda s: sleeps.append(s))
    stop = threading.Event()
    pause = threading.Event()
    tu.precise_sleep(0.004, stop_event=stop, pause_event=pause)
    assert sleeps


def test_precise_sleep_coarse_loop_pause_event(monkeypatch):
    """precise_sleep coarse loop with pause_event entering loop body."""
    monkeypatch.setattr(tu.time, "perf_counter", _RampingClock())
    sleeps = []
    monkeypatch.setattr(tu.time, "sleep", lambda s: sleeps.append(s))
    pause = threading.Event()
    tu.precise_sleep(0.004, pause_event=pause)
    assert sleeps


def test_precise_sleep_coarse_no_events(monkeypatch):
    """precise_sleep coarse loop without stop/pause uses time.sleep."""
    monkeypatch.setattr(tu.time, "perf_counter", _RampingClock())
    sleeps = []
    monkeypatch.setattr(tu.time, "sleep", lambda s: sleeps.append(s))
    tu.precise_sleep(0.003)
    assert any(s > 0 for s in sleeps)


def test_precise_sleep_busy_wait_stop_interrupt(monkeypatch):
    """Busy-wait loop breaks on stop_event.is_set()."""
    monkeypatch.setattr(tu.time, "perf_counter", _RampingClock())
    monkeypatch.setattr(tu.time, "sleep", lambda s: None)
    stop = threading.Event()
    stop.set()
    tu.precise_sleep(0.01, stop_event=stop)


def test_precise_sleep_busy_wait_pause_interrupt(monkeypatch):
    """Busy-wait loop breaks on pause_event.is_set()."""
    monkeypatch.setattr(tu.time, "perf_counter", _RampingClock())
    monkeypatch.setattr(tu.time, "sleep", lambda s: None)
    pause = threading.Event()
    pause.set()
    tu.precise_sleep(0.01, pause_event=pause)

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
        assert mod._winmm is None
    finally:
        importlib.reload(mod)
