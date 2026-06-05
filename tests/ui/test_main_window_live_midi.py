from types import SimpleNamespace
from typing import Any, cast

from output import OutputBackendSendError, OutputBackendUnavailableError
from tests.helpers.fakes import FakeLiveBackend, FakeSignal, FakeThread


def test_handle_live_midi_message_routes_to_backend(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    backend = FakeLiveBackend()
    w.live_backend = backend

    w._handle_live_midi_message(SimpleNamespace(type="note_on", note=60, velocity=90))
    w._handle_live_midi_message(SimpleNamespace(type="note_on", note=60, velocity=0))
    w._handle_live_midi_message(SimpleNamespace(type="note_off", note=61, velocity=0))
    w._handle_live_midi_message(SimpleNamespace(type="control_change", control=64, value=127))
    w._handle_live_midi_message(SimpleNamespace(type="control_change", control=64, value=0))

    assert backend.calls[0] == ("note_on", 60, 90)
    assert backend.calls[1] == ("note_off", 60)
    assert backend.calls[2] == ("note_off", 61)
    assert backend.calls[3] == ("pedal_on",)
    assert backend.calls[4] == ("pedal_off",)


def test_on_midi_input_finished_resets_state(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    w.midi_input_active = True
    w.midi_input_thread = object()
    w.midi_input_worker = object()

    w._on_midi_input_finished()

    assert w.midi_input_active is False
    assert w.midi_input_thread is None
    assert w.midi_input_worker is None
    assert w.midi_input_connect_btn.isEnabled() is True
    assert w.midi_input_disconnect_btn.isEnabled() is False


def test_on_input_mode_changed_piano_and_back(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    refresh_calls = []
    disconnect_calls = []
    monkeypatch.setattr(w, "_refresh_midi_inputs", lambda show_dialog=True: refresh_calls.append(show_dialog))
    monkeypatch.setattr(w, "_disconnect_midi_input", lambda: disconnect_calls.append(True))

    w.input_mode_piano_radio.setChecked(True)
    w._on_input_mode_changed()
    assert refresh_calls

    w.midi_input_active = True
    w.input_mode_file_radio.setChecked(True)
    w._on_input_mode_changed()
    assert len(disconnect_calls) >= 1


def test_refresh_midi_inputs_populates_combo(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    monkeypatch.setattr("main_window.mido.get_input_names", lambda: ["A", "B"])

    w._refresh_midi_inputs()

    assert w.midi_input_combo.count() == 2
    assert w.midi_input_combo.itemText(0) == "A"


def test_connect_midi_input_no_device_and_running_playback_stops_first(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    events = []

    class Ctrl:
        is_running = True

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    monkeypatch.setattr(w, "handle_stop", lambda: events.append(("stop", None)))
    monkeypatch.setattr(w, "_log_warning", lambda m: events.append(("warn", m)))
    monkeypatch.setattr("main_window.QMessageBox.warning", lambda *a, **k: events.append(("dialog", None)))
    monkeypatch.setattr(w.midi_input_combo, "currentText", lambda: "")

    w._connect_midi_input()

    assert ("stop", None) in events
    assert any(e[0] == "warn" for e in events)
    assert ("dialog", None) in events


def test_disconnect_midi_input_handles_worker_stop_exception(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    logs = []

    class Worker:
        def stop(self):
            raise RuntimeError("stop fail")

    class Thread:
        def quit(self):
            logs.append("quit")

        def wait(self, _timeout=None):
            logs.append("wait")

    w.midi_input_active = True
    w.midi_input_worker = Worker()
    w.midi_input_thread = Thread()
    monkeypatch.setattr(w, "add_log_message", lambda m: logs.append(m))
    monkeypatch.setattr(w, "_release_all_live_keys", lambda: logs.append("release_all"))

    w._disconnect_midi_input()

    assert any("Error stopping MIDI input worker" in str(x) for x in logs)
    assert "quit" in logs
    assert "wait" in logs
    assert "release_all" in logs


def test_on_midi_input_error_and_warning_routes_to_loggers(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    errors = []
    warnings = []
    monkeypatch.setattr(w, "_log_error", lambda m, **k: errors.append(m))
    monkeypatch.setattr(w, "_log_warning", lambda m: warnings.append(m))

    w._on_midi_input_error("boom")
    w._on_midi_input_warning("careful")

    assert errors == ["MIDI input connection failed: boom"]
    assert warnings == ["MIDI input worker: careful"]


def test_connect_midi_input_when_already_active_noop(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    w.midi_input_active = True
    called = []
    monkeypatch.setattr("main_window.create_backend", lambda *a, **k: called.append(True))

    w._connect_midi_input()

    assert called == []


def test_refresh_midi_inputs_exception_path(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    errs = []
    monkeypatch.setattr(
        "main_window.mido.get_input_names",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(w, "_log_error", lambda m, **k: errs.append((m, k)))

    w._refresh_midi_inputs(show_dialog=False)

    assert errs and "Failed to list MIDI input devices" in errs[0][0]
    assert errs[0][1].get("show_dialog") is False


def test_release_all_live_keys_no_backend_noop(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    w.live_backend = None
    w._release_all_live_keys()


def test_on_key_layout_changed_recreates_backend_when_active(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    old = FakeLiveBackend()
    new = FakeLiveBackend()
    w.live_backend = old
    w.midi_input_active = True
    monkeypatch.setattr("main_window.create_backend", lambda *a, **k: new)

    w._on_key_layout_changed(True)

    assert ("shutdown",) in old.calls
    assert w.live_backend is new


def test_on_output_mode_changed_recreates_backend_when_active(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    old = FakeLiveBackend()
    new = FakeLiveBackend()
    w.live_backend = old
    w.midi_input_active = True
    monkeypatch.setattr("main_window.create_backend", lambda *a, **k: new)

    idx = w.output_mode_combo.findData("midi_numpad")
    w.output_mode_combo.setCurrentIndex(idx)

    w._on_output_mode_changed()

    assert ("shutdown",) in old.calls
    assert w.live_backend is new


def test_on_input_mode_changed_forces_tab_zero_from_visualizer(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    monkeypatch.setattr(w, "_refresh_midi_inputs", lambda show_dialog=True: None)

    class FakeTabs:
        def __init__(self):
            self.enabled: dict[int, bool] = {}
            self.index = 1  # Visualizer tab (index 1 in new layout)

        def setTabEnabled(self, idx, enabled):
            self.enabled[idx] = enabled

        def currentIndex(self):
            return self.index

        def setCurrentIndex(self, idx):
            self.index = idx

    tabs = FakeTabs()
    w.tabs = tabs
    w.input_mode_piano_radio.setChecked(True)
    w._on_input_mode_changed()

    assert tabs.enabled[1] is False  # Visualizer tab disabled
    assert tabs.enabled[2] is False  # Humanization tab disabled
    assert tabs.index == 0


def test_connect_midi_input_success_path(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    events = []

    class Ctrl:
        is_running = False

        def stop_and_wait(self, timeout_ms=None):
            return None

    class Worker:
        def __init__(self, name):
            self.name = name
            self.message_received = FakeSignal()
            self.connected = FakeSignal()
            self.connection_error = FakeSignal()
            self.warning = FakeSignal()
            self.finished = FakeSignal()

        def moveToThread(self, thread):
            self.thread = thread

        def run(self):
            return None

        def stop(self):
            return None

    w.playback_controller = Ctrl()
    w.midi_input_combo.clear()
    w.midi_input_combo.addItem("P1")
    monkeypatch.setattr("main_window.QThread", FakeThread)
    monkeypatch.setattr("main_window.MidiInputWorker", Worker)
    monkeypatch.setattr("main_window.create_backend", lambda *a, **k: FakeLiveBackend())

    w._connect_midi_input()

    assert w.midi_input_active is True
    assert w.midi_input_connect_btn.isEnabled() is False
    assert w.midi_input_disconnect_btn.isEnabled() is True
    assert "Connecting to: P1" in w.midi_input_status_label.text()


def test_connect_midi_input_backend_unavailable_does_not_start_worker(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    errors = []

    class Ctrl:
        is_running = False

        def stop_and_wait(self, timeout_ms=None):
            return None

    def unavailable(*_args, **_kwargs):
        raise OutputBackendUnavailableError("pydirectinput missing")

    w.playback_controller = Ctrl()
    w.midi_input_combo.clear()
    w.midi_input_combo.addItem("P1")
    monkeypatch.setattr("main_window.create_backend", unavailable)
    monkeypatch.setattr(w, "_log_error", lambda m, **k: errors.append((m, k)))

    w._connect_midi_input()

    assert w.midi_input_active is False
    assert w.midi_input_thread is None
    assert w.midi_input_worker is None
    assert w.midi_input_connect_btn.isEnabled() is True
    assert w.midi_input_disconnect_btn.isEnabled() is False
    assert any("MIDI input could not start" in message for message, _ in errors)
    assert errors[0][1]["show_dialog"] is True


def test_on_midi_input_connected_updates_ui_and_log(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    events = []
    monkeypatch.setattr(w, "add_log_message", lambda m: events.append(m))

    w._on_midi_input_connected("My Device")

    assert w.midi_input_status_label.text() == "Connected to: My Device"
    assert any("Connected to MIDI input: My Device" in e for e in events)


def test_disconnect_midi_input_inactive_noop(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    w.midi_input_active = False

    w._disconnect_midi_input()


def test_handle_live_midi_message_guard_paths(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    w.live_backend = None
    w._handle_live_midi_message(SimpleNamespace(type="note_on", note=60, velocity=90))

    w.live_backend = FakeLiveBackend()
    w._handle_live_midi_message(SimpleNamespace(type="control_change", control=1, value=127))


def test_handle_live_midi_message_output_error_is_visible_and_disconnects(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    errors = []
    disconnects = []

    class BadBackend(FakeLiveBackend):
        def note_on(self, pitch, velocity):
            raise OutputBackendSendError("send failed")

    w.live_backend = BadBackend()
    monkeypatch.setattr(w, "_log_error", lambda m, **k: errors.append((m, k)))
    monkeypatch.setattr(w, "_disconnect_midi_input", lambda: disconnects.append(True))

    w._handle_live_midi_message(SimpleNamespace(type="note_on", note=60, velocity=90))

    assert any("Live MIDI output failed" in message for message, _ in errors)
    assert errors[0][1]["show_dialog"] is True
    assert disconnects == [True]


def test_handle_live_midi_message_missing_note_is_ignored(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    backend = FakeLiveBackend()
    w.live_backend = backend

    w._handle_live_midi_message(SimpleNamespace(type="note_on", velocity=90))
    w._handle_live_midi_message(SimpleNamespace(type="note_off", velocity=0))

    assert backend.calls == []


def test_live_midi_backend_recreation_workflow(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    backends = [FakeLiveBackend(), FakeLiveBackend(), FakeLiveBackend()]

    class Ctrl:
        is_running = False

        def stop_and_wait(self, timeout_ms=None):
            return None

    class Worker:
        def __init__(self, name):
            self.name = name
            self.message_received = FakeSignal()
            self.connected = FakeSignal()
            self.connection_error = FakeSignal()
            self.warning = FakeSignal()
            self.finished = FakeSignal()
            self.stop_calls = 0

        def moveToThread(self, thread):
            self.thread = thread

        def run(self):
            return None

        def stop(self):
            self.stop_calls += 1

    w.playback_controller = Ctrl()
    w.midi_input_combo.clear()
    w.midi_input_combo.addItem("P1")
    monkeypatch.setattr("main_window.QThread", FakeThread)
    monkeypatch.setattr("main_window.MidiInputWorker", Worker)
    monkeypatch.setattr("main_window.create_backend", lambda *a, **k: backends.pop(0))

    w._connect_midi_input()
    backend_a = w.live_backend
    assert backend_a is not None

    w._handle_live_midi_message(SimpleNamespace(type="note_on", note=60, velocity=90))

    idx = w.output_mode_combo.findData("midi_numpad")
    w.output_mode_combo.setCurrentIndex(idx)

    backend_b = w.live_backend
    assert backend_b is not None
    assert backend_b is not backend_a

    w._handle_live_midi_message(SimpleNamespace(type="note_off", note=60, velocity=0))
    w._disconnect_midi_input()

    assert ("note_on", 60, 90) in backend_a.calls
    assert ("shutdown",) in backend_a.calls
    assert ("note_off", 60) in backend_b.calls
    assert ("shutdown",) in backend_b.calls
    assert w.midi_input_worker.stop_calls == 1
    assert w.midi_input_thread.quit_called is True
    assert w.midi_input_thread.wait_calls[-1] == 2000


def test_live_midi_output_mode_recreate_failure_disconnects(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    errors = []
    disconnects = []
    backend = FakeLiveBackend()
    w.live_backend = backend
    w.midi_input_active = True

    def unavailable(*_args, **_kwargs):
        raise OutputBackendUnavailableError("pydirectinput missing")

    monkeypatch.setattr("main_window.create_backend", unavailable)
    monkeypatch.setattr(w, "_log_error", lambda m, **k: errors.append((m, k)))
    monkeypatch.setattr(w, "_disconnect_midi_input", lambda: disconnects.append(True))

    w._on_output_mode_changed()

    assert ("shutdown",) in backend.calls
    assert w.live_backend is None
    assert any("MIDI input output unavailable" in message for message, _ in errors)
    assert disconnects == [True]


def test_live_midi_key_layout_recreate_failure_disconnects(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    errors = []
    disconnects = []
    backend = FakeLiveBackend()
    w.live_backend = backend
    w.midi_input_active = True

    def unavailable(*_args, **_kwargs):
        raise OutputBackendUnavailableError("pydirectinput missing")

    monkeypatch.setattr("main_window.create_backend", unavailable)
    monkeypatch.setattr(w, "_log_error", lambda m, **k: errors.append((m, k)))
    monkeypatch.setattr(w, "_disconnect_midi_input", lambda: disconnects.append(True))

    w._on_key_layout_changed()

    assert ("shutdown",) in backend.calls
    assert w.live_backend is None
    assert any("MIDI input output unavailable" in message for message, _ in errors)
    assert disconnects == [True]
