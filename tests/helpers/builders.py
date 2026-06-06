from __future__ import annotations

from typing import TYPE_CHECKING, Any

from models import KeyEvent, MidiTrack, Note, MusicalSection

if TYPE_CHECKING:
    from core.tempo_map import TempoMap


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


def make_key_event(
    time: float,
    action: str,
    *,
    priority: int = 2,
    key_char: str = "",
    pitch: int | None = None,
    velocity: int = 100,
) -> KeyEvent:
    """Create a KeyEvent with sensible defaults.

    >>> make_key_event(0.5, "press", pitch=60)
    KeyEvent(time=0.5, priority=2, action='press', key_char='', pitch=60, velocity=100)
    """
    return KeyEvent(
        time=time,
        priority=priority,
        action=action,
        key_char=key_char,
        pitch=pitch,
        velocity=velocity,
    )


def make_midi_track(
    index: int = 0,
    name: str = "Test Track",
    *,
    program_change: int = 0,
    is_drum: bool = False,
    notes: list[Note] | None = None,
    pedal_events: list[tuple[float, int]] | None = None,
) -> MidiTrack:
    """Create a MidiTrack with sensible defaults.

    >>> make_midi_track(0, "Piano")
    MidiTrack(index=0, name='Piano', ...)
    """
    return MidiTrack(
        index=index,
        name=name,
        program_change=program_change,
        is_drum=is_drum,
        notes=notes or [],
        pedal_events=pedal_events or [],
    )


def make_tempo_map(
    tempo_events: list[tuple[float, int]] | None = None,
    time_sigs: list[tuple[float, int, int]] | None = None,
) -> TempoMap:
    """Create a TempoMap with sensible defaults.

    Defaults to a single tempo event (120 BPM) at time 0.

    >>> make_tempo_map().get_tempo_at(0.0)
    500000
    """
    from core.tempo_map import TempoMap

    return TempoMap(
        tempo_events or [(0.0, 500000)],
        time_sigs or [(0.0, 4, 4)],
    )


def make_config(**overrides: Any) -> Any:
    """Create a Config dataclass with the given field overrides.

    Any keyword argument is set as an attribute on a default Config instance.
    Unknown keys are silently set.

    >>> cfg = make_config(pedal_style="legato")
    >>> cfg.pedal_style
    'legato'
    """
    from config_repository import Config

    cfg = Config()
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg
