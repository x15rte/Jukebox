from __future__ import annotations

from typing import Any

from models import KeyEvent
from output.output import OutputBackend


class FakeEvent(KeyEvent):
    def __init__(
        self,
        time: float,
        priority: int,
        action: str,
        key_char: str = "",
        pitch: int | None = None,
        velocity: int = 100,
    ):
        super().__init__(time, priority, action, key_char, pitch, velocity)


class FakeBackend(OutputBackend):
    def __init__(self):
        self.calls: list[tuple[str, Any]] = []

    def note_on(self, pitch: int, velocity: int) -> None:
        self.calls.append(("note_on", (pitch, velocity)))

    def note_off(self, pitch: int) -> None:
        self.calls.append(("note_off", pitch))

    def pedal_on(self) -> None:
        self.calls.append(("pedal_on", None))

    def pedal_off(self) -> None:
        self.calls.append(("pedal_off", None))

    def execute_batch(self, events):
        self.calls.append(("execute_batch", list(events)))

    def shutdown(self) -> None:
        self.calls.append(("shutdown", None))


class RecorderBackend(OutputBackend):
    def __init__(self):
        self.calls: list[tuple[Any, ...]] = []

    def note_on(self, pitch, velocity):
        self.calls.append(("note_on", pitch, velocity))

    def note_off(self, pitch):
        self.calls.append(("note_off", pitch))

    def pedal_on(self):
        self.calls.append(("pedal_on",))

    def pedal_off(self):
        self.calls.append(("pedal_off",))

    def shutdown(self):
        self.calls.append(("shutdown",))


class FakeLiveBackend(OutputBackend):
    def __init__(self):
        self.calls: list[tuple[Any, ...]] = []

    def note_on(self, pitch, velocity):
        self.calls.append(("note_on", pitch, velocity))

    def note_off(self, pitch):
        self.calls.append(("note_off", pitch))

    def pedal_on(self):
        self.calls.append(("pedal_on",))

    def pedal_off(self):
        self.calls.append(("pedal_off",))

    def shutdown(self):
        self.calls.append(("shutdown",))


class FakeSignal:
    def __init__(self):
        self._subs: list[Any] = []
        self.emitted: list[tuple[Any, ...]] = []

    def connect(self, fn):
        self._subs.append(fn)

    def emit(self, *args):
        self.emitted.append(args)
        for fn in list(self._subs):
            fn(*args)


class FakeListener:
    def __init__(self, on_press=None):
        self.on_press = on_press
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class FakeInPort:
    def __init__(self, messages=None):
        self._messages = list(messages or [])
        self.closed = False

    def iter_pending(self):
        out = list(self._messages)
        self._messages.clear()
        return out

    def close(self):
        self.closed = True


class _PressedContext:
    def __init__(self, sink: list[tuple[Any, ...]], mods: tuple[Any, ...]):
        self._sink = sink
        self._mods = mods

    def __enter__(self):
        self._sink.append(self._mods)
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeController:
    def __init__(self):
        self.pressed_mods: list[tuple[Any, ...]] = []
        self.presses: list[Any] = []
        self.releases: list[Any] = []

    def pressed(self, *mods):
        return _PressedContext(self.pressed_mods, mods)

    def press(self, key):
        self.presses.append(key)

    def release(self, key):
        self.releases.append(key)


class FakeThread:
    def __init__(self):
        self.started = FakeSignal()
        self._running = False
        self.quit_called = False
        self.wait_calls: list[int | None] = []

    def start(self):
        self._running = True
        self.started.emit()

    def isRunning(self):
        return self._running

    def quit(self):
        self.quit_called = True
        self._running = False

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        self._running = False
        return True


class FakePlaybackPlayer:
    def __init__(self, events, backend, config, total_duration):
        self.events = events
        self.backend = backend
        self.config = config
        self.total_duration = total_duration
        self.playback_finished = FakeSignal()
        self.status_updated = FakeSignal()
        self.progress_updated = FakeSignal()
        self.visualizer_updated = FakeSignal()
        self.stopped = False
        self.stop_calls = 0
        self.paused_toggles = 0
        self.seek_calls: list[Any] = []

    def moveToThread(self, thread):
        self.thread = thread

    def play(self):
        return None

    def stop(self):
        self.stopped = True
        self.stop_calls += 1

    def toggle_pause(self):
        self.paused_toggles += 1

    def seek(self, target):
        self.seek_calls.append(target)
