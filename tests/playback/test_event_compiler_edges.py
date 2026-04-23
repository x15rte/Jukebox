from playback.player import EventCompiler
from tests.helpers.builders import make_note


def test_compile_triggers_humanizer_when_enable_flags_used(monkeypatch):
    notes = [make_note(1, 60, 0.0, 0.3, hand="right")]
    sections = []

    calls = {"init": 0, "prep": 0, "hand": 0, "rubato": 0}

    class H:
        def __init__(self, config):
            calls["init"] += 1

        def prepare_shared_offsets(self, n):
            calls["prep"] += 1

        def apply_to_hand(self, n, hand, resync):
            calls["hand"] += 1

        def apply_tempo_rubato(self, n, s):
            calls["rubato"] += 1

    monkeypatch.setattr("playback.player.Humanizer", H)

    out = EventCompiler.compile(
        notes,
        sections,
        {"enable_vary_timing": True, "pedal_style": "none"},
    )

    assert out
    assert calls["init"] == 1
    assert calls["prep"] == 1
    assert calls["hand"] == 2
    assert calls["rubato"] == 1


def test_mistake_pitch_white_key_returns_none_when_no_candidates(monkeypatch):
    monkeypatch.setattr("playback.player.KeyMapper.is_black_key", lambda p: p != 0)
    out = EventCompiler._mistake_pitch(0)
    assert out is None
