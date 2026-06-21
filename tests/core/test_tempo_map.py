import pytest
import mido

from core.tempo_map import GlobalTickMap, TempoMap, get_time_groups
from tests.helpers.builders import make_note


def test_get_time_groups_uses_threshold_boundary():
    notes = [
        make_note(1, 60, 0.000, 0.2),
        make_note(2, 62, 0.015, 0.2),
        make_note(3, 64, 0.031, 0.2),
    ]
    groups = get_time_groups(notes, threshold=0.015)
    assert len(groups) == 2
    assert [n.id for n in groups[0]] == [1, 2]
    assert [n.id for n in groups[1]] == [3]


def test_get_time_groups_empty_returns_empty():
    assert get_time_groups([]) == []


def test_tempo_map_round_trip_and_tempo_lookup():
    tm = TempoMap([(0.0, 500000), (2.0, 1000000)], [(0.0, 4, 4)])
    t = tm.beat_to_time(3.0)
    b = tm.time_to_beat(t)
    assert abs(b - 3.0) < 1e-9
    assert tm.get_tempo_at(0.5) == 500000
    assert tm.get_tempo_at(3.0) == 1000000


def test_tempo_map_measure_boundaries_default_signature():
    tm = TempoMap([(0.0, 500000)], [])
    measures = tm.get_measure_boundaries(total_duration=4.5)
    assert len(measures) >= 2
    assert measures[0][0] == 0.0
    assert measures[0][1] > measures[0][0]


def test_tempo_map_measure_boundaries_breaks_on_future_time_signature():
    tm = TempoMap([(0.0, 500000)], [(0.0, 4, 4), (10.0, 3, 4)])

    measures = tm.get_measure_boundaries(total_duration=2.0)

    assert measures
    assert measures[0][0] == 0.0


def test_global_tick_map_tick_to_time_with_tempo_change():
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    tr.append(mido.MetaMessage("set_tempo", tempo=1000000, time=480))

    gmap = GlobalTickMap(mid)
    t1 = gmap.tick_to_time(480)
    t2 = gmap.tick_to_time(960)

    assert abs(t1 - 0.5) < 1e-6
    assert abs(t2 - 1.5) < 1e-6


def test_tempo_map_negative_time_and_beat_return_zero():
    tm = TempoMap([(0.0, 500000)], [(0.0, 4, 4)])
    assert tm.time_to_beat(-1.0) == 0.0
    assert tm.beat_to_time(-1.0) == 0.0


def test_tempo_map_build_segments_inserts_zero_segment_when_first_tempo_late():
    tm = TempoMap([(1.0, 600000)], [])

    assert tm._segments[0] == (0.0, 0.0, 500000)


def test_global_tick_map_collects_time_signature_events():
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("time_signature", numerator=3, denominator=4, time=0))

    gmap = GlobalTickMap(mid)
    assert gmap.time_signatures and gmap.time_signatures[0][1:] == (3, 4)


def test_global_tick_map_tick_to_time_breaks_on_future_entry():
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    tr.append(mido.MetaMessage("set_tempo", tempo=1000000, time=480))

    gmap = GlobalTickMap(mid)

    assert abs(gmap.tick_to_time(240) - 0.25) < 1e-6


def test_tempo_map_invalid_tempo_scale():
    """TempoMap raises ValueError for non-positive, nan, or infinite tempo_scale."""
    import math
    for bad in [0.0, -1.0, float("nan"), float("inf")]:
        with pytest.raises(ValueError, match="tempo_scale"):
            TempoMap([(0.0, 500000)], [], tempo_scale=bad)


def test_tempo_map_get_tempo_at_before_first_event():
    """get_tempo_at returns 500_000 for time before any tempo event."""
    tm = TempoMap([(1.0, 600000)], [])
    assert tm.get_tempo_at(0.5) == 500_000


def test_tempo_map_get_tempo_at_negative_time():
    """get_tempo_at returns 500_000 for negative time (idx < 0)."""
    tm = TempoMap([], [])
    assert tm.get_tempo_at(-1.0) == 500_000


def test_tempo_map_measure_boundaries_prepends_default_ts():
    """When first time signature starts after time 0, default 4/4 is prepended."""
    tm = TempoMap([(0.0, 500000)], [(2.0, 4, 4)])
    measures = tm.get_measure_boundaries(total_duration=4.0)
    assert len(measures) >= 1
    assert measures[0][0] == 0.0


def test_tempo_map_measure_boundaries_breaks_on_bad_ts():
    """get_measure_boundaries breaks when time signature has zero denominator."""
    tm = TempoMap([(0.0, 500000)], [(0.0, 4, 0)])
    measures = tm.get_measure_boundaries(total_duration=4.0)
    assert measures == []


def test_tempo_map_measure_boundaries_breaks_on_zero_beats():
    """get_measure_boundaries breaks when numerator is zero."""
    tm = TempoMap([(0.0, 500000)], [(0.0, 0, 4)])
    measures = tm.get_measure_boundaries(total_duration=4.0)
    assert measures == []
