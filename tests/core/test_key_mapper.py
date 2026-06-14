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


def test_get_key_data_clamps_below_min_to_min():
    km = KeyMapper(use_88_key_layout=False)
    low = km.get_key_data(20)
    at_min = km.get_key_data(36)
    assert low is not None
    assert at_min is not None
    assert low == at_min


def test_get_key_data_clamps_above_max_to_max():
    km = KeyMapper(use_88_key_layout=False)
    high = km.get_key_data(110)
    at_max = km.get_key_data(96)
    assert high is not None
    assert at_max is not None
    assert high == at_max


def test_88_key_layout_has_left_and_right_ctrl_regions():
    km = KeyMapper(use_88_key_layout=True)
    for pitch in range(21, 36):
        data = km.get_key_data(pitch)
        assert data is not None
        assert Key.ctrl in data["modifiers"]
    for pitch in range(97, 109):
        data = km.get_key_data(pitch)
        assert data is not None
        assert Key.ctrl in data["modifiers"]
    middle = km.get_key_data(55)
    assert middle is not None
    assert middle["modifiers"] == []


def test_is_black_key_boundaries():
    assert KeyMapper.is_black_key(0) is False
    assert KeyMapper.is_black_key(1) is True
    assert KeyMapper.is_black_key(11) is False
    assert KeyMapper.is_black_key(127) is False
    assert KeyMapper.is_black_key(3) is True
    assert KeyMapper.is_black_key(6) is True
    assert KeyMapper.is_black_key(8) is True
    assert KeyMapper.is_black_key(10) is True

