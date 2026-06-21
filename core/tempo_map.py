"""Tempo/beat mapping and time grouping helpers."""

import bisect
import math
from typing import List, Tuple

import mido

from models import Note


def get_time_groups(notes: List[Note], threshold: float = 0.015) -> List[List[Note]]:
    """Group notes whose start times are within *threshold* seconds of each other."""
    if not notes:
        return []
    notes = sorted(notes, key=lambda n: n.start_time)
    groups: List[List[Note]] = []
    current = [notes[0]]
    for i in range(1, len(notes)):
        if notes[i].start_time - current[-1].start_time <= threshold:
            current.append(notes[i])
        else:
            groups.append(current)
            current = [notes[i]]
    groups.append(current)
    return groups


class TempoMap:
    """Bidirectional mapping between wall-clock seconds and musical beats.

    *tempo_events*: ``[(time_sec, tempo_microseconds), ...]``
    *time_signatures*: ``[(time_sec, numerator, denominator), ...]``
    """

    def __init__(
        self,
        tempo_events: List[Tuple[float, int]],
        time_signatures: List[Tuple[float, int, int]],
        tempo_scale: float = 1.0,
    ):
        if tempo_scale <= 0 or math.isnan(tempo_scale) or math.isinf(tempo_scale):
            raise ValueError(f"tempo_scale must be positive and finite, got {tempo_scale}")
        self.events = sorted(tempo_events, key=lambda x: x[0])
        self.time_signatures = sorted(time_signatures, key=lambda x: x[0])
        self.tempo_scale = tempo_scale
        self.time_signatures = [(t / self.tempo_scale, n, d) for t, n, d in self.time_signatures]
        self._segments: List[Tuple[float, float, int]] = []
        self._build_segments()
        self._start_times = [s[0] for s in self._segments]
        self._beat_starts = [s[1] for s in self._segments]
        self.has_explicit_time_signatures = len(self.time_signatures) > 0 and not (
            len(self.time_signatures) == 1
            and abs(self.time_signatures[0][0]) < 1e-9
            and self.time_signatures[0][1] == 4
            and self.time_signatures[0][2] == 4
        )

    def _build_segments(self):
        beat = 0.0
        last_t = 0.0
        tempo = 500_000
        if not self.events or self.events[0][0] > 0:
            self._segments.append((0.0, 0.0, tempo))
        for t, raw_tempo in self.events:
            t_scaled = t / self.tempo_scale
            new_tempo = max(1, raw_tempo)
            spb = tempo / 1_000_000.0
            beat += (t_scaled - last_t) / spb
            self._segments.append((t_scaled, beat, new_tempo))
            last_t = t_scaled
            tempo = new_tempo

    def time_to_beat(self, t: float) -> float:
        idx = bisect.bisect_right(self._start_times, t) - 1
        if idx < 0:
            return 0.0
        st, sb, tempo = self._segments[idx]
        return sb + (t - st) / (tempo / 1_000_000.0)

    def beat_to_time(self, b: float) -> float:
        idx = bisect.bisect_right(self._beat_starts, b) - 1
        if idx < 0:
            return 0.0
        st, sb, tempo = self._segments[idx]
        return st + (b - sb) * (tempo / 1_000_000.0)

    def get_tempo_at(self, time: float) -> int:
        idx = bisect.bisect_right(self._start_times, time) - 1
        if idx < 0:
            return 500_000
        return self._segments[idx][2]

    def get_measure_boundaries(
        self, total_duration: float
    ) -> List[Tuple[float, float]]:
        ts_list = self.time_signatures if self.time_signatures else [(0.0, 4, 4)]
        # If the first time signature starts after time 0, prepend a default 4/4
        if ts_list and ts_list[0][0] > 1e-9:
            ts_list = [(0.0, 4, 4)] + ts_list
        total_beats = self.time_to_beat(total_duration)
        measures: List[Tuple[float, float]] = []
        beat = 0.0
        ts_idx = 0
        while beat < total_beats:
            t = self.beat_to_time(beat)
            while ts_idx + 1 < len(ts_list) and t >= ts_list[ts_idx + 1][0] - 1e-9:
                ts_idx += 1
            active = ts_list[ts_idx]
            if active[2] <= 0:
                break
            measure_beats = active[1] * (4.0 / active[2])
            if measure_beats <= 0:
                break
            end_beat = beat + measure_beats
            measures.append((t, self.beat_to_time(end_beat)))
            beat = end_beat
        return measures


class GlobalTickMap:
    """Converts absolute MIDI ticks to wall-clock seconds using tempo changes."""
    def get_entries(self) -> List[Tuple[int, float, int]]:
        """Return list of (tick, time_sec, tempo_us) entries."""
        return list(self._entries)

    def __init__(self, midi_file: mido.MidiFile):
        self.ticks_per_beat = midi_file.ticks_per_beat or 480
        self._entries: List[Tuple[int, float, int]] = []
        self.time_signatures: List[Tuple[float, int, int]] = []
        self._build(midi_file)

    def _build(self, midi_file: mido.MidiFile):
        merged = mido.merge_tracks(midi_file.tracks)
        t = 0.0
        tick = 0
        tempo = 500_000
        self._entries.append((0, 0.0, tempo))
        acc = 0
        for msg in merged:
            acc += msg.time
            dt = mido.tick2second(acc - tick, self.ticks_per_beat, tempo)
            t += dt
            tick = acc
            if msg.type == "set_tempo":
                tempo = max(1, min(msg.tempo, 10_000_000))
                self._entries.append((tick, t, tempo))
            elif msg.type == "time_signature":
                self.time_signatures.append((t, msg.numerator, msg.denominator))

    def tick_to_time(self, target_tick: int) -> float:
        target_tick = max(0, target_tick)
        last_tick, last_time, tempo = self._entries[0]
        for e_tick, e_time, e_tempo in self._entries:
            if target_tick >= e_tick:
                last_tick, last_time, tempo = e_tick, e_time, e_tempo
            else:
                break
        return last_time + mido.tick2second(
            target_tick - last_tick, self.ticks_per_beat, tempo
        )
