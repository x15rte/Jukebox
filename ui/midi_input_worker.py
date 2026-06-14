"""MIDI input worker: reads MIDI messages from a hardware input port on a background thread."""

from __future__ import annotations

import threading

import mido
from PyQt6.QtCore import QObject, pyqtSignal as Signal

from logger_core import jukebox_logger


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
            self._inport = mido.open_input(self._port)  # pyright: ignore[reportAttributeAccessIssue]
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
                    self.warning.emit(
                        f"Failed to close MIDI input port during cleanup: {e}"
                    )
                self._inport = None
        self.finished.emit()
