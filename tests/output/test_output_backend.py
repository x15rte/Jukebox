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

    # execute_batch entry is recorded first, then individual calls from super()
    assert b.calls[0][0] == "execute_batch"
    assert b.calls[1][0] == "pedal_on"
    assert b.calls[2][0] == "note_off"
    assert b.calls[3][0] == "note_on"


def test_create_backend_midi_numpad(monkeypatch):
    b = create_backend("midi_numpad", use_88_key_layout=False)
    assert b.__class__.__name__ == "NumpadBackend"


def test_create_backend_key_mode():
    b = create_backend("key", use_88_key_layout=False)
    assert b.__class__.__name__ == "KeyboardBackend"
