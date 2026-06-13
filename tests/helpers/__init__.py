"""Test helper re-exports for ergonomic imports.

Usage:
    from tests.helpers import make_note, FakeBackend
"""

from tests.helpers.builders import (  # safe — core imports are lazy
    make_note,
    make_section,
)

_fake_names = {
    "FakeBackend",
    "FakeEvent",
    "FakeListener",
    "FakeLiveBackend",
    "FakePlaybackPlayer",
    "FakeSignal",
    "FakeThread",
    "RecorderBackend",
}

# Only statically-imported names are listed in __all__; fake names
# are resolved at runtime via __getattr__ to avoid triggering
# output.output → pynput at import time (which breaks conftest's
# pynput-stub logic on headless CI).
__all__ = [
    "make_note",
    "make_section",
]


def __getattr__(name: str):
    """Lazy-load fakes (see module docstring for rationale)."""
    if name in _fake_names:
        import tests.helpers.fakes as _fakes  # noqa: PLC0415

        return getattr(_fakes, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
