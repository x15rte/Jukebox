import logging
import sys

import pytest

import logger_core
from logger_core import _JukeboxLogger, JukeboxLogger


def test_set_gui_callback_replaces_existing_callbacks():
    lg = _JukeboxLogger()
    events = []

    def cb1(level, msg):
        events.append(("cb1", level, msg))

    def cb2(level, msg):
        events.append(("cb2", level, msg))

    lg.set_gui_callback(cb1)
    lg.set_gui_callback(cb2)
    lg.info("hello")

    assert len(events) == 1
    assert events[0][0] == "cb2"


def test_add_and_remove_gui_callback_idempotent():
    lg = _JukeboxLogger()
    events = []

    def cb(level, msg):
        events.append((level, msg))

    lg.add_gui_callback(cb)
    lg.add_gui_callback(cb)
    lg.info("a")
    assert len(events) == 1

    lg.remove_gui_callback(cb)
    lg.info("b")
    assert len(events) == 1


def test_clear_gui_callbacks():
    lg = _JukeboxLogger()
    events = []

    def cb(level, msg):
        events.append((level, msg))

    lg.add_gui_callback(cb)
    lg.clear_gui_callbacks()
    lg.info("a")
    assert events == []


def test_callback_count():
    lg = _JukeboxLogger()

    def cb(level, msg):
        pass

    assert lg.callback_count == 0
    lg.add_gui_callback(cb)
    assert lg.callback_count == 1
    lg.add_gui_callback(cb)
    assert lg.callback_count == 1  # idempotent
    lg.remove_gui_callback(cb)
    assert lg.callback_count == 0


def test_current_level_name_default():
    lg = _JukeboxLogger()
    assert lg.current_level_name == "INFO"


def test_current_level_name_after_set():
    lg = _JukeboxLogger()
    lg.set_level("DEBUG")
    assert lg.current_level_name == "DEBUG"
    lg.set_level("WARNING")
    assert lg.current_level_name == "WARNING"


def test_is_file_logging_enabled(tmp_path):
    lg = _JukeboxLogger()
    assert lg.is_file_logging_enabled is False
    p = tmp_path / "x" / "log.txt"
    lg.enable_file_logging(str(p))
    assert lg.is_file_logging_enabled is True
    lg.disable_file_logging()
    assert lg.is_file_logging_enabled is False


def test_set_level_with_unknown_name_defaults_info():
    lg = _JukeboxLogger()
    lg.set_level("not-a-level")
    assert lg._logger.level == logging.INFO


def test_enable_file_logging_empty_path_is_noop():
    lg = _JukeboxLogger()
    lg.enable_file_logging("")
    assert lg._file_handler is None


def test_enable_file_logging_noop_when_same_handler(tmp_path):
    lg = _JukeboxLogger()
    p = tmp_path / "a" / "log.txt"

    lg.enable_file_logging(str(p), max_bytes=111, backup_count=2)
    h1 = lg._file_handler
    lg.enable_file_logging(str(p), max_bytes=111, backup_count=2)

    assert lg._file_handler is h1


def test_enable_file_logging_replaces_old_handler_even_if_close_fails(tmp_path, monkeypatch):
    lg = _JukeboxLogger()
    p1 = tmp_path / "x" / "log1.txt"
    p2 = tmp_path / "x" / "log2.txt"

    lg.enable_file_logging(str(p1))

    def bad_close():
        raise RuntimeError("close failed")

    monkeypatch.setattr(lg._file_handler, "close", bad_close)
    lg.enable_file_logging(str(p2))

    assert lg._file_handler is not None
    assert lg._file_handler.baseFilename.endswith("log2.txt")


def test_disable_file_logging_no_handler_noop():
    lg = _JukeboxLogger()
    lg.disable_file_logging()


def test_disable_file_logging_close_exception_is_swallowed(tmp_path, monkeypatch):
    lg = _JukeboxLogger()
    p = tmp_path / "x" / "log.txt"
    lg.enable_file_logging(str(p))

    def bad_close():
        raise RuntimeError("boom")

    monkeypatch.setattr(lg._file_handler, "close", bad_close)
    lg.disable_file_logging()
    assert lg._file_handler is None


def test_log_exc_info_at_requested_level():
    """BUG-1 guard: log() with exc_info=True must respect the requested level."""
    lg = _JukeboxLogger()
    lg.set_level("DEBUG")
    events = []
    lg.add_gui_callback(lambda level, msg: events.append(level))

    try:
        raise ValueError("x")
    except ValueError:
        lg.log("DEBUG", "msg", exc_info=True)

    assert events == ["DEBUG"]


def test_log_exc_info_no_active_exception():
    """BUG-2 guard: exc_info=True with no active exception produces clean output."""
    lg = _JukeboxLogger()
    events = []
    lg.add_gui_callback(lambda level, msg: events.append(msg))

    # No exception being handled — exc_info should be silently omitted.
    lg.log("ERROR", "clean", exc_info=True)

    assert events == ["clean"]
    assert "NoneType" not in events[0]


def test_log_with_exc_info_appends_traceback_and_notifies_callbacks():
    lg = _JukeboxLogger()
    events = []
    lg.set_level("DEBUG")
    lg.add_gui_callback(lambda level, msg: events.append((level, msg)))

    try:
        raise ValueError("x")
    except ValueError:
        lg.error("problem", exc_info=True)

    assert events
    assert events[0][0] == "ERROR"
    assert "Traceback" in events[0][1]


def test_log_skips_callbacks_when_level_disabled():
    lg = _JukeboxLogger()
    events = []
    lg.set_level("ERROR")
    lg.add_gui_callback(lambda level, msg: events.append((level, msg)))

    lg.info("hello")
    assert events == []


def test_log_callback_exception_does_not_break_logging():
    lg = _JukeboxLogger()
    calls = {"ok": 0}

    def bad_cb(_level, _msg):
        raise RuntimeError("cb boom")

    def ok_cb(_level, _msg):
        calls["ok"] += 1

    lg.set_level("DEBUG")
    lg.add_gui_callback(bad_cb)
    lg.add_gui_callback(ok_cb)

    lg.info("hello")
    assert calls["ok"] == 1


def test_info_exc_info():
    """exc_info on info() convenience method."""
    lg = _JukeboxLogger()
    events = []
    lg.add_gui_callback(lambda level, msg: events.append((level, msg)))

    try:
        raise ValueError("x")
    except ValueError:
        lg.info("msg", exc_info=True)

    assert events[0][0] == "INFO"
    assert "Traceback" in events[0][1]


def test_warning_exc_info():
    """exc_info on warning() convenience method."""
    lg = _JukeboxLogger()
    events = []
    lg.add_gui_callback(lambda level, msg: events.append((level, msg)))

    try:
        raise ValueError("x")
    except ValueError:
        lg.warning("msg", exc_info=True)

    assert events[0][0] == "WARNING"
    assert "Traceback" in events[0][1]


def test_debug_exc_info():
    """exc_info on debug() convenience method."""
    lg = _JukeboxLogger()
    lg.set_level("DEBUG")
    events = []
    lg.add_gui_callback(lambda level, msg: events.append((level, msg)))

    try:
        raise ValueError("x")
    except ValueError:
        lg.debug("msg", exc_info=True)

    assert events[0][0] == "DEBUG"
    assert "Traceback" in events[0][1]


def test_critical_logs_at_critical():
    lg = _JukeboxLogger()
    events = []
    lg.set_level("DEBUG")
    lg.add_gui_callback(lambda level, msg: events.append((level, msg)))

    lg.critical("boom")
    assert events[0][0] == "CRITICAL"


def test_critical_exc_info():
    lg = _JukeboxLogger()
    events = []
    lg.set_level("DEBUG")
    lg.add_gui_callback(lambda level, msg: events.append((level, msg)))

    try:
        raise ValueError("x")
    except ValueError:
        lg.critical("boom", exc_info=True)

    assert events[0][0] == "CRITICAL"
    assert "Traceback" in events[0][1]


def test_exception_convenience():
    """exception() logs at ERROR with traceback."""
    lg = _JukeboxLogger()
    events = []
    lg.set_level("DEBUG")
    lg.add_gui_callback(lambda level, msg: events.append((level, msg)))

    try:
        raise ValueError("x")
    except ValueError:
        lg.exception("boom")

    assert events[0][0] == "ERROR"
    assert "Traceback" in events[0][1]


def test_repr():
    lg = _JukeboxLogger()
    r = repr(lg)
    assert "JukeboxLogger" in r
    assert "INFO" in r
    assert "callbacks=0" in r
    assert "file_logging=off" in r


def test_public_class_name():
    """Both old private name and new public name work."""
    assert JukeboxLogger is _JukeboxLogger


def test_unicode_stderr_does_not_crash(monkeypatch):
    """Edge case: Unicode characters that don't fit the console codepage."""
    lg = _JukeboxLogger()
    # Replace stderr with a mock that can't handle Unicode.
    class NarrowStream:
        encoding = "ascii"

        def write(self, s):
            # Simulate cp437-like narrow encoding — will be set to 'replace'
            pass

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stderr", NarrowStream())
    # Recreate the logger so the handler picks up the narrow stream.
    lg2 = _JukeboxLogger()
    lg2.set_level("DEBUG")
    # This should not raise even though the stream is ASCII-only.
    lg2.info("Unicode test: ☃ é 中文")
    # Verify the handler has errors='replace' for safety.
    h = lg2._logger.handlers[0]
    stream = getattr(h, "stream", None)
    assert stream is None or getattr(stream, "errors", "") in ("replace",)


def test_global_singleton_has_expected_type():
    assert isinstance(logger_core.jukebox_logger, _JukeboxLogger)
