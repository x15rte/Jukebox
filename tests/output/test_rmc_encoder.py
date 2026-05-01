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


def test_process_mido_message_dispatches(monkeypatch):
    calls = []
    monkeypatch.setattr(rmc, "send_note_message", lambda n, v, off: calls.append(("note", n, v, off)))
    monkeypatch.setattr(rmc, "send_pedal", lambda v: calls.append(("pedal", v)))

    rmc.process_mido_message(SimpleNamespace(type="note_on", note=60, velocity=100))
    rmc.process_mido_message(SimpleNamespace(type="note_on", note=60, velocity=0))
    rmc.process_mido_message(SimpleNamespace(type="note_off", note=61, velocity=0))
    rmc.process_mido_message(SimpleNamespace(type="control_change", control=64, value=70))
    rmc.process_mido_message(SimpleNamespace(type="clock"))

    assert calls[0] == ("note", 60, 100, False)
    assert calls[1] == ("note", 60, 0, True)
    assert calls[2] == ("note", 61, 0, True)
    assert calls[3] == ("pedal", 70)


def test_encode_and_send_message_falls_back_when_batched_send_fails(monkeypatch):
    tapped = []
    monkeypatch.setattr(rmc, "ensure_numlock_on", lambda: None)
    monkeypatch.setattr(rmc, "_use_batched_sendinput", True)
    monkeypatch.setattr(rmc, "_send_frame_batched", lambda *a, **k: False)
    monkeypatch.setattr(rmc, "_tap_key", lambda name: tapped.append(name))

    rmc.encode_and_send_message(1, 2, 3, 4)

    assert rmc._use_batched_sendinput is False
    assert tapped == ["multiply", "numpad1", "numpad2", "numpad3", "numpad4"]

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
    monkeypatch.setattr(rmc.jukebox_logger, "debug", lambda m: logs.append(m))
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
    assert rmc._numlock_ensured is True


def test_tap_key_handles_pydirectinput_exception(monkeypatch):
    logs = []
    monkeypatch.setattr(rmc.jukebox_logger, "debug", lambda m: logs.append(m))

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

    class _Native:
        @staticmethod
        def post_macos_key_event(vk, down, flags):
            events.append((vk, down, flags))

    import sys

    monkeypatch.setitem(sys.modules, "native", _Native)
    rmc._tap_key("numpad1")

    assert events == [(42, True, 0), (42, False, 0)]


def test_tap_key_macos_cgevent_logs_on_exception(monkeypatch):
    logs = []
    monkeypatch.setattr(rmc.jukebox_logger, "debug", lambda m: logs.append(m))
    monkeypatch.setattr(rmc, "_use_pydirectinput", False)
    monkeypatch.setattr(rmc, "_platform", "Darwin")
    monkeypatch.setattr(rmc, "_platform_map", {"numpad1": 42})

    class _Native:
        @staticmethod
        def post_macos_key_event(vk, down, flags):
            raise RuntimeError("cg boom")

    import sys

    monkeypatch.setitem(sys.modules, "native", _Native)
    rmc._tap_key("numpad1")

    assert any("macOS CGEvent key send failed" in m for m in logs)


def test_tap_key_pynput_exception_branch(monkeypatch):
    logs = []
    monkeypatch.setattr(rmc.jukebox_logger, "debug", lambda m: logs.append(m))
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


def test_process_mido_message_note_missing_and_non_pedal_cc(monkeypatch):
    calls = []
    monkeypatch.setattr(rmc, "send_note_message", lambda *a: calls.append(("note", a)))
    monkeypatch.setattr(rmc, "send_pedal", lambda v: calls.append(("pedal", v)))

    rmc.process_mido_message(SimpleNamespace(type="note_on", velocity=100))
    rmc.process_mido_message(SimpleNamespace(type="control_change", control=1, value=70))

    assert calls == []


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
        importlib.reload(mod)
