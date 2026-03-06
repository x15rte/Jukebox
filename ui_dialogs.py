"""UI components used by the main window: track selection dialog, hotkey manager, MIDI input worker."""

from __future__ import annotations

import threading
from pynput import keyboard
from pynput.keyboard import Key, KeyCode
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QDialogButtonBox, QComboBox,
)
from PyQt6.QtCore import QObject, pyqtSignal as Signal, Qt
import mido

from models import MidiTrack


def parse_hotkey_string(s: str | None) -> Key | KeyCode:
    """Parse config string to pynput Key or KeyCode (special key name or single char); default Key.f6."""
    if not s or not isinstance(s, str):
        return Key.f6
    s = s.strip().lower()
    special = getattr(Key, s, None)
    if special is not None:
        return special
    if len(s) == 1:
        try:
            return KeyCode.from_char(s)
        except Exception:
            return Key.f6
    return Key.f6


class HotkeyManager(QObject):
    """Global hotkey listener: current_key triggers toggle; start_binding() captures next key and emits bound_updated."""
    toggle_requested = Signal()
    bound_updated = Signal(str)

    def __init__(self):
        super().__init__()
        self.current_key = Key.f6
        self.listener = None
        self.listening_for_bind = False
        self._start_listener()

    def _start_listener(self):
        self.listener = keyboard.Listener(on_press=self.on_press)
        self.listener.start()

    def _format_key_string(self, key):
        if hasattr(key, "char") and key.char:
            return key.char
        return str(key).replace("Key.", "")

    def on_press(self, key):
        if self.listening_for_bind:
            self.current_key = key
            self.listening_for_bind = False
            self.bound_updated.emit(self._format_key_string(key))
            return
        if key == self.current_key:
            self.toggle_requested.emit()

    def start_binding(self):
        self.listening_for_bind = True


class TrackSelectionDialog(QDialog):
    """Table of tracks with Play checkbox and Hand (Auto/Left/Right); get_selection() returns (track, role) for checked rows."""

    def __init__(self, tracks: list[MidiTrack], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Tracks & Assign Hands")
        self.resize(700, 400)
        self.tracks = tracks
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        info_label = QLabel("Select the tracks you want to play. You can also manually assign hands to specific tracks.")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Play", "Track Name", "Instrument", "Notes", "Hand Assignment"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        self.table.setRowCount(len(self.tracks))
        self.checkboxes = []
        self.role_combos = []

        for i, track in enumerate(self.tracks):
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check_state = Qt.CheckState.Unchecked if track.is_drum else Qt.CheckState.Checked
            check_item.setCheckState(check_state)
            self.table.setItem(i, 0, check_item)
            self.checkboxes.append(check_item)

            name_item = QTableWidgetItem(track.name)
            name_font = name_item.font()
            name_font.setFamily("Segoe UI Emoji")
            name_item.setFont(name_font)
            self.table.setItem(i, 1, name_item)

            self.table.setItem(i, 2, QTableWidgetItem(track.instrument_name))
            self.table.setItem(i, 3, QTableWidgetItem(str(track.note_count)))
            combo = QComboBox()
            combo.addItems(["Auto-Detect", "Left Hand", "Right Hand"])
            self.table.setCellWidget(i, 4, combo)
            self.role_combos.append(combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_selection(self):
        result = []
        for i, track in enumerate(self.tracks):
            if self.checkboxes[i].checkState() == Qt.CheckState.Checked:
                role = self.role_combos[i].currentText()
                result.append((track, role))
        return result


class MidiInputWorker(QObject):
    """Reads MIDI messages from a hardware input port on a background thread."""
    message_received = Signal(object)
    connected = Signal()
    connection_error = Signal(str)
    warning = Signal(str)
    finished = Signal()

    def __init__(self, port: str):
        super().__init__()
        self._port = port
        self._inport = None
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()
        port = self._inport
        if port is not None:
            try:
                port.close()
            except OSError as e:
                self.warning.emit(f"Failed to close MIDI input port: {e}")

    def run(self):
        try:
            self._inport = mido.open_input(self._port)
        except Exception as e:
            self.connection_error.emit(str(e))
            self.finished.emit()
            return
        self.connected.emit()
        try:
            while not self._stop_event.is_set():
                for msg in self._inport.iter_pending():
                    if self._stop_event.is_set():
                        break
                    self.message_received.emit(msg)
                self._stop_event.wait(0.005)
        except Exception as e:
            self.connection_error.emit(str(e))
        finally:
            if self._inport is not None:
                try:
                    self._inport.close()
                except OSError as e:
                    self.warning.emit(f"Failed to close MIDI input port during cleanup: {e}")
                self._inport = None
        self.finished.emit()
