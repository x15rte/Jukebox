"""Data models for MIDI parsing and playback (notes, tracks, key events, sections, key state)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Note:
    """Single note: pitch (MIDI 0–127), start/duration in seconds, optional hand assignment."""

    id: int
    pitch: int
    velocity: int
    start_time: float
    duration: float
    hand: str = "unknown"
    original_track_index: int = -1
    channel: int = -1

    def __post_init__(self):
        if not 0 <= self.pitch <= 127:
            raise ValueError(
                f"pitch {self.pitch} out of range [0, 127]"
            )
        if not 0 <= self.velocity <= 127:
            raise ValueError(f"velocity {self.velocity} out of range [0, 127]")
        if self.start_time < 0:
            raise ValueError(f"start_time {self.start_time} must be >= 0")
        if self.duration < 0:
            raise ValueError(f"duration {self.duration} must be >= 0")

    @property
    def end_time(self) -> float:
        return self.start_time + self.duration


@dataclass
class MidiTrack:
    """Single MIDI track metadata plus list of notes; instrument_name uses GM program ranges."""

    index: int
    name: str
    program_change: int
    is_drum: bool
    notes: List[Note]
    pedal_events: List[Tuple[float, int]] = field(default_factory=list)

    @property
    def note_count(self) -> int:
        return len(self.notes)

    @property
    def instrument_name(self) -> str:
        if self.is_drum:
            return "Drums/Percussion"
        if 0 <= self.program_change <= 7:
            return "Piano"
        if 8 <= self.program_change <= 15:
            return "Chromatic Perc"
        if 16 <= self.program_change <= 23:
            return "Organ"
        if 24 <= self.program_change <= 31:
            return "Guitar"
        if 32 <= self.program_change <= 39:
            return "Bass"
        if 40 <= self.program_change <= 47:
            return "Strings"
        if 48 <= self.program_change <= 55:
            return "Ensemble"
        if 56 <= self.program_change <= 63:
            return "Brass"
        if 64 <= self.program_change <= 71:
            return "Reed"
        if 72 <= self.program_change <= 79:
            return "Pipe"
        if 80 <= self.program_change <= 87:
            return "Synth Lead"
        if 88 <= self.program_change <= 95:
            return "Synth Pad"
        if 96 <= self.program_change <= 103:
            return "Synth Effects"
        if 104 <= self.program_change <= 111:
            return "Ethnic"
        if 112 <= self.program_change <= 119:
            return "Percussive"
        if 120 <= self.program_change <= 127:
            return "Sound Effects"
        return f"Instrument {self.program_change}"


@dataclass(order=False)
class KeyEvent:
    """Event at a given time: key press/release or pedal; priority used to order same-frame events."""

    time: float
    priority: int
    action: str
    key_char: str
    pitch: Optional[int] = None
    velocity: int = 100

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, KeyEvent):
            return NotImplemented
        # Compare fields in order, with None pitch sorted after any pitch
        self_key = (
            self.time,
            self.priority,
            self.action,
            self.key_char,
            self.pitch if self.pitch is not None else float("inf"),
            self.velocity,
        )
        other_key = (
            other.time,
            other.priority,
            other.action,
            other.key_char,
            other.pitch if other.pitch is not None else float("inf"),
            other.velocity,
        )
        return self_key < other_key



@dataclass
class MusicalSection:
    """Time span of notes with articulation and pace labels for humanization/rubato."""

    start_time: float
    end_time: float
    notes: List[Note]
    articulation_label: str = "unknown"
    pace_label: str = "normal"

    start_beat: float = 0.0
    end_beat: float = 0.0

    def __post_init__(self):
        if self.end_time < self.start_time:
            self.end_time = self.start_time
        if self.end_beat < self.start_beat:
            self.end_beat = self.start_beat


@dataclass
class KeyState:
    """Tracks whether a key is currently down."""

    key_char: str
    is_active: bool = False

    def press(self):
        if not self.is_active:
            self.is_active = True

    def release(self):
        if self.is_active:
            self.is_active = False



