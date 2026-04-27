from typing import Any, cast

from core.midi_parser import MidiParser
from core.tempo_map import TempoMap
from models import MidiTrack
from playback.playback_service import PlaybackService
from tests.helpers.builders import make_note
from tests.helpers.midi_fixtures import midi_fixture_path

PlaybackService = cast(Any, PlaybackService)


def test_prepare_playback_uses_preparsed_when_tempo_matches(monkeypatch):
    notes = [make_note(1, 60, 0.0, 0.5, hand="unknown")]
    tr = MidiTrack(0, "T", 0, False, notes, [(0.1, 127)])

    class DummyTempo:
        pass

    dummy_map = DummyTempo()

    called = {"parse": 0}

    def fake_parse(*args, **kwargs):
        called["parse"] += 1
        return [tr], dummy_map

    monkeypatch.setattr("playback.playback_service.MidiParser.parse_structure", fake_parse)
    monkeypatch.setattr("playback.playback_service.EventCompiler.compile", lambda n, s, c: [])
    monkeypatch.setattr("playback.playback_service.SectionAnalyzer.analyze", lambda self: [])

    result = PlaybackService.prepare_playback(
        "x.mid",
        [(tr, "Left Hand")],
        {"tempo": 100, "simulate_hands": False},
        preparsed=cast(tuple[list[MidiTrack], TempoMap], ([tr], dummy_map)),
        preparsed_tempo_scale=1.0,
    )

    final_notes, _, _, total_dur, tempo_map = result
    assert called["parse"] == 0
    assert len(final_notes) == 1
    assert final_notes[0].hand == "left"
    assert total_dur > 0
    assert tempo_map is dummy_map


def test_prepare_playback_reparses_when_tempo_changes(monkeypatch):
    notes = [make_note(1, 62, 0.0, 0.4, hand="unknown")]
    tr = MidiTrack(1, "T2", 0, False, notes, [])

    called = {"parse": 0}

    def fake_parse(*args, **kwargs):
        called["parse"] += 1
        return [tr], object()

    monkeypatch.setattr("playback.playback_service.MidiParser.parse_structure", fake_parse)
    monkeypatch.setattr("playback.playback_service.EventCompiler.compile", lambda n, s, c: [])
    monkeypatch.setattr("playback.playback_service.SectionAnalyzer.analyze", lambda self: [])

    PlaybackService.prepare_playback(
        "x.mid",
        [(tr, "Auto-Detect")],
        {"tempo": 120, "simulate_hands": False},
        preparsed=cast(tuple[list[MidiTrack], TempoMap], ([tr], object())),
        preparsed_tempo_scale=1.0,
    )
    assert called["parse"] == 1


def test_prepare_playback_defaults_unknown_hands_by_pitch(monkeypatch):
    low = make_note(1, 50, 0.0, 0.2, hand="unknown")
    high = make_note(2, 70, 0.1, 0.2, hand="unknown")
    tr = MidiTrack(2, "T3", 0, False, [high, low], [])

    monkeypatch.setattr("playback.playback_service.MidiParser.parse_structure", lambda *_a, **_k: ([tr], object()))
    monkeypatch.setattr("playback.playback_service.EventCompiler.compile", lambda n, s, c: [])
    monkeypatch.setattr("playback.playback_service.SectionAnalyzer.analyze", lambda self: [])

    final_notes, _sections, _events, _dur, _tempo = PlaybackService.prepare_playback(
        "x.mid",
        [(tr, "Auto-Detect")],
        {"tempo": 100, "simulate_hands": False},
    )

    assert [n.hand for n in final_notes] == ["left", "right"]


def test_prepare_playback_simulate_hands_uses_engine(monkeypatch):
    note = make_note(1, 61, 0.0, 0.2, hand="unknown")
    tr = MidiTrack(3, "T4", 0, False, [note], [])

    class Engine:
        called = False

        def assign_hands(self, notes):
            Engine.called = True
            notes[0].hand = "left"

    monkeypatch.setattr("playback.playback_service.MidiParser.parse_structure", lambda *_a, **_k: ([tr], object()))
    monkeypatch.setattr("playback.playback_service.FingeringEngine", Engine)
    monkeypatch.setattr("playback.playback_service.EventCompiler.compile", lambda n, s, c: [])
    monkeypatch.setattr("playback.playback_service.SectionAnalyzer.analyze", lambda self: [])

    final_notes, _sections, _events, _dur, _tempo = PlaybackService.prepare_playback(
        "x.mid",
        [(tr, "Auto-Detect")],
        {"tempo": 100, "simulate_hands": True},
    )

    assert Engine.called is True
    assert final_notes[0].hand == "left"


def test_prepare_playback_includes_raw_pedal_events_in_config(monkeypatch):
    note = make_note(1, 64, 0.0, 0.3, hand="unknown")
    t1 = MidiTrack(4, "A", 0, False, [note], [(2.0, 0), (0.5, 127)])
    t2 = MidiTrack(5, "B", 0, False, [note], [(1.0, 127)])

    seen = {}

    def fake_compile(_n, _s, cfg):
        seen["pedals"] = cfg.get("raw_pedal_events")
        return []

    monkeypatch.setattr("playback.playback_service.MidiParser.parse_structure", lambda *_a, **_k: ([t1, t2], object()))
    monkeypatch.setattr("playback.playback_service.EventCompiler.compile", fake_compile)
    monkeypatch.setattr("playback.playback_service.SectionAnalyzer.analyze", lambda self: [])

    PlaybackService.prepare_playback(
        "x.mid",
        [(t1, "Auto-Detect"), (t2, "Auto-Detect")],
        {"tempo": 100, "simulate_hands": False},
    )

    assert seen["pedals"] == [(0.5, 127), (1.0, 127), (2.0, 0)]


def test_prepare_playback_right_hand_role_assignment(monkeypatch):
    note = make_note(1, 55, 0.0, 0.2, hand="unknown")
    tr = MidiTrack(6, "R", 0, False, [note], [])

    monkeypatch.setattr("playback.playback_service.MidiParser.parse_structure", lambda *_a, **_k: ([tr], object()))
    monkeypatch.setattr("playback.playback_service.EventCompiler.compile", lambda n, s, c: [])
    monkeypatch.setattr("playback.playback_service.SectionAnalyzer.analyze", lambda self: [])

    final_notes, _sections, _events, _dur, _tempo = PlaybackService.prepare_playback(
        "x.mid",
        [(tr, "Right Hand")],
        {"tempo": 100, "simulate_hands": False},
    )

    assert len(final_notes) == 1
    assert final_notes[0].hand == "right"


def test_prepare_playback_real_fixture_remaps_original_pedal_with_humanizer(
    monkeypatch,
):
    midi_path = midi_fixture_path("basic_pedal.mid")
    parsed_tracks, _tempo_map = MidiParser.parse_structure(str(midi_path), tempo_scale=1.0)
    assert parsed_tracks
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *_a, **_k: 0.05)
    monkeypatch.setattr("analysis.humanizer.random.random", lambda: 1.0)

    final_notes, sections, events, total_dur, _ = PlaybackService.prepare_playback(
        str(midi_path),
        [(parsed_tracks[0], "Auto-Detect")],
        {
            "tempo": 100,
            "simulate_hands": False,
            "pedal_style": "original",
            "enable_vary_timing": True,
            "vary_timing": True,
            "timing_variance": 0.1,
            "countdown": False,
            "start_offset": 0.0,
        },
    )

    assert len(final_notes) == 1
    assert final_notes[0].pitch == 60
    assert final_notes[0].hand == "right"
    assert sections
    assert events
    assert total_dur > 0
    assert [event.time for event in events] == sorted(event.time for event in events)
    assert [(event.action, event.key_char, event.pitch, event.time) for event in events] == [
        ("pedal", "down", None, 0.05),
        ("press", "", 60, 0.05),
        ("pedal", "up", None, 0.55),
        ("release", "", 60, 0.55),
    ]
