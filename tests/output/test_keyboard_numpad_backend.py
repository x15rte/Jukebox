from typing import Any, cast

import pytest

import output.output as out

out = cast(Any, out)
from tests.helpers import pydirectinput_stub
from tests.helpers.fakes import FakeEvent


class _PressedCtx:
    def __init__(self, store, mods):
        self.store = store
        self.mods = mods

    def __enter__(self):
        self.store.append(tuple(self.mods))

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeController:
    def __init__(self):
        self.presses = []
        self.releases = []
        self.pressed_modifiers = []

    def pressed(self, *mods):
        return _PressedCtx(self.pressed_modifiers, mods)

    def press(self, key):
        self.presses.append(key)

    def release(self, key):
        self.releases.append(key)



def test_keyboard_backend_overlapping_same_base_key(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    ctrl = cast(FakeController, kb._kb)

    key_data = kb._mapper.get_key_data(60)
    assert key_data is not None
    base_key = key_data["key"]

    kb.note_on(60, 100)
    kb.note_on(61, 100)
    # note_on(61) releases 't' for polyphony (was_active=True) then re-presses it
    assert ctrl.releases.count(base_key) == 1

    kb.note_off(60)
    # note_off(60) should NOT add another release — pitch 61 is still active
    assert ctrl.releases.count(base_key) == 1

    kb.note_off(61)
    # now release should happen
    assert ctrl.releases.count(base_key) == 2


def test_keyboard_backend_pedal_and_shutdown(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    ctrl = cast(FakeController, kb._kb)

    kb.pedal_on()
    kb.pedal_off()
    kb.note_on(60, 100)
    kb.shutdown()

    assert len(ctrl.presses) >= 2
    assert len(ctrl.releases) >= 2


def test_numpad_backend_note_pedal_and_shutdown(monkeypatch):
    calls = []
    monkeypatch.setattr(out.rmc, "send_note_message", lambda *a, **k: calls.append(("note", a, k)))
    monkeypatch.setattr(out.rmc, "send_pedal", lambda *a, **k: calls.append(("pedal", a, k)))
    monkeypatch.setattr(out.rmc, "reset_batched_sendinput", lambda: calls.append(("reset", (), {})))

    nb = out.NumpadBackend(inter_message_delay=0.0)
    nb.note_on(60, 100)
    nb.note_off(60)
    nb.pedal_on()
    nb.pedal_off()
    nb.shutdown()

    kinds = [c[0] for c in calls]
    assert "note" in kinds
    assert "pedal" in kinds
    assert "reset" in kinds

def test_keyboard_backend_note_on_off_exact_key_and_modifier_sequence(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    ctrl = cast(FakeController, kb._kb)

    kb.note_on(61, 100)
    kb.note_off(61)

    key_data = kb._mapper.get_key_data(61)
    assert key_data is not None
    base_key = key_data["key"]

    # Modifiers are now pressed individually (not via context manager) and
    # released in note_off via _release_key_if_unused.
    assert ctrl.pressed_modifiers == []  # no longer uses context manager
    assert ctrl.presses == [out.Key.shift, base_key]  # modifier pressed first
    assert ctrl.releases == [base_key, out.Key.shift]  # base key then modifier


def test_output_backend_execute_batch_matches_in_game_event_order(monkeypatch):
    calls = []
    monkeypatch.setattr(out.rmc, "send_note_message", lambda *a, **k: calls.append(("note", a, k)))
    monkeypatch.setattr(out.rmc, "send_pedal", lambda *a, **k: calls.append(("pedal", a, k)))
    monkeypatch.setattr(out.rmc, "reset_batched_sendinput", lambda: None)

    nb = out.NumpadBackend(inter_message_delay=0.0)
    nb.execute_batch(
        [
            FakeEvent(0.0, 2, "press", key_char="", pitch=64, velocity=96),
            FakeEvent(0.0, 0, "pedal", key_char="up"),
            FakeEvent(0.0, 1, "release", key_char="", pitch=60),
            FakeEvent(0.0, 3, "pedal", key_char="down"),
        ]
    )

    assert calls == [
        ("pedal", (127,), {}),
        ("note", (60,), {"velocity": 0, "is_note_off": True}),
        ("note", (64, 96), {"is_note_off": False}),
    ]


def test_windows_key_backend_configures_scan_codes(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)

    out.KeyboardBackend(use_88_key_layout=True)

    mapped_keys = {
        data["key"] for data in out.KeyMapper(use_88_key_layout=True).key_map.values()
    }
    required_keys = mapped_keys | {"space", "shiftleft", "ctrlleft", "altleft"}

    assert required_keys <= set(out._WINDOWS_KEY_SCAN_CODES)
    assert fake_pdi.PAUSE == 0
    assert fake_pdi.FAILSAFE is False
    for key_name, scan_code in out._WINDOWS_KEY_SCAN_CODES.items():
        assert fake_pdi.KEYBOARD_MAPPING[key_name] == scan_code


def test_windows_key_backend_does_not_use_pynput_fallback(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    pydirectinput_stub.install(monkeypatch)

    def bad_controller():
        raise AssertionError("pynput Controller must not be created on Windows KEY mode")

    monkeypatch.setattr(out, "Controller", bad_controller)
    kb = out.KeyboardBackend(use_88_key_layout=False)

    assert kb._kb is None
    assert kb._use_pydirectinput is True


def test_windows_key_backend_note_sequences(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)

    kb = out.KeyboardBackend(use_88_key_layout=True)
    normal_data = kb._mapper.get_key_data(60)
    shift_data = kb._mapper.get_key_data(61)
    ctrl_data = kb._mapper.get_key_data(21)
    assert normal_data is not None
    assert shift_data is not None
    assert ctrl_data is not None

    normal_base = normal_data["key"]
    shift_base = shift_data["key"]
    ctrl_base = ctrl_data["key"]

    kb.note_on(60, 100)
    kb.note_off(60)
    kb.note_on(61, 100)
    kb.note_off(61)
    kb.note_on(21, 100)
    kb.note_off(21)

    assert fake_pdi.sent_batches == [
        [(normal_base, True)],            # note_on(60)
        [(normal_base, False)],           # note_off(60) - key_up
        [("shiftleft", True), (shift_base, True)],  # note_on(61) - mods stay held
        [(shift_base, False)],            # note_off(61) - key_up base
        [("shiftleft", False)],           # note_off(61) - key_up modifier
        [("ctrlleft", True), (ctrl_base, True)],    # note_on(21) - mods stay held
        [(ctrl_base, False)],             # note_off(21) - key_up base
        [("ctrlleft", False)],            # note_off(21) - key_up modifier
    ]
    assert fake_pdi.down == [
        normal_base,
        "shiftleft",
        shift_base,
        "ctrlleft",
        ctrl_base,
    ]
    assert fake_pdi.up == [
        normal_base,
        shift_base,
        "shiftleft",
        ctrl_base,
        "ctrlleft",
    ]


def test_windows_key_backend_overlapping_same_base_release(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)
    sleeps = []
    monkeypatch.setattr(out.time, "sleep", lambda seconds: sleeps.append(seconds))

    kb = out.KeyboardBackend(use_88_key_layout=False)
    key_data = kb._mapper.get_key_data(36)
    assert key_data is not None
    base = key_data["key"]

    kb.note_on(36, 100)
    kb.note_on(37, 100)
    kb.note_off(36)

    assert fake_pdi.up.count(base) == 1
    assert sleeps == [out._WINDOWS_KEY_REPRESS_DELAY]

    kb.note_off(37)

    assert fake_pdi.up.count(base) == 2


def test_windows_key_backend_execute_batch_inserts_release_press_gap(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    data = kb._mapper.get_key_data(60)
    assert data is not None
    base = data["key"]

    kb.note_on(60, 100)
    fake_pdi.sent_batches.clear()

    # Release and press of the same pitch — base-class repress sleep is removed
    # (each backend's note_on handles its own repress delay internally).
    kb.execute_batch(
        [
            FakeEvent(0.0, 4, "release", key_char="", pitch=60, velocity=0),
            FakeEvent(0.0, 2, "press", key_char="", pitch=60, velocity=100),
        ]
    )

    assert fake_pdi.sent_batches == [
        [(base, False)],
        [(base, True)],
    ]


def test_windows_key_backend_execute_batch_routes_pedals(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)

    kb = out.KeyboardBackend(use_88_key_layout=False)

    kb.execute_batch(
        [
            FakeEvent(0.0, 0, "pedal", key_char="down"),
            FakeEvent(0.0, 1, "pedal", key_char="up"),
        ]
    )

    assert fake_pdi.sent_batches == [
        [("space", True)],
        [("space", False)],
    ]


def test_windows_key_backend_pedal_idempotency_and_shutdown(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    key_data = kb._mapper.get_key_data(61)
    assert key_data is not None
    base = key_data["key"]

    kb.pedal_on()
    kb.pedal_on()
    kb.pedal_off()
    kb.pedal_off()

    assert fake_pdi.down.count("space") == 1
    assert fake_pdi.up.count("space") == 1

    kb.note_on(61, 100)
    kb.pedal_on()
    kb.shutdown()

    assert fake_pdi.sent_batches[-1] == [
        (base, False),
        ("space", False),
        ("shiftleft", False),
        ("ctrlleft", False),
        ("altleft", False),
    ]
    assert base in fake_pdi.up
    assert fake_pdi.up.count("space") == 2
    assert "shiftleft" in fake_pdi.up
    assert "ctrlleft" in fake_pdi.up
    assert "altleft" in fake_pdi.up


def test_windows_key_backend_missing_pydirectinput_is_unavailable(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    pydirectinput_stub.block(monkeypatch)

    with pytest.raises(out.OutputBackendUnavailableError):
        out.KeyboardBackend(use_88_key_layout=False)


def test_windows_key_backend_send_failure_handled(monkeypatch):
    """Send failure is caught internally; modifiers cleaned up, no leak."""
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)
    kb = out.KeyboardBackend(use_88_key_layout=False)

    fake_pdi.send_exception = RuntimeError("send failed")

    # Error is caught internally; no exception propagates
    kb.note_on(60, 100)
    # State should be clean — no leaked press or modifier tracking
    assert kb._active_pitches == {}
    assert kb._held_modifiers == {}


def test_windows_key_backend_partial_send_handled(monkeypatch):
    """Partial send (result=0) is caught internally; no leak."""
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)
    kb = out.KeyboardBackend(use_88_key_layout=False)

    fake_pdi.send_result = 0

    # Error is caught internally; no exception propagates
    kb.note_on(60, 100)
    assert kb._active_pitches == {}
    assert kb._held_modifiers == {}
