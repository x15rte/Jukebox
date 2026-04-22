from types import SimpleNamespace
from typing import Any, cast

import pytest

from config_repository import ConfigRepository, ConfigLoadError
from main_window import MainWindow
from tests.helpers.builders import make_note
from tests.helpers.fakes import FakeSignal, FakeThread

MainWindow = cast(Any, MainWindow)


class FakeLiveBackend:
    def __init__(self):
        self.calls = []

    def note_on(self, note, vel):
        self.calls.append(("note_on", note, vel))

    def note_off(self, note):
        self.calls.append(("note_off", note))

    def pedal_on(self):
        self.calls.append(("pedal_on",))

    def pedal_off(self):
        self.calls.append(("pedal_off",))

    def shutdown(self):
        self.calls.append(("shutdown",))



def _make_window(qtbot, monkeypatch, tmp_path) -> Any:
    repo = ConfigRepository(config_dir=tmp_path)
    monkeypatch.setattr("main_window.ConfigRepository", lambda: repo)
    monkeypatch.setattr("main_window.QTimer.singleShot", lambda *_a, **_k: None)
    w = cast(Any, MainWindow(app_version="test"))
    qtbot.addWidget(w)
    return w


def test_init_raises_runtime_error_on_invalid_config_bindings(
    qtbot, monkeypatch, tmp_path
):
    repo = ConfigRepository(config_dir=tmp_path)
    monkeypatch.setattr("main_window.ConfigRepository", lambda: repo)
    monkeypatch.setattr("main_window.QTimer.singleShot", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "main_window.validate_config_ui_bindings",
        lambda: (_ for _ in ()).throw(ValueError("broken bindings")),
    )

    with pytest.raises(RuntimeError, match="Invalid config UI bindings: broken bindings"):
        MainWindow(app_version="test")


def test_set_current_file_labels_updates_widgets(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    w._set_current_file_labels("C:/tmp/song.mid")
    assert w.file_path_label.text() == "song.mid"
    assert w.current_file_bottom_label.text() == "song.mid"

    w._set_current_file_labels(None)
    assert w.file_path_label.text() == "No file selected."


def test_handle_live_midi_message_routes_to_backend(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
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


def test_gather_config_without_tracks_shows_warning(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    warnings = []
    monkeypatch.setattr(w, "_log_error", lambda *a, **k: None)
    monkeypatch.setattr("main_window.QMessageBox.warning", lambda *a, **k: warnings.append(True))

    cfg = w.gather_config()
    assert cfg is None
    assert warnings == [True]


def test_on_midi_input_finished_resets_state(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    w.midi_input_active = True
    w.midi_input_thread = object()
    w.midi_input_worker = object()

    w._on_midi_input_finished()

    assert w.midi_input_active is False
    assert w.midi_input_thread is None
    assert w.midi_input_worker is None
    assert w.midi_input_connect_btn.isEnabled() is True
    assert w.midi_input_disconnect_btn.isEnabled() is False


def test_log_message_to_plain_strips_tags(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    out = w._log_message_to_plain("<b>Hello &amp; bye</b>")
    assert out == "Hello & bye"


def test_toggle_playback_state_paused_resumes_and_scrubs(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    called = {"toggle": 0, "scrub": []}

    class Ctrl:
        state = "paused"
        is_running = True

        def toggle_pause(self):
            called["toggle"] += 1

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    w.timeline_widget.current_time = 1.23
    monkeypatch.setattr(w, "_on_visual_scrub", lambda t: called["scrub"].append(t))

    w.toggle_playback_state()

    assert called["toggle"] == 1
    assert called["scrub"] == [1.23]


def test_toggle_playback_state_stopped_starts_play(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    called = []

    class Ctrl:
        state = "stopped"
        is_running = False

    w.playback_controller = Ctrl()
    monkeypatch.setattr(w, "handle_play", lambda: called.append(True))

    w.toggle_playback_state()
    assert called == [True]


def test_update_play_stop_labels_for_states(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    w.playback_state = "stopped"
    w._update_play_stop_labels()
    assert "Play" in w.play_button.text()

    w.playback_state = "paused"
    w._update_play_stop_labels()
    assert "Resume" in w.play_button.text()

    w.playback_state = "playing"
    w._update_play_stop_labels()
    assert "Pause" in w.play_button.text()


def test_on_input_mode_changed_piano_and_back(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
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


def test_refresh_midi_inputs_populates_combo(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr("main_window.mido.get_input_names", lambda: ["A", "B"])

    w._refresh_midi_inputs()

    assert w.midi_input_combo.count() == 2
    assert w.midi_input_combo.itemText(0) == "A"


def test_update_88_key_visibility_follows_output_mode(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    idx_key = w.output_mode_combo.findData("key")
    idx_num = w.output_mode_combo.findData("midi_numpad")

    w.output_mode_combo.setCurrentIndex(idx_key)
    w._update_88_key_visibility()
    assert w.use_88_key_check.isHidden() is False

    w.output_mode_combo.setCurrentIndex(idx_num)
    w._update_88_key_visibility()
    assert w.use_88_key_check.isHidden() is True


def test_handle_stop_and_reset_call_controller(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    calls = {"stop": 0, "seek": []}

    class Ctrl:
        is_running = True

        def stop(self):
            calls["stop"] += 1

        def seek(self, t):
            calls["seek"].append(t)

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    w.total_song_duration_sec = 10.0

    w.handle_stop()
    w.handle_reset()

    assert calls["stop"] == 1
    assert calls["seek"] == [0]


def test_close_event_stops_everything(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []

    class Ctrl:
        is_running = True

        def stop_and_wait(self, timeout_ms=None):
            events.append(("stop_and_wait", timeout_ms))

    class HK:
        def stop(self):
            events.append(("hk_stop", None))

    class LB:
        def shutdown(self):
            events.append(("live_shutdown", None))

    w.playback_controller = Ctrl()
    w.hotkey_manager = HK()
    w.live_backend = LB()
    monkeypatch.setattr(w, "_save_config", lambda: events.append(("save", None)))
    monkeypatch.setattr(w, "_disconnect_midi_input", lambda: events.append(("disconnect", None)))
    w.midi_input_active = True

    class E:
        def __init__(self):
            self.accepted = False

        def accept(self):
            self.accepted = True

    e = E()
    w.closeEvent(cast(Any, e))

    assert ("save", None) in events
    assert ("disconnect", None) in events
    assert ("live_shutdown", None) in events
    assert ("stop_and_wait", 1000) in events
    assert ("hk_stop", None) in events
    assert e.accepted is True


def test_toggle_always_on_top_no_show_when_not_visible(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    shown = []
    monkeypatch.setattr(w, "isVisible", lambda: False)
    monkeypatch.setattr(w, "show", lambda: shown.append(True))

    w._toggle_always_on_top(True)
    assert shown == []


def test_update_time_label_format(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    w._update_time_label(61, 125)
    assert w.time_label.text() == "01:01 / 02:05"


def test_copy_log_to_clipboard(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    copied = {}

    class Clip:
        def setText(self, t):
            copied["text"] = t

    monkeypatch.setattr("main_window.QApplication.clipboard", lambda: Clip())
    w.log_output.setPlainText("hello")
    w._copy_log_to_clipboard()
    assert copied["text"] == "hello"


def test_get_log_file_path_uses_config_dir(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    p = w._get_log_file_path()
    assert p.name == "log.txt"
    assert str(tmp_path) in str(p)


def test_on_playback_finished_resets_controls(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []
    monkeypatch.setattr(w.piano_widget, "clear", lambda: events.append("clear"))
    monkeypatch.setattr(w, "set_controls_enabled", lambda e: events.append(("controls", e)))

    w.on_playback_finished()

    assert "clear" in events
    assert ("controls", True) in events
    assert w.stop_button.isEnabled() is False


def test_set_controls_enabled_sets_groupboxes(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    groups = w.findChildren(type(w.settings_group))

    w.set_controls_enabled(False)
    assert all(not g.isEnabled() for g in groups)

    w.set_controls_enabled(True)
    assert all(g.isEnabled() for g in groups)


def test_check_macos_accessibility_opens_settings_when_requested(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr("main_window.sys.platform", "darwin")
    monkeypatch.setattr("main_window.is_macos_accessibility_trusted", lambda: False)

    opened = []
    monkeypatch.setattr(
        "main_window.open_macos_accessibility_preferences", lambda: opened.append(True)
    )

    class FakeMessageBox:
        class ButtonRole:
            ActionRole = 1
            AcceptRole = 2

        def __init__(self, *_a, **_k):
            self._open = object()
            self._clicked = None

        def setWindowTitle(self, *_a):
            return None

        def setText(self, *_a):
            return None

        def addButton(self, text, _role):
            if text == "Open System Settings":
                return self._open
            return object()

        def exec(self):
            self._clicked = self._open

        def clickedButton(self):
            return self._clicked

    monkeypatch.setattr("main_window.QMessageBox", FakeMessageBox)

    w._check_macos_accessibility()

    assert opened == [True]


def test_change_hotkey_starts_binding_and_dialog(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    started = []
    infos = []

    monkeypatch.setattr(w.hotkey_manager, "start_binding", lambda: started.append(True))
    monkeypatch.setattr("main_window.QMessageBox.information", lambda *a, **k: infos.append(True))

    w._change_hotkey()

    assert started == [True]
    assert infos == [True]
    assert w.hk_btn.isEnabled() is False
    assert w.hk_btn.text() == "Listening..."


def test_update_playback_tab_appearance_locked_and_unlocked(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    w.playback_state = "playing"
    w._update_playback_tab_appearance()
    assert "locked" in w.tabs.tabToolTip(0).lower()

    w.playback_state = "stopped"
    w._update_playback_tab_appearance()
    assert w.tabs.tabToolTip(0) == ""


def test_on_tab_changed_when_locked_shows_dialog_and_redirects(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    infos = []
    monkeypatch.setattr("main_window.QMessageBox.information", lambda *a, **k: infos.append(True))

    w.playback_state = "paused"
    w.tabs.setCurrentIndex(2)
    w._on_tab_changed(0)

    assert infos == [True]
    assert w.tabs.currentIndex() == 1


def test_on_timeline_seek_logs_and_calls_controller_when_running(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    logs = []
    seeks = []

    class Ctrl:
        is_running = True

        def seek(self, t):
            seeks.append(t)

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    monkeypatch.setattr(w, "add_log_message", lambda m: logs.append(m))

    w._on_timeline_seek(1.25)

    assert logs and "Seeking to 1.25s" in logs[0]
    assert seeks == [1.25]


def test_on_log_save_to_file_toggled_enables_and_disables(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []

    monkeypatch.setattr("main_window.jukebox_logger.enable_file_logging", lambda p: events.append(("enable", p)))
    monkeypatch.setattr("main_window.jukebox_logger.disable_file_logging", lambda: events.append(("disable", None)))
    monkeypatch.setattr(w, "add_log_message", lambda m: events.append(("log", m)))
    monkeypatch.setattr(w, "_save_config", lambda: events.append(("save", None)))

    w._on_log_save_to_file_toggled(True)
    w._on_log_save_to_file_toggled(False)

    assert any(e[0] == "enable" for e in events)
    assert any(e[0] == "disable" for e in events)
    assert [e for e in events if e[0] == "save"]


def test_on_status_updated_routes_levels(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    errors = []
    warnings = []
    infos = []

    monkeypatch.setattr("main_window.jukebox_logger.error", lambda m: errors.append(m))
    monkeypatch.setattr("main_window.jukebox_logger.warning", lambda m: warnings.append(m))
    monkeypatch.setattr(w, "add_log_message", lambda m: infos.append(m))

    w._on_status_updated("Error: boom")
    w._on_status_updated("warning: heads up")
    w._on_status_updated("all good")

    assert errors == ["Error: boom"]
    assert warnings == ["warning: heads up"]
    assert infos == ["all good"]


def test_append_log_error_multiline_and_trim(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr("main_window.MAX_LOG_ENTRIES", 1)

    w._append_log("ERROR", "boom\ntrace line")
    w._append_log("INFO", "ok")

    assert len(w._log_entries) == 1
    assert w._log_entries[0]["level"] == "INFO"


def test_save_config_logs_error_on_oserror(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    errors = []

    monkeypatch.setattr(w, "_config_from_ui", lambda: object())
    monkeypatch.setattr(
        w.config_repo,
        "save",
        lambda _c: (_ for _ in ()).throw(OSError("disk fail")),
    )
    monkeypatch.setattr(
        w,
        "_log_error",
        lambda message, **kwargs: errors.append((message, kwargs)),
    )

    w._save_config()

    assert errors
    assert "Error saving config" in errors[0][0]
    assert errors[0][1].get("show_dialog") is True


def test_load_config_handles_config_load_error(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []

    err = ConfigLoadError(tmp_path / "config.json", ValueError("bad"), tmp_path / "backup.json")
    monkeypatch.setattr(w.config_repo, "load", lambda: (_ for _ in ()).throw(err))
    monkeypatch.setattr(w, "_log_error", lambda msg, **_k: events.append(("error", msg)))
    monkeypatch.setattr(w, "_reset_controls_to_default", lambda: events.append(("reset", None)))
    monkeypatch.setattr(w, "_update_enabled_states", lambda: events.append(("enabled", None)))

    w._load_config()

    assert any("Config file could not be loaded" in e[1] for e in events if e[0] == "error")
    assert ("reset", None) in events
    assert ("enabled", None) in events


def test_load_config_success_applies_effects_and_updates(qtbot, monkeypatch, tmp_path):
    from config_repository import Config

    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []
    cfg = Config()

    monkeypatch.setattr(w.config_repo, "load", lambda: cfg)
    monkeypatch.setattr(w, "_apply_config_to_ui", lambda c: events.append(("apply", c)))
    monkeypatch.setattr("main_window.apply_config_effects", lambda win, c: events.append(("effects", c)))
    monkeypatch.setattr(w, "_update_enabled_states", lambda: events.append(("enabled", None)))
    monkeypatch.setattr(w, "_update_88_key_visibility", lambda: events.append(("vis", None)))
    monkeypatch.setattr(w, "_update_play_stop_labels", lambda: events.append(("labels", None)))

    w._load_config()

    assert ("apply", cfg) in events
    assert ("effects", cfg) in events
    assert ("enabled", None) in events
    assert ("vis", None) in events
    assert ("labels", None) in events


def test_connect_midi_input_no_device_and_running_playback_stops_first(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []

    class Ctrl:
        is_running = True

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    w.midi_input_combo.clear()

    monkeypatch.setattr(w, "handle_stop", lambda: events.append(("stop", None)))
    monkeypatch.setattr(w, "_log_warning", lambda m: events.append(("warn", m)))
    monkeypatch.setattr("main_window.QMessageBox.warning", lambda *a, **k: events.append(("dialog", None)))

    w._connect_midi_input()

    assert ("stop", None) in events
    assert any(e[0] == "warn" for e in events)
    assert ("dialog", None) in events


def test_disconnect_midi_input_handles_worker_stop_exception(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    w.midi_input_active = True
    events = []

    class Worker:
        def stop(self):
            raise RuntimeError("stop boom")

    class Thread:
        def quit(self):
            events.append(("quit", None))

        def wait(self, t):
            events.append(("wait", t))

    w.midi_input_worker = Worker()
    w.midi_input_thread = Thread()
    monkeypatch.setattr(w, "_release_all_live_keys", lambda: events.append(("release", None)))
    monkeypatch.setattr(w, "add_log_message", lambda m: events.append(("log", m)))

    w._disconnect_midi_input()

    assert ("release", None) in events
    assert ("quit", None) in events
    assert ("wait", 2000) in events
    assert any(e[0] == "log" and "Error stopping MIDI input worker" in e[1] for e in events)


def test_on_midi_input_error_and_warning_routes_to_loggers(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    errs = []
    warns = []

    monkeypatch.setattr(w, "_log_error", lambda m, **k: errs.append((m, k)))
    monkeypatch.setattr(w, "_log_warning", lambda m: warns.append(m))

    w._on_midi_input_error("bad port")
    w._on_midi_input_warning("heads up")

    assert errs and "MIDI input connection failed" in errs[0][0]
    assert warns == ["MIDI input worker: heads up"]


def test_log_message_to_plain_empty_and_fallback(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    assert w._log_message_to_plain("") == ""

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "html":
            raise ImportError("no html")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = w._log_message_to_plain("<b>x</b>")
    assert out == "x"


def test_toggle_always_on_top_visible_reapplies_state(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    calls = []

    monkeypatch.setattr(w, "isVisible", lambda: True)
    monkeypatch.setattr(w, "show", lambda: calls.append("show"))
    monkeypatch.setattr(w, "activateWindow", lambda: calls.append("activate"))
    monkeypatch.setattr(w, "raise_", lambda: calls.append("raise"))

    w._toggle_always_on_top(True)
    assert calls == ["show", "activate", "raise"]


def test_update_playback_tab_appearance_no_tabs_attr_returns_early(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    delattr(w, "tabs")
    w._update_playback_tab_appearance()


def test_update_playback_tab_appearance_tabbar_none_returns_early(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    class TabsNoBar:
        def tabBar(self):
            return None

    w.tabs = TabsNoBar()
    w._update_playback_tab_appearance()


def test_on_playback_state_changed_updates_state_and_ui(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []
    monkeypatch.setattr(w, "_update_play_stop_labels", lambda: events.append("labels"))
    monkeypatch.setattr(
        w, "_update_playback_tab_appearance", lambda: events.append("tabs")
    )

    w._on_playback_state_changed("paused")

    assert w.playback_state == "paused"
    assert events == ["labels", "tabs"]


def test_toggle_playback_state_returns_when_controller_missing(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    ctrl = w.playback_controller
    delattr(w, "playback_controller")
    w.toggle_playback_state()
    w.playback_controller = ctrl


def test_create_info_icon_sets_tooltip(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    icon = w._create_info_icon("tip")
    assert icon.toolTip() == "tip"


def test_connect_midi_input_when_already_active_noop(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    w.midi_input_active = True
    called = []
    monkeypatch.setattr("main_window.create_backend", lambda *a, **k: called.append(True))

    w._connect_midi_input()

    assert called == []


def test_refresh_midi_inputs_exception_path(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    errs = []
    monkeypatch.setattr(
        "main_window.mido.get_input_names",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(w, "_log_error", lambda m, **k: errs.append((m, k)))

    w._refresh_midi_inputs(show_dialog=False)

    assert errs and "Failed to list MIDI input devices" in errs[0][0]
    assert errs[0][1].get("show_dialog") is False


def test_on_tab_changed_unlocked_updates_last_index(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    w.playback_state = "stopped"
    w._on_tab_changed(2)
    assert w._last_tab_index == 2


def test_on_timeline_seek_logs_even_when_not_running(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    logs = []

    class Ctrl:
        is_running = False

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    monkeypatch.setattr(w, "add_log_message", lambda m: logs.append(m))

    w._on_timeline_seek(2.5)

    assert logs and "Seeking to 2.50s" in logs[0]


def test_on_visual_scrub_sets_active_pitches(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    got = []

    w.current_notes = [
        make_note(1, 60, 0.0, 1.0),
        make_note(2, 64, 0.5, 0.5),
        make_note(3, 67, 2.0, 0.3),
    ]
    w.total_song_duration_sec = 3.0
    monkeypatch.setattr(w.piano_widget, "set_active_pitches", lambda s: got.append(set(s)))

    w._on_visual_scrub(0.75)

    assert got[-1] == {60, 64}


def test_update_progress_updates_scroll_when_not_dragging(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []

    class Ctrl:
        total_duration = 10.0
        is_running = False

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    w.timeline_widget.is_dragging = False
    monkeypatch.setattr(w.timeline_widget, "set_position", lambda t: events.append(("pos", t)))
    monkeypatch.setattr(w.piano_widget, "update", lambda: events.append(("piano_update", None)))
    monkeypatch.setattr(w, "_update_time_label", lambda c, t: events.append(("label", c, t)))
    monkeypatch.setattr(w.timeline_widget, "width", lambda: 1000)
    monkeypatch.setattr(w.scroll_area, "width", lambda: 200)

    class HB:
        def setValue(self, v):
            events.append(("scroll", v))

    monkeypatch.setattr(w.scroll_area, "horizontalScrollBar", lambda: HB())

    w.update_progress(2.0)

    assert ("pos", 2.0) in events
    assert any(e[0] == "scroll" for e in events)


def test_update_progress_skips_when_dragging(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []

    class Ctrl:
        total_duration = 10.0
        is_running = False

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    w.timeline_widget.is_dragging = True
    monkeypatch.setattr(w.timeline_widget, "set_position", lambda t: events.append(("pos", t)))

    w.update_progress(1.0)

    assert events == []


def test_update_progress_no_scrollbar_branch(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []

    class Ctrl:
        total_duration = 10.0
        is_running = False

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    w.timeline_widget.is_dragging = False
    monkeypatch.setattr(w.timeline_widget, "set_position", lambda t: events.append(("pos", t)))
    monkeypatch.setattr(w.piano_widget, "update", lambda: events.append(("piano", None)))
    monkeypatch.setattr(w, "_update_time_label", lambda c, t: events.append(("label", c, t)))
    monkeypatch.setattr(w.timeline_widget, "width", lambda: 1000)
    monkeypatch.setattr(w.scroll_area, "width", lambda: 200)
    monkeypatch.setattr(w.scroll_area, "horizontalScrollBar", lambda: None)

    w.update_progress(1.0)

    assert ("pos", 1.0) in events
    assert any(e[0] == "label" for e in events)


def test_reset_controls_to_default_logs_and_calls_resets(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []

    monkeypatch.setattr(w, "add_log_message", lambda m: events.append(("log", m)))
    monkeypatch.setattr(w, "_reset_playback_group_to_default", lambda: events.append(("playback", None)))
    monkeypatch.setattr(w, "_reset_humanization_group_to_default", lambda: events.append(("human", None)))

    w._reset_controls_to_default()

    assert any(e[0] == "log" for e in events)
    assert ("playback", None) in events
    assert ("human", None) in events


def test_current_output_mode_fallback_when_no_combo(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    delattr(w, "output_mode_combo")
    assert w._current_output_mode() == "key"


def test_release_all_live_keys_no_backend_noop(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    w.live_backend = None
    w._release_all_live_keys()


def test_on_key_layout_changed_recreates_backend_when_active(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []

    class LB:
        def shutdown(self):
            events.append(("shutdown", None))

    w.live_backend = LB()
    w.midi_input_active = True

    class NewLB:
        def shutdown(self):
            return None

    monkeypatch.setattr("main_window.create_backend", lambda *a, **k: NewLB())

    w._on_key_layout_changed(True)

    assert ("shutdown", None) in events


def test_on_output_mode_changed_recreates_backend_when_active(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []

    class LB:
        def shutdown(self):
            events.append(("shutdown", None))

    w.live_backend = LB()
    w.midi_input_active = True

    class NewLB:
        def shutdown(self):
            return None

    monkeypatch.setattr("main_window.create_backend", lambda *a, **k: NewLB())

    w._on_output_mode_changed()

    assert ("shutdown", None) in events


def test_parse_and_select_tracks_parse_error(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    errs = []

    monkeypatch.setattr(
        "main_window.MidiParser.parse_structure",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("bad midi")),
    )
    monkeypatch.setattr(w, "_log_error", lambda m, **k: errs.append((m, k)))

    w._parse_and_select_tracks("x.mid")

    assert errs and "Failed to parse MIDI" in errs[0][0]


def test_parse_and_select_tracks_cancel_resets_file_label(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []

    class Dialog:
        def __init__(self, tracks, parent):
            self._tracks = tracks

        def exec(self):
            return 0

        def get_selection(self):
            return []

    monkeypatch.setattr("main_window.MidiParser.parse_structure", lambda *_a, **_k: ([], object()))
    monkeypatch.setattr("main_window.TrackSelectionDialog", Dialog)
    monkeypatch.setattr(w, "add_log_message", lambda m: events.append(("log", m)))

    w._parse_and_select_tracks("x.mid")

    assert w.selected_tracks_info is None
    assert w.file_path_label.text() == "No file selected."
    assert any("cancelled" in e[1] for e in events if e[0] == "log")


def test_parse_and_select_tracks_accept_builds_preview_and_updates_ui(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    n1 = make_note(1, 55, 0.0, 0.5)
    n2 = make_note(2, 65, 0.2, 0.4)
    track = SimpleNamespace(notes=[n1, n2])
    tempo_map = object()

    class Dialog:
        def __init__(self, tracks, parent):
            self._tracks = tracks

        def exec(self):
            from main_window import QDialog

            return QDialog.DialogCode.Accepted

        def get_selection(self):
            return [(track, "Auto")]

    monkeypatch.setattr("main_window.MidiParser.parse_structure", lambda *_a, **_k: ([track], tempo_map))
    monkeypatch.setattr("main_window.TrackSelectionDialog", Dialog)

    timeline_events = []
    monkeypatch.setattr(w.timeline_widget, "set_data", lambda notes, dur, tm: timeline_events.append((notes, dur, tm)))
    monkeypatch.setattr(w.timeline_widget, "set_position", lambda p: timeline_events.append(("pos", p)))
    monkeypatch.setattr(w, "_on_visual_scrub", lambda t: timeline_events.append(("scrub", t)))
    monkeypatch.setattr(w, "_update_time_label", lambda c, t: timeline_events.append(("label", c, t)))

    w._parse_and_select_tracks("x.mid")

    assert w.selected_tracks_info is not None
    assert w.play_button.isEnabled() is True
    assert w.reset_button.isEnabled() is True
    assert w.total_song_duration_sec == pytest.approx(0.6)
    assert any(ev[0] == "scrub" for ev in timeline_events)
    assert any(ev[2] is tempo_map for ev in timeline_events if isinstance(ev, tuple) and len(ev) == 3)


def test_handle_play_running_toggles_state(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    class Ctrl:
        is_running = True

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    called = []
    monkeypatch.setattr(w, "toggle_playback_state", lambda: called.append(True))

    w.handle_play()

    assert called == [True]


def test_handle_play_returns_when_no_config(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    class Ctrl:
        is_running = False

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    monkeypatch.setattr(w, "gather_config", lambda: None)
    saved = []
    monkeypatch.setattr(w, "_save_config", lambda: saved.append(True))

    w.handle_play()

    assert saved == []


def test_handle_play_returns_when_tracks_missing_after_config(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    class Ctrl:
        is_running = False

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    monkeypatch.setattr(w, "gather_config", lambda: {"midi_file": "x.mid", "output_mode": "key"})
    monkeypatch.setattr(w, "_save_config", lambda: None)
    w.selected_tracks_info = None

    w.handle_play()


def test_handle_play_prepare_error_logs(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    errs = []

    class Ctrl:
        is_running = False

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    w.selected_tracks_info = [(SimpleNamespace(notes=[]), "Left Hand")]
    w.parsed_tracks = []
    w.parsed_tempo_map = object()

    cfg = {"midi_file": "x.mid", "output_mode": "key", "use_88_key_layout": False}
    monkeypatch.setattr(w, "gather_config", lambda: dict(cfg))
    monkeypatch.setattr(w, "_save_config", lambda: None)
    monkeypatch.setattr(
        "main_window.PlaybackService.prepare_playback",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("prep fail")),
    )
    monkeypatch.setattr(w, "_log_error", lambda m, **k: errs.append((m, k)))

    w.handle_play()

    assert errs and "Error preparing playback" in errs[0][0]


def test_handle_play_success_sets_start_offset_and_starts_controller(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []

    class Ctrl:
        is_running = False

        def start(self, *args, **kwargs):
            events.append(("start", args, kwargs))

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    w.selected_tracks_info = [(SimpleNamespace(notes=[]), "Left Hand")]
    w.parsed_tracks = []
    w.parsed_tempo_map = object()
    w.parsed_tempo_scale = 1.0
    w.timeline_widget.total_duration = 8.0
    w.timeline_widget.current_time = 2.0

    cfg = {
        "midi_file": "x.mid",
        "output_mode": "key",
        "use_88_key_layout": False,
        "macos_use_pynput": False,
    }
    monkeypatch.setattr(w, "gather_config", lambda: dict(cfg))
    monkeypatch.setattr(w, "_save_config", lambda: events.append(("save", None)))
    monkeypatch.setattr(w, "set_controls_enabled", lambda e: events.append(("controls", e)))

    final_notes = [make_note(1, 60, 0.0, 1.0)]
    compiled_events = [SimpleNamespace(action="press")]
    monkeypatch.setattr(
        "main_window.PlaybackService.prepare_playback",
        lambda *_a, **_k: (final_notes, [], compiled_events, 16.0, object()),
    )
    monkeypatch.setattr(w.timeline_widget, "set_data", lambda notes, dur, tm: events.append(("set_data", notes, dur)))

    logs = []
    monkeypatch.setattr(w, "add_log_message", lambda m: logs.append(m))

    w.handle_play()

    assert any(e[0] == "start" for e in events)
    start_call = [e for e in events if e[0] == "start"][0]
    start_cfg = start_call[1][1]
    assert start_cfg["start_offset"] == pytest.approx(4.0)
    assert any("KEY mode does not preserve MIDI velocity dynamics" in m for m in logs)
    assert w.stop_button.isEnabled() is True


def test_handle_play_success_without_key_mode_skips_velocity_log(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    class Ctrl:
        is_running = False

        def start(self, *args, **kwargs):
            return None

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    w.selected_tracks_info = [(SimpleNamespace(notes=[]), "Left Hand")]
    w.parsed_tracks = []
    w.parsed_tempo_map = object()

    cfg = {
        "midi_file": "x.mid",
        "output_mode": "midi_numpad",
        "use_88_key_layout": False,
        "macos_use_pynput": False,
    }
    monkeypatch.setattr(w, "gather_config", lambda: dict(cfg))
    monkeypatch.setattr(w, "_save_config", lambda: None)
    monkeypatch.setattr(w, "set_controls_enabled", lambda _e: None)
    monkeypatch.setattr(
        "main_window.PlaybackService.prepare_playback",
        lambda *_a, **_k: ([make_note(1, 60, 0.0, 1.0)], [], [], 1.0, object()),
    )

    logs = []
    monkeypatch.setattr(w, "add_log_message", lambda m: logs.append(m))

    w.handle_play()

    assert not any("velocity dynamics" in m for m in logs)


def test_on_hotkey_bound_updates_widgets(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    w.hk_btn.setEnabled(False)
    w.hk_btn.setText("Listening...")

    w._on_hotkey_bound("f7")

    assert w.hk_label.text().endswith("f7")
    assert w.hk_btn.text() == "Change"
    assert w.hk_btn.isEnabled() is True


def test_toggle_always_on_top_false_branch(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr(w, "isVisible", lambda: False)
    w._toggle_always_on_top(False)


def test_on_input_mode_changed_forces_tab_zero_from_visualizer(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr(w, "_refresh_midi_inputs", lambda show_dialog=True: None)

    class FakeTabs:
        def __init__(self):
            self.enabled = None
            self.index = 1

        def setTabEnabled(self, idx, enabled):
            self.enabled = (idx, enabled)

        def currentIndex(self):
            return self.index

        def setCurrentIndex(self, idx):
            self.index = idx

    tabs = FakeTabs()
    w.tabs = tabs
    w.input_mode_piano_radio.setChecked(True)
    w._on_input_mode_changed()

    assert tabs.enabled == (1, False)
    assert tabs.index == 0


def test_connect_midi_input_success_path(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    class Ctrl:
        is_running = False

        def stop_and_wait(self, timeout_ms=None):
            return None

    class FakeWorker:
        def __init__(self, _port):
            self.message_received = FakeSignal()
            self.connected = FakeSignal()
            self.connection_error = FakeSignal()
            self.warning = FakeSignal()
            self.finished = FakeSignal()

        def moveToThread(self, _thread):
            return None

        def run(self):
            return None

        def stop(self):
            return None

    w.playback_controller = Ctrl()
    w.midi_input_combo.clear()
    w.midi_input_combo.addItem("P1")
    monkeypatch.setattr("main_window.QThread", FakeThread)
    monkeypatch.setattr("main_window.MidiInputWorker", FakeWorker)
    monkeypatch.setattr("main_window.create_backend", lambda *a, **k: FakeLiveBackend())

    w._connect_midi_input()

    assert w.midi_input_active is True
    assert w.midi_input_connect_btn.isEnabled() is False
    assert w.midi_input_disconnect_btn.isEnabled() is True
    assert "Connecting to: P1" in w.midi_input_status_label.text()


def test_on_midi_input_connected_updates_ui_and_log(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    logs = []
    monkeypatch.setattr(w, "add_log_message", lambda m: logs.append(m))

    w._on_midi_input_connected("PortA")

    assert w.midi_input_status_label.text() == "Connected to: PortA"
    assert any("Connected to MIDI input: PortA" in m for m in logs)


def test_disconnect_midi_input_inactive_noop(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    w.midi_input_active = False
    w._disconnect_midi_input()


def test_handle_live_midi_message_guard_paths(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    w.live_backend = None
    w._handle_live_midi_message(SimpleNamespace(type="note_on", note=60, velocity=100))

    backend = FakeLiveBackend()
    w.live_backend = backend
    w._handle_live_midi_message(SimpleNamespace(type="note_on", note=None, velocity=100))

    assert backend.calls == []


def test_toggle_all_humanization_and_select_all_state(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    w._toggle_all_humanization(True)
    checks = [c for c in w.all_humanization_checks.values() if c.text()]
    assert all(c.isChecked() for c in checks)

    w.all_humanization_checks["vary_timing"].setChecked(False)
    w._update_select_all_state()
    assert w.select_all_humanization_check.isChecked() is False


def test_check_macos_accessibility_early_return_paths(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    monkeypatch.setattr("main_window.sys.platform", "win32")
    w._check_macos_accessibility()

    monkeypatch.setattr("main_window.sys.platform", "darwin")
    monkeypatch.setattr("main_window.is_macos_accessibility_trusted", lambda: True)
    w._check_macos_accessibility()


def test_log_warning_and_error_show_dialog_paths(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    warns = []
    errs = []
    dialogs = []

    monkeypatch.setattr("main_window.jukebox_logger.warning", lambda m: warns.append(m))
    monkeypatch.setattr(
        "main_window.jukebox_logger.error", lambda m, **k: errs.append((m, k))
    )
    monkeypatch.setattr(
        "main_window.QMessageBox.critical", lambda *a, **k: dialogs.append(True)
    )

    w._log_warning("warn x")
    w._log_error("err x", show_dialog=True)

    assert warns == ["warn x"]
    assert errs and errs[0][0] == "err x"
    assert dialogs == [True]


def test_on_log_level_changed_sets_level_and_saves(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    events = []

    monkeypatch.setattr("main_window.jukebox_logger.set_level", lambda l: events.append(("level", l)))
    monkeypatch.setattr(w, "_save_config", lambda: events.append(("save", None)))

    w._on_log_level_changed("DEBUG")

    assert ("level", "DEBUG") in events
    assert ("save", None) in events


def test_append_log_initializes_and_error_empty_details_branch(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    delattr(w, "_log_entries")

    w._append_log("ERROR", "boom\n   ")

    assert w._log_entries
    assert "[ERROR]" in w._log_entries[-1]["html"]


def test_apply_log_filter_query_filters_out_nonmatching(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    w._log_entries = [
        {"level": "INFO", "plain": "hello world", "html": "<span>a</span>"},
        {"level": "INFO", "plain": "bye", "html": "<span>b</span>"},
    ]
    w.log_filter_edit.setText("hello")

    w._apply_log_filter()

    assert "a" in w.log_output.toPlainText()
    assert "b" not in w.log_output.toPlainText()


def test_update_enabled_states_ignores_non_text_check(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    class Dummy:
        def text(self):
            return ""

        def isChecked(self):
            return False

    w.all_humanization_checks["dummy"] = Dummy()
    w._update_enabled_states()


def test_gather_config_success_includes_midi_file(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)
    w.selected_tracks_info = [(SimpleNamespace(notes=[]), "Left Hand")]
    w.file_path_label.setToolTip("C:/tmp/x.mid")

    cfg = w.gather_config()

    assert cfg is not None
    assert cfg["midi_file"] == "C:/tmp/x.mid"


def test_select_file_running_is_noop(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    class Ctrl:
        is_running = True

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    called = []
    monkeypatch.setattr(
        "main_window.QFileDialog.getOpenFileName", lambda *a, **k: called.append(True)
    )

    w.select_file()

    assert called == []


def test_select_file_success_calls_parser_and_updates_labels(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    class Ctrl:
        is_running = False

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    monkeypatch.setattr(
        "main_window.QFileDialog.getOpenFileName",
        lambda *a, **k: ("C:/tmp/song.mid", "MIDI Files"),
    )
    events = []
    monkeypatch.setattr(w, "add_log_message", lambda m: events.append(("log", m)))
    monkeypatch.setattr(w, "_parse_and_select_tracks", lambda p: events.append(("parse", p)))

    w.select_file()

    assert w.file_path_label.text() == "song.mid"
    assert ("parse", "C:/tmp/song.mid") in events


def test_parse_and_select_tracks_assigns_left_and_right_roles(
    qtbot, monkeypatch, tmp_path
):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    left_track = SimpleNamespace(notes=[make_note(1, 70, 0.0, 0.2)])
    right_track = SimpleNamespace(notes=[make_note(2, 50, 0.3, 0.2)])

    class Dialog:
        def __init__(self, tracks, parent):
            self._tracks = tracks

        def exec(self):
            from main_window import QDialog

            return QDialog.DialogCode.Accepted

        def get_selection(self):
            return [(left_track, "Left Hand"), (right_track, "Right Hand")]

    monkeypatch.setattr(
        "main_window.MidiParser.parse_structure",
        lambda *_a, **_k: ([left_track, right_track], object()),
    )
    monkeypatch.setattr("main_window.TrackSelectionDialog", Dialog)

    w._parse_and_select_tracks("x.mid")

    hands = [n.hand for n in w.current_notes]
    assert "left" in hands
    assert "right" in hands


def test_close_event_logs_save_config_exception(qtbot, monkeypatch, tmp_path):
    w = _make_window(qtbot, monkeypatch, tmp_path)

    class Ctrl:
        is_running = False

        def stop_and_wait(self, timeout_ms=None):
            return None

    class HK:
        def stop(self):
            return None

    class E:
        def __init__(self):
            self.accepted = False

        def accept(self):
            self.accepted = True

    logs = []
    w.playback_controller = Ctrl()
    w.hotkey_manager = HK()
    monkeypatch.setattr(w, "_save_config", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr("main_window.jukebox_logger.error", lambda m, **k: logs.append(m))

    e = E()
    w.closeEvent(cast(Any, e))

    assert e.accepted is True
    assert any("Error during closeEvent cleanup" in m for m in logs)
