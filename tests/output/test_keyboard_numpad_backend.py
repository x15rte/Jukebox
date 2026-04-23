from typing import Any, cast

import output.output as out

out = cast(Any, out)
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
    kb.note_off(60)

    assert base_key not in ctrl.releases

    kb.note_off(61)
    assert base_key in ctrl.releases


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

    assert ctrl.pressed_modifiers == [(out.Key.shift,)]
    assert ctrl.presses == [base_key]
    assert ctrl.releases == [base_key]


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
