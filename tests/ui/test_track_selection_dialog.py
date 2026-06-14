from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog

from models import MidiTrack
from tests.helpers.builders import make_note
from ui.track_selection_dialog import TrackSelectionDialog


def test_track_selection_dialog_defaults_and_get_selection(qtbot):
    tracks = [
        MidiTrack(0, "Piano", 0, False, [make_note(1, 60, 0.0, 0.2)]),
        MidiTrack(1, "Drums", 0, True, [make_note(2, 36, 0.0, 0.2)]),
    ]
    dlg = TrackSelectionDialog(tracks)
    qtbot.addWidget(dlg)

    assert dlg.checkboxes[0].checkState() == Qt.CheckState.Checked
    assert dlg.checkboxes[1].checkState() == Qt.CheckState.Unchecked

    sel = dlg.get_selection()
    assert len(sel) == 1
    assert sel[0][0].name == "Piano"

def test_track_selection_dialog_cancel_returns_empty(qtbot):
    tracks = [
        MidiTrack(0, "Piano", 0, False, [make_note(1, 60, 0.0, 0.2)]),
        MidiTrack(1, "Drums", 0, True, [make_note(2, 36, 0.0, 0.2)]),
    ]
    dlg = TrackSelectionDialog(tracks)
    qtbot.addWidget(dlg)

    # Uncheck default-checked track, then reject
    dlg.checkboxes[0].setCheckState(Qt.CheckState.Unchecked)
    dlg.reject()
    assert dlg.result() == QDialog.DialogCode.Rejected

    sel = dlg.get_selection()
    assert sel == []


def test_track_selection_dialog_multi_select_all(qtbot):
    tracks = [
        MidiTrack(0, "Piano", 0, False, [make_note(1, 60, 0.0, 0.2)]),
        MidiTrack(1, "Guitar", 0, False, [make_note(2, 64, 0.0, 0.2)]),
        MidiTrack(2, "Drums", 0, True, [make_note(3, 36, 0.0, 0.2)]),
    ]
    dlg = TrackSelectionDialog(tracks)
    qtbot.addWidget(dlg)

    dlg.checkboxes[0].setCheckState(Qt.CheckState.Checked)
    dlg.checkboxes[1].setCheckState(Qt.CheckState.Checked)
    sel = dlg.get_selection()
    assert len(sel) == 2
    assert sel[0][0].name == "Piano"
    assert sel[1][0].name == "Guitar"

    dlg.checkboxes[2].setCheckState(Qt.CheckState.Checked)
    sel = dlg.get_selection()
    assert len(sel) == 3


def test_track_selection_dialog_hand_role_assignment(qtbot):
    tracks = [
        MidiTrack(0, "Piano", 0, False, [make_note(1, 60, 0.0, 0.2)]),
    ]
    dlg = TrackSelectionDialog(tracks)
    qtbot.addWidget(dlg)

    dlg.role_combos[0].setCurrentText("Left Hand")
    sel = dlg.get_selection()
    assert sel[0][1] == "Left Hand"

    dlg.role_combos[0].setCurrentText("Right Hand")
    sel = dlg.get_selection()
    assert sel[0][1] == "Right Hand"

    dlg.role_combos[0].setCurrentText("Auto-Detect")
    sel = dlg.get_selection()
    assert sel[0][1] == "Auto-Detect"
