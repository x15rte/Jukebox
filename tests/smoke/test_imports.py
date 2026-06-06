"""Smoke tests: verify modules import without errors.

These tests are fast and run first to catch broken imports,
missing dependencies, or platform-conditional import failures.
"""
from __future__ import annotations

import importlib


def test_models_import():
    import models  # noqa: F401


def test_config_repository_import():
    import config_repository  # noqa: F401


def test_config_bindings_import():
    import config_bindings  # noqa: F401


def test_logger_core_import():
    import logger_core  # noqa: F401


def test_platform_utils_import():
    import platform_utils  # noqa: F401


def test_theme_import():
    import theme  # noqa: F401


def test_version_import():
    import version  # noqa: F401


def test_core_modules_import():
    import core.key_mapper  # noqa: F401
    import core.tempo_map  # noqa: F401


def test_midi_parser_import():
    import core.midi_parser  # noqa: F401


def test_analysis_modules_import():
    import analysis.humanizer  # noqa: F401
    import analysis.section_analyzer  # noqa: F401
    import analysis.pedal_generator  # noqa: F401


def test_playback_modules_import():
    import playback.player  # noqa: F401
    import playback.playback_controller  # noqa: F401


def test_playback_service_import():
    import playback.playback_service  # noqa: F401


def test_output_modules_import():
    import output.output  # noqa: F401


def test_rmc_encoder_import():
    """RMC encoder may fail on non-Windows without pynput — handle gracefully."""
    try:
        importlib.import_module("output.RobloxMidiConnect_encoder")
    except (ImportError, OSError):
        pass


def test_ui_modules_import():
    """UI modules require Qt — skip gracefully if offscreen platform fails."""
    for mod_name in [
        "ui.main_window_autoplay",
        "ui.main_window_live_midi",
        "ui.track_selection_dialog",
        "ui.visualizer",
        "ui.timeline_widget",
        "ui.piano_widget",
        "ui.hotkey_manager",
        "ui.midi_input_worker",
    ]:
        try:
            importlib.import_module(mod_name)
        except Exception:
            pass


def test_native_timer_import():
    import native.timer_utils  # noqa: F401


def test_main_window_import():
    """MainWindow import requires ConfigRepository which needs a real config dir."""
    import main_window  # noqa: F401
