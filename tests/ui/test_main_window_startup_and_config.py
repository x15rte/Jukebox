from typing import Any, cast

import pytest

from config_repository import ConfigLoadError, ConfigRepository
from main_window import MainWindow

MainWindow = cast(Any, MainWindow)


def test_init_raises_runtime_error_on_invalid_config_bindings(
    window_factory, monkeypatch, tmp_path
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


def test_close_event_stops_everything(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    events = []

    class Ctrl:
        is_running = True
        def stop(self):
            events.append(("stop", None))
        def stop_and_wait(self, timeout_ms=2000):
            self.stop()
            events.append(("stop_and_wait", None))
        def stop_and_wait_blocking(self, timeout_ms=2000):
            self.stop()
            events.append(("stop_and_wait_blocking", None))
    class HK:
        class _Signal:
            @staticmethod
            def disconnect():
                pass
        toggle_requested = _Signal()
        bound_updated = _Signal()
        def stop(self):
            events.append(("hk_stop", None))

    w.playback_controller = Ctrl()
    w.hotkey_manager = HK()
    monkeypatch.setattr(w, "_save_config", lambda: events.append(("save", None)))
    monkeypatch.setattr(w, "_disconnect_midi_input", lambda: events.append(("disconnect", None)))
    w.midi_input_active = True
    w._config_dirty = True  # simulate unsaved changes so close flushes them

    class E:
        def __init__(self):
            self.accepted = False

        def accept(self):
            self.accepted = True

    e = E()
    w.closeEvent(cast(Any, e))

    assert ("save", None) in events
    assert ("disconnect", None) in events
    assert ("stop", None) in events
    assert ("hk_stop", None) in events
    assert e.accepted is True


def test_save_config_logs_error_on_oserror(window_factory, monkeypatch, tmp_path):
    w = window_factory()
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


def test_load_config_handles_config_load_error(window_factory, monkeypatch, tmp_path):
    w = window_factory()
    events = []

    err = ConfigLoadError(tmp_path / "config.json", ValueError("bad"), tmp_path / "backup.json")
    monkeypatch.setattr(w.config_repo, "load", lambda: (_ for _ in ()).throw(err))
    monkeypatch.setattr(w, "_log_error", lambda msg, **_k: events.append(("error", msg)))
    monkeypatch.setattr(w, "_reset_controls_to_default", lambda: events.append(("reset", None)))
    monkeypatch.setattr(w, "_update_enabled_states", lambda: events.append(("enabled", None)))

    w._load_config()

    assert any("Failed to load config from" in e[1] for e in events if e[0] == "error")
    assert ("reset", None) in events
    assert ("enabled", None) in events


def test_load_config_success_applies_effects_and_updates(window_factory, monkeypatch, tmp_path):
    from config_repository import Config

    w = window_factory()
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


@pytest.mark.parametrize(
    ("direct_input", "expected"),
    [
        (True, "available"),
        (False, "not available"),
    ],
)
def test_log_startup_capabilities_logs_windows_direct_input_status(
    window_factory, monkeypatch, tmp_path, direct_input, expected
):
    w = window_factory()
    logs = []

    monkeypatch.setattr(
        "main_window.get_capabilities",
        lambda: {
            "platform": "win32",
            "high_res_timer": True,
            "direct_input": direct_input,
        },
    )
    monkeypatch.setattr("main_window.jukebox_logger.info", lambda m: logs.append(m))

    w._log_startup_capabilities()

    assert "Platform: win32; high-resolution timer: available." in logs
    assert f"Windows direct input (pydirectinput): {expected}." in logs


def test_close_event_logs_save_config_exception(window_factory, monkeypatch, tmp_path):
    w = window_factory()

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
    w._config_dirty = True

    e = E()
    w.closeEvent(cast(Any, e))

    assert e.accepted is True
    assert any("Error flushing config" in m for m in logs)
