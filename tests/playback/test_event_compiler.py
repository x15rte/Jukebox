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


def test_mistake_pitch_stays_in_bounds_for_black_key(monkeypatch):
    monkeypatch.setattr("playback.player.random.shuffle", lambda _: None)
    out = EventCompiler._mistake_pitch(1)
    assert out is not None and 0 <= out <= 127


def test_compile_black_box_with_original_pedal_and_note_lifecycle():
    notes = [
        make_note(1, 52, 0.0, 0.5, hand="left"),
        make_note(2, 55, 0.5, 0.5, hand="right"),
    ]

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

    assert {e.pitch for e in press_events} == {52, 55}
    assert {e.pitch for e in release_events} == {52, 55}
    assert len(press_events) == 2
    assert len(release_events) == 2
