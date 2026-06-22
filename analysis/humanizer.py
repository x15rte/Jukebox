"""Humanization: timing variance, articulation, chord roll, drift correction, tempo rubato, and hand assignment."""

import random
from random import Random

_original_gauss = random.gauss
_original_random = random.random
from collections import defaultdict
from collections.abc import Mapping
from typing import Any, Dict, List, Set

import numpy as np

from models import Note, MusicalSection
from core import get_time_groups

_DRIFT_NOISE_SIGMA = 0.004
_DRIFT_SHARED_FACTOR = 0.3
MAX_DRIFT = 0.5

class Humanizer:
    """Applies timing variance, articulation, chord roll, drift correction, and tempo rubato per section pace."""

    def __init__(self, config: Mapping[str, Any]):
        self.config = config
        self.left_hand_drift = 0.0
        self.right_hand_drift = 0.0
        self._rng = Random(42)  # nosec: fixed seed for reproducibility, not security
        self._shared_drift_offsets: Dict[float, float] = {}
    def _gauss(self, mu: float, sigma: float) -> float:
        # Respect global monkeypatches (used by existing tests)
        if random.gauss is not _original_gauss:
            return random.gauss(mu, sigma)
        return self._rng.gauss(mu, sigma)

    def _rand(self) -> float:
        if random.random is not _original_random:
            return random.random()  # nosec: not used for security
        return self._rng.random()
    def prepare_shared_offsets(self, all_notes: List[Note]) -> None:
        """Precompute one timing offset per combined time group for shared drift (both hands). Call before apply_to_hand."""
        self._shared_drift_offsets = {}
        if not self.config.get("enable_drift_correction"):
            return
        time_groups = get_time_groups(all_notes)
        sigma = self.config.get("drift_shared_sigma", 0.004)
        for group in time_groups:
            offset = self._gauss(0, sigma)  # nosec B311: non-crypto randomness for musical timing only
            offset = max(-3 * sigma, min(3 * sigma, offset))
            t_key = round(group[0].start_time, 3)
            self._shared_drift_offsets[t_key] = offset

    def apply_to_hand(self, notes: List[Note], hand: str, resync_points: Set[float]):
        """Apply timing/articulation/roll per group; resync_points are times where both hands hit together (decay drift)."""
        if hand not in ('left', 'right'):
            raise ValueError(f"Invalid hand '{hand}': expected 'left' or 'right'")

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
            t_key = round(group[0].start_time, 3)
            is_resync_point = any(abs(t_key - rp) <= 0.001 for rp in resync_points)

            if self.config.get("enable_drift_correction") and is_resync_point:
                decay = self.config.get("drift_decay_factor", 0.999)
                if hand == "left":
                    self.left_hand_drift *= decay
                else:
                    self.right_hand_drift *= decay

            group_timing_offset = 0.0
            if self.config.get("vary_timing"):
                sigma = self.config.get("timing_variance", 0.01)
                group_timing_offset = self._gauss(0, sigma)  # nosec B311: non-crypto randomness for musical timing variance only
                group_timing_offset = max(
                    -3 * sigma, min(3 * sigma, group_timing_offset)
                )

            group_articulation = self.config.get("articulation", 1.0)
            if self.config.get("vary_articulation"):
                group_articulation -= self._rand() * 0.1  # nosec B311
                group_articulation = max(0.1, group_articulation)
            # Drift correction: compute shared+noise but defer drift update until after for-note
            drift_shared = 0.0
            drift_noise = 0.0
            if self.config.get("enable_drift_correction"):
                shared_key = min(self._shared_drift_offsets.keys(),
                                 key=lambda k: abs(k - t_key),
                                 default=None)
                if shared_key is not None and abs(shared_key - t_key) <= 0.015:
                    drift_shared = self._shared_drift_offsets.get(shared_key, 0.0) * self.config.get(
                        "drift_shared_factor", _DRIFT_SHARED_FACTOR
                    )
                sigma = self.config.get("drift_noise_sigma", _DRIFT_NOISE_SIGMA)
                drift_noise = self._gauss(0, sigma)  # nosec B311: non-crypto randomness for musical drift only
                max_dev = 3 * sigma
                drift_noise = max(-max_dev, min(max_dev, drift_noise))

            for note in group:
                current_drift = (
                    self.left_hand_drift if hand == "left" else self.right_hand_drift
                )
                note.start_time += group_timing_offset
                if self.config.get("enable_drift_correction"):
                    note.start_time += current_drift
                note.start_time = max(0.0, note.start_time)

                original_duration = note.duration
                note.duration *= group_articulation
                if note.duration < 0.03:
                    # Preserve proportion: floor at 10% of original, minimum 0.01s
                    proportion_floor = max(0.01, original_duration * 0.1)
                    note.duration = max(note.duration, proportion_floor)

            # Chord roll applies AFTER timing offsets, on clamped times
            if self.config.get("enable_chord_roll") and len(group) > 1:
                group.sort(key=lambda n: n.pitch)
                for i, note in enumerate(group):
                    note.start_time += i * 0.006

            # Drift update happens after notes are adjusted (so for-note loop uses pre-update drift)
            if self.config.get("enable_drift_correction"):
                if hand == "left":
                    self.left_hand_drift += drift_shared + drift_noise
                    self.left_hand_drift = max(-MAX_DRIFT, min(MAX_DRIFT, self.left_hand_drift))
                else:
                    self.right_hand_drift += drift_shared + drift_noise
                    self.right_hand_drift = max(-MAX_DRIFT, min(MAX_DRIFT, self.right_hand_drift))

    def apply_tempo_rubato(self, all_notes: List[Note], sections: List[MusicalSection]):
        """Shift note times within each section by a sine curve; intensity scales by section pace (fast/slow)."""
        if not self.config.get("enable_tempo_sway"):
            return
        base_intensity = self.config.get("tempo_sway_intensity", 0.0)
        invert_sway = self.config.get("invert_tempo_sway", False)
        note_map: Dict[int, List[Note]] = defaultdict(list)
        for note in all_notes:
            note_map[note.id].append(note)
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
                for target in note_map.get(note.id, []):
                    rel_pos = (note.start_time - section.start_time) / section_duration
                    time_shift = np.sin(rel_pos * 2 * np.pi) * intensity
                    # Don't shift a note before time 0
                    max_shift = target.start_time
                    time_shift = max(-max_shift, min(time_shift, max_shift))
                    target.start_time -= time_shift
            section.notes.sort(key=lambda n: n.start_time)


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
        hand = "left" if avg_pitch < 60 else "right"
        for n in unassigned:
            n.hand = hand
