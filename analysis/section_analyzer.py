"""Musical section analysis: segmentation by measures or silence, articulation/pace classification."""

import math
from typing import List, Optional, Set

from models import Note, MusicalSection
from core import TempoMap


class SectionAnalyzer:
    """Splits notes into sections by measures (if time sigs) or by grand pauses; classifies articulation and pace."""

    def __init__(self, notes: List[Note], tempo_map: TempoMap):
        self.notes = sorted(notes, key=lambda n: n.start_time)
        self.tempo_map = tempo_map

    def analyze(self) -> List[MusicalSection]:
        """Use measure boundaries if time signatures exist, else segment by silence (>2 beats gap)."""
        if not self.notes:
            return []
        if self.tempo_map.has_explicit_time_signatures:
            return self._analyze_by_measures()
        else:
            return self._analyze_by_silence()

    def _analyze_by_silence(self) -> List[MusicalSection]:
        """Segment at gaps > 2 beats; classify articulation (left-hand overlap ratio) and pace per section."""
        boundaries = self._detect_grand_pauses()
        sections = []
        for i in range(len(boundaries) - 1):
            start_idx = boundaries[i]
            end_idx = boundaries[i + 1] - 1
            if start_idx > end_idx:
                continue
            sec_notes = self.notes[start_idx : end_idx + 1]
            if not sec_notes:
                continue
            start_time = sec_notes[0].start_time
            end_time = max(n.end_time for n in sec_notes)
            start_beat = self.tempo_map.time_to_beat(start_time)
            end_beat = self.tempo_map.time_to_beat(end_time)
            articulation = self._classify_bass_articulation(sec_notes)
            pace = self._classify_pace_beats(sec_notes, start_beat, end_beat)
            sections.append(
                MusicalSection(
                    start_time,
                    end_time,
                    sec_notes,
                    articulation,
                    pace,
                    start_beat,
                    end_beat,
                )
            )
        return sections

    def _analyze_by_measures(self) -> List[MusicalSection]:
        """Merge consecutive measures with same articulation/pace into sections."""
        total_dur = max(n.end_time for n in self.notes)
        measures = self.tempo_map.get_measure_boundaries(total_dur)
        if not measures:
            return self._analyze_by_silence()
        sections = []
        current_section_start: Optional[float] = None
        current_notes_in_section = []
        seen_ids: Set[int] = set()  # Accumulates across all sections — prevents long notes spanning multiple measures from appearing in multiple sections.
        prev_style = None
        prev_pace = None

        def classify_chunk(chunk_notes, s_time, e_time):
            s_beat = self.tempo_map.time_to_beat(s_time)
            e_beat = self.tempo_map.time_to_beat(e_time)
            art = self._classify_bass_articulation(chunk_notes)
            pace = self._classify_pace_beats(chunk_notes, s_beat, e_beat)
            return art, pace

        for m_start, m_end in measures:
            notes_in_measure = [
                n
                for n in self.notes
                if n.start_time < m_end and n.end_time > m_start
            ]
            if not notes_in_measure:
                style, pace = (prev_style or "legato"), (prev_pace or "normal")
            else:
                style, pace = classify_chunk(notes_in_measure, m_start, m_end)
            if prev_style is None:
                prev_style = style
                prev_pace = pace
                new_notes = [n for n in notes_in_measure if n.id not in seen_ids]
                seen_ids.update(n.id for n in new_notes)
                if new_notes:
                    if current_section_start is None:
                        current_section_start = m_start
                current_notes_in_section.extend(new_notes)
                continue
            if style != prev_style or pace != prev_pace:
                if current_notes_in_section:
                    section_start = current_section_start if current_section_start is not None else current_notes_in_section[0].start_time
                    sec_end = max(n.end_time for n in current_notes_in_section)
                    s_beat = self.tempo_map.time_to_beat(section_start)
                    e_beat = self.tempo_map.time_to_beat(sec_end)
                    sections.append(
                        MusicalSection(
                            section_start,
                            sec_end,
                            list(current_notes_in_section),
                            prev_style or "legato",
                            prev_pace or "normal",
                            s_beat,
                            e_beat,
                        )
                    )
                current_section_start = m_start
                current_notes_in_section = []
                seen_ids = set()
                prev_style = style
                prev_pace = pace
            new_notes = [n for n in notes_in_measure if n.id not in seen_ids]
            seen_ids.update(n.id for n in new_notes)
            current_notes_in_section.extend(new_notes)

        if current_notes_in_section:
            section_start = current_section_start if current_section_start is not None else current_notes_in_section[0].start_time
            sec_end = max(n.end_time for n in current_notes_in_section)
            s_beat = self.tempo_map.time_to_beat(section_start)
            e_beat = self.tempo_map.time_to_beat(sec_end)
            sections.append(
                MusicalSection(
                    section_start,
                    sec_end,
                    list(current_notes_in_section),
                    prev_style or "legato",
                    prev_pace or "normal",
                    s_beat,
                    e_beat,
                )
            )
        return sections

    def _detect_grand_pauses(self) -> List[int]:
        """Return note indices that start a new segment after a gap > 2 beats."""
        indices = [0]
        if not self.notes:
            return indices
        last_end_time = self.notes[0].end_time
        for i in range(1, len(self.notes)):
            current_start = self.notes[i].start_time
            gap_beats = self.tempo_map.time_to_beat(current_start) - self.tempo_map.time_to_beat(last_end_time)
            if gap_beats > 2.0:
                indices.append(i)
            last_end_time = max(last_end_time, self.notes[i].end_time)
        indices.append(len(self.notes))
        return indices

    def _classify_bass_articulation(self, notes: List[Note]) -> str:
        """Legato / staccato / hybrid from left-hand note duration vs inter-onset ratio."""
        lh_notes = [n for n in notes if n.hand == "left"]
        if len(lh_notes) < 2:
            return "legato"
        total_overlap = 0.0
        total_possible = 0.0
        lh_notes.sort(key=lambda n: n.start_time)
        for i in range(len(lh_notes) - 1):
            curr = lh_notes[i]
            next_n = lh_notes[i + 1]
            curr_beat = self.tempo_map.time_to_beat(curr.start_time)
            next_beat = self.tempo_map.time_to_beat(next_n.start_time)
            ioi_beats = next_beat - curr_beat
            if math.isnan(ioi_beats):
                continue
            if ioi_beats <= 0:
                continue
            dur_beats = self.tempo_map.time_to_beat(curr.end_time) - curr_beat
            if math.isnan(dur_beats):
                continue
            if dur_beats < 0:
                continue
            ratio = dur_beats / ioi_beats
            total_overlap += min(ratio, 1.2)
            total_possible += 1.0
        if total_possible == 0:
            return "legato"
        avg_ratio = total_overlap / total_possible
        if avg_ratio >= 0.95:
            return "legato"
        if avg_ratio <= 0.60:
            return "staccato"
        return "hybrid"

    def _classify_pace_beats(
        self, notes: List[Note], start_beat: float, end_beat: float
    ) -> str:
        duration_beats = end_beat - start_beat
        if duration_beats <= 0 or math.isnan(duration_beats):
            return "normal"
        npb = len(notes) / duration_beats
        if npb > 3.5:
            return "fast"
        if npb < 1.0:
            return "slow"
        return "normal"
