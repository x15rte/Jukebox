from __future__ import annotations

from typing import Any

import pytest

from analysis.humanizer import FingeringEngine, Humanizer
from tests.helpers.builders import make_note, make_section


def test_apply_to_hand_noop_when_all_features_off():
    cfg: dict[str, Any] = {}
    hz = Humanizer(cfg)
    notes = [make_note(1, 60, 1.0, 0.5, hand="right")]
    hz.apply_to_hand(notes, "right", set())
    assert notes[0].start_time == 1.0
    assert notes[0].duration == 0.5


def test_prepare_shared_offsets_requires_timing_and_drift():
    hz = Humanizer({"vary_timing": True, "enable_drift_correction": False})
    notes = [make_note(1, 60, 0.0, 0.2)]
    hz.prepare_shared_offsets(notes)
    assert hz._shared_drift_offsets == {}


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

    assert notes[0].start_time <= notes[1].start_time
    assert notes[0].duration == 0.03
    assert notes[1].duration == 0.03


@pytest.mark.parametrize(
    ("cfg", "note_start", "section_len"),
    [
        pytest.param(
            {"enable_tempo_sway": True, "tempo_sway_intensity": 0.02},
            0.2,
            0.5,
            id="short_section",
        ),
        pytest.param(
            {"enable_tempo_sway": False, "tempo_sway_intensity": 0.1},
            1.0,
            2.0,
            id="disabled",
        ),
    ],
)
def test_apply_tempo_rubato_noop(cfg, note_start, section_len):
    hz = Humanizer(cfg)
    n = make_note(1, 60, note_start, 0.1)
    sec = make_section(0.0, section_len, [n], pace="normal")
    hz.apply_tempo_rubato([n], [sec])
    assert n.start_time == note_start


def test_apply_tempo_rubato_changes_time_on_long_section(monkeypatch):
    cfg = {"enable_tempo_sway": True, "tempo_sway_intensity": 0.02}
    hz = Humanizer(cfg)
    monkeypatch.setattr("analysis.humanizer.np.sin", lambda x: 1.0)
    n = make_note(1, 60, 1.0, 0.1)
    sec = make_section(0.0, 2.0, [n], pace="normal")
    hz.apply_tempo_rubato([n], [sec])
    assert n.start_time < 1.0


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

    assert n_fast.start_time < n_slow.start_time


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

    assert hz._shared_drift_offsets
    key = round(notes[0].start_time, 2)
    assert hz._shared_drift_offsets[key] == 0.03


@pytest.mark.parametrize(
    ("hand", "decay", "drift_attr", "note_pitch", "note_start", "shared_offset", "expected_start", "expected_drift"),
    [
        pytest.param("left", 0.5, "left_hand_drift", 55, 1.0, 0.1, 1.2, 0.3, id="left_drift_update"),
        pytest.param("right", 0.25, "right_hand_drift", 72, 2.0, 0.2, 2.1, 0.3, id="right_drift_update"),
    ],
)
def test_apply_to_hand_resync_and_drift_update(monkeypatch, hand, decay, drift_attr, note_pitch, note_start, shared_offset, expected_start, expected_drift):
    hz = Humanizer(
        {
            "vary_timing": False,
            "vary_articulation": False,
            "enable_drift_correction": True,
            "drift_decay_factor": decay,
            "drift_shared_factor": 1.0,
            "drift_noise_sigma": 0.01,
        }
    )
    monkeypatch.setattr("analysis.humanizer.random.gauss", lambda *_a, **_k: 0.0)
    notes = [make_note(1, note_pitch, note_start, 0.2, hand=hand)]
    setattr(hz, drift_attr, 0.4)
    hz._shared_drift_offsets = {note_start: shared_offset}

    hz.apply_to_hand(notes, hand, {note_start})

    assert notes[0].start_time == expected_start
    assert getattr(hz, drift_attr) == pytest.approx(expected_drift)


@pytest.mark.parametrize(
    ("notes_input", "expected_hands"),
    [
        pytest.param(
            [(50, "unknown", 0.0), (70, "unknown", 0.1)],
            ["left", "right"],
            id="auto_assigned_by_pitch",
        ),
        pytest.param(
            [(50, "unknown", 0.0), (53, "unknown", 0.0), (70, "right", 1.0)],
            ["left", "left", "right"],
            id="chord_left_preset_right",
        ),
        pytest.param(
            [(50, "left", 0.0), (53, "left", 0.0)],
            ["left", "left"],
            id="already_assigned_noop",
        ),
    ],
)
def test_fingering_engine_hand_assignment(notes_input, expected_hands):
    notes = [
        make_note(i, pitch, start, 0.2, hand=hand)
        for i, (pitch, hand, start) in enumerate(notes_input, start=1)
    ]
    eng = FingeringEngine()
    eng.assign_hands(notes)
    assert [n.hand for n in notes] == expected_hands
