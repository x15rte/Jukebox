from models import KeyEvent, KeyState, MidiTrack, Note


def test_note_end_time_property():
    n = Note(1, 60, 100, 1.25, 0.5)
    if not (n.end_time == 1.75):
        raise AssertionError("Assertion failed")


def test_midi_track_instrument_name_ranges_and_drum_override():
    t = MidiTrack(0, "A", 5, False, [])
    if not (t.instrument_name == "Piano"):
        raise AssertionError("Assertion failed")

    t.program_change = 9
    if not (t.instrument_name == "Chromatic Perc"):
        raise AssertionError("Assertion failed")

    t.program_change = 20
    if not (t.instrument_name == "Organ"):
        raise AssertionError("Assertion failed")

    t.program_change = 24
    if not (t.instrument_name == "Guitar"):
        raise AssertionError("Assertion failed")

    t.program_change = 32
    if not (t.instrument_name == "Bass"):
        raise AssertionError("Assertion failed")

    t.program_change = 40
    if not (t.instrument_name == "Strings"):
        raise AssertionError("Assertion failed")

    t.program_change = 48
    if not (t.instrument_name == "Ensemble"):
        raise AssertionError("Assertion failed")

    t.program_change = 99
    if not (t.instrument_name == "Instrument 99"):
        raise AssertionError("Assertion failed")

    t.is_drum = True
    if not (t.instrument_name == "Drums/Percussion"):
        raise AssertionError("Assertion failed")


def test_key_state_press_release():
    ks = KeyState("a")
    if not (ks.is_physically_down is False):
        raise AssertionError("Assertion failed")
    ks.press()
    if not (ks.is_physically_down is True):
        raise AssertionError("Assertion failed")
    ks.release()
    if not (ks.is_physically_down is False):
        raise AssertionError("Assertion failed")


def test_midi_track_note_count_and_key_event_defaults():
    t = MidiTrack(1, "B", 0, False, [Note(1, 60, 100, 0.0, 0.1), Note(2, 61, 100, 0.1, 0.1)])
    if not (t.note_count == 2):
        raise AssertionError("Assertion failed")

    e = KeyEvent(time=1.0, priority=1, action="press", key_char="a")
    if not (e.pitch is None):
        raise AssertionError("Assertion failed")
    if not (e.velocity == 100):
        raise AssertionError("Assertion failed")
