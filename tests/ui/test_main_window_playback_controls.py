from types import SimpleNamespace

import pytest

from tests.helpers.builders import make_note


def test_toggle_playback_state_paused_resumes_and_scrubs(window_factory, monkeypatch, tmp_path):
    w = window_factory()
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


def test_toggle_playback_state_stopped_starts_play(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    called = []

    class Ctrl:
        state = "stopped"
        is_running = False

    w.playback_controller = Ctrl()
    monkeypatch.setattr(w, "handle_play", lambda: called.append(True))

    w.toggle_playback_state()
    assert called == [True]


def test_update_play_stop_labels_for_states(window_factory, monkeypatch, tmp_path):
    w = window_factory()

    w.playback_state = "stopped"
    w._update_play_stop_labels()
    assert "Play" in w.play_button.text()

    w.playback_state = "paused"
    w._update_play_stop_labels()
    assert "Resume" in w.play_button.text()

    w.playback_state = "playing"
    w._update_play_stop_labels()
    assert "Pause" in w.play_button.text()


def test_handle_stop_and_reset_call_controller(window_factory, monkeypatch, tmp_path):
    w = window_factory()
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


def test_on_playback_finished_resets_controls(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    events = []
    monkeypatch.setattr(w.piano_widget, "clear", lambda: events.append("clear"))
    monkeypatch.setattr(w, "set_controls_enabled", lambda e: events.append(("controls", e)))

    w.on_playback_finished()

    assert "clear" in events
    assert ("controls", True) in events
    assert w.stop_button.isEnabled() is False


def test_on_timeline_seek_logs_and_calls_controller_when_running(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
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

    w._on_timeline_seek(2.5)

    assert seeks == [2.5]
    assert logs and "Seeking to 2.50s" in logs[0]


def test_on_playback_state_changed_updates_state_and_ui(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    events = []
    monkeypatch.setattr(w, "_update_play_stop_labels", lambda: events.append("labels"))
    monkeypatch.setattr(
        w, "_update_playback_tab_appearance", lambda: events.append("tabs")
    )

    w._on_playback_state_changed("paused")

    assert w.playback_state == "paused"
    assert events == ["labels", "tabs"]


def test_toggle_playback_state_returns_when_controller_missing(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    ctrl = w.playback_controller
    delattr(w, "playback_controller")
    w.toggle_playback_state()
    w.playback_controller = ctrl


def test_on_timeline_seek_logs_even_when_not_running(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    logs = []

    class Ctrl:
        is_running = False

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    monkeypatch.setattr(w, "add_log_message", lambda m: logs.append(m))

    w._on_timeline_seek(2.5)

    assert logs and "Seeking to 2.50s" in logs[0]


def test_on_visual_scrub_sets_active_pitches(window_factory, monkeypatch, tmp_path):
    w = window_factory()
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
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
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


def test_update_progress_skips_when_dragging(window_factory, monkeypatch, tmp_path):
    w = window_factory()
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


def test_update_progress_no_scrollbar_branch(window_factory, monkeypatch, tmp_path):
    w = window_factory()
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


def test_handle_play_running_toggles_state(window_factory, monkeypatch, tmp_path):
    w = window_factory()

    class Ctrl:
        is_running = True

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    called = []
    monkeypatch.setattr(w, "toggle_playback_state", lambda: called.append(True))

    w.handle_play()

    assert called == [True]


def test_handle_play_returns_when_no_config(window_factory, monkeypatch, tmp_path):
    w = window_factory()

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
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    errs = []

    class Ctrl:
        is_running = False

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    monkeypatch.setattr(w, "gather_config", lambda: {"midi_file": "x.mid", "output_mode": "key"})
    monkeypatch.setattr(w, "_save_config", lambda: None)
    monkeypatch.setattr(w, "_log_error", lambda m, **k: errs.append((m, k)))
    w.selected_tracks_info = None

    w.handle_play()

    assert errs and "No tracks selected" in errs[0][0]


def test_handle_play_prepare_error_logs(window_factory, monkeypatch, tmp_path):
    w = window_factory()
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
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
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
    assert start_cfg["start_offset"] == pytest.approx(0.0)
    assert any("KEY mode does not preserve MIDI velocity dynamics" in m for m in logs)
    assert w.stop_button.isEnabled() is True


def test_handle_play_success_without_key_mode_skips_velocity_log(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()

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


def test_handle_play_backend_start_failure_restores_controls(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    events = []

    class Ctrl:
        is_running = False

        def start(self, *args, **kwargs):
            events.append(("start", args, kwargs))
            return False

        def stop_and_wait(self, timeout_ms=None):
            return None

    w.playback_controller = Ctrl()
    w.selected_tracks_info = [(SimpleNamespace(notes=[]), "Left Hand")]
    w.parsed_tracks = []
    w.parsed_tempo_map = object()

    cfg = {
        "midi_file": "x.mid",
        "output_mode": "key",
        "use_88_key_layout": False,
    }
    monkeypatch.setattr(w, "gather_config", lambda: dict(cfg))
    monkeypatch.setattr(w, "_save_config", lambda: None)
    monkeypatch.setattr(
        w,
        "set_controls_enabled",
        lambda enabled: events.append(("controls", enabled)),
    )
    monkeypatch.setattr(
        "main_window.PlaybackService.prepare_playback",
        lambda *_a, **_k: ([make_note(1, 60, 0.0, 1.0)], [], [], 1.0, object()),
    )

    w.handle_play()

    assert any(event[0] == "start" for event in events)
    assert [event for event in events if event[0] == "controls"] == [
        ("controls", False),
        ("controls", True),
    ]
    assert w.stop_button.isEnabled() is False
    assert w.play_button.isEnabled() is True


def test_parse_select_then_handle_play_workflow_uses_selected_tracks_and_seek_ratio(
    window_factory, monkeypatch, tmp_path
):
    w = window_factory()
    events = []

    class Ctrl:
        is_running = False

        def start(self, *args, **kwargs):
            events.append(("start", args, kwargs))

        def stop_and_wait(self, timeout_ms=None):
            return None

    class Dialog:
        def __init__(self, tracks, parent):
            self._tracks = tracks

        def exec(self):
            return 1

        def get_selection(self):
            return [(parsed_track, "Auto")]

    parsed_track = SimpleNamespace(notes=[make_note(1, 55, 0.0, 0.5), make_note(2, 67, 0.4, 0.3)])
    prepared_notes = [make_note(3, 60, 0.0, 1.0, hand="left")]
    tempo_map = object()
    prepared_tempo_map = object()

    w.playback_controller = Ctrl()
    monkeypatch.setattr(
        "main_window.MidiParser.parse_structure",
        lambda *_a, **_k: ([parsed_track], tempo_map),
    )
    monkeypatch.setattr("main_window.TrackSelectionDialog", Dialog)
    monkeypatch.setattr(w, "_save_config", lambda: events.append(("save", None)))
    monkeypatch.setattr(w, "set_controls_enabled", lambda enabled: events.append(("controls", enabled)))
    monkeypatch.setattr(
        "main_window.PlaybackService.prepare_playback",
        lambda midi_file, selected_tracks_info, config, **_k: (
            prepared_notes,
            [],
            [SimpleNamespace(action="press")],
            10.0,
            prepared_tempo_map,
        ),
    )

    logs = []
    monkeypatch.setattr(w, "add_log_message", lambda m: logs.append(m))

    w._set_current_file_labels("C:/tmp/song.mid")
    w._parse_and_select_tracks("C:/tmp/song.mid")
    w.timeline_widget.current_time = 0.2
    w.timeline_widget.total_duration = 0.8
    w.handle_play()

    assert w.selected_tracks_info == [(parsed_track, "Auto")]
    assert any(e[0] == "save" for e in events)
    assert any(e[0] == "controls" and e[1] is False for e in events)
    start_call = [e for e in events if e[0] == "start"][0]
    start_cfg = start_call[1][1]
    assert start_cfg["midi_file"] == "C:/tmp/song.mid"
    assert start_cfg["start_offset"] == pytest.approx(0.0)
    assert w.current_notes == prepared_notes
    assert w.total_song_duration_sec == 10.0
    assert any("Preparing playback..." in m for m in logs)
