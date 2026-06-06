"""Tests for TrackSelectionDialog: track selection, role assignment, edge cases."""
from __future__ import annotations

from PyQt6.QtCore import Qt

from models import MidiTrack
from tests.helpers.builders import make_note
from ui.track_selection_dialog import TrackSelectionDialog


def _make_track(
    index: int,
    name: str,
    is_drum: bool,
    *,
    note_count: int = 1,
) -> MidiTrack:
    notes = [make_note(i, 60, float(i) * 0.1, 0.2) for i in range(note_count)]
    return MidiTrack(index, name, 0, is_drum, notes)


def test_default_selection_drum_unchecked_piano_checked(qtbot):
    tracks = [
        _make_track(0, "Piano", False),
        _make_track(1, "Drums", True),
    ]
    dlg = TrackSelectionDialog(tracks)
    qtbot.addWidget(dlg)

    assert dlg.checkboxes[0].checkState() == Qt.CheckState.Checked
    assert dlg.checkboxes[1].checkState() == Qt.CheckState.Unchecked

    sel = dlg.get_selection()
    assert len(sel) == 1
    assert sel[0][0].name == "Piano"


def test_get_selection_includes_role_string(qtbot):
    """The second element of each selection tuple is the role combo text."""
    tracks = [_make_track(0, "Piano", False)]
    dlg = TrackSelectionDialog(tracks)
    qtbot.addWidget(dlg)

    sel = dlg.get_selection()
    assert len(sel) == 1
    # Default role is "Auto-Detect"
    assert sel[0][1] == "Auto-Detect"


def test_get_selection_all_tracks_checked(qtbot):
    tracks = [
        _make_track(0, "Piano", False),
        _make_track(1, "Melody", False),
        _make_track(2, "Bass", False),
    ]
    dlg = TrackSelectionDialog(tracks)
    qtbot.addWidget(dlg)

    sel = dlg.get_selection()
    assert len(sel) == 3


def test_get_selection_all_unchecked_returns_empty(qtbot):
    """Manually uncheck all tracks and verify empty selection."""
    tracks = [
        _make_track(0, "Piano", False),
    ]
    dlg = TrackSelectionDialog(tracks)
    qtbot.addWidget(dlg)

    dlg.checkboxes[0].setCheckState(Qt.CheckState.Unchecked)
    sel = dlg.get_selection()
    assert len(sel) == 0


def test_combo_box_has_expected_items(qtbot):
    tracks = [_make_track(0, "Piano", False)]
    dlg = TrackSelectionDialog(tracks)
    qtbot.addWidget(dlg)

    for i in range(len(tracks)):
        combo = dlg.table.cellWidget(i, 4)
        assert combo is not None
        assert combo.count() == 3
        assert combo.itemText(0) == "Auto-Detect"
        assert combo.itemText(1) == "Left Hand"
        assert combo.itemText(2) == "Right Hand"


def test_empty_track_list(qtbot):
    """Dialog should handle zero tracks without crashing."""
    dlg = TrackSelectionDialog([])
    qtbot.addWidget(dlg)

    sel = dlg.get_selection()
    assert len(sel) == 0


def test_single_track(qtbot):
    track = _make_track(0, "Solo", False)
    dlg = TrackSelectionDialog([track])
    qtbot.addWidget(dlg)

    sel = dlg.get_selection()
    assert len(sel) == 1
    assert sel[0][0].name == "Solo"


def test_all_drum_tracks_start_unchecked(qtbot):
    tracks = [
        _make_track(0, "Drums1", True),
        _make_track(1, "Drums2", True),
    ]
    dlg = TrackSelectionDialog(tracks)
    qtbot.addWidget(dlg)

    for cb in dlg.checkboxes:
        assert cb.checkState() == Qt.CheckState.Unchecked

    sel = dlg.get_selection()
    assert len(sel) == 0


def test_table_column_count(qtbot):
    tracks = [_make_track(0, "Piano", False)]
    dlg = TrackSelectionDialog(tracks)
    qtbot.addWidget(dlg)

    assert dlg.table.columnCount() == 5
