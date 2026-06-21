# pyright: reportAttributeAccessIssue=false

import builtins
import ctypes
import importlib
import platform
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

import output.RobloxMidiConnect_encoder as rmc

pytestmark = pytest.mark.rmc_low_level

_RMC_PATH = (
    Path(__file__).resolve().parents[2] / "output" / "RobloxMidiConnect_encoder.py"
)


class _PDIKeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _PDIInputUnion(ctypes.Union):
    _fields_ = [("ki", _PDIKeyBdInput)]


class _PDIInput(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", _PDIInputUnion)]


class _PDIModule:
    def __init__(self):
        self.PAUSE = 1
        self.KEYBOARD_MAPPING = {}
        self.Input = _PDIInput


def _load_rmc_namespace(monkeypatch, *, pydirectinput=None, missing_pydirectinput=False):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pydirectinput":
            if missing_pydirectinput:
                raise ImportError("missing pydirectinput")
            return pydirectinput
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(builtins, "__import__", fake_import)
    return runpy.run_path(str(_RMC_PATH), run_name="__rmc_import_test__")


def test_encode_note_components_clamps_velocity():
    a, b, c, d = rmc._encode_note_components(60, 999, False)
    assert (a, b) == (5, 0)
    assert 0 <= c <= 11
    assert 0 <= d <= 11


def test_send_pedal_uses_sentinel(monkeypatch):
    sent = {}

    def fake_send(a, b, c, d, inter_key_delay=0):
        sent["vals"] = (a, b, c, d)

    monkeypatch.setattr(rmc, "encode_and_send_message", fake_send)
    rmc.send_pedal(127)

    a, b, c, d = sent["vals"]
    assert a == rmc.PEDAL_SENTINEL // 12
    assert b == rmc.PEDAL_SENTINEL % 12
    assert (c, d) == (10, 7)


def test_encode_and_send_message_falls_back_when_batched_send_fails(monkeypatch):
    tapped = []
    monkeypatch.setattr(rmc, "ensure_numlock_on", lambda: None)
    monkeypatch.setattr(rmc, "_use_batched_sendinput", True)
    monkeypatch.setattr(rmc, "_send_frame_batched", lambda *a, **k: False)
    monkeypatch.setattr(rmc, "_tap_key", lambda name: tapped.append(name))

    rmc.encode_and_send_message(1, 2, 3, 4)

    # Fallback to _tap_key when batched send fails
    assert tapped == ["multiply", "numpad1", "numpad2", "numpad3", "numpad4"]

    # Second call should still try batched (no permanent fallback)
    tapped.clear()
    rmc.encode_and_send_message(1, 2, 3, 4)
    assert tapped[0] == "multiply"
    assert tapped[1:5] == ["numpad1", "numpad2", "numpad3", "numpad4"]


def test_encode_and_send_message_returns_after_successful_batch(monkeypatch):
    tapped = []
    monkeypatch.setattr(rmc, "ensure_numlock_on", lambda: None)
    monkeypatch.setattr(rmc, "_use_batched_sendinput", True)
    monkeypatch.setattr(rmc, "_send_frame_batched", lambda *a, **k: True)
    monkeypatch.setattr(rmc, "_tap_key", lambda name: tapped.append(name))

    rmc.encode_and_send_message(1, 2, 3, 4)

    assert rmc._use_batched_sendinput is True
    assert tapped == []


def test_ensure_numlock_windows_path_taps_when_off(monkeypatch):
    calls = []

    class _PDI:
        @staticmethod
        def keyDown(name, _pause=False):
            calls.append(("down", name))

        @staticmethod
        def keyUp(name, _pause=False):
            calls.append(("up", name))

    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_numlock_ensured", False)
    monkeypatch.setattr(rmc, "_use_pydirectinput", True)
    monkeypatch.setattr(rmc, "pydirectinput", _PDI, raising=False)

    class _User32:
        @staticmethod
        def GetKeyState(_v):
            return 0

    monkeypatch.setattr(
        rmc.ctypes, "windll", SimpleNamespace(user32=_User32()), raising=False
    )

    rmc.ensure_numlock_on()

    assert calls == [("down", "numlock"), ("up", "numlock")]


def test_ensure_numlock_windows_returns_when_already_on(monkeypatch):
    calls = []

    class _PDI:
        @staticmethod
        def keyDown(name, _pause=False):
            calls.append(("down", name))

        @staticmethod
        def keyUp(name, _pause=False):
            calls.append(("up", name))

    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_numlock_ensured", False)
    monkeypatch.setattr(rmc, "_use_pydirectinput", True)
    monkeypatch.setattr(rmc, "pydirectinput", _PDI, raising=False)

    class _User32:
        @staticmethod
        def GetKeyState(_v):
            return 1

    monkeypatch.setattr(
        rmc.ctypes, "windll", SimpleNamespace(user32=_User32()), raising=False
    )

    rmc.ensure_numlock_on()

    assert calls == []


def test_ensure_numlock_windows_handles_exception(monkeypatch):
    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_numlock_ensured", False)

    class _User32:
        @staticmethod
        def GetKeyState(_v):
            raise RuntimeError("nope")

    monkeypatch.setattr(
        rmc.ctypes, "windll", SimpleNamespace(user32=_User32()), raising=False
    )

    rmc.ensure_numlock_on()


def test_tap_key_pydirectinput_and_pynput_paths(monkeypatch):
    pdi_calls = []

    class _PDI:
        @staticmethod
        def keyDown(name, _pause=False):
            pdi_calls.append(("down", name))

        @staticmethod
        def keyUp(name, _pause=False):
            pdi_calls.append(("up", name))

    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_use_pydirectinput", True)
    monkeypatch.setattr(rmc, "pydirectinput", _PDI, raising=False)
    rmc._tap_key("numpad1")
    assert pdi_calls == [("down", "numpad1"), ("up", "numpad1")]

    presses = []
    monkeypatch.setattr(rmc, "_use_pydirectinput", False)
    monkeypatch.setattr(rmc, "_platform", "Linux")
    monkeypatch.setattr(rmc, "_precomputed_keys", {"numpad2": "KC2"})

    class _KBCtrl:
        def press(self, k):
            presses.append(("press", k))

        def release(self, k):
            presses.append(("release", k))

    monkeypatch.setattr(rmc, "_keyboard", _KBCtrl())
    rmc._tap_key("numpad2")
    assert presses == [("press", "KC2"), ("release", "KC2")]


def test_tap_key_windows_without_pydirectinput_does_not_use_pynput(monkeypatch):
    logs = []
    presses = []
    monkeypatch.setattr(rmc.jukebox_logger, "warning", lambda m, **k: logs.append(m))
    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_use_pydirectinput", False)
    monkeypatch.setattr(rmc, "_precomputed_keys", {"numpad1": "KC1"})

    class _KBCtrl:
        def press(self, k):
            presses.append(("press", k))

        def release(self, k):
            presses.append(("release", k))

    monkeypatch.setattr(rmc, "_keyboard", _KBCtrl())

    rmc._tap_key("numpad1")

    assert presses == []
    assert any("pydirectinput is unavailable" in m for m in logs)


def test_transport_availability_helpers(monkeypatch):
    monkeypatch.setattr(rmc, "_use_pydirectinput", False)
    assert rmc.is_using_pydirectinput() is False

    monkeypatch.setattr(rmc, "_use_pydirectinput", True)
    assert rmc.is_using_pydirectinput() is True

    monkeypatch.setattr(rmc, "_keyboard", object())
    monkeypatch.setattr(
        rmc,
        "_precomputed_keys",
        {"multiply": object(), **{name: object() for name in rmc.ENCODED_KEYS}},
    )
    assert rmc.is_using_pynput() is True

    monkeypatch.setattr(rmc, "_precomputed_keys", {"multiply": object()})
    assert rmc.is_using_pynput() is False


def test_reset_batched_sendinput_branches(monkeypatch):
    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_use_pydirectinput", True)
    monkeypatch.setattr(rmc, "_use_batched_sendinput", False)

    rmc.reset_batched_sendinput()
    assert rmc._use_batched_sendinput is True

    monkeypatch.setattr(rmc, "_use_batched_sendinput", True)
    rmc.reset_batched_sendinput()
    assert rmc._use_batched_sendinput is True


def test_reset_batched_sendinput_noop_non_windows(monkeypatch):
    monkeypatch.setattr(rmc, "_platform", "Linux")
    monkeypatch.setattr(rmc, "_use_pydirectinput", True)
    monkeypatch.setattr(rmc, "_use_batched_sendinput", False)

    rmc.reset_batched_sendinput()
    assert rmc._use_batched_sendinput is False


def test_ensure_numlock_returns_when_already_ensured(monkeypatch):
    monkeypatch.setattr(rmc, "_numlock_ensured", True)
    monkeypatch.setattr(rmc, "_platform", "Windows")

    class _User32:
        @staticmethod
        def GetKeyState(_v):
            raise RuntimeError("should not run")

    monkeypatch.setattr(
        rmc.ctypes, "windll", SimpleNamespace(user32=_User32()), raising=False
    )
    rmc.ensure_numlock_on()


def test_ensure_numlock_non_windows_noop(monkeypatch):
    monkeypatch.setattr(rmc, "_numlock_ensured", False)
    monkeypatch.setattr(rmc, "_platform", "Linux")
    rmc.ensure_numlock_on()
    assert rmc._numlock_ensured is False


def test_tap_key_handles_pydirectinput_exception(monkeypatch):
    logs = []
    monkeypatch.setattr(rmc.jukebox_logger, "warning", lambda m, **k: logs.append(m))

    class _PDI:
        @staticmethod
        def keyDown(name, _pause=False):
            raise RuntimeError(f"bad {name}")

        @staticmethod
        def keyUp(name, _pause=False):
            return None

    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_use_pydirectinput", True)
    monkeypatch.setattr(rmc, "pydirectinput", _PDI, raising=False)

    rmc._tap_key("numpad1")
    assert any("pydirectinput key send failed" in m for m in logs)


def test_tap_key_macos_cgevent_paths(monkeypatch):
    events = []
    monkeypatch.setattr(rmc, "_use_pydirectinput", False)
    monkeypatch.setattr(rmc, "_platform", "Darwin")
    monkeypatch.setattr(rmc, "_platform_map", {"numpad1": 42})
    monkeypatch.setattr(rmc, "_pmke", lambda vk, down, flags: events.append((vk, down, flags)))
    rmc._tap_key("numpad1")
    assert events == [(42, True, 0), (42, False, 0)]


def test_tap_key_macos_cgevent_logs_on_exception(monkeypatch):
    logs = []
    monkeypatch.setattr(rmc.jukebox_logger, "warning", lambda m, **k: logs.append(m))
    monkeypatch.setattr(rmc, "_use_pydirectinput", False)
    monkeypatch.setattr(rmc, "_platform", "Darwin")
    monkeypatch.setattr(rmc, "_platform_map", {"numpad1": 42})

    def _raise(_, __, ___):
        raise RuntimeError("cg boom")

    monkeypatch.setattr(rmc, "_pmke", _raise)
    rmc._tap_key("numpad1")
    assert any("macOS CGEvent key send failed" in m for m in logs)


def test_tap_key_pynput_exception_branch(monkeypatch):
    logs = []
    monkeypatch.setattr(rmc.jukebox_logger, "warning", lambda m, **k: logs.append(m))
    monkeypatch.setattr(rmc, "_use_pydirectinput", False)
    monkeypatch.setattr(rmc, "_platform", "Linux")
    monkeypatch.setattr(rmc, "_precomputed_keys", {"numpad2": "KC2"})

    class _KBCtrl:
        def press(self, _k):
            raise RuntimeError("press boom")

        def release(self, _k):
            return None

    monkeypatch.setattr(rmc, "_keyboard", _KBCtrl())
    rmc._tap_key("numpad2")

    assert any("pynput key send failed" in m for m in logs)


def test_send_frame_batched_writes_scans_and_checks_result(monkeypatch):
    class _KI:
        def __init__(self):
            self.wScan = 0

    class _II:
        def __init__(self):
            self.ki = _KI()

    class _Input:
        def __init__(self):
            self.ii = _II()

    frame = [_Input() for _ in range(10)]
    monkeypatch.setattr(rmc, "_frame_inputs", frame, raising=False)
    monkeypatch.setattr(rmc, "_frame_sizeof", 1, raising=False)
    monkeypatch.setattr(rmc, "_use_batched_sendinput", True)

    class _User32:
        @staticmethod
        def SendInput(n, _inputs, _sz):
            return n

    monkeypatch.setattr(
        rmc.ctypes, "windll", SimpleNamespace(user32=_User32()), raising=False
    )

    ok = rmc._send_frame_batched(1, 2, 3, 4, 5)

    assert ok is True
    assert [frame[i].ii.ki.wScan for i in range(10)] == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]


def test_send_frame_batched_returns_false_without_windll(monkeypatch):
    monkeypatch.setattr(rmc, "_use_batched_sendinput", True)
    monkeypatch.setattr(rmc, "_get_windll", lambda: None)
    assert rmc._send_frame_batched(1, 2, 3, 4, 5) is False


def test_encode_and_send_message_clamps_indices(monkeypatch):
    sent = []
    monkeypatch.setattr(rmc, "ensure_numlock_on", lambda: None)
    monkeypatch.setattr(rmc, "_use_batched_sendinput", False)
    monkeypatch.setattr(rmc, "_tap_key", lambda name: sent.append(name))

    rmc.encode_and_send_message(-5, 999, 2, 3)

    assert sent == ["multiply", "numpad0", "add", "numpad2", "numpad3"]


def test_encode_and_send_message_uses_delay(monkeypatch):
    sent = []
    sleeps = []
    monkeypatch.setattr(rmc, "ensure_numlock_on", lambda: None)
    monkeypatch.setattr(rmc, "_use_batched_sendinput", False)
    monkeypatch.setattr(rmc, "_tap_key", lambda name: sent.append(name))
    monkeypatch.setattr(rmc.time, "sleep", lambda s: sleeps.append(s))

    rmc.encode_and_send_message(1, 2, 3, 4, inter_key_delay=0.01)

    assert sent[0] == "multiply"
    assert sent[1:] == ["numpad1", "numpad2", "numpad3", "numpad4"]
    assert sleeps == [0.01, 0.01, 0.01, 0.01]


def test_send_note_message_passes_encoded_components(monkeypatch):
    sent = []
    monkeypatch.setattr(rmc, "encode_and_send_message", lambda a, b, c, d, inter_key_delay=0: sent.append((a, b, c, d, inter_key_delay)))

    rmc.send_note_message(61, 100, False)

    assert sent and sent[0][:4] == rmc._encode_note_components(61, 100, False)


def test_send_pedal_clamps_value(monkeypatch):
    sent = []
    monkeypatch.setattr(rmc, "encode_and_send_message", lambda a, b, c, d, inter_key_delay=0: sent.append((a, b, c, d)))

    rmc.send_pedal(999)

    a, b, c, d = sent[0]
    assert (a, b) == (rmc.PEDAL_SENTINEL // 12, rmc.PEDAL_SENTINEL % 12)
    assert (c, d) == (10, 7)


def test_encode_and_send_message_emits_exact_rmc_key_sequence(monkeypatch):
    sent = []
    monkeypatch.setattr(rmc, "ensure_numlock_on", lambda: None)
    monkeypatch.setattr(rmc, "_use_batched_sendinput", False)
    monkeypatch.setattr(rmc, "_tap_key", lambda name: sent.append(name))

    rmc.encode_and_send_message(5, 0, 8, 4)

    assert sent == ["multiply", "numpad5", "numpad0", "numpad8", "numpad4"]


def test_send_note_message_note_off_uses_zero_velocity_digits(monkeypatch):
    sent = []
    monkeypatch.setattr(rmc, "encode_and_send_message", lambda a, b, c, d, inter_key_delay=0: sent.append((a, b, c, d)))

    rmc.send_note_message(73, 120, True)

    assert sent == [(6, 1, 0, 0)]




def test_encode_note_components_note_off_and_clamped_velocity():
    assert rmc._encode_note_components(60, 90, True) == (5, 0, 0, 0)
    a, b, c, d = rmc._encode_note_components(60, -10, False)
    assert (a, b, c, d) == (5, 0, 0, 0)


def test_windows_import_configures_pydirectinput_batched_sendinput(monkeypatch):
    pydirectinput = _PDIModule()

    ns = _load_rmc_namespace(monkeypatch, pydirectinput=pydirectinput)

    assert ns["_use_pydirectinput"] is True
    assert ns["_use_batched_sendinput"] is True
    assert pydirectinput.PAUSE == 0
    assert pydirectinput.KEYBOARD_MAPPING == ns["_SCAN_CODES"]
    assert len(ns["_frame_inputs"]) == 10
    assert ns["_frame_sizeof"] == ctypes.sizeof(pydirectinput.Input)
    assert ns["_frame_inputs"][0].type == ns["_INPUT_KEYBOARD"]
    assert ns["_frame_inputs"][0].ii.ki.wVk == 0
    assert ns["_frame_inputs"][0].ii.ki.time == 0
    assert ns["_frame_inputs"][0].ii.ki.dwFlags == ns["_KEYEVENTF_SCANCODE"]
    assert ns["_frame_inputs"][1].ii.ki.dwFlags == (
        ns["_KEYEVENTF_SCANCODE"] | ns["_KEYEVENTF_KEYUP"]
    )
    assert ns["_keyboard"] is None
    assert ns["_kb"] is None


def test_import_sets_pydirectinput_false_on_import_error(monkeypatch):
    ns = _load_rmc_namespace(monkeypatch, missing_pydirectinput=True)
    assert ns["_use_pydirectinput"] is False
    assert ns["_use_batched_sendinput"] is False


def test_import_leaves_keyboard_none_when_pynput_missing(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pynput":
            raise ImportError("missing pynput")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    mod = importlib.reload(rmc)
    try:
        assert mod._kb is None
        assert mod._keyboard is None
    finally:
        monkeypatch.undo()
        importlib.reload(rmc)


def test_import_linux_path_pynput_available(monkeypatch):
    """Cover Linux code path: pynput import succeeds, _precomputed_keys populated."""
    monkeypatch.setattr("platform.system", lambda: "Linux")

    mod = importlib.reload(rmc)
    try:
        assert mod._kb is not None
        assert mod._keyboard is not None
        # _precomputed_keys populated from VK_CODES["Linux"] (empty) ->
        # falls back to _platform_map from VK_CODES["Linux"].
        # Since VK_CODES has no "Linux" key, _platform_map is {} and
        # _precomputed_keys is also {}.  The key assertion is that line 202
        # executed at all (tested by _kb not being None).
        assert isinstance(mod._precomputed_keys, dict)
    finally:
        monkeypatch.undo()
        importlib.reload(mod)


def test_import_linux_path_pynput_missing(monkeypatch):
    """Cover Linux code path: pynput import fails, _kb stays None."""
    monkeypatch.setattr("platform.system", lambda: "Linux")

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pynput":
            raise ImportError("missing pynput")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    mod = importlib.reload(rmc)
    try:
        assert mod._kb is None
        assert mod._keyboard is None
    finally:
        monkeypatch.undo()
        importlib.reload(rmc)


def test_send_frame_batched_partial_success_calls_send_key_down_up(monkeypatch):
    """Partial SendInput (result=6) calls _send_key_down/_send_key_up for remaining 2 keys."""
    frame = [SimpleNamespace(ii=SimpleNamespace(ki=SimpleNamespace(wScan=0)))
             for _ in range(10)]
    monkeypatch.setattr(rmc, "_frame_inputs", frame, raising=False)
    monkeypatch.setattr(rmc, "_frame_sizeof", 1, raising=False)
    monkeypatch.setattr(rmc, "_use_batched_sendinput", True)

    class _User32:
        @staticmethod
        def SendInput(n, _inputs, _sz):
            return 6  # 3 full keys sent (6 of 10 events)

    monkeypatch.setattr(
        rmc.ctypes, "windll", SimpleNamespace(user32=_User32()), raising=False
    )

    key_down_calls: list[int] = []
    key_up_calls: list[int] = []
    monkeypatch.setattr(rmc, "_send_key_down", lambda sc: key_down_calls.append(sc))
    monkeypatch.setattr(rmc, "_send_key_up", lambda sc: key_up_calls.append(sc))

    ok = rmc._send_frame_batched(1, 2, 3, 4, 5)

    assert ok is True
    # 3 full keys handled by SendInput (result 6 → fully_sent=3),
    # remaining keys 4 and 5 get _send_key_down + _send_key_up
    assert key_down_calls == [4, 5]
    assert key_up_calls == [4, 5]


def test_send_frame_batched_partial_success_odd_result(monkeypatch):
    """Odd partial result: KEYUP sent for the incomplete key, then _send_key_down/up for rest."""
    frame = [SimpleNamespace(ii=SimpleNamespace(ki=SimpleNamespace(wScan=0)))
             for _ in range(10)]
    monkeypatch.setattr(rmc, "_frame_inputs", frame, raising=False)
    monkeypatch.setattr(rmc, "_frame_sizeof", 1, raising=False)
    monkeypatch.setattr(rmc, "_use_batched_sendinput", True)

    class _User32:
        @staticmethod
        def SendInput(n, _inputs, _sz):
            return 7  # 3 full keys + 1 incomplete (KEYDOWN only of 4th key)

    monkeypatch.setattr(
        rmc.ctypes, "windll", SimpleNamespace(user32=_User32()), raising=False
    )

    key_down_calls: list[int] = []
    key_up_calls: list[int] = []
    monkeypatch.setattr(rmc, "_send_key_down", lambda sc: key_down_calls.append(sc))
    monkeypatch.setattr(rmc, "_send_key_up", lambda sc: key_up_calls.append(sc))

    ok = rmc._send_frame_batched(1, 2, 3, 4, 5)

    assert ok is True
    # result=7 → fully_sent=3, result%2=1 → send_key_up(scs[3]=4), fully_sent=4
    # then send_key_down(5) + send_key_up(5)
    assert key_down_calls == [5]
    assert key_up_calls == [4, 5]

def test_import_darwin_path_sets_pmke(monkeypatch):
    """Cover Darwin import: _pmke set from native module (line 67)."""
    import types as _types
    import sys as _sys

    native_mod = _types.ModuleType("native")
    native_mod.post_macos_key_event = lambda vk, is_down, flags: True
    monkeypatch.setitem(_sys.modules, "native", native_mod)
    monkeypatch.setattr(platform, "system", lambda: "Darwin")

    ns = runpy.run_path(str(_RMC_PATH), run_name="__rmc_darwin_test__")
    assert ns.get("_pmke") is not None
    assert ns.get("_platform") == "Darwin"


def test_ensure_numlock_double_checked_locking(monkeypatch):
    """Cover double-checked locking return inside the lock (line 232)."""
    monkeypatch.setattr(rmc, "_numlock_ensured", False)

    class _MockLock:
        def __enter__(self):
            rmc._numlock_ensured = True
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(rmc, "_numlock_lock", _MockLock())
    monkeypatch.setattr(rmc, "_platform", "Windows")
    rmc.ensure_numlock_on()


def test_ensure_numlock_windows_pydirectinput_exception(monkeypatch):
    """Cover exception handler in pydirectinput numlock toggling (lines 245-246)."""
    monkeypatch.setattr(rmc, "_numlock_ensured", False)
    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_use_pydirectinput", True)
    monkeypatch.setattr(rmc, "pydirectinput", SimpleNamespace(
        keyDown=lambda *a, **k: (_ for _ in ()).throw(Exception("pdi fail")),
        keyUp=lambda *a, **k: None,
    ))
    monkeypatch.setattr(
        rmc, "_get_windll",
        lambda: SimpleNamespace(user32=SimpleNamespace(GetKeyState=lambda _: 0)),
    )

    rmc.ensure_numlock_on()
    assert rmc._numlock_ensured is False


def test_tap_key_windows_pydirectinput_keyup_exception(monkeypatch):
    """Cover pydirectinput keyUp exception in _tap_key (lines 265-266)."""
    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_use_pydirectinput", True)
    calls = []

    def _failing_keyup(*a, **k):
        calls.append(("up_fail", a[0]))
        raise Exception("keyUp error")

    monkeypatch.setattr(rmc, "pydirectinput", SimpleNamespace(
        keyDown=lambda *a, **k: calls.append(("down", a[0])),
        keyUp=_failing_keyup,
    ))

    rmc._tap_key("numpad5")
    assert calls == [("down", "numpad5"), ("up_fail", "numpad5")]


def test_tap_key_linux_key_not_in_precomputed(monkeypatch):
    """Cover missing key in precomputed mappings (lines 286-287)."""
    monkeypatch.setattr(rmc, "_platform", "Linux")
    monkeypatch.setattr(rmc, "_precomputed_keys", {"otherkey": "KC1"})
    monkeypatch.setattr(rmc, "_keyboard", SimpleNamespace(press=lambda k: None, release=lambda k: None))

    rmc._tap_key("numpad5")


def test_tap_key_linux_keyboard_none(monkeypatch):
    """Cover pynput keyboard controller None branch (lines 290-291)."""
    monkeypatch.setattr(rmc, "_platform", "Linux")
    monkeypatch.setattr(rmc, "_precomputed_keys", {"numpad5": "KC5"})
    monkeypatch.setattr(rmc, "_keyboard", None)

    rmc._tap_key("numpad5")


def test_send_key_up_early_return_non_windows(monkeypatch):
    """Cover _send_key_up early return on non-Windows (line 304-305)."""
    monkeypatch.setattr(rmc, "_platform", "Linux")
    rmc._send_key_up(42)


def test_send_key_up_early_return_not_pydirectinput(monkeypatch):
    """Cover _send_key_up early return when not using pydirectinput (lines 304-305)."""
    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_use_pydirectinput", False)
    rmc._send_key_up(42)


def test_send_key_up_early_return_no_windll(monkeypatch):
    """Cover _send_key_up early return when windll is None (lines 306-308)."""
    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_use_pydirectinput", True)
    monkeypatch.setattr(rmc, "_get_windll", lambda: None)
    rmc._send_key_up(42)

def test_send_key_up_early_return_pydirectinput_none(monkeypatch):
    """Cover _send_key_up early return when pydirectinput is None (lines 309-310)."""
    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_use_pydirectinput", True)
    monkeypatch.setattr(rmc, "_get_windll", lambda: object())
    monkeypatch.setattr(rmc, "pydirectinput", None)
    rmc._send_key_up(42)


def test_send_key_up_sendinput_failure_warning(monkeypatch):
    """Cover _send_key_up SendInput failure warning (lines 315-317)."""
    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_use_pydirectinput", True)
    monkeypatch.setattr(rmc, "pydirectinput", _PDIModule())

    class _User32:
        @staticmethod
        def SendInput(n, inputs, sz):
            return 0  # failure

    monkeypatch.setattr(rmc.ctypes, "windll", SimpleNamespace(user32=_User32()), raising=False)
    rmc._send_key_up(42)


def test_send_key_down_early_return_non_windows(monkeypatch):
    """Cover _send_key_down early return on non-Windows (lines 321-322)."""
    monkeypatch.setattr(rmc, "_platform", "Linux")
    rmc._send_key_down(42)


def test_send_key_down_early_return_not_pydirectinput(monkeypatch):
    """Cover _send_key_down early return when not using pydirectinput (lines 321-322)."""
    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_use_pydirectinput", False)
    rmc._send_key_down(42)


def test_send_key_down_early_return_no_windll(monkeypatch):
    """Cover _send_key_down early return when windll is None (lines 323-325)."""
    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_use_pydirectinput", True)
    monkeypatch.setattr(rmc, "_get_windll", lambda: None)
    rmc._send_key_down(42)

def test_send_key_down_early_return_pydirectinput_none(monkeypatch):
    """Cover _send_key_down early return when pydirectinput is None (lines 328-329)."""
    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_use_pydirectinput", True)
    monkeypatch.setattr(rmc, "_get_windll", lambda: object())
    monkeypatch.setattr(rmc, "pydirectinput", None)
    rmc._send_key_down(42)


def test_send_key_down_sendinput_failure_warning(monkeypatch):
    """Cover _send_key_down SendInput failure warning (lines 332-334)."""
    monkeypatch.setattr(rmc, "_platform", "Windows")
    monkeypatch.setattr(rmc, "_use_pydirectinput", True)
    monkeypatch.setattr(rmc, "pydirectinput", _PDIModule())

    class _User32:
        @staticmethod
        def SendInput(n, inputs, sz):
            return 0  # failure

    monkeypatch.setattr(rmc.ctypes, "windll", SimpleNamespace(user32=_User32()), raising=False)
    rmc._send_key_down(42)


def test_send_frame_batched_returns_false_when_batched_disabled(monkeypatch):
    """Cover _use_batched_sendinput check in _send_frame_batched (line 340)."""
    monkeypatch.setattr(rmc, "_use_batched_sendinput", False)
    assert rmc._send_frame_batched(1, 2, 3, 4, 5) is False


def test_send_frame_batched_returns_false_when_sendinput_fails(monkeypatch):
    """Cover SendInput returning 0 in _send_frame_batched (line 377)."""
    frame = [SimpleNamespace(ii=SimpleNamespace(ki=SimpleNamespace(wScan=0)))
             for _ in range(10)]
    monkeypatch.setattr(rmc, "_frame_inputs", frame, raising=False)
    monkeypatch.setattr(rmc, "_frame_sizeof", 1, raising=False)
    monkeypatch.setattr(rmc, "_use_batched_sendinput", True)

    class _User32:
        @staticmethod
        def SendInput(n, _inputs, _sz):
            return 0  # complete failure

    monkeypatch.setattr(rmc.ctypes, "windll", SimpleNamespace(user32=_User32()), raising=False)

    ok = rmc._send_frame_batched(1, 2, 3, 4, 5)
    assert ok is False
