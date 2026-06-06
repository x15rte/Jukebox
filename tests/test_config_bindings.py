from pathlib import Path

import pytest

import config_bindings as cb
from config_repository import Config


class DummyRadio:
    def __init__(self):
        self._checked = False

    def setChecked(self, v):
        self._checked = bool(v)

    def isChecked(self):
        return self._checked

    def blockSignals(self, _v):
        return None


class DummyCombo:
    def __init__(self, items=None):
        self._items = list(items or [])
        self._text = self._items[0][0] if self._items else ""
        self._blocked = []

    def count(self):
        return len(self._items)

    def itemData(self, i):
        return self._items[i][1]

    def setCurrentIndex(self, i):
        self._text = self._items[i][0]

    def currentText(self):
        return self._text

    def setCurrentText(self, t):
        self._text = t

    def blockSignals(self, v):
        self._blocked.append(v)


class DummyTabs:
    def __init__(self):
        self.enabled = {}
        self.cur = 0

    def setTabEnabled(self, i, e):
        self.enabled[i] = e

    def currentIndex(self):
        return self.cur

    def setCurrentIndex(self, i):
        self.cur = i


class DummyFlagWidget:
    def __init__(self):
        self.visible = None

    def setVisible(self, v):
        self.visible = bool(v)


class DummyLogSaveCheck:
    def __init__(self):
        self.checked = False
        self.blocked = []

    def blockSignals(self, v):
        self.blocked.append(v)

    def setChecked(self, v):
        self.checked = bool(v)

    def isChecked(self):
        return self.checked


class DummyHKLabel:
    def __init__(self):
        self.text = ""

    def setText(self, t):
        self.text = t


class DummyHotkeyManager:
    def __init__(self):
        self.current_key = None

    def format_key_string(self, key):
        return str(key)


class DummyGeometry:
    def __init__(self, payload=b""):
        self.payload = payload

    def toBase64(self):
        class _B:
            def __init__(self, p):
                self.p = p

            def data(self):
                return self.p

        return _B(self.payload)

    def size(self):
        return len(self.payload)


class DummyWidget:
    def __init__(self):
        self.input_mode_file_radio = DummyRadio()
        self.input_mode_single_radio = DummyRadio()
        self.input_mode_playlist_radio = DummyRadio()
        self.input_mode_piano_radio = DummyRadio()
        self.file_input_widget = DummyFlagWidget()
        self.file_single_widget = DummyFlagWidget()
        self.file_playlist_widget = DummyFlagWidget()
        self.piano_input_widget = DummyFlagWidget()
        self._playback_file_only_widget = DummyFlagWidget()
        self.humanization_group = DummyFlagWidget()
        self.settings_group = DummyFlagWidget()
        self.tabs = DummyTabs()
        self.midi_input_active = False
        self.output_mode_combo = DummyCombo(items=[("Key", "key"), ("Numpad", "midi_numpad")])
        self.log_level_combo = DummyCombo(items=[("INFO", "INFO"), ("DEBUG", "DEBUG")])
        self.log_save_to_file_check = DummyLogSaveCheck()
        self.config_dir = Path(".")
        self.disconnected = 0
        self.refresh_calls = []
        self.hk_label = DummyHKLabel()
        self.hotkey_manager = DummyHotkeyManager()
        self.restore_calls = []
        self._saved = []

    def _on_file_submode_changed(self):
        self._saved.append(("file_submode", self.input_mode_playlist_radio.isChecked()))

    def _save_config(self):
        self._saved.append(("save_config", None))

    def _update_88_key_visibility(self):
        return None

    def _refresh_midi_inputs(self, show_dialog=False):
        self.refresh_calls.append(show_dialog)

    def _disconnect_midi_input(self):
        self.disconnected += 1

    def saveGeometry(self):
        return DummyGeometry(b"QUJD")

    def restoreGeometry(self, data):
        self.restore_calls.append(data)



def test_validate_config_ui_bindings_passes_default():
    cb.validate_config_ui_bindings(cb.CONFIG_UI_BINDINGS)


def test_validate_config_ui_bindings_rejects_duplicate_key():
    dup = list(cb.CONFIG_UI_BINDINGS) + [cb.CONFIG_UI_BINDINGS[0]]
    with pytest.raises(ValueError, match="Duplicate"):
        cb.validate_config_ui_bindings(dup)


def test_apply_input_mode_effects_switches_tabs():
    w = DummyWidget()
    cb._apply_input_mode(w, "piano")
    assert w.tabs.enabled[1] is False
    cb._apply_input_mode(w, "file")
    assert w.tabs.enabled[1] is True


def test_set_output_mode_combo_by_data_calls_visibility_update():
    w = DummyWidget()
    cb._set_output_mode_combo(w, "midi_numpad")
    assert w.output_mode_combo.currentText() == "Numpad"


def test_apply_config_effects_runs_without_error(monkeypatch):
    w = DummyWidget()
    monkeypatch.setattr(cb, "_set_save_log_to_file", lambda *a, **k: None)
    monkeypatch.setattr(cb, "_set_log_level", lambda *a, **k: None)
    cb.apply_config_effects(w, Config(input_mode="file", save_log_to_file=False, log_level="INFO"))


def test_set_hotkey_from_config_updates_label():
    w = DummyWidget()
    cb._set_hotkey_from_config(w, "f7")
    assert "f7" in w.hk_label.text


def test_set_log_level_combo_normalizes_invalid_value():
    w = DummyWidget()
    cb._set_log_level_combo(w, "not-a-level")
    assert w.log_level_combo.currentText() == "INFO"


def test_validate_config_ui_bindings_rejects_invalid_entries():
    with pytest.raises(ValueError, match="3-item tuple"):
        cb.validate_config_ui_bindings([("x",)])

    with pytest.raises(ValueError, match="Unknown config binding key"):
        cb.validate_config_ui_bindings([("unknown_key", lambda w: None, lambda w, v: None)])

    with pytest.raises(ValueError, match="callable"):
        cb.validate_config_ui_bindings([("tempo", 1, lambda w, v: None)])


def test_apply_input_mode_refresh_and_disconnect_paths():
    w = DummyWidget()

    w.tabs.cur = 1
    cb._apply_input_mode(w, "piano")
    assert w.tabs.cur == 0
    assert w.tabs.enabled[1] is False
    assert w.refresh_calls == [False]

    w.midi_input_active = True
    cb._apply_input_mode(w, "file")
    assert w.tabs.enabled[1] is True
    assert w.disconnected == 1


def test_set_output_mode_combo_no_match_still_updates_visibility(monkeypatch):
    w = DummyWidget()
    called = []
    monkeypatch.setattr(w, "_update_88_key_visibility", lambda: called.append(True))
    cb._set_output_mode_combo(w, "missing")
    assert called == [True]


def test_set_hotkey_from_config_no_value_noop():
    w = DummyWidget()
    before = w.hk_label.text
    cb._set_hotkey_from_config(w, "")
    assert w.hk_label.text == before


def test_window_geometry_get_and_set():
    w = DummyWidget()
    out = cb._get_window_geometry(w)
    assert out is not None

    cb._set_window_geometry(w, out)
    assert w.restore_calls


def test_set_window_geometry_empty_and_invalid(monkeypatch):
    w = DummyWidget()
    cb._set_window_geometry(w, None)
    assert w.restore_calls == []

    class EmptyBA:
        @staticmethod
        def fromBase64(_b):
            class _X:
                def isEmpty(self):
                    return True

            return _X()

    monkeypatch.setattr(cb, "QByteArray", EmptyBA)
    cb._set_window_geometry(w, "QUJD")
    assert w.restore_calls == []


def test_set_save_log_checkbox_blocks_signals():
    w = DummyWidget()
    cb._set_save_log_to_file_checkbox(w, True)
    assert w.log_save_to_file_check.checked is True
    assert w.log_save_to_file_check.blocked == [True, False]


def test_set_log_level_combo_empty_and_existing_level_no_signal_block():
    w = DummyWidget()
    w.log_level_combo.setCurrentText("INFO")
    cb._set_log_level_combo(w, "")
    assert w.log_level_combo.currentText() == "INFO"

    w.log_level_combo._blocked.clear()
    cb._set_log_level_combo(w, "info")
    assert w.log_level_combo._blocked == []


def test_set_save_log_to_file_and_set_log_level(monkeypatch):
    w = DummyWidget()
    events = []

    monkeypatch.setattr(cb.jukebox_logger, "enable_file_logging", lambda p: events.append(("enable", p)))
    monkeypatch.setattr(cb.jukebox_logger, "disable_file_logging", lambda: events.append(("disable", None)))
    monkeypatch.setattr(cb.jukebox_logger, "set_level", lambda l: events.append(("level", l)))

    cb._set_save_log_to_file(w, True)
    cb._set_save_log_to_file(w, False)
    cb._set_log_level(w, "debug")

    assert any(e[0] == "enable" for e in events)
    assert any(e[0] == "disable" for e in events)
    assert ("level", "DEBUG") in events
