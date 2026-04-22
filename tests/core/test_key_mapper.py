from pynput.keyboard import Key

from core.key_mapper import KeyMapper


def test_get_key_data_clamps_range_for_61_layout():
    km = KeyMapper(use_88_key_layout=False)
    low = km.get_key_data(0)
    at_min = km.get_key_data(36)
    high = km.get_key_data(127)
    at_max = km.get_key_data(96)
    if not (low == at_min):
        raise AssertionError("Assertion failed")
    if not (high == at_max):
        raise AssertionError("Assertion failed")


def test_88_layout_has_ctrl_bands():
    km = KeyMapper(use_88_key_layout=True)
    left = km.get_key_data(21)
    right = km.get_key_data(97)
    if not (left is not None and Key.ctrl in left["modifiers"]):
        raise AssertionError("Assertion failed")
    if not (right is not None and Key.ctrl in right["modifiers"]):
        raise AssertionError("Assertion failed")


def test_black_key_mapping_uses_shift_in_middle_range():
    km = KeyMapper(use_88_key_layout=False)
    data = km.get_key_data(37)
    if not (data is not None):
        raise AssertionError("Assertion failed")
    if not (Key.shift in data["modifiers"]):
        raise AssertionError("Assertion failed")


def test_pitch_to_name_and_black_key_detection():
    if not (KeyMapper.pitch_to_name(60) == "C4"):
        raise AssertionError("Assertion failed")
    if not (KeyMapper.is_black_key(61) is True):
        raise AssertionError("Assertion failed")
    if not (KeyMapper.is_black_key(60) is False):
        raise AssertionError("Assertion failed")


def test_get_key_for_pitch_and_bounds_properties():
    km = KeyMapper(use_88_key_layout=False)
    if not (km.get_key_for_pitch(60) is not None):
        raise AssertionError("Assertion failed")
    if not (km.lower_ctrl_bound == 0):
        raise AssertionError("Assertion failed")
    if not (km.upper_ctrl_bound == 128):
        raise AssertionError("Assertion failed")
