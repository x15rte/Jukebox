from pathlib import Path
from typing import Any, cast

import mido

from core.midi_parser import MidiParser
from core.tempo_map import TempoMap
from models import MidiTrack
from playback.playback_service import PlaybackService
from tests.helpers.builders import make_note

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


def test_prepare_playback_black_box_real_parse_and_compile(tmp_path: Path):
    midi_path = tmp_path / "single_note.mid"

    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    track.append(mido.MetaMessage("track_name", name="Piano", time=0))
    track.append(mido.Message("program_change", program=0, channel=0, time=0))
    track.append(mido.Message("note_on", note=64, velocity=90, channel=0, time=0))
    track.append(mido.Message("note_off", note=64, velocity=0, channel=0, time=480))
    track.append(mido.Message("control_change", control=64, value=127, channel=0, time=0))
    track.append(mido.Message("control_change", control=64, value=0, channel=0, time=240))

    mid.save(str(midi_path))

    parsed_tracks, _tempo_map = MidiParser.parse_structure(str(midi_path), tempo_scale=1.0)
    assert parsed_tracks

    final_notes, sections, events, total_dur, _ = PlaybackService.prepare_playback(
        str(midi_path),
        [(parsed_tracks[0], "Auto-Detect")],
        {
            "tempo": 100,
            "simulate_hands": False,
            "pedal_style": "original",
            "countdown": False,
            "start_offset": 0.0,
        },
    )

    assert len(final_notes) == 1
    assert final_notes[0].pitch == 64
    assert final_notes[0].hand == "right"
    assert sections
    assert total_dur > 0

    actions = [e.action for e in events]
    assert "press" in actions
    assert "release" in actions
    pedal_events = [e for e in events if e.action == "pedal"]
    assert pedal_events
    assert any(e.key_char == "down" for e in pedal_events)
    assert any(e.key_char == "up" for e in pedal_events)
