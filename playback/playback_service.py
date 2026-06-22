"""Playback preparation service: MIDI parsing, track selection, humanization, event compilation.

Decouples orchestration logic from the GUI so it can be tested and reused (e.g. future CLI).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from logger_core import jukebox_logger
from typing import Any, List, Tuple, Optional

from models import Note, KeyEvent, MusicalSection
from core import MidiParser, TempoMap
from analysis import SectionAnalyzer, FingeringEngine
from .player import EventCompiler
from models import MidiTrack


class PlaybackService:
    """Prepares a playback run: parse MIDI, apply hand assignment and sections, compile key events."""

    @staticmethod
    def prepare_playback(
        midi_file: str,
        selected_tracks_info: List[Tuple[MidiTrack, str]],
        config: Mapping[str, Any],
        preparsed: Optional[Tuple[List[MidiTrack], TempoMap]] = None,
        preparsed_tempo_scale: float = 1.0,
    ) -> Tuple[List[Note], List[MusicalSection], List[KeyEvent], float, TempoMap]:
        """Build final notes, sections, compiled events, total duration, and tempo map.

        :param midi_file: Path to the MIDI file.
        :param selected_tracks_info: List of (MidiTrack, role_str) for selected tracks; role_str is "Left Hand", "Right Hand", or "Auto-Detect".
        :param config: Playback config dict (tempo, pedal_style, humanization flags, etc.).
        :return: (final_notes, sections, compiled_events, total_duration_sec, tempo_map).
        :raises: Exception on parse or compile errors (caller should log with exc_info and show dialog).
        """
        tempo_scale = config.get("tempo", 100) / 100.0
        if preparsed is not None and abs(tempo_scale - preparsed_tempo_scale) < 1e-9:
            tracks, tempo_map = preparsed
        else:
            tracks, tempo_map = MidiParser.parse_structure(midi_file, tempo_scale)

        selected_indices = [t.index for t, _ in selected_tracks_info]
        role_map = {t.index: r for t, r in selected_tracks_info}

        final_notes: List[Note] = []
        raw_pedal_events = []
        for track in tracks:
            if track.index in selected_indices:
                raw_pedal_events.extend(track.pedal_events)
                role = role_map[track.index]
                for note in track.notes:
                    new_note = copy.deepcopy(note)
                    if role == "Left Hand":
                        new_note.hand = "left"
                    elif role == "Right Hand":
                        new_note.hand = "right"
                    final_notes.append(new_note)
                if track.pedal_events:
                    jukebox_logger.debug(
                        f"Track {track.index} ('{track.name}'): {len(track.pedal_events)} sustain pedal events"
                    )
        # Deduplicate consecutive same-value pedal events at the same timestamp
        raw_pedal_events.sort(key=lambda pe: pe[0])
        deduped = []
        for t, val in raw_pedal_events:
            if deduped and deduped[-1][0] == t and deduped[-1][1] == val:
                continue
            deduped.append((t, val))
        raw_pedal_events = deduped
        config = dict(config)
        config["raw_pedal_events"] = raw_pedal_events

        final_notes.sort(key=lambda n: n.start_time)

        if config.get("simulate_hands", False):
            engine = FingeringEngine()
            engine.assign_hands(final_notes)
        else:
            for note in final_notes:
                if note.hand == "unknown":
                    note.hand = "left" if note.pitch < 60 else "right"

        analyzer = SectionAnalyzer(final_notes, tempo_map)
        sections = analyzer.analyze()

        total_dur = max(n.end_time for n in final_notes) if final_notes else 0.0
        if total_dur == 0.0 and raw_pedal_events:
            last_time = max(pe[0] for pe in raw_pedal_events)
            # If last pedal event is a press without matching release, extend duration
            last_val = raw_pedal_events[-1][1]
            if last_val >= 64:
                last_time += 2.0
            total_dur = last_time
        if total_dur <= 0.0:
            total_dur = 1.0

        compiled_events = EventCompiler.compile(final_notes, sections, config)
        if compiled_events:
            total_dur = max(e.time for e in compiled_events)
            if total_dur < 0.1:
                total_dur = 0.1
        return final_notes, sections, compiled_events, total_dur, tempo_map
