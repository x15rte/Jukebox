"""Core MIDI parsing, tempo mapping, and key mapping.

Submodules:
- tempo_map: TempoMap, get_time_groups
- midi_parser: MidiParser
- key_mapper: KeyMapper
"""

from .tempo_map import TempoMap, get_time_groups
from .midi_parser import MidiParser
from .key_mapper import KeyMapper

__all__ = ["TempoMap", "get_time_groups", "MidiParser", "KeyMapper"]
