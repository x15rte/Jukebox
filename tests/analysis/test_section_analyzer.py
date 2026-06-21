from typing import Any, cast

from analysis.section_analyzer import SectionAnalyzer
from core.tempo_map import TempoMap
from tests.helpers.builders import make_note


def _tempo_map(explicit=False):
    ts = [(0.0, 4, 4)]
    if explicit:
        ts = [(0.0, 3, 4), (3.0, 4, 4)]
    return TempoMap([(0.0, 500000)], ts)


def test_analyze_empty_returns_empty():
    sa = SectionAnalyzer([], _tempo_map())
    assert sa.analyze() == []


def test_analyze_by_silence_splits_on_large_gap():
    notes = [
        make_note(1, 48, 0.0, 0.2, hand="left"),
        make_note(2, 50, 0.3, 0.2, hand="left"),
        make_note(3, 52, 2.5, 0.2, hand="left"),
    ]
    sa = SectionAnalyzer(notes, _tempo_map())
    sections = sa.analyze()
    assert len(sections) == 2


def test_classify_bass_articulation_boundaries():
    tm = _tempo_map()
    stacc = [
        make_note(1, 40, 0.0, 0.1, hand="left"),
        make_note(2, 41, 0.5, 0.1, hand="left"),
    ]
    sa = SectionAnalyzer(stacc, tm)
    assert sa._classify_bass_articulation(stacc) == "staccato"

    lega = [
        make_note(3, 40, 0.0, 0.6, hand="left"),
        make_note(4, 41, 0.5, 0.6, hand="left"),
    ]
    assert sa._classify_bass_articulation(lega) == "legato"


def test_classify_pace_beats_thresholds():
    tm = _tempo_map()
    notes = [make_note(i, 60, i * 0.01, 0.1, hand="right") for i in range(40)]
    sa = SectionAnalyzer(notes, tm)
    assert sa._classify_pace_beats(notes, 0.0, 8.0) == "fast"
    assert sa._classify_pace_beats(notes[:2], 0.0, 8.0) == "slow"


def test_analyze_by_measures_path_with_explicit_signatures():
    notes = [make_note(1, 60, 0.1, 0.2, hand="right"), make_note(2, 62, 3.2, 0.2, hand="right")]
    sa = SectionAnalyzer(notes, _tempo_map(explicit=True))
    sections = sa.analyze()
    assert len(sections) >= 1


def test_detect_grand_pauses_handles_empty_notes():
    sa = SectionAnalyzer([], _tempo_map())
    assert sa._detect_grand_pauses() == [0]


def test_analyze_by_silence_skips_empty_boundaries(monkeypatch):
    notes = [make_note(1, 48, 0.0, 0.2, hand="left")]
    sa = SectionAnalyzer(notes, _tempo_map())
    monkeypatch.setattr(sa, "_detect_grand_pauses", lambda: [0, 0, 1])
    sections = sa._analyze_by_silence()
    assert len(sections) == 1


def test_classify_bass_articulation_single_or_nonpositive_ioi_defaults_legato():
    tm = _tempo_map()
    sa = SectionAnalyzer([], tm)

    single = [make_note(1, 40, 0.0, 0.1, hand="left")]
    assert sa._classify_bass_articulation(single) == "legato"

    same_start = [
        make_note(1, 40, 0.0, 0.2, hand="left"),
        make_note(2, 41, 0.0, 0.2, hand="left"),
    ]
    assert sa._classify_bass_articulation(same_start) == "legato"


def test_classify_bass_articulation_hybrid_branch():
    tm = _tempo_map()
    sa = SectionAnalyzer([], tm)

    notes = [
        make_note(1, 40, 0.0, 0.35, hand="left"),
        make_note(2, 41, 0.5, 0.35, hand="left"),
    ]
    assert sa._classify_bass_articulation(notes) == "hybrid"


def test_classify_pace_zero_or_normal_paths():
    tm = _tempo_map()
    sa = SectionAnalyzer([], tm)
    notes = [make_note(1, 60, 0.0, 0.2, hand="right")]

    assert sa._classify_pace_beats(notes, 1.0, 1.0) == "normal"
    assert sa._classify_pace_beats(notes * 2, 0.0, 2.0) == "normal"


def test_analyze_by_measures_with_empty_measure_uses_prev_style(monkeypatch):
    notes = [
        make_note(1, 40, 0.1, 0.2, hand="left"),
        make_note(2, 41, 2.2, 0.2, hand="left"),
    ]
    sa = SectionAnalyzer(notes, _tempo_map(explicit=True))
    monkeypatch.setattr(
        sa.tempo_map,
        "get_measure_boundaries",
        lambda _t: [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)],
    )

    sections = sa._analyze_by_measures()
    assert len(sections) >= 1
    for s in sections:
        assert s.start_time >= 0
        assert s.end_time > s.start_time
        assert s.articulation_label in ("legato", "staccato", "hybrid")
        assert s.pace_label in ("fast", "slow", "normal")


def test_analyze_by_measures_style_change_splits_sections(monkeypatch):
    notes = [
        make_note(1, 40, 0.1, 0.2, hand="left"),
        make_note(2, 41, 1.1, 0.8, hand="left"),
    ]
    sa = SectionAnalyzer(notes, _tempo_map(explicit=True))
    monkeypatch.setattr(
        sa.tempo_map,
        "get_measure_boundaries",
        lambda _t: [(0.0, 1.0), (1.0, 2.0)],
    )

    orig = sa._classify_bass_articulation
    calls = {"n": 0}

    def wrapped(chunk):
        calls["n"] += 1
        if calls["n"] == 1:
            return "staccato"
        return "legato"

    monkeypatch.setattr(sa, "_classify_bass_articulation", wrapped)
    sections = sa._analyze_by_measures()

    assert len(sections) >= 2
    sa._classify_bass_articulation = orig


def test_analyze_by_silence_handles_empty_slice_notes(monkeypatch):
    sa = SectionAnalyzer([make_note(1, 48, 0.0, 0.2, hand="left")], _tempo_map())

    class _SliceEmpty:
        def __getitem__(self, _idx):
            return []

    sa.notes = cast(Any, _SliceEmpty())
    monkeypatch.setattr(sa, "_detect_grand_pauses", lambda: [0, 1])

    sections = sa._analyze_by_silence()

    assert sections == []


def test_analyze_by_measures_empty_boundaries_falls_back_to_silence():
    """When get_measure_boundaries returns empty, _analyze_by_measures falls back to _analyze_by_silence."""
    tm = TempoMap([(0.0, 500000)], [(0.0, 4, 0)])  # zero denominator → empty boundaries
    notes = [make_note(1, 48, 0.0, 0.2, hand="left")]
    sa = SectionAnalyzer(notes, tm)
    sections = sa._analyze_by_measures()
    assert len(sections) >= 1
