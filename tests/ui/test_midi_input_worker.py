from types import SimpleNamespace

from ui.midi_input_worker import MidiInputWorker


def test_worker_emits_connection_error_and_finished(monkeypatch):
    worker = MidiInputWorker("bad-port")
    errors = []
    finished = []
    worker.connection_error.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))

    monkeypatch.setattr(
        "ui.midi_input_worker.mido.open_input",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    worker.run()

    if not (errors == ["boom"]):
        raise AssertionError("Assertion failed")
    if not (finished == [True]):
        raise AssertionError("Assertion failed")


def test_worker_reads_messages_and_finishes(monkeypatch):
    worker = MidiInputWorker("ok-port")
    received = []
    connected = []
    finished = []

    worker.message_received.connect(received.append)
    worker.connected.connect(lambda: connected.append(True))
    worker.finished.connect(lambda: finished.append(True))

    class Port:
        def __init__(self):
            self.closed = False
            self._count = 0

        def iter_pending(self):
            self._count += 1
            if self._count == 1:
                return [SimpleNamespace(type="note_on", note=60, velocity=100)]
            worker._stop_event.set()
            return []

        def close(self):
            self.closed = True

    port = Port()
    monkeypatch.setattr("ui.midi_input_worker.mido.open_input", lambda *_a, **_k: port)

    worker.run()

    if not (connected == [True]):
        raise AssertionError("Assertion failed")
    if not (len(received) == 1):
        raise AssertionError("Assertion failed")
    if not (getattr(received[0], "note") == 60):
        raise AssertionError("Assertion failed")
    if not (finished == [True]):
        raise AssertionError("Assertion failed")
    if not (port.closed is True):
        raise AssertionError("Assertion failed")


def test_stop_emits_warning_when_close_fails():
    worker = MidiInputWorker("ok-port")
    warnings = []
    worker.warning.connect(warnings.append)

    class Port:
        def close(self):
            raise OSError("close boom")

    worker._inport = Port()
    worker.stop()

    if not (worker._stop_event.is_set() is True):
        raise AssertionError("Assertion failed")
    if not (warnings and "close boom" in warnings[0]):
        raise AssertionError("Assertion failed")


def test_run_emits_connection_error_when_iter_pending_fails(monkeypatch):
    worker = MidiInputWorker("ok-port")
    errors = []
    finished = []
    worker.connection_error.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))

    class Port:
        def iter_pending(self):
            raise RuntimeError("loop boom")

        def close(self):
            return None

    monkeypatch.setattr("ui.midi_input_worker.mido.open_input", lambda *_a, **_k: Port())

    worker.run()

    if not (errors == ["loop boom"]):
        raise AssertionError("Assertion failed")
    if not (finished == [True]):
        raise AssertionError("Assertion failed")


def test_run_emits_warning_when_cleanup_close_fails(monkeypatch):
    worker = MidiInputWorker("ok-port")
    warnings = []
    worker.warning.connect(warnings.append)

    class Port:
        def __init__(self):
            self._once = False

        def iter_pending(self):
            if not self._once:
                self._once = True
                worker._stop_event.set()
            return []

        def close(self):
            raise OSError("cleanup boom")

    monkeypatch.setattr("ui.midi_input_worker.mido.open_input", lambda *_a, **_k: Port())

    worker.run()

    if not (warnings and "cleanup boom" in warnings[0]):
        raise AssertionError("Assertion failed")


def test_run_breaks_inner_loop_when_stop_event_set_during_iteration(monkeypatch):
    worker = MidiInputWorker("ok-port")
    received = []
    worker.message_received.connect(received.append)

    class Port:
        def __init__(self):
            self._calls = 0

        def iter_pending(self):
            self._calls += 1
            if self._calls == 1:
                return [
                    SimpleNamespace(type="note_on", note=60, velocity=100),
                    SimpleNamespace(type="note_on", note=61, velocity=100),
                ]
            worker._stop_event.set()
            return []

        def close(self):
            return None

    port = Port()

    def on_message(_msg):
        worker._stop_event.set()

    worker.message_received.connect(on_message)
    monkeypatch.setattr("ui.midi_input_worker.mido.open_input", lambda *_a, **_k: port)

    worker.run()

    if not (len(received) == 1):
        raise AssertionError("Assertion failed")
    if not (received[0].note == 60):
        raise AssertionError("Assertion failed")
