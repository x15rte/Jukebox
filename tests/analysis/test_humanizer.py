import pytest

from analysis.humanizer import FingeringEngine, Humanizer
from tests.helpers.builders import make_note, make_section


def test_apply_to_hand_noop_when_all_features_off():
    cfg = {}
    hz = Humanizer(cfg)
    notes = [make_note(1, 60, 1.0, 0.5, hand="right")]
    hz.apply_to_hand(notes, "right", set())
    if not (notes[0].start_time == 1.0):
        raise AssertionError("Assertion failed")
    if not (notes[0].duration == 0.5):
        raise AssertionError("Assertion failed")


def test_prepare_shared_offsets_requires_timing_and_drift():
    hz = Humanizer({"vary_timing": True, "enable_drift_correction": False})
    notes = [make_note(1, 60, 0.0, 0.2)]
    hz.prepare_shared_offsets(notes)
    if not (hz._shared_drift_offsets == {}):
        raise AssertionError("Assertion failed")


def test_apply_to_hand_applies_roll_and_duration_floor(monkeypatch):
    cfg = {
        "vary_timing": True,
        "timing_variance": 0.01,
        "vary_articulation": True,
        "articulation": 1.0,
        "enable_chord_roll": True,
    }
    hz = Humanizer(cfg)
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *a, **k: 0.0)
    monkeypatch.setattr("analysis.humanizer.random.random", lambda *a, **k: 1.0)

    notes = [
        make_note(1, 60, 0.0, 0.01, hand="right"),
        make_note(2, 64, 0.0, 0.01, hand="right"),
    ]
    hz.apply_to_hand(notes, "right", set())

    if not (notes[0].start_time <= notes[1].start_time):
        raise AssertionError("Assertion failed")
    if not (notes[0].duration == 0.03):
        raise AssertionError("Assertion failed")
    if not (notes[1].duration == 0.03):
        raise AssertionError("Assertion failed")


def test_apply_tempo_rubato_skips_short_sections():
    cfg = {"enable_tempo_sway": True, "tempo_sway_intensity": 0.02}
    hz = Humanizer(cfg)
    n = make_note(1, 60, 0.2, 0.1)
    sec = make_section(0.0, 0.5, [n], pace="normal")
    hz.apply_tempo_rubato([n], [sec])
    if not (n.start_time == 0.2):
        raise AssertionError("Assertion failed")


def test_apply_tempo_rubato_changes_time_on_long_section(monkeypatch):
    cfg = {"enable_tempo_sway": True, "tempo_sway_intensity": 0.02}
    hz = Humanizer(cfg)
    monkeypatch.setattr("analysis.humanizer.np.sin", lambda x: 1.0)
    n = make_note(1, 60, 1.0, 0.1)
    sec = make_section(0.0, 2.0, [n], pace="normal")
    hz.apply_tempo_rubato([n], [sec])
    if not (n.start_time < 1.0):
        raise AssertionError("Assertion failed")


def test_fingering_engine_assigns_unknown_hands():
    notes = [
        make_note(1, 50, 0.0, 0.2, hand="unknown"),
        make_note(2, 70, 0.2, 0.2, hand="unknown"),
    ]
    eng = FingeringEngine()
    eng.assign_hands(notes)
    if not (notes[0].hand == "left"):
        raise AssertionError("Assertion failed")
    if not (notes[1].hand == "right"):
        raise AssertionError("Assertion failed")


def test_prepare_shared_offsets_populates_and_clamps(monkeypatch):
    hz = Humanizer(
        {
            "vary_timing": True,
            "enable_drift_correction": True,
            "timing_variance": 0.01,
        }
    )
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *_a, **_k: 0.2)
    notes = [
        make_note(1, 60, 0.123, 0.2, hand="left"),
        make_note(2, 64, 0.127, 0.2, hand="right"),
    ]

    hz.prepare_shared_offsets(notes)

    if not (hz._shared_drift_offsets):
        raise AssertionError("Assertion failed")
    key = round(notes[0].start_time, 2)
    if not (hz._shared_drift_offsets[key] == 0.03):
        raise AssertionError("Assertion failed")


def test_apply_to_hand_resync_and_drift_update(monkeypatch):
    hz = Humanizer(
        {
            "vary_timing": False,
            "vary_articulation": False,
            "enable_drift_correction": True,
            "drift_decay_factor": 0.5,
            "drift_shared_factor": 1.0,
            "drift_noise_sigma": 0.01,
        }
    )
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *_a, **_k: 0.0)
    notes = [make_note(1, 55, 1.0, 0.2, hand="left")]
    hz.left_hand_drift = 0.4
    hz._shared_drift_offsets = {1.0: 0.1}

    hz.apply_to_hand(notes, "left", {1.0})

    if not (notes[0].start_time == 1.2):
        raise AssertionError("Assertion failed")
    if not (hz.left_hand_drift == pytest.approx(0.3)):
        raise AssertionError("Assertion failed")


def test_apply_tempo_rubato_fast_and_slow_invert(monkeypatch):
    monkeypatch.setattr("analysis.humanizer.np.sin", lambda _x: 1.0)
    n_fast = make_note(1, 60, 1.0, 0.2)
    n_slow = make_note(2, 62, 1.0, 0.2)

    hz = Humanizer(
        {
            "enable_tempo_sway": True,
            "tempo_sway_intensity": 0.04,
            "invert_tempo_sway": True,
        }
    )
    sec_fast = make_section(0.0, 2.0, [n_fast], pace="fast")
    sec_slow = make_section(0.0, 2.0, [n_slow], pace="slow")

    hz.apply_tempo_rubato([n_fast, n_slow], [sec_fast, sec_slow])

    if not (n_fast.start_time < n_slow.start_time):
        raise AssertionError("Assertion failed")


def test_fingering_engine_chord_and_preserved_hand():
    chord = [
        make_note(1, 50, 0.0, 0.2, hand="unknown"),
        make_note(2, 53, 0.0, 0.2, hand="unknown"),
    ]
    preset = make_note(3, 70, 1.0, 0.2, hand="right")

    eng = FingeringEngine()
    eng.assign_hands(chord + [preset])

    if not (all(n.hand == "left" for n in chord)):
        raise AssertionError("Assertion failed")
    if not (preset.hand == "right"):
        raise AssertionError("Assertion failed")


def test_apply_to_hand_right_resync_decay_and_drift_update(monkeypatch):
    hz = Humanizer(
        {
            "vary_timing": False,
            "vary_articulation": False,
            "enable_drift_correction": True,
            "drift_decay_factor": 0.25,
            "drift_shared_factor": 1.0,
            "drift_noise_sigma": 0.01,
        }
    )
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *_a, **_k: 0.0)
    notes = [make_note(1, 72, 2.0, 0.2, hand="right")]
    hz.right_hand_drift = 0.4
    hz._shared_drift_offsets = {2.0: 0.2}

    hz.apply_to_hand(notes, "right", {2.0})

    if not (notes[0].start_time == 2.1):
        raise AssertionError("Assertion failed")
    if not (hz.right_hand_drift == pytest.approx(0.3)):
        raise AssertionError("Assertion failed")


def test_apply_tempo_rubato_disabled_noop():
    hz = Humanizer({"enable_tempo_sway": False, "tempo_sway_intensity": 0.1})
    n = make_note(1, 60, 1.0, 0.2)
    sec = make_section(0.0, 2.0, [n], pace="normal")

    hz.apply_tempo_rubato([n], [sec])

    if not (n.start_time == 1.0):
        raise AssertionError("Assertion failed")


def test_fingering_engine_chord_already_assigned_noop():
    chord = [
        make_note(1, 50, 0.0, 0.2, hand="left"),
        make_note(2, 53, 0.0, 0.2, hand="left"),
    ]

    eng = FingeringEngine()
    eng.assign_hands(chord)

    if not (all(n.hand == "left" for n in chord)):
        raise AssertionError("Assertion failed")
