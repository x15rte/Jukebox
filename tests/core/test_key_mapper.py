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


def test_88_layout_has_ctrl_bands():
    km = KeyMapper(use_88_key_layout=True)
    left = km.get_key_data(21)
    right = km.get_key_data(97)
    assert left is not None and Key.ctrl in left["modifiers"]
    assert right is not None and Key.ctrl in right["modifiers"]


def test_black_key_mapping_uses_shift_in_middle_range():
    km = KeyMapper(use_88_key_layout=False)
    data = km.get_key_data(37)
    assert data is not None
    assert Key.shift in data["modifiers"]


def test_is_black_key_detection():
    assert KeyMapper.is_black_key(61) is True
    assert KeyMapper.is_black_key(60) is False


