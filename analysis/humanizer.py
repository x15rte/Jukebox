"""Humanization: timing variance, articulation, chord roll, drift correction, tempo rubato, and hand assignment."""

import random
from collections.abc import Mapping
from typing import Any, Dict, List, Set

import numpy as np

from models import Note, MusicalSection
from core import get_time_groups

_DRIFT_NOISE_SIGMA = 0.004
_DRIFT_SHARED_FACTOR = 0.3


class Humanizer:
    """Applies timing variance, articulation, chord roll, drift correction, and tempo rubato per section pace."""

    def __init__(self, config: Mapping[str, Any]):
        self.config = config
        self.left_hand_drift = 0.0
        self.right_hand_drift = 0.0
        self._shared_drift_offsets: Dict[float, float] = {}

    def prepare_shared_offsets(self, all_notes: List[Note]) -> None:
        """Precompute one timing offset per combined time group for shared drift (both hands). Call before apply_to_hand."""
        self._shared_drift_offsets = {}
        if not (
            self.config.get("vary_timing")
            and self.config.get("enable_drift_correction")
        ):
            return
        time_groups = get_time_groups(all_notes)
        sigma = self.config.get("timing_variance", 0.01)
        for group in time_groups:
            offset = random.gauss(0, sigma)  # nosec B311: non-crypto randomness for musical timing only
            offset = max(-3 * sigma, min(3 * sigma, offset))
            t_key = round(group[0].start_time, 2)
            self._shared_drift_offsets[t_key] = offset

    def apply_to_hand(self, notes: List[Note], hand: str, resync_points: Set[float]):
        """Apply timing/articulation/roll per group; resync_points are times where both hands hit together (decay drift)."""
        if not any(
            [
                self.config.get("vary_timing"),
                self.config.get("vary_articulation"),
                self.config.get("enable_drift_correction"),
                self.config.get("enable_chord_roll"),
            ]
        ):
            return

        time_groups = get_time_groups(notes)
        for group in time_groups:
            t_key = round(group[0].start_time, 2)
            is_resync_point = t_key in resync_points

            if self.config.get("enable_drift_correction") and is_resync_point:
                decay = self.config.get("drift_decay_factor", 1.0)
                if hand == "left":
                    self.left_hand_drift *= decay
                else:
                    self.right_hand_drift *= decay

            group_timing_offset = 0.0
            if self.config.get("vary_timing"):
                sigma = self.config.get("timing_variance", 0.01)
                group_timing_offset = random.gauss(0, sigma)  # nosec B311: non-crypto randomness for musical timing variance only
                group_timing_offset = max(
                    -3 * sigma, min(3 * sigma, group_timing_offset)
                )

            group_articulation = self.config.get("articulation", 1.0)
            if self.config.get("vary_articulation"):
                group_articulation -= random.random() * 0.1  # nosec B311: non-crypto randomness for musical articulation only

            if self.config.get("enable_chord_roll") and len(group) > 1:
                group.sort(key=lambda n: n.pitch)
                for i, note in enumerate(group):
                    note.start_time += i * 0.006

            for note in group:
                current_drift = (
                    self.left_hand_drift if hand == "left" else self.right_hand_drift
                )
                note.start_time += group_timing_offset
                if self.config.get("enable_drift_correction"):
                    note.start_time += current_drift

                note.duration *= group_articulation
                if note.duration < 0.03:
                    note.duration = 0.03

            if self.config.get("enable_drift_correction"):
                shared = self._shared_drift_offsets.get(t_key, 0.0) * self.config.get(
                    "drift_shared_factor", _DRIFT_SHARED_FACTOR
                )
                sigma = self.config.get("drift_noise_sigma", _DRIFT_NOISE_SIGMA)
                drift_noise = random.gauss(0, sigma)  # nosec B311: non-crypto randomness for musical drift only
                max_dev = 3 * sigma
                drift_noise = max(-max_dev, min(max_dev, drift_noise))
                if hand == "left":
                    self.left_hand_drift += shared + drift_noise
                else:
                    self.right_hand_drift += shared + drift_noise

    def apply_tempo_rubato(self, all_notes: List[Note], sections: List[MusicalSection]):
        """Shift note times within each section by a sine curve; intensity scales by section pace (fast/slow)."""
        if not self.config.get("enable_tempo_sway"):
            return
        base_intensity = self.config.get("tempo_sway_intensity", 0.0)
        invert_sway = self.config.get("invert_tempo_sway", False)
        note_map = {note.id: note for note in all_notes}
        for section in sections:
            pace_multiplier = 1.0
            if section.pace_label == "fast":
                pace_multiplier = 1.5 if invert_sway else 0.25
            elif section.pace_label == "slow":
                pace_multiplier = 0.25 if invert_sway else 1.5
            section_duration = section.end_time - section.start_time
            if section_duration < 1.0:
                continue
            intensity = base_intensity * pace_multiplier
            for note in section.notes:
                if note.id in note_map:
                    rel_pos = (note.start_time - section.start_time) / section_duration
                    time_shift = np.sin(rel_pos * np.pi) * intensity
                    note_map[note.id].start_time -= time_shift


class FingeringEngine:
    """Assigns left/right hand by pitch; chords use average pitch. Split at MIDI 60 (middle C)."""

    def assign_hands(self, notes: List[Note]):
        time_groups = get_time_groups(notes)
        for group in time_groups:
            if len(group) == 1:
                self._assign_single_note(group[0])
            else:
                self._assign_chord(group)

    def _assign_single_note(self, note: Note):
        if note.hand != "unknown":
            return
        note.hand = "left" if note.pitch < 60 else "right"  # 60 = middle C

    def _assign_chord(self, chord_notes: List[Note]):
        unassigned = [n for n in chord_notes if n.hand == "unknown"]
        if not unassigned:
            return
        avg_pitch = sum(n.pitch for n in unassigned) / len(unassigned)
        hand = "left" if avg_pitch < 60 else "right"  # 60 = middle C
        for n in unassigned:
            n.hand = hand
