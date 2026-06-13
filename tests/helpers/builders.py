from __future__ import annotations
from models import Note, MusicalSection

def make_note(
    note_id: int,
    pitch: int,
    start: float,
    duration: float,
    *,
    velocity: int = 100,
    hand: str = "unknown",
    track_index: int = 0,
    channel: int = 0,
) -> Note:
    return Note(
        id=note_id,
        pitch=pitch,
        velocity=velocity,
        start_time=start,
        duration=duration,
        hand=hand,
        original_track_index=track_index,
        channel=channel,
    )


def make_section(
    start: float,
    end: float,
    notes: list[Note],
    *,
    pace: str = "normal",
) -> MusicalSection:
    return MusicalSection(
        start_time=start,
        end_time=end,
        notes=notes,
        articulation_label="unknown",
        pace_label=pace,
        start_beat=0.0,
        end_beat=0.0,
    )


