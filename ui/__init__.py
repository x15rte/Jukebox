"""UI components: visualizer, hotkey management, track selection, MIDI input worker.

Submodules:
- visualizer: PianoWidget, TimelineWidget
- hotkey_manager: HotkeyManager
- track_selection_dialog: TrackSelectionDialog
- midi_input_worker: MidiInputWorker
"""

from .visualizer import PianoWidget, TimelineWidget
from .hotkey_manager import HotkeyManager
from .track_selection_dialog import TrackSelectionDialog
from .midi_input_worker import MidiInputWorker

__all__ = [
    "PianoWidget",
    "TimelineWidget",
    "HotkeyManager",
    "TrackSelectionDialog",
    "MidiInputWorker",
]
