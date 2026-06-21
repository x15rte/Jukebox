import pytest

from models import KeyEvent, KeyState, MidiTrack, MusicalSection, Note


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
    assert t.instrument_name == "Synth Effects"

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



def test_key_event_ordering_by_time_then_priority():
    events = [
        KeyEvent(time=2.0, priority=1, action="a", key_char="x"),
        KeyEvent(time=1.0, priority=2, action="b", key_char="x"),
        KeyEvent(time=2.0, priority=0, action="c", key_char="x"),
        KeyEvent(time=1.0, priority=0, action="d", key_char="x"),
    ]
    sorted_list = sorted(events)
    assert sorted_list[0].action == "d"
    assert sorted_list[1].action == "b"
    assert sorted_list[2].action == "c"
    assert sorted_list[3].action == "a"


def test_note_end_time_with_zero_duration():
    n1 = Note(1, 60, 100, 1.0, 0.0)
    assert n1.end_time == 1.0
    with pytest.raises(ValueError, match="duration .* must be >= 0"):
        Note(2, 60, 100, 1.0, -0.5)


def test_key_event_equality_uses_all_fields():
    """KeyEvent equality should distinguish different action/pitch/velocity at same time+priority."""
    base = KeyEvent(0.0, 2, "press", "c", 60, 100)
    same = KeyEvent(0.0, 2, "press", "c", 60, 100)
    diff_action = KeyEvent(0.0, 2, "release", "c", 60, 100)
    diff_pitch = KeyEvent(0.0, 2, "press", "c", 64, 100)
    diff_velocity = KeyEvent(0.0, 2, "press", "c", 60, 80)
    diff_key_char = KeyEvent(0.0, 2, "press", "d", 60, 100)
    diff_time = KeyEvent(0.5, 2, "press", "c", 60, 100)

    assert base == same
    assert base != diff_action
    assert base != diff_pitch
    assert base != diff_velocity
    assert base != diff_key_char
    assert base != diff_time



def test_note_validation():
    with pytest.raises(ValueError, match="pitch.*out of range"):
        Note(1, -1, 100, 0.0, 0.1)
    with pytest.raises(ValueError, match="velocity.*out of range"):
        Note(1, 60, -1, 0.0, 0.1)
    with pytest.raises(ValueError, match="start_time.*must be >= 0"):
        Note(1, 60, 100, -0.1, 0.1)


def test_midi_track_instrument_name_all_ranges():
    t = MidiTrack(0, "x", 0, False, [])
    for prog, expected in [
        (56, "Brass"), (64, "Reed"), (72, "Pipe"),
        (80, "Synth Lead"), (88, "Synth Pad"), (96, "Synth Effects"),
        (104, "Ethnic"), (112, "Percussive"), (120, "Sound Effects"),
        (200, "Instrument 200"),
    ]:
        t.program_change = prog
        assert t.instrument_name == expected, f"prog={prog}"


def test_key_event_lt_non_keyevent():
    e = KeyEvent(time=1.0, priority=1, action="press", key_char="a")
    result = e.__lt__("not a KeyEvent")
    assert result is NotImplemented


def test_musical_section_post_init_fixes_end_time():
    s = MusicalSection(start_time=5.0, end_time=3.0, notes=[])
    assert s.end_time == 5.0

def test_musical_section_post_init_fixes_end_beat():
    s = MusicalSection(start_time=0.0, end_time=2.0, start_beat=5.0, end_beat=3.0, notes=[])
    assert s.end_beat == 5.0
