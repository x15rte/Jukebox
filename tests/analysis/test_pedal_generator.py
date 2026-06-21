import pytest

from analysis.pedal_generator import PedalGenerator
from models import KeyEvent
from tests.helpers.builders import make_note, make_section


def test_generate_none_returns_empty():
    out = PedalGenerator.generate_events({"pedal_style": "none"}, [], [])
    assert out == []


def test_generate_unknown_style_returns_empty():
    out = PedalGenerator.generate_events({"pedal_style": "unsupported"}, [], [])
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


@pytest.mark.parametrize("pedal_style", ["legato", "rhythmic"])
def test_generate_treble_only_section_uses_earliest_note_start(pedal_style):
    notes = [
        make_note(1, 72, 0.5, 0.1, hand="right"),
        make_note(2, 76, 0.2, 0.3, hand="right"),
    ]
    sec = make_section(0.0, 1.0, notes)

    out = PedalGenerator.generate_events({"pedal_style": pedal_style}, notes, [sec])

    assert [(e.time, e.key_char) for e in out] == [(0.2, "down"), (0.6, "up")]


@pytest.mark.parametrize(
    ("pedal_style", "scenario"),
    [
        ("legato", "truncate_overlap"),
        ("legato", "preserve_non_overlapping"),
        ("legato", "preserve_tail_overlap"),
        ("rhythmic", "truncate_overlap"),
        ("rhythmic", "preserve_non_overlapping"),
        ("rhythmic", "preserve_tail_overlap"),
    ],
)
def test_generate_section_styles(pedal_style, scenario):
    scenarios = {
        "truncate_overlap": {
            "notes": [
                make_note(1, 40, 0.0, 0.4, hand="left"),
                make_note(2, 43, 0.3, 0.3, hand="left"),
            ],
            "sections": [
                make_section(0.0, 0.4, [make_note(1, 40, 0.0, 0.4, hand="left")]),
                make_section(0.5, 0.8, [make_note(2, 43, 0.3, 0.3, hand="left")]),
            ],
            "expected": [(0.0, "down"), (0.3, "up"), (0.3, "down"), (0.6, "up")],
        },
        "preserve_non_overlapping": {
            "notes": [
                make_note(1, 40, 0.0, 0.1, hand="left"),
                make_note(2, 40, 1.0, 0.1, hand="left"),
                make_note(3, 43, 0.85, 0.05, hand="left"),
            ],
            "sections": [
                make_section(0.0, 1.2, [make_note(1, 40, 0.0, 0.1, hand="left"), make_note(2, 40, 1.0, 0.1, hand="left")]),
                make_section(0.8, 0.95, [make_note(3, 43, 0.85, 0.05, hand="left")]),
            ],
            "expected": [
                (0.0, "down"),
                (0.1, "up"),
                (0.85, "down"),
                (0.9, "up"),
                (1.0, "down"),
                (1.1, "up"),
            ],
        },
        "preserve_tail_overlap": {
            "notes": [
                make_note(1, 40, 0.8, 0.4, hand="left"),
                make_note(2, 43, 0.85, 0.05, hand="left"),
            ],
            "sections": [
                make_section(0.8, 1.2, [make_note(1, 40, 0.8, 0.4, hand="left")]),
                make_section(1.1, 1.2, [make_note(2, 43, 0.85, 0.05, hand="left")]),
            ],
            "expected_key_chars": ["down", "up", "down", "up", "down", "up"],
            "expected_times": pytest.approx([0.8, 0.85, 0.85, 0.9, 0.9, 1.2]),
        },
    }
    cfg = scenarios[scenario]
    out = PedalGenerator.generate_events(
        {"pedal_style": pedal_style},
        cfg["notes"],
        cfg["sections"],
    )
    if scenario == "preserve_tail_overlap":
        assert [e.key_char for e in out] == cfg["expected_key_chars"]
        assert [e.time for e in out] == cfg["expected_times"]
    else:
        assert [(e.time, e.key_char) for e in out] == cfg["expected"]


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


def test_generate_rhythmic_merges_overlapping_group_spans():
    notes = [
        make_note(1, 40, 0.0, 0.2, hand="left"),
        make_note(2, 42, 0.15, 0.2, hand="left"),
    ]
    sec = make_section(0.0, 1.0, notes)

    out = PedalGenerator.generate_events({"pedal_style": "rhythmic"}, notes, [sec])

    assert [(e.time, e.key_char) for e in out] == [(0.0, "down"), (0.35, "up")]


def test_generate_rhythmic_merges_adjacent_group_spans():
    notes = [
        make_note(1, 40, 0.0, 0.2, hand="left"),
        make_note(2, 42, 0.2, 0.2, hand="left"),
    ]
    sec = make_section(0.0, 1.0, notes)

    out = PedalGenerator.generate_events({"pedal_style": "rhythmic"}, notes, [sec])

    assert [(e.time, e.key_char) for e in out] == [
        (0.0, "down"),
        (0.4, "up"),
    ]


def test_coalesce_overlapping_intervals_empty_input_returns_empty():
    assert PedalGenerator._coalesce_overlapping_intervals([]) == []


def test_merge_section_intervals_preserves_tail_when_overlap_starts_inside_interval():
    intervals = [(0.9, 1.5)]

    PedalGenerator._merge_section_intervals(intervals, [(0.8, 1.0)])

    assert intervals == [(0.8, 1.0), (1.0, 1.5)]


def test_intervals_to_events_skips_zero_or_negative_length_intervals():
    events = PedalGenerator._intervals_to_events(
        [(0.0, 0.0), (2.0, 1.0), (1.0, 1.5)]
    )

    assert [(event.time, event.key_char) for event in events] == [
        (1.0, "down"),
        (1.5, "up"),
    ]


def test_events_to_intervals_ignores_non_pedal_events():
    events = [
        KeyEvent(0.0, 2, "press", "", pitch=60),
        KeyEvent(0.2, 1, "pedal", "down"),
        KeyEvent(0.4, 4, "release", "", pitch=60),
        KeyEvent(0.7, 0, "pedal", "up"),
    ]

    assert PedalGenerator._events_to_intervals(events) == [(0.2, 0.7)]


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


def test_events_to_intervals_overlapping_down():
    """Two consecutive downs without up in between creates interval for each."""
    events = [
        KeyEvent(0.0, 1, "pedal", "down"),
        KeyEvent(0.5, 1, "pedal", "down"),
        KeyEvent(1.0, 0, "pedal", "up"),
    ]
    intervals = PedalGenerator._events_to_intervals(events)
    assert (0.0, 0.5) in intervals
    assert (0.5, 1.0) in intervals


def test_events_to_intervals_dangling_down():
    """Unclosed down at end creates 0.1s interval."""
    events = [
        KeyEvent(0.0, 1, "pedal", "down"),
    ]
    intervals = PedalGenerator._events_to_intervals(events)
    assert intervals == [(0.0, 0.1)]


def test_harmonic_pedal_same_time_different_pitch_skips_first_down():
    """When first two bass notes start at same time with different pitch, skip initial down."""
    events: list[KeyEvent] = []
    bass_notes = [
        make_note(1, 48, 0.0, 0.5),
        make_note(2, 55, 0.0, 0.3),  # same time, different pitch
    ]
    PedalGenerator._generate_harmonic_pedal(events, bass_notes)
    # No down at time 0.0 since harmony change at same time
    downs = [e for e in events if e.key_char == "down" and abs(e.time - 0.0) < 1e-9]
    assert not downs


def test_adaptive_driver_trailing_silence_early_release():
    """Trailing silence > 0.35s after last driver note triggers early release."""
    driver_notes = [make_note(1, 48, 0.0, 1.0)]  # ends at 1.0
    all_notes = [
        make_note(1, 48, 0.0, 1.0),
        make_note(2, 55, 1.5, 0.5),  # overall ends at 2.0, gap > 0.35
    ]
    out = PedalGenerator._generate_adaptive_pedal_driver(driver_notes, all_notes)
    # Should have early release at last_end (1.0)
    ups = [e for e in out if e.key_char == "up"]
    assert any(abs(e.time - 1.0) < 1e-9 for e in ups)
