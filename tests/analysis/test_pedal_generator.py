from analysis.pedal_generator import PedalGenerator
from tests.helpers.builders import make_note, make_section


def test_generate_none_returns_empty():
    out = PedalGenerator.generate_events({"pedal_style": "none"}, [], [])
    assert out == []


def test_generate_original_uses_raw_events():
    out = PedalGenerator.generate_events(
        {"pedal_style": "original", "raw_pedal_events": [(0.0, 127), (1.0, 0)]},
        [],
        [],
    )
    assert [e.action for e in out] == ["pedal", "pedal"]
    assert [e.key_char for e in out] == ["down", "up"]


def test_generate_original_falls_back_to_hybrid_when_missing_raw():
    notes = [
        make_note(1, 40, 0.0, 0.4, hand="left"),
        make_note(2, 41, 0.5, 0.4, hand="left"),
    ]
    out = PedalGenerator.generate_events({"pedal_style": "original"}, notes, [])
    assert len(out) >= 2
    assert out[0].key_char == "down"
    assert out[-1].key_char == "up"


def test_harmonic_pedal_repedals_on_harmony_change():
    notes = [
        make_note(1, 40, 0.0, 0.3, hand="left"),
        make_note(2, 43, 0.2, 0.3, hand="left"),
    ]
    sec = make_section(0.0, 1.0, notes)
    out = PedalGenerator.generate_events({"pedal_style": "legato"}, notes, [sec])
    assert any(e.key_char == "down" for e in out)
    assert any(e.key_char == "up" for e in out)


def test_convert_raw_pedal_state_machine():
    out = PedalGenerator._convert_raw_pedal([(0.0, 127), (0.2, 100), (0.4, 0), (0.6, 0)])
    assert [(e.time, e.key_char) for e in out] == [(0.0, "down"), (0.4, "up")]


def test_generate_hybrid_uses_treble_when_no_left_hand():
    notes = [
        make_note(1, 72, 0.0, 0.2, hand="right"),
        make_note(2, 74, 0.4, 0.2, hand="right"),
    ]
    out = PedalGenerator.generate_events({"pedal_style": "hybrid"}, notes, [])
    assert out[0].key_char == "down"
    assert out[-1].key_char == "up"


def test_generate_legato_section_without_left_hand_holds_whole_section():
    notes = [
        make_note(1, 72, 0.0, 0.2, hand="right"),
        make_note(2, 76, 0.2, 0.5, hand="right"),
    ]
    sec = make_section(0.0, 1.0, notes)

    out = PedalGenerator.generate_events({"pedal_style": "legato"}, notes, [sec])

    assert [(e.time, e.key_char) for e in out] == [(0.0, "down"), (0.7, "up")]


def test_generate_rhythmic_emits_per_left_hand_group():
    notes = [
        make_note(1, 40, 0.0, 0.2, hand="left"),
        make_note(2, 42, 0.5, 0.2, hand="left"),
    ]
    sec = make_section(0.0, 1.0, notes)

    out = PedalGenerator.generate_events({"pedal_style": "rhythmic"}, notes, [sec])

    assert [(e.time, e.key_char) for e in out] == [
        (0.0, "down"),
        (0.2, "up"),
        (0.5, "down"),
        (0.7, "up"),
    ]


def test_adaptive_driver_long_gap_releases_and_restarts():
    d = [
        make_note(1, 40, 0.0, 0.2, hand="left"),
        make_note(2, 41, 1.0, 0.2, hand="left"),
    ]

    out = PedalGenerator._generate_adaptive_pedal_driver(d, d)

    assert (0.2, "up") in [(e.time, e.key_char) for e in out]
    assert (1.0, "down") in [(e.time, e.key_char) for e in out]


def test_adaptive_driver_window_unsafe_interval_triggers_repedal():
    d = [
        make_note(1, 40, 0.0, 0.3, hand="left"),
        make_note(2, 45, 0.31, 0.3, hand="left"),
    ]
    all_notes = d + [make_note(3, 46, 0.31, 0.1, hand="right")]

    out = PedalGenerator._generate_adaptive_pedal_driver(d, all_notes)

    repedal_pairs = [(e.time, e.key_char) for e in out if e.time in (0.31, 0.36)]
    assert (0.31, "up") in repedal_pairs
    assert (0.36, "down") in repedal_pairs


def test_harmonic_pedal_gap_branch():
    notes = [
        make_note(1, 40, 0.0, 0.2, hand="left"),
        make_note(2, 40, 0.5, 0.2, hand="left"),
    ]
    events = []

    PedalGenerator._generate_harmonic_pedal(events, notes)

    assert (0.2, "up") in [(e.time, e.key_char) for e in events]
    assert (0.5, "down") in [(e.time, e.key_char) for e in events]


def test_generate_skips_empty_section_notes():
    notes = [make_note(1, 40, 0.0, 0.2, hand="left")]
    sec = make_section(0.0, 1.0, [])

    out = PedalGenerator.generate_events({"pedal_style": "legato"}, notes, [sec])

    assert out == []


def test_adaptive_driver_empty_driver_notes_returns_empty():
    out = PedalGenerator._generate_adaptive_pedal_driver([], [])

    assert out == []


def test_harmonic_pedal_noop_with_empty_bass_notes():
    events = []

    PedalGenerator._generate_harmonic_pedal(events, [])

    assert events == []
