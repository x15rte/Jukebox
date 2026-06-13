"""Pedal event generation: original, hybrid (adaptive), legato (harmonic), rhythmic, none."""

from collections.abc import Mapping
from typing import Any, List, Optional, Tuple

from models import Note, KeyEvent, MusicalSection
from core import get_time_groups


class PedalGenerator:
    """Produces pedal down/up KeyEvents. Styles: original (from MIDI), hybrid (adaptive), legato (harmonic), rhythmic (per chord), none."""

    @staticmethod
    def generate_events(
        config: Mapping[str, Any], final_notes: List[Note], sections: List[MusicalSection]
    ) -> List[KeyEvent]:
        style = config.get("pedal_style")
        if style == "none":
            return []

        if style == "original":
            raw = config.get("raw_pedal_events", [])
            if raw:
                return PedalGenerator._convert_raw_pedal(raw)
            style = "hybrid"

        if style == "hybrid":
            bass_notes = [n for n in final_notes if n.hand == "left"]
            bass_notes.sort(key=lambda n: n.start_time)
            if not bass_notes:
                treble_notes = [n for n in final_notes if n.hand == "right"]
                treble_notes.sort(key=lambda n: n.start_time)
                return PedalGenerator._generate_adaptive_pedal_driver(
                    treble_notes, final_notes
                )
            return PedalGenerator._generate_adaptive_pedal_driver(
                bass_notes, final_notes
            )

        if style not in {"legato", "rhythmic"}:
            return []

        intervals: List[Tuple[float, float]] = []

        for section in sections:
            section_intervals = PedalGenerator._build_section_intervals(style, section)
            if not section_intervals:
                continue
            PedalGenerator._merge_section_intervals(intervals, section_intervals)

        return PedalGenerator._intervals_to_events(intervals)

    @staticmethod
    def _build_section_intervals(
        style: str, section: MusicalSection
    ) -> List[Tuple[float, float]]:
        if not section.notes:
            return []

        lh_notes = [n for n in section.notes if n.hand == "left"]
        lh_notes.sort(key=lambda n: n.start_time)
        if not lh_notes:
            start = min(n.start_time for n in section.notes)
            end = max(n.end_time for n in section.notes)
            return [(start, end)]

        if style == "rhythmic":
            intervals: List[Tuple[float, float]] = []
            for group in get_time_groups(lh_notes):
                start = group[0].start_time
                end = max(n.end_time for n in group)
                intervals.append((start, end))
            return PedalGenerator._coalesce_overlapping_intervals(intervals)

        section_events: List[KeyEvent] = []
        PedalGenerator._generate_harmonic_pedal(section_events, lh_notes)
        return PedalGenerator._events_to_intervals(section_events)

    @staticmethod
    def _coalesce_overlapping_intervals(
        intervals: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        if not intervals:
            return []

        merged: List[Tuple[float, float]] = []
        for start, end in sorted(intervals):
            if not merged:
                merged.append((start, end))
                continue

            current_start, current_end = merged[-1]
            if start < current_end:
                merged[-1] = (current_start, max(current_end, end))
            else:
                merged.append((start, end))

        return merged

    @staticmethod
    def _merge_section_intervals(
        intervals: List[Tuple[float, float]],
        section_intervals: List[Tuple[float, float]],
    ) -> None:
        remaining = intervals

        for start_boundary, end_boundary in section_intervals:
            updated: List[Tuple[float, float]] = []
            for start, end in remaining:
                if end <= start_boundary or start >= end_boundary:
                    updated.append((start, end))
                elif start < start_boundary:
                    # Later sections take priority once overlap begins, but
                    # unrelated later spans from earlier sections stay intact.
                    updated.append((start, start_boundary))
                    if end > end_boundary:
                        updated.append((end_boundary, end))
                elif end > end_boundary:
                    updated.append((end_boundary, end))
            remaining = updated

        merged: List[Tuple[float, float]] = []
        existing_idx = 0
        section_idx = 0

        while existing_idx < len(remaining) and section_idx < len(section_intervals):
            if remaining[existing_idx][0] <= section_intervals[section_idx][0]:
                merged.append(remaining[existing_idx])
                existing_idx += 1
            else:
                merged.append(section_intervals[section_idx])
                section_idx += 1

        merged.extend(remaining[existing_idx:])
        merged.extend(section_intervals[section_idx:])
        intervals[:] = merged

    @staticmethod
    def _intervals_to_events(intervals: List[Tuple[float, float]]) -> List[KeyEvent]:
        events: List[KeyEvent] = []
        for start, end in intervals:
            if end <= start:
                continue
            events.append(KeyEvent(start, 1, "pedal", "down"))
            events.append(KeyEvent(end, 0, "pedal", "up"))
        return events

    @staticmethod
    def _events_to_intervals(events: List[KeyEvent]) -> List[Tuple[float, float]]:
        intervals: List[Tuple[float, float]] = []
        active_start: Optional[float] = None

        for event in events:
            if event.action != "pedal":
                continue
            if event.key_char == "down":
                active_start = event.time
            elif event.key_char == "up" and active_start is not None:
                intervals.append((active_start, max(active_start, event.time)))
                active_start = None

        return intervals

    @staticmethod
    def _generate_adaptive_pedal_driver(
        driver_notes: List[Note], all_notes: List[Note]
    ) -> List[KeyEvent]:
        events: List[KeyEvent] = []
        if not driver_notes:
            return events

        PEDAL_LAG = 0.05  # Seconds between pedal up and down when repedaling.
        UNSAFE_INTERVALS = {1, 6}  # m2, tritone; repedal to avoid clash.

        for i in range(len(driver_notes)):
            curr = driver_notes[i]
            next_n = driver_notes[i + 1] if i < len(driver_notes) - 1 else None

            if i == 0:
                events.append(KeyEvent(curr.start_time, 1, "pedal", "down"))

            gap = 0.0
            if next_n:
                gap = next_n.start_time - curr.end_time

            if gap > 0.35:
                events.append(KeyEvent(curr.end_time, 0, "pedal", "up"))
                if next_n:
                    events.append(KeyEvent(next_n.start_time, 1, "pedal", "down"))
            else:
                should_repedal = False

                if next_n:
                    linear_interval = abs(next_n.pitch - curr.pitch) % 12
                    if linear_interval in UNSAFE_INTERVALS:
                        should_repedal = True

                    if not should_repedal and all_notes:
                        window_notes = [
                            n
                            for n in all_notes
                            if abs(n.start_time - next_n.start_time) <= 0.05
                        ]
                        if window_notes:
                            lowest_pitch = min(n.pitch for n in window_notes)
                            for n in window_notes:
                                interval = abs(n.pitch - lowest_pitch) % 12
                                if interval in UNSAFE_INTERVALS:
                                    should_repedal = True
                                    break

                if should_repedal and next_n:
                    events.append(KeyEvent(next_n.start_time, 0, "pedal", "up"))
                    events.append(
                        KeyEvent(next_n.start_time + PEDAL_LAG, 1, "pedal", "down")
                    )

        final_end = max(n.end_time for n in driver_notes)
        events.append(KeyEvent(final_end, 0, "pedal", "up"))
        return events

    @staticmethod
    def _generate_harmonic_pedal(events: List[KeyEvent], bass_notes: List[Note]):
        """Pedal down at each bass note; up then down on harmony change or gap > 0.15s."""
        if not bass_notes:
            return
        current_bass_pitch = -1
        for i, note in enumerate(bass_notes):
            is_new_harmony = note.pitch != current_bass_pitch
            prev_end = bass_notes[i - 1].end_time if i > 0 else 0
            has_gap = (note.start_time - prev_end) > 0.15
            if i == 0:
                events.append(KeyEvent(note.start_time, 1, "pedal", "down"))
            elif has_gap:
                events.append(KeyEvent(prev_end, 0, "pedal", "up"))
                events.append(KeyEvent(note.start_time, 1, "pedal", "down"))
            elif is_new_harmony:
                events.append(KeyEvent(note.start_time, 0, "pedal", "up"))
                events.append(KeyEvent(note.start_time, 1, "pedal", "down"))
            current_bass_pitch = note.pitch
        final_end = max(n.end_time for n in bass_notes)
        events.append(KeyEvent(final_end, 0, "pedal", "up"))

    @staticmethod
    def _convert_raw_pedal(raw_events: list) -> List[KeyEvent]:
        """Convert parsed MIDI CC64 events to KeyEvent objects (value >= 64 -> down, < 64 -> up)."""
        events = []
        pedal_down = False
        for t, value in raw_events:
            if value >= 64 and not pedal_down:
                events.append(KeyEvent(t, 1, "pedal", "down"))
                pedal_down = True
            elif value < 64 and pedal_down:
                events.append(KeyEvent(t, 0, "pedal", "up"))
                pedal_down = False
        return events
