"""Test helper re-exports for ergonomic imports.

Usage:
    from tests.helpers import make_note, FakeBackend
"""

from tests.helpers.builders import (  # safe — core imports are lazy
    make_config,
    make_key_event,
    make_midi_track,
    make_note,
    make_section,
    make_tempo_map,
)

_fake_names = {
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
}

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


def __getattr__(name: str):
    """Lazy-load fakes so ``tests.helpers`` can be imported without triggering
    ``output.output`` → ``pynput``, which breaks conftest's pynput-stub logic."""
    if name in _fake_names:
        import tests.helpers.fakes as _fakes  # noqa: PLC0415

        return getattr(_fakes, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
