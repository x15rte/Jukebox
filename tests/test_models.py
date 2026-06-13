from models import KeyEvent, KeyState, MidiTrack, Note


def test_note_end_time_property():
    n = Note(1, 60, 100, 1.25, 0.5)
    assert n.end_time == 1.75


def test_midi_track_instrument_name_ranges_and_drum_override():
    t = MidiTrack(0, "A", 5, False, [])
    assert t.instrument_name == "Piano"

    t.program_change = 9
    assert t.instrument_name == "Chromatic Perc"

    t.program_change = 20
    assert t.instrument_name == "Organ"

    t.program_change = 24
    assert t.instrument_name == "Guitar"

    t.program_change = 32
    assert t.instrument_name == "Bass"

    t.program_change = 40
    assert t.instrument_name == "Strings"

    t.program_change = 48
    assert t.instrument_name == "Ensemble"

    t.program_change = 99
    assert t.instrument_name == "Instrument 99"

    t.is_drum = True
    assert t.instrument_name == "Drums/Percussion"


def test_key_state_press_release():
    ks = KeyState("a")
    assert ks.is_active is False
    ks.press()
    assert ks.is_active is True
    ks.release()
    assert ks.is_active is False


def test_midi_track_note_count_and_key_event_defaults():
    t = MidiTrack(1, "B", 0, False, [Note(1, 60, 100, 0.0, 0.1), Note(2, 61, 100, 0.1, 0.1)])
    assert t.note_count == 2

    e = KeyEvent(time=1.0, priority=1, action="press", key_char="a")
    assert e.pitch is None
    assert e.velocity == 100
