from types import SimpleNamespace

import pytest

from tests.helpers.builders import make_note


def test_set_current_file_labels_updates_widgets(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    w._set_current_file_labels("C:/tmp/song.mid")
    assert w.file_path_label.text() == "song.mid"
    assert w.current_file_bottom_label.text() == "song.mid"

    w._set_current_file_labels(None)
    assert w.file_path_label.text() == "No file selected."


def test_parse_and_select_tracks_parse_error(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    errs = []

    monkeypatch.setattr(
        "main_window.MidiParser.parse_structure",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("bad midi")),
    )
    monkeypatch.setattr(w, "_log_error", lambda m, **k: errs.append((m, k)))

    w._parse_and_select_tracks("x.mid")

    assert errs and "Failed to parse MIDI" in errs[0][0]


def test_parse_and_select_tracks_cancel_resets_file_label(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
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
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()

    n1 = make_note(1, 55, 0.0, 0.5)
    n2 = make_note(2, 65, 0.2, 0.4)
    track = SimpleNamespace(notes=[n1, n2])
    tempo_map = object()

    class Dialog:
        def __init__(self, tracks, parent):
            self._tracks = tracks

        def exec(self):
            return 1

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


def test_gather_config_success_includes_midi_file(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    w.selected_tracks_info = [(SimpleNamespace(notes=[]), "Left Hand")]
    w.file_path_label.setToolTip("C:/tmp/x.mid")

    cfg = w.gather_config()

    assert cfg is not None
    assert cfg["midi_file"] == "C:/tmp/x.mid"


def test_select_file_running_is_noop(window_factory, monkeypatch, tmp_path):
    w = window_factory()

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
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()

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
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()

    left_track = SimpleNamespace(notes=[make_note(1, 70, 0.0, 0.2)])
    right_track = SimpleNamespace(notes=[make_note(2, 50, 0.3, 0.2)])

    class Dialog:
        def __init__(self, tracks, parent):
            self._tracks = tracks

        def exec(self):
            return 1

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
