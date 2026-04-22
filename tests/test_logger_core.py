import logging

import pytest

import logger_core
from logger_core import _JukeboxLogger


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

    if not (len(events) == 1):
        raise AssertionError("Assertion failed")
    if not (events[0][0] == "cb2"):
        raise AssertionError("Assertion failed")


def test_add_and_remove_gui_callback_idempotent():
    lg = _JukeboxLogger()
    events = []

    def cb(level, msg):
        events.append((level, msg))

    lg.add_gui_callback(cb)
    lg.add_gui_callback(cb)
    lg.info("a")
    if not (len(events) == 1):
        raise AssertionError("Assertion failed")

    lg.remove_gui_callback(cb)
    lg.info("b")
    if not (len(events) == 1):
        raise AssertionError("Assertion failed")


def test_set_level_with_unknown_name_defaults_info():
    lg = _JukeboxLogger()
    lg.set_level("not-a-level")
    if not (lg._logger.level == logging.INFO):
        raise AssertionError("Assertion failed")


def test_enable_file_logging_noop_when_same_handler(tmp_path):
    lg = _JukeboxLogger()
    p = tmp_path / "a" / "log.txt"

    lg.enable_file_logging(str(p), max_bytes=111, backup_count=2)
    h1 = lg._file_handler
    lg.enable_file_logging(str(p), max_bytes=111, backup_count=2)

    if not (lg._file_handler is h1):
        raise AssertionError("Assertion failed")


def test_enable_file_logging_replaces_old_handler_even_if_close_fails(tmp_path, monkeypatch):
    lg = _JukeboxLogger()
    p1 = tmp_path / "x" / "log1.txt"
    p2 = tmp_path / "x" / "log2.txt"

    lg.enable_file_logging(str(p1))

    def bad_close():
        raise RuntimeError("close failed")

    monkeypatch.setattr(lg._file_handler, "close", bad_close)
    lg.enable_file_logging(str(p2))

    if not (lg._file_handler is not None):
        raise AssertionError("Assertion failed")
    if not (lg._file_handler.baseFilename.endswith("log2.txt")):
        raise AssertionError("Assertion failed")


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
    if not (lg._file_handler is None):
        raise AssertionError("Assertion failed")


def test_log_with_exc_info_appends_traceback_and_notifies_callbacks():
    lg = _JukeboxLogger()
    events = []
    lg.set_level("DEBUG")
    lg.add_gui_callback(lambda level, msg: events.append((level, msg)))

    try:
        raise ValueError("x")
    except ValueError:
        lg.error("problem", exc_info=True)

    if not (events):
        raise AssertionError("Assertion failed")
    if not (events[0][0] == "ERROR"):
        raise AssertionError("Assertion failed")
    if not ("Traceback" in events[0][1]):
        raise AssertionError("Assertion failed")


def test_log_skips_callbacks_when_level_disabled():
    lg = _JukeboxLogger()
    events = []
    lg.set_level("ERROR")
    lg.add_gui_callback(lambda level, msg: events.append((level, msg)))

    lg.info("hello")
    if not (events == []):
        raise AssertionError("Assertion failed")


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
    if not (calls["ok"] == 1):
        raise AssertionError("Assertion failed")


def test_global_singleton_has_expected_type():
    if not (isinstance(logger_core.jukebox_logger, _JukeboxLogger)):
        raise AssertionError("Assertion failed")
