"""Test helper re-exports for ergonomic imports.

Usage:
    from tests.helpers import make_note, FakeBackend
"""

from tests.helpers.builders import (
    make_config,
    make_key_event,
    make_midi_track,
    make_note,
    make_section,
    make_tempo_map,
)
from tests.helpers.fakes import (
    FakeBackend,
    FakeEvent,
    FakeHumanizer,
    FakeInPort,
    FakeListener,
    FakeLiveBackend,
    FakePedalGenerator,
    FakePlaybackPlayer,
    FakeSectionAnalyzer,
    FakeSignal,
    FakeThread,
    RecorderBackend,
)

__all__ = [
    "FakeBackend",
    "FakeEvent",
    "FakeHumanizer",
    "FakeInPort",
    "FakeListener",
    "FakeLiveBackend",
    "FakePedalGenerator",
    "FakePlaybackPlayer",
    "FakeSectionAnalyzer",
    "FakeSignal",
    "FakeThread",
    "RecorderBackend",
    "make_config",
    "make_key_event",
    "make_midi_track",
    "make_note",
    "make_section",
    "make_tempo_map",
]
