from __future__ import annotations

import math

import pytest

from playback.player import EventCompiler
from tests.helpers.builders import make_note


def _stub_humanizer(monkeypatch, *, apply_to_hand_impl=None, apply_tempo_rubato_impl=None):
    """Monkeypatches playback.player.Humanizer for edge tests."""
    class H:
        def __init__(self, config):
            pass

        @staticmethod
        def prepare_shared_offsets(notes):
            pass

        @staticmethod
        def apply_to_hand(notes, hand, resync):
            if apply_to_hand_impl:
                apply_to_hand_impl(notes, hand, resync)

        @staticmethod
        def apply_tempo_rubato(notes, sections):
            if apply_tempo_rubato_impl:
                apply_tempo_rubato_impl(notes, sections)

    monkeypatch.setattr("playback.player.Humanizer", H)


def test_compile_triggers_humanizer_when_enable_flags_used(monkeypatch):
    notes = [make_note(1, 60, 0.0, 0.3, hand="right")]
    sections = []

    calls: dict[str, int] = {}

    class H:
        def __init__(self, config):
            calls["init"] = 1

        @staticmethod
        def prepare_shared_offsets(n):
            calls["prep"] = calls.get("prep", 0) + 1

        @staticmethod
        def apply_to_hand(n, hand, resync):
            calls["hand"] = calls.get("hand", 0) + 1

        @staticmethod
        def apply_tempo_rubato(n, s):
            calls["rubato"] = calls.get("rubato", 0) + 1

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


def test_mistake_pitch_lowest_boundary(monkeypatch):
    monkeypatch.setattr("playback.player.random.shuffle", lambda _: None)
    out = EventCompiler._mistake_pitch(0)
    assert out is None or 0 <= out <= 127


def test_mistake_pitch_highest_boundary(monkeypatch):
    monkeypatch.setattr("playback.player.random.shuffle", lambda _: None)
    out = EventCompiler._mistake_pitch(127)
    assert out is None or 0 <= out <= 127


def test_compile_empty_notes_returns_empty(monkeypatch):
    _stub_humanizer(monkeypatch)
    out = EventCompiler.compile([], [], {"pedal_style": "none"})
    assert out == []


def test_compile_empty_sections_returns_events(monkeypatch):
    notes = [make_note(1, 60, 0.0, 0.5, hand="right")]
    _stub_humanizer(monkeypatch)
    out = EventCompiler.compile(notes, [], {"pedal_style": "none"})
    assert out


# -- Private-method unit tests moved from test_event_compiler.py --


def test_collapse_anchor_deltas_empty_input_returns_empty():
    assert EventCompiler._collapse_anchor_deltas([], prefer_latest=True) == []


def test_build_note_timing_deltas_skips_unmatched_original_note_ids():
    original_notes = [
        make_note(1, 60, 0.0, 1.0, hand="right"),
        make_note(2, 64, 2.0, 0.5, hand="right"),
    ]
    humanized_notes = [
        make_note(1, 60, 0.25, 1.25, hand="right"),
        make_note(3, 67, 4.0, 0.5, hand="right"),
    ]

    onset_deltas, release_deltas = EventCompiler._build_note_timing_deltas(
        original_notes,
        humanized_notes,
    )

    assert onset_deltas == [(0.0, 0.25)]
    assert release_deltas == [(1.0, 0.5)]


def test_find_anchor_match_and_delta_empty_input_use_none_and_zero():
    assert EventCompiler._find_anchor_match([], 1.5) is None
    assert EventCompiler._find_anchor_delta([], 1.5) == 0.0


def test_find_anchor_match_without_nearest_prefers_previous_anchor():
    anchor_deltas = [(1.0, 0.1), (3.0, 0.2)]

    assert (
        EventCompiler._find_anchor_match(
            anchor_deltas,
            2.5,
            prefer_nearest=False,
        )
        == (1.0, 0.1)
    )


def test_find_anchor_match_with_nearest_can_still_return_previous_anchor():
    anchor_deltas = [(1.0, 0.1), (2.0, 0.2)]

    assert EventCompiler._find_anchor_match(anchor_deltas, 1.2) == (1.0, 0.1)


def test_find_raw_pedal_up_delta_falls_back_to_onset_delta_without_release_anchors():
    onset_deltas = [(1.0, 0.15)]

    assert EventCompiler._find_raw_pedal_up_delta(1.2, onset_deltas, []) == 0.15


def test_find_raw_pedal_up_delta_returns_release_delta_without_onset_anchors():
    release_deltas = [(1.0, 0.35)]

    assert EventCompiler._find_raw_pedal_up_delta(1.2, [], release_deltas) == 0.35


def test_normalize_remapped_pedal_spans_leaves_separated_spans_unchanged():
    spans = [(0.0, 0.5), (1.0, 1.5)]

    normalized_spans, trailing_down_time = EventCompiler._normalize_remapped_pedal_spans(
        spans
    )

    assert normalized_spans == spans
    assert trailing_down_time is None
    assert all(down < up for down, up in normalized_spans)
    assert all(
        normalized_spans[idx][1] < normalized_spans[idx + 1][0]
        for idx in range(len(normalized_spans) - 1)
    )


def test_normalize_remapped_pedal_spans_uses_epsilon_separation_for_same_start_overlap():
    spans = [(1.0, 2.0), (1.0, 3.0)]

    normalized_spans, trailing_down_time = EventCompiler._normalize_remapped_pedal_spans(
        spans
    )

    expected_first_up = math.nextafter(1.0, math.inf)
    expected_second_down = math.nextafter(expected_first_up, math.inf)

    assert normalized_spans == [(1.0, expected_first_up), (expected_second_down, 3.0)]
    assert trailing_down_time is None
    assert all(down < up for down, up in normalized_spans)
    assert all(
        normalized_spans[idx][1] < normalized_spans[idx + 1][0]
        for idx in range(len(normalized_spans) - 1)
    )


def test_normalize_remapped_pedal_spans_shortens_last_span_before_trailing_down():
    spans = [(1.0, 3.0)]

    normalized_spans, trailing_down_time = EventCompiler._normalize_remapped_pedal_spans(
        spans,
        trailing_down_time=2.0,
    )

    assert normalized_spans == [(1.0, math.nextafter(2.0, -math.inf))]
    assert trailing_down_time == 2.0
    assert all(down < up for down, up in normalized_spans)


def test_normalize_remapped_pedal_spans_pushes_trailing_down_forward_when_no_room():
    spans = [(2.0, 3.0)]

    normalized_spans, trailing_down_time = EventCompiler._normalize_remapped_pedal_spans(
        spans,
        trailing_down_time=2.0,
    )

    expected_last_up = math.nextafter(2.0, math.inf)
    expected_trailing_down = math.nextafter(expected_last_up, math.inf)

    assert normalized_spans == [(2.0, expected_last_up)]
    assert trailing_down_time == expected_trailing_down
    assert all(down < up for down, up in normalized_spans)
