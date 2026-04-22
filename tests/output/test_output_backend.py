from output.output import create_backend
from tests.helpers.fakes import FakeEvent, RecorderBackend


def test_execute_batch_orders_pedal_release_press():
    b = RecorderBackend()
    events = [
        FakeEvent(0.0, 4, "release", key_char="", pitch=60),
        FakeEvent(0.0, 1, "pedal", key_char="down"),
        FakeEvent(0.0, 2, "press", key_char="", pitch=64, velocity=120),
    ]
    b.execute_batch(events)

    if not (b.calls[0][0] == "pedal_on"):
        raise AssertionError("Assertion failed")
    if not (b.calls[1][0] == "note_off"):
        raise AssertionError("Assertion failed")
    if not (b.calls[2][0] == "note_on"):
        raise AssertionError("Assertion failed")


def test_create_backend_midi_numpad(monkeypatch):
    monkeypatch.setattr("output.output.rmc.set_macos_cgevent", lambda *a, **k: None)
    b = create_backend("midi_numpad", use_88_key_layout=False)
    if not (b.__class__.__name__ == "NumpadBackend"):
        raise AssertionError("Assertion failed")


def test_create_backend_key_mode():
    b = create_backend("key", use_88_key_layout=False)
    if not (b.__class__.__name__ == "KeyboardBackend"):
        raise AssertionError("Assertion failed")
