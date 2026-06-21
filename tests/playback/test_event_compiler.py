import math

import pytest

from playback.player import EventCompiler
from tests.helpers.builders import make_note, make_section


def _section_for(notes):
    return [
        make_section(
            min(n.start_time for n in notes),
            max(n.end_time for n in notes),
            notes,
            pace="normal",
        )
    ]


def _pedal_events(events):
    return [e for e in events if e.action == "pedal"]


def _stub_humanizer(monkeypatch, *, apply_to_hand_impl=None, apply_tempo_rubato_impl=None):
    """Monkeypatches playback.player.Humanizer with a minimal no-op stub.

    Optional callbacks receive (notes, hand, resync) or (notes, sections)
    when the corresponding method is called.
    """
    class H:
        def __init__(self, config):
            pass

        @staticmethod
        def prepare_shared_offsets(notes):
            pass

        @staticmethod
        def apply_to_hand(notes, hand, resync):
            if apply_to_hand_impl:
                apply_to_hand_impl(notes, hand, resync)

        @staticmethod
        def apply_tempo_rubato(notes, sections):
            if apply_tempo_rubato_impl:
                apply_tempo_rubato_impl(notes, sections)

    monkeypatch.setattr("playback.player.Humanizer", H)


def test_compile_produces_press_release_pairs_sorted():
    notes = [
        make_note(1, 60, 0.0, 0.5, hand="right"),
        make_note(2, 64, 0.1, 0.4, hand="right"),
    ]
    events = EventCompiler.compile(notes, _section_for(notes), {"pedal_style": "none"})

    assert len(events) == 4
    assert all(events[i].time <= events[i + 1].time for i in range(len(events) - 1))
    assert [e.action for e in events].count("press") == 2
    assert [e.action for e in events].count("release") == 2


def test_compile_can_emit_mistake_notes(monkeypatch):
    notes = [make_note(1, 60, 0.0, 0.3, hand="right")]
    monkeypatch.setattr("playback.player.random.random", lambda: 0.0)
    monkeypatch.setattr("playback.player.EventCompiler._mistake_pitch", lambda _: 61)

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {"enable_mistakes": True, "mistake_chance": 100, "pedal_style": "none"},
    )
    press_pitches = [e.pitch for e in events if e.action == "press"]
    assert press_pitches == [61]


def test_compile_with_pedal_none_skips_pedal_remapping(monkeypatch):
    notes = [make_note(1, 60, 0.0, 0.3, hand="right")]
    _stub_humanizer(monkeypatch)
    monkeypatch.setattr(
        "playback.player.EventCompiler._build_pedal_notes",
        lambda *_a, **_k: pytest.fail("pedal notes remapping should be skipped"),
    )
    monkeypatch.setattr(
        "playback.player.EventCompiler._build_pedal_sections",
        lambda *_a, **_k: pytest.fail("pedal section remapping should be skipped"),
    )

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {"enable_vary_timing": True, "pedal_style": "none"},
    )

    assert [e.action for e in events] == ["press", "release"]


def test_mistake_pitch_stays_in_bounds_for_black_key(monkeypatch):
    monkeypatch.setattr("playback.player.random.shuffle", lambda _: None)
    out = EventCompiler._mistake_pitch(1)
    assert out is not None and 0 <= out <= 127


def test_compile_original_raw_pedal_stays_literal_without_humanizer():
    notes = [make_note(1, 52, 0.0, 1.0, hand="left")]

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "original",
            "raw_pedal_events": [(0.0, 127), (0.75, 0)],
            "enable_mistakes": False,
        },
    )

    assert all(events[i].time <= events[i + 1].time for i in range(len(events) - 1))

    pedal_events = [e for e in events if e.action == "pedal"]
    assert [(e.time, e.key_char) for e in pedal_events] == [(0.0, "down"), (0.75, "up")]

    press_events = [e for e in events if e.action == "press"]
    release_events = [e for e in events if e.action == "release"]

    assert {e.pitch for e in press_events} == {52}
    assert {e.pitch for e in release_events} == {52}
    assert len(press_events) == 1
    assert len(release_events) == 1


def test_compile_hybrid_pedal_uses_original_lengths_for_articulation_humanization(
    monkeypatch,
):
    notes = [
        make_note(1, 40, 0.0, 0.1, hand="left"),
        make_note(2, 40, 0.4, 0.1, hand="left"),
    ]
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *_a, **_k: 0.0)
    monkeypatch.setattr("analysis.humanizer.random.random", lambda: 1.0)

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "hybrid",
            "enable_vary_articulation": True,
            "vary_articulation": True,
            "articulation": 0.5,
        },
    )

    pedal_events = _pedal_events(events)

    assert [(e.time, e.key_char) for e in pedal_events] == [(0.0, "down"), (0.5, "up")]


def test_compile_hybrid_pedal_uses_humanized_start_times_for_timing_variation(
    monkeypatch,
):
    notes = [
        make_note(1, 40, 0.0, 0.1, hand="left"),
        make_note(2, 40, 0.4, 0.1, hand="left"),
    ]
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *_a, **_k: 0.05)
    monkeypatch.setattr("analysis.humanizer.random.random", lambda: 1.0)

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "hybrid",
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up"]
    assert [e.time for e in pedal_events] == pytest.approx([0.05, 0.55])


def test_compile_original_fallback_pedal_uses_humanized_start_times_and_original_lengths(
    monkeypatch,
):
    notes = [
        make_note(1, 40, 0.0, 0.1, hand="left"),
        make_note(2, 40, 0.4, 0.1, hand="left"),
    ]
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *_a, **_k: 0.05)
    monkeypatch.setattr("analysis.humanizer.random.random", lambda: 1.0)

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "original",
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
            "enable_vary_articulation": True,
            "vary_articulation": True,
            "articulation": 0.5,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up"]
    assert [e.time for e in pedal_events] == pytest.approx([0.05, 0.55])


def test_compile_original_raw_pedal_follows_humanized_note_timing(monkeypatch):
    notes = [make_note(1, 40, 0.0, 1.0, hand="left")]
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *_a, **_k: 0.05)
    monkeypatch.setattr("analysis.humanizer.random.random", lambda: 1.0)

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "original",
            "raw_pedal_events": [(0.0, 127), (1.0, 0)],
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
            "enable_vary_articulation": True,
            "vary_articulation": True,
            "articulation": 1.0,
        },
    )

    pedal_events = _pedal_events(events)
    press_events = [e for e in events if e.action == "press"]
    release_events = [e for e in events if e.action == "release"]

    assert [e.key_char for e in pedal_events] == ["down", "up"]
    assert [e.time for e in pedal_events] == pytest.approx([0.05, 0.95])
    assert [e.time for e in press_events] == pytest.approx([0.05])
    assert [e.time for e in release_events] == pytest.approx([0.95])


def test_compile_original_raw_pedal_without_transitions_does_not_fallback(monkeypatch):
    notes = [make_note(1, 40, 0.0, 0.5, hand="left")]

    def _shift_onset(notes, hand, resync):
        for note in notes:
            note.start_time += 0.1

    _stub_humanizer(monkeypatch, apply_to_hand_impl=_shift_onset)
    raw_pedal_events = [(0.0, 0), (0.2, 0)]

    without_humanizer = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "original",
            "raw_pedal_events": raw_pedal_events,
        },
    )
    with_humanizer = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "original",
            "raw_pedal_events": raw_pedal_events,
            "enable_vary_timing": True,
        },
    )

    assert _pedal_events(without_humanizer) == []
    assert _pedal_events(with_humanizer) == []


def test_compile_original_raw_pedal_normalizes_transition_state_machine_before_remap(
    monkeypatch,
):
    notes = [
        make_note(1, 40, 0.0, 0.5, hand="left"),
        make_note(2, 43, 1.0, 0.5, hand="left"),
    ]
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *_a, **_k: 0.05)
    monkeypatch.setattr("analysis.humanizer.random.random", lambda: 1.0)

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "original",
            "raw_pedal_events": [
                (0.0, 127),
                (0.1, 100),
                (0.5, 0),
                (0.6, 0),
                (1.0, 127),
                (1.1, 120),
            ],
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up", "down", "up"]
    assert [e.time for e in pedal_events] == pytest.approx([0.05, 0.55, 1.05, 1.15])


def test_compile_original_raw_pedal_preserves_alternating_repedal_order(monkeypatch):
    notes = [
        make_note(1, 40, 0.0, 0.5, hand="left"),
        make_note(2, 43, 1.0, 0.3, hand="left"),
    ]

    def _reorder_notes(notes, hand, resync):
        for note in notes:
            if note.id == 1:
                note.start_time = 0.4
                note.duration = 0.8
            else:
                note.start_time = 0.8
                note.duration = 0.2

    _stub_humanizer(monkeypatch, apply_to_hand_impl=_reorder_notes)

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "original",
            "raw_pedal_events": [(0.0, 127), (0.5, 0), (1.0, 127), (1.3, 0)],
            "enable_vary_timing": True,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up", "down", "up"]
    assert all(events[i].time <= events[i + 1].time for i in range(len(events) - 1))
    assert pedal_events[0].time == pytest.approx(0.4)
    assert pedal_events[2].time == pytest.approx(0.8)
    assert pedal_events[3].time == pytest.approx(1.0)
    assert pedal_events[0].time < pedal_events[1].time < pedal_events[2].time < pedal_events[3].time
    assert pedal_events[1].time == math.nextafter(pedal_events[2].time, -math.inf)


def test_compile_original_raw_pedal_preserves_crossed_repedal_span_with_real_humanizer(
    monkeypatch,
):
    notes = [
        make_note(1, 40, 0.0, 1.0, hand="left"),
        make_note(2, 43, 1.2, 0.2, hand="left"),
    ]
    offsets = iter([0.2, -0.2])
    monkeypatch.setattr(
        "analysis.humanizer.random.gauss",
        lambda *_a, **_k: next(offsets),
    )

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "original",
            "raw_pedal_events": [(0.0, 127), (1.0, 0), (1.2, 127), (1.4, 0)],
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.2,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up", "down", "up"]
    assert all(events[i].time <= events[i + 1].time for i in range(len(events) - 1))
    assert pedal_events[0].time == pytest.approx(0.2)
    assert pedal_events[2].time == pytest.approx(1.0)
    assert pedal_events[3].time == pytest.approx(1.2)
    assert pedal_events[0].time < pedal_events[1].time < pedal_events[2].time < pedal_events[3].time
    assert pedal_events[1].time == math.nextafter(pedal_events[2].time, -math.inf)
    assert pedal_events[3].time - pedal_events[2].time == pytest.approx(0.2)


def test_compile_original_raw_pedal_same_onset_chord_uses_earliest_humanized_anchor(
    monkeypatch,
):
    notes = [
        make_note(1, 72, 0.0, 1.0, hand="left"),
        make_note(2, 60, 0.0, 1.0, hand="left"),
    ]
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *_a, **_k: 0.05)

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "original",
            "raw_pedal_events": [(0.0, 127), (1.0, 0)],
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
            "enable_chord_roll": True,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up"]
    assert pedal_events[0].time == pytest.approx(0.05)


def test_compile_original_raw_pedal_same_release_time_uses_latest_humanized_anchor(
    monkeypatch,
):
    notes = [
        make_note(1, 72, 0.0, 1.0, hand="left"),
        make_note(2, 60, 0.0, 1.0, hand="left"),
    ]
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *_a, **_k: 0.05)

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "original",
            "raw_pedal_events": [(0.0, 127), (1.0, 0)],
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
            "enable_chord_roll": True,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up"]
    assert pedal_events[1].time == pytest.approx(1.056)


def test_compile_original_raw_pedal_uses_nearest_upcoming_onset_for_anticipatory_down(
    monkeypatch,
):
    notes = [
        make_note(1, 40, 0.0, 0.2, hand="left"),
        make_note(2, 43, 1.0, 0.2, hand="left"),
    ]
    offsets = iter([0.0, 0.1])
    monkeypatch.setattr(
        "analysis.humanizer.random.gauss",
        lambda *_a, **_k: next(offsets),
    )

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "original",
            "raw_pedal_events": [(0.92, 127), (1.2, 0)],
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up"]
    assert pedal_events[0].time == pytest.approx(1.02)


def test_compile_original_raw_pedal_uses_upcoming_onset_for_anticipatory_up(
    monkeypatch,
):
    notes = [
        make_note(1, 40, 0.0, 0.2, hand="left"),
        make_note(2, 43, 1.0, 0.2, hand="left"),
    ]

    def _nudge_note2(notes, hand, resync):
        for note in notes:
            if note.id == 2:
                note.start_time = 1.1
                note.duration = 0.1

    _stub_humanizer(monkeypatch, apply_to_hand_impl=_nudge_note2)

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "original",
            "raw_pedal_events": [(0.92, 127), (0.98, 0)],
            "enable_vary_timing": True,
        },
    )

    pedal_events = _pedal_events(events)
    note2_press = next(e for e in events if e.action == "press" and e.pitch == 43)
    note2_release = next(e for e in events if e.action == "release" and e.pitch == 43)

    assert [e.key_char for e in pedal_events] == ["down", "up"]
    assert pedal_events[0].time == pytest.approx(1.02)
    assert pedal_events[1].time == pytest.approx(1.08)
    assert note2_press.time == pytest.approx(1.1)
    assert note2_release.time == pytest.approx(1.2)
    assert all(events[i].time < events[i + 1].time for i in range(len(events) - 1))


def test_compile_original_raw_pedal_uses_nearest_release_anchor_for_anticipatory_up(
    monkeypatch,
):
    notes = [
        make_note(1, 40, 0.0, 0.2, hand="left"),
        make_note(2, 43, 1.0, 0.2, hand="left"),
    ]
    offsets = iter([0.0, 0.1])
    monkeypatch.setattr(
        "analysis.humanizer.random.gauss",
        lambda *_a, **_k: next(offsets),
    )

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "original",
            "raw_pedal_events": [(0.92, 127), (1.08, 0)],
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up"]
    assert pedal_events[1].time == pytest.approx(1.18)


def test_compile_original_raw_pedal_nudges_same_timestamp_up_after_down(
    monkeypatch,
):
    notes = [make_note(1, 40, 0.0, 1.0, hand="left")]
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *_a, **_k: 0.05)
    monkeypatch.setattr("analysis.humanizer.random.random", lambda: 1.0)

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "original",
            "raw_pedal_events": [(0.0, 127), (0.0, 0)],
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
            "enable_vary_articulation": True,
            "vary_articulation": True,
            "articulation": 1.0,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up"]
    assert all(events[i].time <= events[i + 1].time for i in range(len(events) - 1))
    assert pedal_events[0].time == pytest.approx(0.05)
    assert pedal_events[1].time > pedal_events[0].time


@pytest.mark.parametrize("pedal_style", ["legato", "rhythmic"])
def test_compile_treble_only_pedal_uses_earliest_remapped_section_bounds(
    monkeypatch, pedal_style
):
    notes = [
        make_note(1, 72, 0.2, 0.3, hand="right"),
        make_note(2, 76, 0.3, 0.2, hand="right"),
    ]
    offsets = iter([0.06, -0.06])
    monkeypatch.setattr(
        "analysis.humanizer.random.gauss",
        lambda *_a, **_k: next(offsets),
    )

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": pedal_style,
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up"]
    assert [e.time for e in pedal_events] == pytest.approx([0.24, 0.56])


@pytest.mark.parametrize("pedal_style", ["legato", "rhythmic"])
def test_compile_section_pedal_truncates_previous_overlap_when_humanized(
    monkeypatch, pedal_style
):
    first_note = make_note(1, 40, 0.0, 0.4, hand="left")
    second_note = make_note(2, 43, 0.5, 0.3, hand="left")
    sections = [
        make_section(0.0, 0.4, [first_note]),
        make_section(0.5, 0.8, [second_note]),
    ]
    offsets = iter([0.0, -0.2])
    monkeypatch.setattr(
        "analysis.humanizer.random.gauss",
        lambda *_a, **_k: next(offsets),
    )
    monkeypatch.setattr("analysis.humanizer.random.random", lambda: 1.0)

    events = EventCompiler.compile(
        [first_note, second_note],
        sections,
        {
            "pedal_style": pedal_style,
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up", "down", "up"]
    assert [e.time for e in pedal_events] == pytest.approx([0.0, 0.3, 0.3, 0.6])


def test_compile_rhythmic_pedal_uses_remapped_section_note_times(monkeypatch):
    notes = [
        make_note(1, 40, 0.0, 0.2, hand="left"),
        make_note(2, 43, 0.5, 0.2, hand="left"),
    ]
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *_a, **_k: 0.05)
    monkeypatch.setattr("analysis.humanizer.random.random", lambda: 1.0)

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "rhythmic",
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up", "down", "up"]
    assert [e.time for e in pedal_events] == pytest.approx([0.05, 0.25, 0.55, 0.75])


def test_compile_rhythmic_pedal_uses_humanized_note_releases(monkeypatch):
    notes = [
        make_note(1, 40, 0.0, 0.4, hand="left"),
        make_note(2, 43, 0.6, 0.4, hand="left"),
    ]
    offsets = iter([0.05, 0.05])
    monkeypatch.setattr(
        "analysis.humanizer.random.gauss",
        lambda *_a, **_k: next(offsets),
    )
    monkeypatch.setattr("analysis.humanizer.random.random", lambda: 0.0)

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "rhythmic",
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
            "enable_vary_articulation": True,
            "vary_articulation": True,
            "articulation": 0.5,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up", "down", "up"]
    assert [e.time for e in pedal_events] == pytest.approx([0.05, 0.25, 0.65, 0.85])


def test_compile_rhythmic_pedal_merges_humanized_overlap_within_section(monkeypatch):
    notes = [
        make_note(1, 40, 0.0, 0.2, hand="left"),
        make_note(2, 43, 0.2, 0.2, hand="left"),
    ]
    offsets = iter([0.05, -0.05])
    monkeypatch.setattr(
        "analysis.humanizer.random.gauss",
        lambda *_a, **_k: next(offsets),
    )

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "rhythmic",
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up"]
    assert [e.time for e in pedal_events] == pytest.approx([0.05, 0.35])


def test_compile_legato_pedal_uses_remapped_section_notes_with_original_lengths(
    monkeypatch,
):
    notes = [
        make_note(1, 40, 0.0, 0.2, hand="left"),
        make_note(2, 40, 0.4, 0.2, hand="left"),
    ]
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *_a, **_k: 0.05)
    monkeypatch.setattr("analysis.humanizer.random.random", lambda: 1.0)

    events = EventCompiler.compile(
        notes,
        _section_for(notes),
        {
            "pedal_style": "legato",
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
            "enable_vary_articulation": True,
            "vary_articulation": True,
            "articulation": 0.5,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up", "down", "up"]
    assert [e.time for e in pedal_events] == pytest.approx([0.05, 0.25, 0.45, 0.65])


@pytest.mark.parametrize("pedal_style", ["legato", "rhythmic"])
def test_compile_section_pedal_sorts_reordered_humanized_sections(
    monkeypatch, pedal_style
):
    first_note = make_note(1, 40, 0.1, 0.2, hand="left")
    second_note = make_note(2, 43, 0.3, 0.2, hand="left")
    sections = [
        make_section(0.1, 0.3, [first_note]),
        make_section(0.3, 0.5, [second_note]),
    ]
    offsets = iter([0.15, -0.15])
    monkeypatch.setattr(
        "analysis.humanizer.random.gauss",
        lambda *_a, **_k: next(offsets),
    )

    events = EventCompiler.compile(
        [first_note, second_note],
        sections,
        {
            "pedal_style": pedal_style,
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == ["down", "up", "down", "up"]
    assert [e.time for e in pedal_events] == pytest.approx([0.15, 0.25, 0.25, 0.45])


@pytest.mark.parametrize("pedal_style", ["legato", "rhythmic"])
def test_compile_section_pedal_preserves_later_spans_from_earlier_section(
    monkeypatch, pedal_style
):
    first_early = make_note(1, 40, 0.0, 0.1, hand="left")
    first_late = make_note(2, 40, 1.0, 0.1, hand="left")
    second = make_note(3, 43, 1.1, 0.05, hand="left")
    sections = [
        make_section(0.0, 1.2, [first_early, first_late]),
        make_section(1.1, 1.2, [second]),
    ]
    offsets = iter([0.0, 0.0, -0.25])
    monkeypatch.setattr(
        "analysis.humanizer.random.gauss",
        lambda *_a, **_k: next(offsets),
    )

    events = EventCompiler.compile(
        [first_early, first_late, second],
        sections,
        {
            "pedal_style": pedal_style,
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == [
        "down",
        "up",
        "down",
        "up",
        "down",
        "up",
    ]
    assert [e.time for e in pedal_events] == pytest.approx(
        [0.0, 0.1, 0.85, 0.9, 1.0, 1.1]
    )


@pytest.mark.parametrize("pedal_style", ["legato", "rhythmic"])
def test_compile_section_pedal_preserves_tail_after_partial_overlap(
    monkeypatch, pedal_style
):
    first = make_note(1, 40, 0.8, 0.4, hand="left")
    second = make_note(2, 43, 1.1, 0.05, hand="left")
    sections = [
        make_section(0.8, 1.2, [first]),
        make_section(1.1, 1.2, [second]),
    ]
    offsets = iter([0.0, -0.25])
    monkeypatch.setattr(
        "analysis.humanizer.random.gauss",
        lambda *_a, **_k: next(offsets),
    )

    events = EventCompiler.compile(
        [first, second],
        sections,
        {
            "pedal_style": pedal_style,
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
        },
    )

    pedal_events = _pedal_events(events)

    assert [e.key_char for e in pedal_events] == [
        "down",
        "up",
        "down",
        "up",
        "down",
        "up",
    ]
    assert [e.time for e in pedal_events] == pytest.approx(
        [0.8, 0.85, 0.85, 0.9, 0.9, 1.2]
    )


def test_build_pedal_sections_reuses_existing_pedal_notes_without_deepcopy(
    monkeypatch,
):
    original_note = make_note(1, 40, 0.0, 0.2, hand="left")
    pedal_note = make_note(1, 40, 0.1, 0.2, hand="left")
    sections = [make_section(0.0, 0.2, [original_note])]

    monkeypatch.setattr(
        "playback.player.copy.deepcopy",
        lambda _value: pytest.fail("deepcopy should not run for remapped section notes"),
    )

    pedal_sections = EventCompiler._build_pedal_sections(
        sections,
        [pedal_note],
        [original_note],
    )

    assert pedal_sections[0].notes == [pedal_note]
    assert pedal_sections[0].start_time == pytest.approx(0.1)
    assert pedal_sections[0].end_time == pytest.approx(0.3)


def test_build_pedal_sections_falls_back_to_deepcopied_original_note():
    original_note = make_note(1, 40, 0.4, 0.6, hand="left")
    section_note = make_note(1, 40, 1.5, 0.1, hand="left")
    sections = [make_section(0.0, 2.0, [section_note])]

    pedal_sections = EventCompiler._build_pedal_sections(
        sections,
        [],
        [original_note],
    )

    remapped_note = pedal_sections[0].notes[0]

    assert remapped_note == original_note
    assert remapped_note is not original_note
    assert remapped_note is not section_note
    assert pedal_sections[0].start_time == pytest.approx(0.4)
    assert pedal_sections[0].end_time == pytest.approx(1.0)
