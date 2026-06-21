"""Config-to-UI binding helpers for Jukebox MainWindow.

Each ``ConfigBinding`` declares the getter/setter lambdas that bridge a
``Config`` field to a MainWindow widget.  The ``is_effectful`` flag marks
fields whose setter triggers side-effects beyond the widget itself
(log-level change, input-mode visibility toggling, etc.) — these are
applied after a full config load but skipped during normal UI→Config reads.
"""

from dataclasses import dataclass, fields
from typing import Any, Callable, Iterable

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtWidgets import QApplication

from config_repository import Config
from logger_core import jukebox_logger, LOG_FILENAME


@dataclass(frozen=True)
class ConfigBinding:
    """Declarative mapping from a Config field to a MainWindow widget pair.

    Attributes:
        key: The ``Config`` field name (must match a dataclass field exactly).
        getter: Callable[MainWindow] → value — reads the widget state.
        setter: Callable[MainWindow, value] → None — writes the widget state.
        is_effectful: If True, the setter has side-effects beyond the widget
            (e.g. toggling visibility, starting/stopping a service). These
            are applied on config load but skipped during UI-only reads.
    """

    key: str
    getter: Callable[[Any], Any]
    setter: Callable[[Any, Any], None]
    is_effectful: bool = False

def _get_pedal_style(w: Any) -> str:
    val = w.pedal_mapping.get(w.pedal_style_combo.currentText())
    if val is None:
        jukebox_logger.warning(f"Unknown pedal style text: {w.pedal_style_combo.currentText()}, falling back to original")
        val = "original"
    return val


def _set_pedal_style(w: Any, v: str) -> None:
    mapped = w.pedal_mapping_inv.get(v)
    if mapped is None:
        jukebox_logger.warning(f"Unknown pedal style value: {v}, falling back to Original")
        mapped = "Original (from MIDI)"
    w.pedal_style_combo.setCurrentText(mapped)
    if w.pedal_style_combo.currentText() != mapped:
        jukebox_logger.warning(f"Pedal style '{mapped}' not in combo, using first option")
        w.pedal_style_combo.setCurrentIndex(0)


CONFIG_UI_BINDINGS: list[ConfigBinding] = [
    ConfigBinding(
        "tempo",
        lambda w: w.tempo_spinbox.value(),
        lambda w, v: w.tempo_spinbox.setValue(v),
    ),
    ConfigBinding(
        "output_mode",
        lambda w: w._current_output_mode(),
        lambda w, v: _set_output_mode_combo(w, v),
    ),
    ConfigBinding(
        "pedal_style",
        lambda w: _get_pedal_style(w),
        lambda w, v: _set_pedal_style(w, v),
    ),
    ConfigBinding(
        "use_88_key_layout",
        lambda w: w.use_88_key_check.isChecked(),
        lambda w, v: w.use_88_key_check.setChecked(v),
    ),
    ConfigBinding(
        "countdown",
        lambda w: w.countdown_check.isChecked(),
        lambda w, v: w.countdown_check.setChecked(v),
    ),
    ConfigBinding(
        "input_mode",
        lambda w: "piano" if w.input_mode_piano_radio.isChecked() else "file",
        lambda w, v: _set_input_mode(w, v),
        is_effectful=True,
    ),
    ConfigBinding(
        "midi_input_device",
        lambda w: w.midi_input_combo.currentText().strip() or None,
        lambda w, v: w.midi_input_combo.setCurrentText(v or ""),
    ),
    ConfigBinding(
        "autoplay_folder",
        lambda w: w.autoplay_folder,
        lambda w, v: w._set_autoplay_folder_path(v),
    ),
    ConfigBinding(
        "autoplay_mode",
        lambda w: w.input_mode_playlist_radio.isChecked(),
        lambda w, v: _set_file_submode(w, v),
    ),
    ConfigBinding(
        "autoplay_delay",
        lambda w: w.autoplay_delay_spinbox.value(),
        lambda w, v: w.autoplay_delay_spinbox.setValue(v),
    ),
    ConfigBinding(
        "autoplay_random_delay",
        lambda w: w.autoplay_random_delay_spinbox.value(),
        lambda w, v: w.autoplay_random_delay_spinbox.setValue(v),
    ),
    ConfigBinding(
        "select_all_humanization",
        lambda w: w.select_all_humanization_check.isChecked(),
        lambda w, v: w.select_all_humanization_check.setChecked(v),
    ),
    ConfigBinding(
        "simulate_hands",
        lambda w: w.all_humanization_checks["simulate_hands"].isChecked(),
        lambda w, v: w.all_humanization_checks["simulate_hands"].setChecked(v),
    ),
    ConfigBinding(
        "enable_chord_roll",
        lambda w: w.all_humanization_checks["enable_chord_roll"].isChecked(),
        lambda w, v: w.all_humanization_checks["enable_chord_roll"].setChecked(v),
    ),
    ConfigBinding(
        "enable_vary_timing",
        lambda w: w.all_humanization_checks["vary_timing"].isChecked(),
        lambda w, v: w.all_humanization_checks["vary_timing"].setChecked(v),
    ),
    ConfigBinding(
        "value_timing_variance",
        lambda w: w.all_humanization_spinboxes["vary_timing"].value(),
        lambda w, v: w.all_humanization_spinboxes["vary_timing"].setValue(v),
    ),
    ConfigBinding(
        "enable_vary_articulation",
        lambda w: w.all_humanization_checks["vary_articulation"].isChecked(),
        lambda w, v: w.all_humanization_checks["vary_articulation"].setChecked(v),
    ),
    ConfigBinding(
        "value_articulation",
        lambda w: w.all_humanization_spinboxes["vary_articulation"].value(),
        lambda w, v: w.all_humanization_spinboxes["vary_articulation"].setValue(v),
    ),
    ConfigBinding(
        "enable_hand_drift",
        lambda w: w.all_humanization_checks["hand_drift"].isChecked(),
        lambda w, v: w.all_humanization_checks["hand_drift"].setChecked(v),
    ),
    ConfigBinding(
        "value_hand_drift_decay",
        lambda w: w.all_humanization_spinboxes["hand_drift"].value(),
        lambda w, v: w.all_humanization_spinboxes["hand_drift"].setValue(v),
    ),
    ConfigBinding(
        "enable_mistakes",
        lambda w: w.all_humanization_checks["mistake_chance"].isChecked(),
        lambda w, v: w.all_humanization_checks["mistake_chance"].setChecked(v),
    ),
    ConfigBinding(
        "value_mistake_chance",
        lambda w: w.all_humanization_spinboxes["mistake_chance"].value(),
        lambda w, v: w.all_humanization_spinboxes["mistake_chance"].setValue(v),
    ),
    ConfigBinding(
        "enable_tempo_sway",
        lambda w: w.all_humanization_checks["tempo_sway"].isChecked(),
        lambda w, v: w.all_humanization_checks["tempo_sway"].setChecked(v),
    ),
    ConfigBinding(
        "value_tempo_sway_intensity",
        lambda w: w.all_humanization_spinboxes["tempo_sway"].value(),
        lambda w, v: w.all_humanization_spinboxes["tempo_sway"].setValue(v),
    ),
    ConfigBinding(
        "invert_tempo_sway",
        lambda w: w.all_humanization_checks["invert_tempo_sway"].isChecked(),
        lambda w, v: w.all_humanization_checks["invert_tempo_sway"].setChecked(v),
    ),
    ConfigBinding(
        "always_on_top",
        lambda w: w.always_top_check.isChecked(),
        lambda w, v: w.always_top_check.setChecked(v),
    ),
    ConfigBinding(
        "opacity",
        lambda w: w.opacity_slider.value(),
        lambda w, v: w.opacity_slider.setValue(v),
    ),
    ConfigBinding(
        "hotkey",
        lambda w: w.hotkey_manager.format_key_string(w.hotkey_manager.get_current_key()),
        lambda w, v: _set_hotkey_from_config(w, v),
    ),
    ConfigBinding(
        "window_geometry",
        lambda w: _get_window_geometry(w),
        lambda w, v: _set_window_geometry(w, v),
    ),
    ConfigBinding(
        "save_log_to_file",
        lambda w: w.log_save_to_file_check.isChecked(),
        lambda w, v: _set_save_log_to_file_checkbox(w, v),
        is_effectful=True,
    ),
    ConfigBinding(
        "log_level",
        lambda w: w.log_level_combo.currentText(),
        lambda w, v: _set_log_level_combo(w, v),
        is_effectful=True,
    ),
]


# Utility helpers ------------------------------------------------------------

def effectful_keys() -> set[str]:
    """Return the set of binding keys that have side-effects."""
    return {b.key for b in CONFIG_UI_BINDINGS if b.is_effectful}


def validate_config_ui_bindings(bindings: Iterable[ConfigBinding] = CONFIG_UI_BINDINGS) -> None:
    """Validate every binding: known field, callable getter/setter, no duplicates."""
    known_fields = {f.name for f in fields(Config)}
    seen: set[str] = set()
    duplicates: set[str] = set()

    for entry in bindings:
        if not isinstance(entry, ConfigBinding):
            raise ValueError("Each binding must be a ConfigBinding instance")
        key = entry.key
        if key in seen:
            duplicates.add(key)
        seen.add(key)
        if key not in known_fields:
            raise ValueError(f"Unknown config binding key: {key}")
        if not callable(entry.getter) or not callable(entry.setter):
            raise ValueError(f"Binding functions must be callable for key: {key}")

    if duplicates:
        dupes = ", ".join(sorted(duplicates))
        raise ValueError(f"Duplicate config binding keys: {dupes}")


def apply_config_effects(widget, config) -> None:
    _apply_input_mode(widget, config.input_mode)
    _set_save_log_to_file(widget, config.save_log_to_file)
    _set_log_level(widget, config.log_level)


def _set_input_mode(widget, value):
    widget.input_mode_file_radio.blockSignals(True)
    widget.input_mode_piano_radio.blockSignals(True)
    try:
        widget.input_mode_file_radio.setChecked(value != "piano")
        widget.input_mode_piano_radio.setChecked(value == "piano")
    finally:
        widget.input_mode_file_radio.blockSignals(False)
        widget.input_mode_piano_radio.blockSignals(False)


def _apply_input_mode(widget, value):
    """Set input mode radios and trigger visibility updates without calling private methods."""
    _set_input_mode(widget, value)
    use_piano = value == "piano"
    if hasattr(widget, "file_input_widget"):
        widget.file_input_widget.setVisible(not use_piano)
    if hasattr(widget, "piano_input_widget"):
        widget.piano_input_widget.setVisible(use_piano)
    if hasattr(widget, "_playback_file_only_widget"):
        widget._playback_file_only_widget.setVisible(not use_piano)
    if hasattr(widget, "tabs"):
        widget.tabs.setTabEnabled(1, not use_piano)
        widget.tabs.setTabEnabled(2, not use_piano)
        if use_piano and widget.tabs.currentIndex() in (1, 2):
            widget.tabs.setCurrentIndex(0)
    if use_piano and hasattr(widget, "_refresh_midi_inputs"):
        widget._refresh_midi_inputs(show_dialog=False)
    elif not use_piano and getattr(widget, "midi_input_active", False):
        if hasattr(widget, "_disconnect_midi_input"):
            widget._disconnect_midi_input()


def _set_file_submode(widget, use_playlist: bool):
    """Set the single-file vs playlist sub-radio under File (MIDI) mode."""
    widget.input_mode_single_radio.blockSignals(True)
    widget.input_mode_playlist_radio.blockSignals(True)
    try:
        widget.input_mode_single_radio.setChecked(not use_playlist)
        widget.input_mode_playlist_radio.setChecked(use_playlist)
    finally:
        widget.input_mode_single_radio.blockSignals(False)
        widget.input_mode_playlist_radio.blockSignals(False)
    if not widget.input_mode_piano_radio.isChecked():
        if hasattr(widget, "_on_file_submode_changed"):
            widget._on_file_submode_changed(True)


def _set_output_mode_combo(widget, value):
    """Set output_mode_combo by internal value (e.g. 'key', 'midi_numpad')."""
    for i in range(widget.output_mode_combo.count()):
        if widget.output_mode_combo.itemData(i) == value:
            widget.output_mode_combo.setCurrentIndex(i)
            break
    else:
        jukebox_logger.warning(f"Output mode '{value}' not available, using first option")
        widget.output_mode_combo.setCurrentIndex(0)
    if hasattr(widget, "_update_88_key_visibility"):
        widget._update_88_key_visibility()


def _set_hotkey_from_config(widget, value):
    if not value:
        return
    # QKeySequence is case-insensitive for special keys; pass the config value directly
    widget.hotkey_manager.set_hotkey(value)
    widget.hk_label.setText(
        f"Start/Stop Hotkey: {widget.hotkey_manager.format_key_string(widget.hotkey_manager.get_current_key())}"
    )
def _get_window_geometry(widget):
    ws = widget.windowState()
    flag = getattr(ws, "value", ws)  # get int value from enum, or use directly if already int
    if flag & Qt.WindowState.WindowMinimized.value:
        return None  # saveGeometry().size() is 0 when iconified
    g = widget.saveGeometry()
    return g.toBase64().data().decode("ascii") if g.size() else None


def _set_window_geometry(widget, value):
    if not value:
        return
    data = QByteArray.fromBase64(value.encode("ascii"))
    if not data.isEmpty():
        if not widget.restoreGeometry(data):
            # Saved geometry is invalid (screen disconnected, etc.)
            # Move to center of primary screen
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                widget.move(geo.center() - widget.rect().center())


def _set_save_log_to_file_checkbox(widget, value):
    widget.log_save_to_file_check.blockSignals(True)
    try:
        widget.log_save_to_file_check.setChecked(bool(value))
    finally:
        widget.log_save_to_file_check.blockSignals(False)


def _set_log_level_combo(widget, value):
    if not value:
        value = "INFO"
    level = str(value).upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        level = "INFO"
    if widget.log_level_combo.currentText() != level:
        widget.log_level_combo.blockSignals(True)
        try:
            widget.log_level_combo.setCurrentText(level)
        finally:
            widget.log_level_combo.blockSignals(False)


def _set_save_log_to_file(widget, value):
    _set_save_log_to_file_checkbox(widget, value)
    log_dir = getattr(widget, "config_dir", None)
    if log_dir is None:
        if value:
            jukebox_logger.warning(
                "Cannot enable file logging: config_dir is not set. "
                "File logging will be activated once config_dir is available."
            )
        return
    log_path = log_dir / LOG_FILENAME
    if value:
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            jukebox_logger.enable_file_logging(str(log_path))
            widget.add_log_message(f"Log is being saved to: {log_path}")
        except Exception as e:
            widget.add_log_message(f"Failed to enable file logging: {e}")
    else:
        jukebox_logger.disable_file_logging()


def _set_log_level(widget, value):
    normalized = str(value).upper()
    _set_log_level_combo(widget, normalized)
    actual_level = widget.log_level_combo.currentText()
    if actual_level != normalized:
        jukebox_logger.warning(f"Log level '{value}' not available, using '{actual_level}'")
        value = actual_level
    else:
        value = normalized
    jukebox_logger.set_level(value)
