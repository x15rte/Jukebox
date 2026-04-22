from PyQt6.QtCore import Qt

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
