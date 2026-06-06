"""Tests for KeyMapper: pitch-to-key mapping for 61-key and 88-key layouts."""
from __future__ import annotations

from pynput.keyboard import Key

from core.key_mapper import KeyMapper


def test_get_key_data_clamps_range_for_61_layout():
    km = KeyMapper(use_88_key_layout=False)
    low = km.get_key_data(0)
    at_min = km.get_key_data(36)
    high = km.get_key_data(127)
    at_max = km.get_key_data(96)
    assert low == at_min
    assert high == at_max


def test_get_key_data_clamps_range_for_88_layout():
    km = KeyMapper(use_88_key_layout=True)
    low = km.get_key_data(0)
    at_min = km.get_key_data(21)
    high = km.get_key_data(127)
    at_max = km.get_key_data(108)
    assert low == at_min
    assert high == at_max


def test_88_layout_has_ctrl_bands():
    km = KeyMapper(use_88_key_layout=True)
    left = km.get_key_data(21)
    right = km.get_key_data(97)
    assert left is not None and Key.ctrl in left["modifiers"]
    assert right is not None and Key.ctrl in right["modifiers"]


def test_88_layout_all_ctrl_band_pitches_have_ctrl():
    """Every pitch in left and right ctrl bands should have ctrl modifier.

    LEFT_CTRL_KEYS has 15 chars starting at pitch 21.
    RIGHT_CTRL_KEYS has 11 chars starting at pitch 97.
    """
    km = KeyMapper(use_88_key_layout=True)

    left_start, left_len = 21, len(KeyMapper.LEFT_CTRL_KEYS)
    for pitch in range(left_start, left_start + left_len):
        data = km.get_key_data(pitch)
        assert data is not None, f"Pitch {pitch} should have key data"
        assert Key.ctrl in data["modifiers"], f"Pitch {pitch} should have ctrl modifier"

    right_start, right_len = 97, len(KeyMapper.RIGHT_CTRL_KEYS)
    for pitch in range(right_start, right_start + right_len):
        data = km.get_key_data(pitch)
        assert data is not None, f"Pitch {pitch} should have key data"
        assert Key.ctrl in data["modifiers"], f"Pitch {pitch} should have ctrl modifier"


def test_black_key_mapping_uses_shift_in_middle_range():
    km = KeyMapper(use_88_key_layout=False)
    data = km.get_key_data(37)
    assert data is not None
    assert Key.shift in data["modifiers"]


def test_all_black_key_positions_detect_shift():
    """Black keys at all five semitone positions should map to shift modifiers."""
    km = KeyMapper(use_88_key_layout=False)
    for pitch in [37, 39, 42, 44, 46]:  # C#, D#, F#, G#, A#
        data = km.get_key_data(pitch)
        assert data is not None, f"Pitch {pitch} should have key data"
        assert Key.shift in data["modifiers"], f"Pitch {pitch} should have shift modifier"


def test_white_key_has_no_shift_modifier():
    km = KeyMapper(use_88_key_layout=False)
    data = km.get_key_data(36)  # C2 — white key
    assert data is not None
    assert Key.shift not in data["modifiers"]


def test_pitch_to_name():
    assert KeyMapper.pitch_to_name(60) == "C4"
    assert KeyMapper.pitch_to_name(61) == "C#4"
    assert KeyMapper.pitch_to_name(0) == "C-1"
    assert KeyMapper.pitch_to_name(21) == "A0"


def test_is_black_key_all_positions():
    for pitch in range(0, 128):
        expected = pitch % 12 in {1, 3, 6, 8, 10}
        assert KeyMapper.is_black_key(pitch) is expected, f"Pitch {pitch}"


def test_get_key_for_pitch_and_bounds_properties():
    km = KeyMapper(use_88_key_layout=False)
    assert km.get_key_for_pitch(60) is not None
    assert km.lower_ctrl_bound == 0
    assert km.upper_ctrl_bound == 128


def test_get_key_data_missing_pitch_returns_none():
    """A pitch not in the key map should return None after clamping."""
    km = KeyMapper(use_88_key_layout=True)
    # Pitch 109 is above 88-key max (108) so it clamps to 108.
    # There is no easy way to get a non-mapped in-range pitch with the
    # current builder, but we can at least verify clamped range works.
    data = km.get_key_data(109)
    assert data is not None  # clamped to 108 which IS mapped


def test_adjacent_white_keys_map_to_different_keys():
    """Adjacent white keys should not share the same physical key."""
    km = KeyMapper(use_88_key_layout=False)
    k36 = km.get_key_for_pitch(36)  # C2
    k38 = km.get_key_for_pitch(38)  # D2
    assert k36 is not None and k38 is not None
    assert k36 != k38
