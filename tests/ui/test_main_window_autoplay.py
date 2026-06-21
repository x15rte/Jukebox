"""Tests for the autoplay (playlist) feature in MainWindow."""

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent

from config_repository import Config
from core import MidiParser
from models import MidiTrack, Note
from tests.helpers.builders import make_note
from tests.helpers.fakes import FakeBackend, FakeSignal, FakeThread, FakePlaybackPlayer
from playback import PlaybackService


def _mock_ctrl(**kw):
    """Build a mock PlaybackController compatible with all autoplay and teardown paths."""
    return SimpleNamespace(
        is_running=kw.get("is_running", False),
        state=kw.get("state", "stopped"),
        player=None,
        total_duration=0.0,
        stop=lambda: None,
        stop_and_wait=lambda timeout_ms=None: None,
        start=lambda *a, **k: kw.get("start_result", True),
        toggle_pause=lambda: None,
        seek=lambda t: None,
    )


# ---------------------------------------------------------------------------
# _autoplay_browse_folder
# ---------------------------------------------------------------------------
def test_autoplay_browse_folder_returns_early_when_playing(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.playback_controller = _mock_ctrl(is_running=True)
    calls: list[str] = []
    monkeypatch.setattr(w, "_set_autoplay_folder_path", lambda *a, **k: calls.append("set"))
    monkeypatch.setattr("main_window.QFileDialog.getExistingDirectory", lambda *a, **k: "")

    w._autoplay_browse_folder()
    assert calls == [], "Should return early without calling _set_autoplay_folder_path"


def test_autoplay_browse_folder_cancelled(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    calls: list[Any] = []
    monkeypatch.setattr("main_window.QFileDialog.getExistingDirectory", lambda *a, **k: "")
    monkeypatch.setattr(w, "_set_autoplay_folder_path", lambda p: calls.append(("set", p)))
    monkeypatch.setattr(w, "_autoplay_scan_folder", lambda: calls.append("scan"))

    w._autoplay_browse_folder()
    assert calls == [], "Should do nothing when dialog is cancelled"


def test_autoplay_browse_folder_success(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    calls: list[Any] = []
    monkeypatch.setattr("main_window.QFileDialog.getExistingDirectory", lambda *a, **k: "/fake/midi/folder")
    monkeypatch.setattr(w, "_set_autoplay_folder_path", lambda p: calls.append(("set", p)))
    monkeypatch.setattr(w, "_autoplay_scan_folder", lambda: calls.append("scan"))

    w._autoplay_browse_folder()
    assert calls == [("set", "/fake/midi/folder"), "scan"]


# ---------------------------------------------------------------------------
# _set_autoplay_folder_path
# ---------------------------------------------------------------------------
def test_set_autoplay_folder_path_sets_path(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    saved: list[Any] = []
    monkeypatch.setattr(w, "_mark_config_dirty", lambda: saved.append(True))

    w.autoplay_folder = None
    w._set_autoplay_folder_path("/some/folder")
    assert w.autoplay_folder == "/some/folder"
    assert w.autoplay_folder_label.toolTip() == "/some/folder"
    assert w.autoplay_reload_btn.isEnabled()
    assert w.autoplay_shuffle_btn.isEnabled()
    assert saved == [True]


def test_set_autoplay_folder_path_clears_path(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    saved: list[Any] = []
    monkeypatch.setattr(w, "_mark_config_dirty", lambda: saved.append(True))

    w.autoplay_folder = "/some/folder"
    w._set_autoplay_folder_path(None)
    assert w.autoplay_folder is None
    assert not w.autoplay_reload_btn.isEnabled()
    assert not w.autoplay_shuffle_btn.isEnabled()
    assert saved == [True]


# ---------------------------------------------------------------------------
# _autoplay_scan_folder
# ---------------------------------------------------------------------------
def test_autoplay_scan_folder_no_folder(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_folder = None
    w._autoplay_scan_folder()


def test_autoplay_scan_folder_empty(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    empty_dir = tmp_path / "empty_midi"
    empty_dir.mkdir()
    w.autoplay_folder = str(empty_dir)

    w._autoplay_scan_folder()
    assert w.autoplay_file_list == []
    assert w.autoplay_current_index == -1
    assert w.autoplay_file_listbox.count() == 0


def test_autoplay_scan_folder_with_files(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    midi_dir = tmp_path / "midi_files"
    midi_dir.mkdir()
    (midi_dir / "b.mid").write_text("dummy")
    (midi_dir / "a.mid").write_text("dummy")

    w.autoplay_folder = str(midi_dir)
    w._autoplay_scan_folder()

    assert len(w.autoplay_file_list) == 2
    assert os.path.basename(w.autoplay_file_list[0]) == "a.mid"
    assert os.path.basename(w.autoplay_file_list[1]) == "b.mid"
    assert w.autoplay_current_index == 0
    assert w.autoplay_file_listbox.count() == 2
    assert "2 MIDI file(s) found." in w.autoplay_info_label.text()


def test_autoplay_scan_folder_filters_extensions(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    midi_dir = tmp_path / "ext_filter"
    midi_dir.mkdir()
    (midi_dir / "song.mid").write_text("dummy")
    (midi_dir / "song.midi").write_text("dummy")
    (midi_dir / "not_midi.txt").write_text("dummy")
    (midi_dir / "song.mp3").write_text("dummy")

    w.autoplay_folder = str(midi_dir)
    w._autoplay_scan_folder()

    assert len(w.autoplay_file_list) == 2


def test_autoplay_scan_folder_cancels_timer(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_next_timer.start(5000)
    assert w.autoplay_next_timer.isActive()
    w._autoplay_scan_folder()
    assert not w.autoplay_next_timer.isActive()


# ---------------------------------------------------------------------------
# _autoplay_jump_to_song
# ---------------------------------------------------------------------------
def test_autoplay_jump_to_song_invalid_row(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = ["song1.mid", "song2.mid"]
    w.autoplay_file_listbox.addItem("test")

    monkeypatch.setattr(w.autoplay_file_listbox, "row", lambda i: -1)
    monkeypatch.setattr(w, "add_log_message", lambda m: None)

    w._autoplay_jump_to_song(w.autoplay_file_listbox.item(0))
    assert w.autoplay_current_index == -1


def test_autoplay_jump_to_song_stops_playback(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = [__file__]
    w.autoplay_file_listbox.addItem("test.mid")
    w.playback_controller = _mock_ctrl(is_running=True)

    monkeypatch.setattr(w, "_autoplay_select_tracks", lambda *a, **k: False)
    monkeypatch.setattr(w, "add_log_message", lambda m: None)

    w._autoplay_jump_to_song(w.autoplay_file_listbox.item(0))
    # Jump is deferred — pending jump stored, index not yet set
    assert w.autoplay_current_index == -1
    assert w._pending_autoplay_jump == 0


def test_autoplay_jump_to_song_previews(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = [__file__]
    w.autoplay_file_listbox.addItem("test.mid")

    notes = [make_note(0, 60, 0.0, 0.5), make_note(1, 64, 0.0, 0.5)]
    tr = MidiTrack(index=0, name="Piano", program_change=0, is_drum=False, notes=notes, pedal_events=[])
    w.selected_tracks_info = [(tr, "Auto-Detect")]
    monkeypatch.setattr(w, "_autoplay_select_tracks", lambda *a, **k: True)
    monkeypatch.setattr(w, "add_log_message", lambda m: None)

    w._autoplay_jump_to_song(w.autoplay_file_listbox.item(0))
    assert w.autoplay_current_index == 0
    assert len(w.current_notes) == 2


def test_autoplay_jump_to_song_previews_left_and_right_hands(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = [__file__]
    w.autoplay_file_listbox.addItem("test.mid")

    ln = make_note(0, 48, 0.0, 0.5)
    rn = make_note(1, 72, 0.1, 0.5)
    left_tr = MidiTrack(index=0, name="Left", program_change=0, is_drum=False, notes=[ln], pedal_events=[])
    right_tr = MidiTrack(index=1, name="Right", program_change=0, is_drum=False, notes=[rn], pedal_events=[])
    w.selected_tracks_info = [(left_tr, "Left Hand"), (right_tr, "Right Hand")]
    monkeypatch.setattr(w, "_autoplay_select_tracks", lambda *a, **k: True)
    monkeypatch.setattr(w, "add_log_message", lambda m: None)

    w._autoplay_jump_to_song(w.autoplay_file_listbox.item(0))
    assert w.autoplay_current_index == 0
    assert len(w.current_notes) == 2
    assert w.current_notes[0].hand == "left"
    assert w.current_notes[1].hand == "right"


def test_autoplay_jump_to_song_parse_exception(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = [__file__]
    w.autoplay_file_listbox.addItem("test.mid")

    def _raise(*a, **k):
        raise ValueError("broken")

    monkeypatch.setattr(w, "_autoplay_select_tracks", _raise)
    monkeypatch.setattr(w, "add_log_message", lambda m: None)

    w._autoplay_jump_to_song(w.autoplay_file_listbox.item(0))
    assert w.autoplay_current_index == 0


# ---------------------------------------------------------------------------
# _autoplay_shuffle
# ---------------------------------------------------------------------------
def test_autoplay_shuffle_fewer_than_two(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = ["only.mid"]
    w._autoplay_shuffle()
    assert w.autoplay_file_list == ["only.mid"]


def test_autoplay_shuffle_reorders(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = ["a.mid", "b.mid", "c.mid"]
    for f in w.autoplay_file_list:
        w.autoplay_file_listbox.addItem(f)

    monkeypatch.setattr("main_window.random.shuffle", lambda lst: lst.reverse())
    monkeypatch.setattr(w, "add_log_message", lambda m: None)

    w._autoplay_shuffle()
    assert w.autoplay_file_list == ["c.mid", "b.mid", "a.mid"]
    assert w.autoplay_current_index == -1


# ---------------------------------------------------------------------------
# _autoplay_select_tracks
# ---------------------------------------------------------------------------
def test_autoplay_select_tracks_no_non_drum(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    drum_track = MidiTrack(
        index=0, name="Drum", program_change=0, is_drum=True,
        notes=[], pedal_events=[],
    )
    monkeypatch.setattr(
        "main_window.MidiParser.parse_structure",
        lambda *a, **k: ([drum_track], None),
    )
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    assert w._autoplay_select_tracks("dummy.mid") is False


def test_autoplay_select_tracks_success(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    piano_track = MidiTrack(
        index=0, name="Piano", program_change=0, is_drum=False,
        notes=[], pedal_events=[],
    )
    monkeypatch.setattr(
        "main_window.MidiParser.parse_structure",
        lambda *a, **k: ([piano_track], None),
    )
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    assert w._autoplay_select_tracks("dummy.mid") is True
    assert w.selected_tracks_info == [(piano_track, "Auto-Detect")]


# ---------------------------------------------------------------------------
# _autoplay_play_current
# ---------------------------------------------------------------------------
def test_autoplay_play_current_stopping_flag(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = ["a.mid"]
    w._autoplay_stopping = True
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    result = w._autoplay_play_current()
    assert result is False
    assert w._autoplay_stopping is False


def test_autoplay_play_current_empty_list(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = []
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    result = w._autoplay_play_current()
    assert result is False


def test_autoplay_play_current_index_out_of_range(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = ["a.mid", "b.mid"]
    w.autoplay_current_index = 5
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    result = w._autoplay_play_current()
    assert result is False
    assert w.autoplay_current_index == -1


def test_autoplay_play_current_parse_skip(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = ["fail.mid", "success.mid"]
    w.autoplay_current_index = 0
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    monkeypatch.setattr(w, "_set_current_file_labels", lambda *a, **k: None)

    parse_calls = []

    def fake_select(fp):
        parse_calls.append(fp)
        if "success" in fp:
            w.selected_tracks_info = [(MidiTrack(index=0, name="", program_change=0, is_drum=False, notes=[], pedal_events=[]), "Auto-Detect")]
            return True
        return False

    monkeypatch.setattr(w, "_autoplay_select_tracks", fake_select)
    monkeypatch.setattr(w, "gather_config", lambda: {"output_mode": "key", "use_88_key_layout": False, "tempo": 100})
    monkeypatch.setattr("main_window.PlaybackService.prepare_playback", lambda *a, **k: ([], [], [], 1.0, None))
    w.playback_controller = _mock_ctrl(start_result=True)

    result = w._autoplay_play_current()
    assert result is True
    assert len(parse_calls) == 2


def test_autoplay_play_current_prepare_error_skip(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = ["fail.mid", "ok.mid"]
    w.autoplay_current_index = 0
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    monkeypatch.setattr(w, "_set_current_file_labels", lambda *a, **k: None)
    monkeypatch.setattr(w, "_autoplay_select_tracks", lambda *a, **k: True)
    monkeypatch.setattr(w, "gather_config", lambda: {"output_mode": "key", "use_88_key_layout": False, "tempo": 100})
    monkeypatch.setattr(w, "_update_autoplay_highlight", lambda: None)
    w.selected_tracks_info = [(MidiTrack(index=0, name="", program_change=0, is_drum=False, notes=[], pedal_events=[]), "Auto-Detect")]

    prepare_calls = []

    def fake_prepare(*a, **k):
        prepare_calls.append(len(prepare_calls))
        if len(prepare_calls) == 1:
            raise ValueError("prepare failed")
        return ([], [], [], 1.0, None)

    monkeypatch.setattr("main_window.PlaybackService.prepare_playback", fake_prepare)
    w.playback_controller = _mock_ctrl(start_result=True)

    result = w._autoplay_play_current()
    assert result is True


def test_autoplay_play_current_gather_config_returns_none(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = ["song.mid"]
    w.autoplay_current_index = 0
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    monkeypatch.setattr(w, "_set_current_file_labels", lambda *a, **k: None)
    monkeypatch.setattr(w, "_autoplay_select_tracks", lambda *a, **k: True)
    monkeypatch.setattr(w, "gather_config", lambda: None)

    result = w._autoplay_play_current()
    assert result is False


def test_autoplay_play_current_start_returns_false(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = ["song.mid"]
    w.autoplay_current_index = 0
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    monkeypatch.setattr(w, "_set_current_file_labels", lambda *a, **k: None)
    monkeypatch.setattr(w, "_autoplay_select_tracks", lambda *a, **k: True)
    monkeypatch.setattr(w, "gather_config", lambda: {"output_mode": "key", "use_88_key_layout": False, "tempo": 100})
    monkeypatch.setattr("main_window.PlaybackService.prepare_playback", lambda *a, **k: ([], [], [], 1.0, None))
    w.selected_tracks_info = [(MidiTrack(index=0, name="", program_change=0, is_drum=False, notes=[], pedal_events=[]), "Auto-Detect")]
    w.playback_controller = _mock_ctrl(start_result=False)

    result = w._autoplay_play_current()
    assert result is False


def test_autoplay_play_current_exception_during_parse(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = ["bad.mid", "good.mid"]
    w.autoplay_current_index = 0
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    monkeypatch.setattr(w, "_set_current_file_labels", lambda *a, **k: None)
    monkeypatch.setattr(w, "_update_autoplay_highlight", lambda: None)

    select_calls = []

    def fake_select(fp):
        select_calls.append(fp)
        if "bad" in fp:
            raise ValueError("parse failed")
        w.selected_tracks_info = [(MidiTrack(index=0, name="", program_change=0, is_drum=False, notes=[], pedal_events=[]), "Auto-Detect")]
        return True

    monkeypatch.setattr(w, "_autoplay_select_tracks", fake_select)
    monkeypatch.setattr(w, "gather_config", lambda: {"output_mode": "key", "use_88_key_layout": False, "tempo": 100})
    monkeypatch.setattr("main_window.PlaybackService.prepare_playback", lambda *a, **k: ([], [], [], 1.0, None))
    w.playback_controller = _mock_ctrl(start_result=True)

    result = w._autoplay_play_current()
    assert result is True
    assert len(select_calls) == 2


def test_autoplay_play_current_resets_no_more_songs(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = []
    w.autoplay_current_index = -1
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    monkeypatch.setattr(w, "_update_autoplay_highlight", lambda: None)
    result = w._autoplay_play_current()
    assert result is False


def test_autoplay_play_current_all_fail_skips_everything(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = ["a.mid", "b.mid"]
    w.autoplay_current_index = 0
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    monkeypatch.setattr(w, "_set_current_file_labels", lambda *a, **k: None)
    monkeypatch.setattr(w, "_update_autoplay_highlight", lambda: None)
    monkeypatch.setattr(w, "_autoplay_select_tracks", lambda *a, **k: False)

    result = w._autoplay_play_current()
    assert result is False
    assert w.autoplay_current_index == -1


def test_autoplay_play_current_success_path(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = ["song.mid"]
    w.autoplay_current_index = 0
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    monkeypatch.setattr(w, "_set_current_file_labels", lambda *a, **k: None)
    monkeypatch.setattr(w, "_autoplay_select_tracks", lambda *a, **k: True)
    monkeypatch.setattr(w, "gather_config", lambda: {"output_mode": "key", "use_88_key_layout": False, "tempo": 100})
    monkeypatch.setattr(w, "_update_autoplay_highlight", lambda: None)
    monkeypatch.setattr("main_window.PlaybackService.prepare_playback", lambda *a, **k: ([], [], [], 1.0, None))
    w.selected_tracks_info = [(MidiTrack(index=0, name="", program_change=0, is_drum=False, notes=[], pedal_events=[]), "Auto-Detect")]
    w.playback_controller = _mock_ctrl(start_result=True)

    result = w._autoplay_play_current()
    assert result is True


# ---------------------------------------------------------------------------
# _update_autoplay_highlight
# ---------------------------------------------------------------------------
def test_update_autoplay_highlight(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_listbox.addItem("a.mid")
    w.autoplay_file_listbox.addItem("b.mid")
    w.autoplay_current_index = 1
    w._update_autoplay_highlight()
    item0 = w.autoplay_file_listbox.item(0)
    item1 = w.autoplay_file_listbox.item(1)
    assert item0 is not None and item1 is not None
    assert not item0.font().bold()
    assert item1.font().bold()


# ---------------------------------------------------------------------------
# _on_file_submode_changed
# ---------------------------------------------------------------------------
def test_on_file_submode_changed_toggle_off(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = ["a.mid", "b.mid"]

    monkeypatch.setattr(w, "_save_config", lambda: None)

    # Switch to playlist first so toggling back to single actually fires
    w.input_mode_playlist_radio.setChecked(True)
    w.autoplay_current_index = 3

    # Now toggle back to single — index resets
    w.input_mode_single_radio.setChecked(True)
    assert w.autoplay_current_index == -1


def test_on_file_submode_changed_toggle_on(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    monkeypatch.setattr(w, "_save_config", lambda: None)

    w.input_mode_playlist_radio.setChecked(True)
    # Toggling to playlist mode doesn't reset index (no previous selection)
    assert w.autoplay_current_index == -1


# ---------------------------------------------------------------------------
# handle_play (playlist branch)
# ---------------------------------------------------------------------------
def test_handle_play_playlist_starts_from_index_zero(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.input_mode_file_radio.setChecked(True)
    w.input_mode_playlist_radio.setChecked(True)
    w.autoplay_file_list = ["a.mid", "b.mid"]
    w.autoplay_current_index = -1
    monkeypatch.setattr(w, "add_log_message", lambda m: None)

    played = []
    monkeypatch.setattr(w, "_autoplay_play_current", lambda: played.append(True))

    w.handle_play()
    assert w.autoplay_current_index == 0
    assert played == [True]


def test_handle_play_playlist_starts_from_selected(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.input_mode_file_radio.setChecked(True)
    w.input_mode_playlist_radio.setChecked(True)
    w.autoplay_file_list = ["a.mid", "b.mid", "c.mid"]
    w.autoplay_current_index = 1
    monkeypatch.setattr(w, "add_log_message", lambda m: None)

    played = []
    monkeypatch.setattr(w, "_autoplay_play_current", lambda: played.append(True))

    w.handle_play()
    assert w.autoplay_current_index == 1
    assert played == [True]


def test_handle_play_playlist_no_files(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.input_mode_file_radio.setChecked(True)
    w.input_mode_playlist_radio.setChecked(True)
    w.autoplay_file_list = []

    played = []
    monkeypatch.setattr(w, "_autoplay_play_current", lambda: played.append(True))
    monkeypatch.setattr(w, "gather_config", lambda: None)
    monkeypatch.setattr("main_window.QMessageBox.warning", lambda *a, **k: None)

    w.handle_play()
    assert played == []


# ---------------------------------------------------------------------------
# handle_stop (playlist branch)
# ---------------------------------------------------------------------------
def test_handle_stop_playlist_with_selection(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.input_mode_file_radio.setChecked(True)
    w.input_mode_playlist_radio.setChecked(True)
    w.autoplay_file_list = ["song.mid"]
    w.autoplay_current_index = 0
    w.playback_controller = _mock_ctrl(is_running=False)
    monkeypatch.setattr(w, "add_log_message", lambda m: None)

    w.handle_stop()
    assert w.autoplay_current_index == 0


def test_handle_stop_playlist_without_selection(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.input_mode_file_radio.setChecked(True)
    w.input_mode_playlist_radio.setChecked(True)
    w.autoplay_file_list = ["song.mid", "song2.mid"]
    w.autoplay_current_index = -1
    w.playback_controller = _mock_ctrl(is_running=False)
    monkeypatch.setattr(w, "add_log_message", lambda m: None)

    w.handle_stop()
    assert w.autoplay_current_index == -1
    assert "2 MIDI file(s) found." in w.autoplay_info_label.text()


def test_handle_stop_playlist_running(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.input_mode_file_radio.setChecked(True)
    w.input_mode_playlist_radio.setChecked(True)
    w.autoplay_file_list = ["song.mid"]
    w.autoplay_current_index = 0

    stop_calls = []
    mock = _mock_ctrl(is_running=True)
    mock.stop = lambda: stop_calls.append(True)
    w.playback_controller = mock

    monkeypatch.setattr(w, "add_log_message", lambda m: None)

    w.handle_stop()
    assert stop_calls == [True]


# ---------------------------------------------------------------------------
# on_playback_finished (playlist branches)
# ---------------------------------------------------------------------------
def test_on_playback_finished_autoplay_advances(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.input_mode_file_radio.setChecked(True)
    w.input_mode_playlist_radio.setChecked(True)
    w.autoplay_file_list = ["a.mid", "b.mid"]
    w.autoplay_current_index = 0
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    monkeypatch.setattr(w, "_update_autoplay_highlight", lambda: None)
    monkeypatch.setattr(w, "_save_config", lambda: None)

    called = []
    monkeypatch.setattr(w, "_autoplay_play_current", lambda: called.append(True))

    w.on_playback_finished()
    assert w.autoplay_current_index == 1
    assert called == [True]


def test_on_playback_finished_autoplay_all_done(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.input_mode_file_radio.setChecked(True)
    w.input_mode_playlist_radio.setChecked(True)
    w.autoplay_file_list = ["a.mid"]
    w.autoplay_current_index = 0
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    monkeypatch.setattr(w, "_update_autoplay_highlight", lambda: None)

    called = []
    monkeypatch.setattr(w, "_autoplay_play_current", lambda: called.append(True))

    w.on_playback_finished()
    assert w.autoplay_current_index == 1
    assert called == []
    assert "All songs played." in w.autoplay_info_label.text()


def test_on_playback_finished_autoplay_stopping_flag(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.input_mode_file_radio.setChecked(True)
    w.input_mode_playlist_radio.setChecked(True)
    w.autoplay_file_list = ["a.mid", "b.mid"]
    w.autoplay_current_index = 0
    w._autoplay_stopping = True
    monkeypatch.setattr(w, "add_log_message", lambda m: None)

    called = []
    monkeypatch.setattr(w, "_autoplay_play_current", lambda: called.append(True))

    w.on_playback_finished()
    assert w._autoplay_stopping is False
    assert called == []


def test_on_playback_finished_not_in_playlist_mode(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = ["a.mid"]
    w.autoplay_current_index = 0
    monkeypatch.setattr(w, "add_log_message", lambda m: None)

    called = []
    monkeypatch.setattr(w, "_autoplay_play_current", lambda: called.append(True))

    w.on_playback_finished()
    assert called == []


def test_on_playback_finished_advance_with_delay(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.input_mode_file_radio.setChecked(True)
    w.input_mode_playlist_radio.setChecked(True)
    w.autoplay_file_list = ["a.mid", "b.mid"]
    w.autoplay_current_index = 0
    w.autoplay_delay_spinbox.setValue(3.0)
    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    monkeypatch.setattr(w, "_update_autoplay_highlight", lambda: None)

    w.on_playback_finished()
    assert w.autoplay_current_index == 1
    assert w.autoplay_next_timer.isActive()
    w.autoplay_next_timer.stop()


# ---------------------------------------------------------------------------
# Config bindings
# ---------------------------------------------------------------------------
def test_config_autoplay_folder_persisted(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    saved = []
    monkeypatch.setattr(w, "_mark_config_dirty", lambda: saved.append(True))

    w._set_autoplay_folder_path("/test/folder")
    config = w._config_from_ui()
    assert config.autoplay_folder == "/test/folder"
    assert saved == [True]  # _mark_config_dirty called by _set_autoplay_folder_path


def test_config_autoplay_mode_field(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.input_mode_single_radio.setChecked(True)
    config1 = w._config_from_ui()
    assert config1.autoplay_mode is False

    w.input_mode_playlist_radio.setChecked(True)
    config2 = w._config_from_ui()
    assert config2.autoplay_mode is True


def test_autoplay_delay_spinbox_config_bound(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_delay_spinbox.setValue(5.5)
    config = w._config_from_ui()
    assert config.autoplay_delay == 5.5


def test_autoplay_random_delay_spinbox_config_bound(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_random_delay_spinbox.setValue(2.5)
    config = w._config_from_ui()
    assert config.autoplay_random_delay == 2.5


def test_autoplay_delay_save_load_roundtrip(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_delay_spinbox.setValue(7.0)
    w.autoplay_random_delay_spinbox.setValue(3.0)
    config = w._config_from_ui()
    written = config.to_dict()
    loaded = Config.from_dict(written)
    assert loaded.autoplay_delay == 7.0
    assert loaded.autoplay_random_delay == 3.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
def test_autoplay_stop_clears_timer(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.input_mode_playlist_radio.setChecked(True)
    w.autoplay_next_timer.start(5000)
    assert w.autoplay_next_timer.isActive()

    w.playback_controller = _mock_ctrl(is_running=False)
    monkeypatch.setattr(w, "add_log_message", lambda m: None)

    w.handle_stop()
    assert not w.autoplay_next_timer.isActive()


def test_autoplay_timer_cancelled_on_close(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_next_timer.start(5000)
    monkeypatch.setattr(w, "_save_config", lambda: None)
    w.playback_controller = _mock_ctrl(is_running=False)
    monkeypatch.setattr(w, "hotkey_manager", SimpleNamespace(stop=lambda: None))

    w.closeEvent(QCloseEvent())
    assert not w.autoplay_next_timer.isActive()


def test_autoplay_jump_when_nothing_playing(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    w.autoplay_file_list = [__file__]
    w.autoplay_file_listbox.addItem("test.mid")

    monkeypatch.setattr(w, "_autoplay_select_tracks", lambda *a, **k: True)
    monkeypatch.setattr(w, "add_log_message", lambda m: None)

    w._autoplay_jump_to_song(w.autoplay_file_listbox.item(0))
    assert w.autoplay_current_index == 0


def test_autoplay_scan_folder_shows_first_file(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    midi_dir = tmp_path / "label_test"
    midi_dir.mkdir()
    (midi_dir / "first.mid").write_text("x")
    (midi_dir / "second.mid").write_text("x")
    w.autoplay_folder = str(midi_dir)

    monkeypatch.setattr(w, "add_log_message", lambda m: None)
    w._autoplay_scan_folder()

    assert "first.mid" in w.current_file_bottom_label.text()
