"""Pedal event generation: original, hybrid (adaptive), legato (harmonic), rhythmic, none."""

from typing import Dict, List

from models import Note, KeyEvent, MusicalSection
from core import get_time_groups


class PedalGenerator:
    """Produces pedal down/up KeyEvents. Styles: original (from MIDI), hybrid (adaptive), legato (harmonic), rhythmic (per chord), none."""

    @staticmethod
    def generate_events(
        config: Dict, final_notes: List[Note], sections: List[MusicalSection]
    ) -> List[KeyEvent]:
        style = config.get("pedal_style")
        if style == "none":
            return []

        if style == "original":
            raw = config.get("raw_pedal_events", [])
            if raw:
                return PedalGenerator._convert_raw_pedal(raw)
            style = "hybrid"

        events = []

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

        for section in sections:
            if not section.notes:
                continue
            lh_notes = [n for n in section.notes if n.hand == "left"]
            lh_notes.sort(key=lambda n: n.start_time)
            if not lh_notes:
                start = section.notes[0].start_time
                end = max(n.end_time for n in section.notes)
                events.append(KeyEvent(start, 1, "pedal", "down"))
                events.append(KeyEvent(end, 0, "pedal", "up"))
                continue

            if style == "rhythmic":
                groups = get_time_groups(lh_notes)
                for g in groups:
                    start = g[0].start_time
                    end = max(n.end_time for n in g)
                    events.append(KeyEvent(start, 1, "pedal", "down"))
                    events.append(KeyEvent(end, 0, "pedal", "up"))
            else:
                PedalGenerator._generate_harmonic_pedal(events, lh_notes)
        return events

    @staticmethod
    def _generate_adaptive_pedal_driver(
        driver_notes: List[Note], all_notes: List[Note]
    ) -> List[KeyEvent]:
        events: List[KeyEvent] = []
        if not driver_notes:
            return events

        PEDAL_LAG = 0.05  # Seconds between pedal up and down when repedaling.
        SAFE_INTERVALS = {0, 3, 4, 5, 7}  # Unison, m3, M3, P4, P5, octave; keep pedal.
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
