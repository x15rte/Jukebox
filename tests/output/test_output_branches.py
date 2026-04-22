from typing import Any, cast

from pynput.keyboard import Key

import output.output as out
from tests.helpers.fakes import FakeController

out = cast(Any, out)


class _PDI:
    def __init__(self):
        self.down = []
        self.up = []

    def keyDown(self, name, _pause=False):
        self.down.append(name)

    def keyUp(self, name, _pause=False):
        self.up.append(name)



def test_keyboard_backend_uses_pydirectinput_on_windows(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._pdi = cast(Any, _PDI())
    kb._use_pydirectinput = True
    kb._kb = None

    pitch = 61
    key_data = kb._mapper.get_key_data(pitch)
    assert key_data is not None
    base_key = key_data["key"]

    kb.note_on(pitch, 100)
    kb.note_off(pitch)
    kb.pedal_on()
    kb.pedal_off()

    assert "shiftleft" in kb._pdi.down
    assert base_key in kb._pdi.down
    assert "space" in kb._pdi.down
    assert "space" in kb._pdi.up


def test_keyboard_backend_macos_cgevent_path(monkeypatch):
    events = []
    monkeypatch.setattr(out.sys, "platform", "darwin")
    monkeypatch.setattr(out, "get_macos_vk_for_key", lambda k: 42)
    monkeypatch.setattr(
        out,
        "get_macos_vk_for_modifier",
        lambda m: 50 if m in (Key.shift, Key.ctrl, Key.alt) else None,
    )
    monkeypatch.setattr(out, "post_macos_key_event", lambda vk, down, flags: events.append((vk, down, flags)) or True)

    kb = out.KeyboardBackend(use_88_key_layout=False, macos_use_pynput=False)
    kb.note_on(61, 100)
    kb.note_off(61)
    kb.pedal_on()
    kb.pedal_off()
    kb.shutdown()

    assert len(events) > 0


def test_numpad_backend_delay_and_idempotent_pedal(monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setattr(out.rmc, "send_note_message", lambda *a, **k: calls.append(("note", a, k)))
    monkeypatch.setattr(out.rmc, "send_pedal", lambda *a, **k: calls.append(("pedal", a, k)))
    monkeypatch.setattr(out.rmc, "reset_batched_sendinput", lambda: calls.append(("reset", (), {})))
    monkeypatch.setattr(out.time, "sleep", lambda s: sleeps.append(s))

    nb = out.NumpadBackend(inter_message_delay=0.001)
    nb.pedal_on()
    nb.pedal_on()
    nb.pedal_off()
    nb.pedal_off()
    nb.note_on(60, 100)
    nb.note_off(60)
    nb.shutdown()

    pedal_calls = [c for c in calls if c[0] == "pedal"]
    assert len(pedal_calls) == 2
    assert sleeps


def test_create_backend_logs_fallback_when_no_pydirectinput(monkeypatch):
    monkeypatch.setattr(out.rmc, "is_using_pydirectinput", lambda: False)
    monkeypatch.setattr(out.sys, "platform", "win32")
    logs = []

    backend = out.create_backend("midi_numpad", log_message=logs.append)
    assert backend.__class__.__name__ == "NumpadBackend"
    assert any("falling back" in msg.lower() for msg in logs)
