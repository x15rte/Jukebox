from types import SimpleNamespace
from typing import Any, cast

import pytest
from PyQt6.QtCore import Qt

from config_repository import Config
from tests.helpers.builders import make_note
from tests.helpers.fakes import FakeLiveBackend, FakeSignal, FakeThread


def test_gather_config_without_tracks_shows_warning(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    warnings = []
    monkeypatch.setattr(w, "_log_error", lambda *a, **k: None)
    monkeypatch.setattr("main_window.QMessageBox.warning", lambda *a, **k: warnings.append(True))

    cfg = w.gather_config()
    assert cfg is None
    assert warnings == [True]



def test_toggle_always_on_top_no_show_when_not_visible(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    shown = []
    monkeypatch.setattr(w, "isVisible", lambda: False)
    monkeypatch.setattr(w, "show", lambda: shown.append(True))

    w._toggle_always_on_top(True)
    assert shown == []


def test_update_time_label_format(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    w._update_time_label(61, 125)
    assert w.time_label.text() == "01:01 / 02:05"


def test_copy_log_to_clipboard(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    copied = {}

    class Clip:
        def setText(self, t):
            copied["text"] = t

    monkeypatch.setattr("main_window.QApplication.clipboard", lambda: Clip())
    w.log_output.setPlainText("hello")
    w._copy_log_to_clipboard()
    assert copied["text"] == "hello"


def test_get_log_file_path_uses_config_dir(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    p = w._get_log_file_path()
    assert p.name == "log.txt"
    assert str(tmp_path) in str(p)


def test_set_controls_enabled_sets_groupboxes(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    groups = w.findChildren(type(w.settings_group))

    w.set_controls_enabled(False)
    assert all(not g.isEnabled() for g in groups)

    w.set_controls_enabled(True)
    assert all(g.isEnabled() for g in groups)


def test_check_macos_accessibility_opens_settings_when_requested(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
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


def test_change_hotkey_starts_binding_and_dialog(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    started = []
    infos = []

    monkeypatch.setattr(w.hotkey_manager, "start_binding", lambda: started.append(True))
    monkeypatch.setattr("main_window.QMessageBox.information", lambda *a, **k: infos.append(True))

    w._change_hotkey()

    assert started == [True]
    assert infos == [True]
    assert w.hk_btn.isEnabled() is False
    assert w.hk_btn.text() == "Listening..."


def test_update_playback_tab_appearance_locked_and_unlocked(window_factory, monkeypatch, tmp_path):
    w = window_factory()

    w.playback_state = "playing"
    w._update_playback_tab_appearance()
    assert "locked" in w.tabs.tabToolTip(0).lower()

    w.playback_state = "stopped"
    w._update_playback_tab_appearance()
    assert w.tabs.tabToolTip(0) == ""


def test_on_tab_changed_never_stops_playback(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    stop_calls = []
    monkeypatch.setattr(w, "handle_stop", lambda: stop_calls.append(True))

    w.playback_state = "paused"
    w.tabs.blockSignals(True)
    w.tabs.setCurrentIndex(0)
    w.tabs.blockSignals(False)

    for idx in (0, 1, 2, 3):
        w._on_tab_changed(idx)

    assert stop_calls == [], "Tab changes should never trigger stop (controls are already disabled)"


def test_on_log_save_to_file_toggled_enables_and_disables(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    events = []

    monkeypatch.setattr("main_window.jukebox_logger.enable_file_logging", lambda p: events.append(("enable", p)))
    monkeypatch.setattr("main_window.jukebox_logger.disable_file_logging", lambda: events.append(("disable", None)))
    monkeypatch.setattr(w, "add_log_message", lambda m: events.append(("log", m)))
    monkeypatch.setattr(w, "_mark_config_dirty", lambda: events.append(("dirty", None)))

    w._on_log_save_to_file_toggled(True)
    w._on_log_save_to_file_toggled(False)

    assert any(e[0] == "enable" for e in events)
    assert any(e[0] == "disable" for e in events)
    assert [e for e in events if e[0] == "dirty"]


def test_on_status_updated_routes_levels(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    errors = []
    warnings = []
    infos = []

    monkeypatch.setattr("main_window.jukebox_logger.error", lambda m: errors.append(m))
    monkeypatch.setattr("main_window.jukebox_logger.warning", lambda m: warnings.append(m))
    monkeypatch.setattr(w, "add_log_message", lambda m: infos.append(m))

    w._on_status_updated("Error: boom")
    w._on_status_updated("warning: heads up")
    w._on_status_updated("all good")

    assert errors == ["boom"]
    assert warnings == ["heads up"]
    assert infos == ["all good"]


def test_append_log_error_multiline_and_trim(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    monkeypatch.setattr("main_window.MAX_LOG_ENTRIES", 1)

    w._append_log("ERROR", "boom\ntrace line")
    w._append_log("INFO", "ok")

    assert len(w._log_entries) == 1
    assert w._log_entries[0]["level"] == "INFO"



def test_toggle_always_on_top_visible_reapplies_state(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    calls = []

    monkeypatch.setattr(w, "isVisible", lambda: True)
    monkeypatch.setattr(w, "show", lambda: calls.append("show"))
    monkeypatch.setattr(w, "activateWindow", lambda: calls.append("activate"))
    monkeypatch.setattr(w, "raise_", lambda: calls.append("raise"))

    w._toggle_always_on_top(True)
    assert calls == ["show", "activate", "raise"]


def test_update_playback_tab_appearance_no_tabs_attr_returns_early(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    delattr(w, "tabs")
    w._update_playback_tab_appearance()


def test_update_playback_tab_appearance_tabbar_none_returns_early(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()

    class TabsNoBar:
        def tabBar(self):
            return None

    w.tabs = TabsNoBar()
    w._update_playback_tab_appearance()




def test_original_pedal_tooltip_matches_raw_pedal_humanizer_behavior(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()

    tooltip = w.pedal_style_combo.itemData(0, Qt.ItemDataRole.ToolTipRole)

    assert "With Humanizer off, existing MIDI pedal events keep their original timing" in tooltip
    assert "With Humanizer on, the same pedal pattern follows the humanized performance" in tooltip
    assert "Falls back to Automatic if none found" in tooltip




def test_reset_controls_to_default_logs_and_calls_resets(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    events = []

    monkeypatch.setattr(w, "add_log_message", lambda m: events.append(("log", m)))
    monkeypatch.setattr(w, "_reset_playback_group_to_default", lambda: events.append(("playback", None)))
    monkeypatch.setattr(w, "_reset_humanization_group_to_default", lambda: events.append(("human", None)))

    w._reset_controls_to_default()

    assert any(e[0] == "log" for e in events)
    assert ("playback", None) in events
    assert ("human", None) in events


def test_reset_controls_to_default_resets_output_mode(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    idx = w.output_mode_combo.findData("midi_numpad")
    w.output_mode_combo.setCurrentIndex(idx)

    w._reset_controls_to_default()

    assert w._current_output_mode() == Config().output_mode
    assert w.use_88_key_check.isVisibleTo(w) is True


def test_current_output_mode_fallback_when_no_combo(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    delattr(w, "output_mode_combo")
    assert w._current_output_mode() == "key"


def test_on_hotkey_bound_updates_widgets(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    w.hk_btn.setEnabled(False)
    w.hk_btn.setText("Listening...")

    w._on_hotkey_bound("f7")

    assert w.hk_label.text().endswith("f7")
    assert w.hk_btn.text() == "Change"
    assert w.hk_btn.isEnabled() is True


def test_toggle_always_on_top_false_branch(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    monkeypatch.setattr(w, "isVisible", lambda: False)
    w._toggle_always_on_top(False)


def test_toggle_all_humanization_and_select_all_state(window_factory, monkeypatch, tmp_path):
    w = window_factory()

    w._toggle_all_humanization(True)
    checks = [c for c in w.all_humanization_checks.values() if c.text()]
    assert all(c.isChecked() for c in checks)

    w.all_humanization_checks["vary_timing"].setChecked(False)
    w._update_select_all_state()
    assert w.select_all_humanization_check.isChecked() is False


def test_check_macos_accessibility_early_return_paths(window_factory, monkeypatch, tmp_path):
    w = window_factory()

    monkeypatch.setattr("main_window.sys.platform", "win32")
    w._check_macos_accessibility()

    monkeypatch.setattr("main_window.sys.platform", "darwin")
    monkeypatch.setattr("main_window.is_macos_accessibility_trusted", lambda: True)
    w._check_macos_accessibility()


def test_log_warning_and_error_show_dialog_paths(window_factory, monkeypatch, tmp_path):
    w = window_factory()
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


def test_on_log_level_changed_sets_level_and_saves(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    events = []

    monkeypatch.setattr("main_window.jukebox_logger.set_level", lambda l: events.append(("level", l)))
    monkeypatch.setattr(w, "_mark_config_dirty", lambda: events.append(("dirty", None)))

    w._on_log_level_changed("DEBUG")

    assert ("level", "DEBUG") in events
    assert ("dirty", None) in events


def test_append_log_error_empty_details_branch(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    w._log_entries.clear()

    w._append_log("ERROR", "boom\n   ")

    assert w._log_entries
    assert "[ERROR]" in w._log_entries[-1]["html"]


def test_render_log_filter_filters_out_nonmatching(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    w._log_entries = [
        {"level": "INFO", "plain": "hello world", "html": "<span>a</span>"},
        {"level": "INFO", "plain": "bye", "html": "<span>b</span>"},
    ]
    w.log_filter_edit.setText("hello")

    w._render_log()

    assert "a" in w.log_output.toPlainText()
    assert "b" not in w.log_output.toPlainText()


def test_update_enabled_states_ignores_non_text_check(window_factory, monkeypatch, tmp_path):
    w = window_factory()

    class Dummy:
        def text(self):
            return ""

        def isChecked(self):
            return False

    w.all_humanization_checks["dummy"] = Dummy()
    w._update_enabled_states()


def test_clear_log_clears_entries(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    w._log_entries.append({"level": "INFO", "plain": "test", "html": "<span>test</span>"})
    w._clear_log()
    assert w._log_entries == []


def test_on_log_filter_text_changed_starts_timer(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    w._on_log_filter_text_changed()
    assert w._log_filter_timer.isActive()
    w._log_filter_timer.stop()


def test_on_log_wrap_toggled_changes_mode(window_factory, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QTextBrowser
    w = window_factory()
    w._on_log_wrap_toggled(True)
    assert w.log_output.lineWrapMode() == QTextBrowser.LineWrapMode.WidgetWidth
    w._on_log_wrap_toggled(False)
    assert w.log_output.lineWrapMode() == QTextBrowser.LineWrapMode.NoWrap


def test_add_log_message_with_level(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    messages = []
    monkeypatch.setattr("main_window.jukebox_logger.log", lambda lvl, msg, **k: messages.append((lvl, msg)))
    w.add_log_message("info default")
    w.add_log_message("warning msg", level="WARNING")
    assert messages[0] == ("INFO", "info default")
    assert messages[1] == ("WARNING", "warning msg")


def test_render_log_auto_scroll_respects_toggle(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    w._log_entries.append({"level": "INFO", "plain": "test", "html": "<span>x</span>"})
    w.log_auto_scroll_check.setChecked(False)
    w._render_log()
    # Should not crash when auto-scroll is off
    assert "x" in w.log_output.toPlainText()



def test_closeEvent_clears_gui_callbacks(window_factory, monkeypatch):
    from PyQt6.QtGui import QCloseEvent

    w = window_factory()
    events = []
    monkeypatch.setattr(
        "main_window.jukebox_logger.clear_gui_callbacks",
        lambda: events.append("clear"),
    )
    w.closeEvent(QCloseEvent())
    assert "clear" in events


def test_refresh_midi_inputs_single_emission(window_factory, monkeypatch):
    w = window_factory()
    error_count = 0

    def count_error(msg, **kwargs):
        nonlocal error_count
        error_count += 1

    monkeypatch.setattr("main_window.jukebox_logger.error", count_error)
    monkeypatch.setattr("mido.get_input_names", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    w._refresh_midi_inputs(show_dialog=False)

    assert error_count == 1


def test_append_log_critical_color(window_factory, monkeypatch):
    w = window_factory()
    w._append_log("CRITICAL", "critical msg")
    html = w._log_entries[-1]["html"]
    assert "#FF3333" in html


def test_append_log_with_filter_active_triggers_full_render(window_factory, monkeypatch):
    w = window_factory()
    w.log_filter_edit.setText("ERROR")
    w._append_log("INFO", "test message")
    # Cover the filter-active branch (full _render_log)


def test_build_preview_notes_no_selected_tracks_returns_early(window_factory, monkeypatch):
    w = window_factory()
    w.selected_tracks_info = None
    w._build_preview_notes(None)
    # Cover the early return when selected_tracks_info is None
