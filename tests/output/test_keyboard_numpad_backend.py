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
    # Old code for pynput does NOT release/re-press on overlap (was_active ignored)
    assert ctrl.releases.count(out.KeyCode.from_vk(ord(base_key))) == 0

    kb.note_off(60)
    # note_off(60) should NOT add another release — pitch 61 is still active
    assert ctrl.releases.count(out.KeyCode.from_vk(ord(base_key))) == 0

    kb.note_off(61)
    # now release should happen
    assert ctrl.releases.count(out.KeyCode.from_vk(ord(base_key))) == 1


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

    # Old code uses `with self._kb.pressed(*modifiers): context manager for pynput.
    # Modifier is pressed by context manager enter (logged in pressed_modifiers),
    # base key pressed inside, modifier released on context manager exit (not tracked by FakeController).
    assert ctrl.pressed_modifiers == [(out.Key.shift,)]
    expected = out.KeyCode.from_vk(ord(base_key))
    assert ctrl.presses == [expected]  # only base key explicitly pressed
    assert ctrl.releases == [expected]  # only base key released in note_off


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

    # Single batch per note_on: mod(s) down + base down + mod(s) up
    # (matches pre-2af9230 working behavior — one SendInput call)
    assert fake_pdi.sent_batches == [
        [(normal_base, True)],                                    # note_on(60)
        [(normal_base, False)],                                   # note_off(60)
        [("shiftleft", True), (shift_base, True), ("shiftleft", False)],  # note_on(61)
        [(shift_base, False)],                                    # note_off(61)
        [("ctrlleft", True), (ctrl_base, True), ("ctrlleft", False)],     # note_on(21)
        [(ctrl_base, False)],                                     # note_off(21)
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
        "shiftleft",      # released during note_on(61)
        shift_base,        # released during note_off(61)
        "ctrlleft",        # released during note_on(21)
        ctrl_base,         # released during note_off(21)
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

def test_windows_key_backend_release_stale_modifier_on_overlap(monkeypatch):
    """When a shifted note overlapped with an unshifted note on the same base key,
    press-and-release ensures modifiers are not held across notes — the game
    captures the pitch at key-down time."""
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)
    kb = out.KeyboardBackend(use_88_key_layout=False)

    # Pitch 60 (C4) maps to base key 't', no modifiers.
    # Pitch 61 (C#4) maps to base key 't', modifier [Key.shift] → "shiftleft".
    base = "t"
    mod = "shiftleft"

    # 1. Press unshifted note — just base key down
    kb.note_on(60, 100)
    assert fake_pdi.sent_batches[-1] == [(base, True)]
    assert fake_pdi.down.count(base) == 1

    # 2. Press shifted note (overlapping — same base key)
    #    Press-and-release: base released, shift down, base down, shift up
    kb.note_on(61, 100)
    # Verify the release + press-and-release sequence happened
    assert fake_pdi.down.count(mod) == 1  # shift was pressed
    assert fake_pdi.down.count(base) == 2  # base pressed twice (first + re-press)
    assert fake_pdi.up.count(mod) >= 1, "Shift should have been released"
    # 3. Release shifted note — unshifted note (60) is still active so base stays
    up_before = len(fake_pdi.up)
    kb.note_off(61)
    # No new release events should have been added
    assert len(fake_pdi.up) == up_before, "note_off(61) should not release anything"

    # 4. Release the final note — base key released
    fake_pdi.up.clear()
    kb.note_off(60)
    assert fake_pdi.up.count(base) == 1


def test_windows_key_backend_pedal_press_and_release_holds_key(monkeypatch):
    """With press-and-release, modifiers are never held. Pedal holds the base
    key but the modifier is already released during note_on."""
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)
    kb = out.KeyboardBackend(use_88_key_layout=False)

    base = "t"
    mod = "shiftleft"

    kb.pedal_on()
    kb.note_on(61, 100)  # C#4 — shift + base (press-and-release)

    # Shift was already released during note_on — not held by pedal
    assert fake_pdi.up.count(mod) >= 1, \
        "Shift should have been released during note_on"

    # Release shifted note while pedal is down — key stays held by pedal
    kb.note_off(61)

    # Key is still physically held by the pedal
    kb.pedal_off()
    assert fake_pdi.up.count(base) == 1


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

    # Old code shutdown releases active pitches, pedal, and ALL three modifiers
    assert fake_pdi.sent_batches[-1] == [
        (base, False),
        ("space", False),
        ("shiftleft", False),
        ("ctrlleft", False),
        ("altleft", False),
    ]
    assert base in fake_pdi.up
    assert fake_pdi.up.count("space") == 2


def test_windows_key_backend_missing_pydirectinput_is_unavailable(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    pydirectinput_stub.block(monkeypatch)

    with pytest.raises(out.OutputBackendUnavailableError):
        out.KeyboardBackend(use_88_key_layout=False)


def test_windows_key_backend_send_failure_handled(monkeypatch):
    """Send failure — old code leaves pitch in active_pitches (added before send)."""
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)
    kb = out.KeyboardBackend(use_88_key_layout=False)

    fake_pdi.send_exception = RuntimeError("send failed")

    # Error propagates as OutputBackendSendError; state is NOT rolled back
    # because active_pitches is updated before send_batch
    with pytest.raises(out.OutputBackendSendError):
        kb.note_on(60, 100)
    # Pitch remains in active_pitches after send failure
    assert kb._active_pitches != {}


def test_windows_key_backend_partial_send_handled(monkeypatch):
    """Partial send (result=0) — old code raises and leaves pitch in active_pitches."""
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)
    kb = out.KeyboardBackend(use_88_key_layout=False)

    fake_pdi.send_result = 0

    # Error propagates; state is NOT rolled back
    with pytest.raises(out.OutputBackendSendError):
        kb.note_on(60, 100)
    assert kb._active_pitches != {}
