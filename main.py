#!/usr/bin/env python3
"""Jukebox GUI: MIDI file/track selection, humanization options, playback (key or Roblox MIDI Connect), hotkey, config persistence."""

import sys
import os
import re
import copy
import shutil
import subprocess  # nosec B404: used with fixed args to query local git only
from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QCheckBox, QSlider, QLabel, QFileDialog,
    QGroupBox, QTabWidget, QComboBox, QDoubleSpinBox,
    QMessageBox, QGridLayout, QStatusBar, QScrollArea, QRadioButton, QLineEdit,
    QTextBrowser, QDialog,
)
from PyQt6.QtCore import QThread, QTimer, QByteArray, pyqtSignal as Signal, Qt
from PyQt6.QtGui import QFont, QIcon
import mido

from models import Note
from core import MidiParser
from visualizer import PianoWidget, TimelineWidget
from player import Player
from output import create_backend
from logger_core import jukebox_logger
from config_repository import Config, ConfigRepository, ConfigLoadError
from playback_service import PlaybackService
from platform_utils import (
    set_app_user_model_id,
    get_capabilities,
    is_macos_accessibility_trusted,
    open_macos_accessibility_preferences,
)
from ui_dialogs import HotkeyManager, TrackSelectionDialog, MidiInputWorker, parse_hotkey_string

APP_NAME = "Jukebox"
APP_ID = "jukebox.piano"
APP_URL = "https://github.com/x15rte/Jukebox"
LOG_FILENAME = "log.txt"
MAX_LOG_ENTRIES = 5000


def _get_git_version() -> str:
    """Return short git rev (HEAD) for display; empty if not a repo or on error."""
    try:
        git_path = shutil.which("git")
        if not git_path:
            return ""
        result = subprocess.run(  # nosec: fixed args, absolute git path from shutil.which; not user-controlled
            [git_path, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        # Not a git repository or git is unavailable; omit version suffix.
        return ""
    return ""


APP_VERSION = _get_git_version()


def _set_output_mode_combo(widget, value):
    """Set output_mode_combo by internal value (e.g. 'key', 'midi_numpad')."""
    for i in range(widget.output_mode_combo.count()):
        if widget.output_mode_combo.itemData(i) == value:
            widget.output_mode_combo.setCurrentIndex(i)
            break
    widget._update_88_key_visibility()


# Single source of truth: Config field name -> (get from UI, set to UI). Used by _config_from_ui and _apply_config_to_ui.
CONFIG_UI_BINDINGS = [
    ("tempo", lambda w: w.tempo_spinbox.value(), lambda w, v: w.tempo_spinbox.setValue(v)),
    ("output_mode", lambda w: w._current_output_mode(), lambda w, v: _set_output_mode_combo(w, v)),
    ("pedal_style", lambda w: w.pedal_mapping.get(w.pedal_style_combo.currentText(), "hybrid"),
     lambda w, v: w.pedal_style_combo.setCurrentText(w.pedal_mapping_inv.get(v, "Original (from MIDI)"))),
    ("use_88_key_layout", lambda w: w.use_88_key_check.isChecked(), lambda w, v: w.use_88_key_check.setChecked(v)),
    ("countdown", lambda w: w.countdown_check.isChecked(), lambda w, v: w.countdown_check.setChecked(v)),
    ("input_mode", lambda w: "piano" if w.input_mode_piano_radio.isChecked() else "file",
     lambda w, v: (_set_input_mode(w, v), w._on_input_mode_changed())),
    ("midi_input_device", lambda w: w.midi_input_combo.currentText().strip() or None,
     lambda w, v: w.midi_input_combo.setCurrentText(v or "")),
    ("select_all_humanization", lambda w: w.select_all_humanization_check.isChecked(),
     lambda w, v: w.select_all_humanization_check.setChecked(v)),
    ("simulate_hands", lambda w: w.all_humanization_checks["simulate_hands"].isChecked(),
     lambda w, v: w.all_humanization_checks["simulate_hands"].setChecked(v)),
    ("enable_chord_roll", lambda w: w.all_humanization_checks["enable_chord_roll"].isChecked(),
     lambda w, v: w.all_humanization_checks["enable_chord_roll"].setChecked(v)),
    ("enable_vary_timing", lambda w: w.all_humanization_checks["vary_timing"].isChecked(),
     lambda w, v: w.all_humanization_checks["vary_timing"].setChecked(v)),
    ("value_timing_variance", lambda w: w.all_humanization_spinboxes["vary_timing"].value(),
     lambda w, v: w.all_humanization_spinboxes["vary_timing"].setValue(v)),
    ("enable_vary_articulation", lambda w: w.all_humanization_checks["vary_articulation"].isChecked(),
     lambda w, v: w.all_humanization_checks["vary_articulation"].setChecked(v)),
    ("value_articulation", lambda w: w.all_humanization_spinboxes["vary_articulation"].value(),
     lambda w, v: w.all_humanization_spinboxes["vary_articulation"].setValue(v)),
    ("enable_hand_drift", lambda w: w.all_humanization_checks["hand_drift"].isChecked(),
     lambda w, v: w.all_humanization_checks["hand_drift"].setChecked(v)),
    ("value_hand_drift_decay", lambda w: w.all_humanization_spinboxes["hand_drift"].value(),
     lambda w, v: w.all_humanization_spinboxes["hand_drift"].setValue(v)),
    ("enable_mistakes", lambda w: w.all_humanization_checks["mistake_chance"].isChecked(),
     lambda w, v: w.all_humanization_checks["mistake_chance"].setChecked(v)),
    ("value_mistake_chance", lambda w: w.all_humanization_spinboxes["mistake_chance"].value(),
     lambda w, v: w.all_humanization_spinboxes["mistake_chance"].setValue(v)),
    ("enable_tempo_sway", lambda w: w.all_humanization_checks["tempo_sway"].isChecked(),
     lambda w, v: w.all_humanization_checks["tempo_sway"].setChecked(v)),
    ("value_tempo_sway_intensity", lambda w: w.all_humanization_spinboxes["tempo_sway"].value(),
     lambda w, v: w.all_humanization_spinboxes["tempo_sway"].setValue(v)),
    ("invert_tempo_sway", lambda w: w.all_humanization_checks["invert_tempo_sway"].isChecked(),
     lambda w, v: w.all_humanization_checks["invert_tempo_sway"].setChecked(v)),
    ("always_on_top", lambda w: w.always_top_check.isChecked(), lambda w, v: w.always_top_check.setChecked(v)),
    ("opacity", lambda w: w.opacity_slider.value(),
     lambda w, v: (w.opacity_slider.setValue(v), w._change_opacity(v))),
    ("hotkey", lambda w: w.hotkey_manager._format_key_string(w.hotkey_manager.current_key),
     lambda w, v: _set_hotkey_from_config(w, v)),
    ("window_geometry", lambda w: _get_window_geometry(w), lambda w, v: _set_window_geometry(w, v)),
    ("save_log_to_file", lambda w: w.log_save_to_file_check.isChecked(),
     lambda w, v: _set_save_log_to_file(w, v)),
    ("log_level", lambda w: w.log_level_combo.currentText(),
     lambda w, v: _set_log_level(w, v)),
]


def _set_input_mode(widget, value):
    widget.input_mode_file_radio.setChecked(value != "piano")
    widget.input_mode_piano_radio.setChecked(value == "piano")


def _set_hotkey_from_config(widget, value):
    if not value:
        return
    widget.hotkey_manager.current_key = parse_hotkey_string(value)
    widget.hk_label.setText(f"Start/Stop Hotkey: {widget.hotkey_manager._format_key_string(widget.hotkey_manager.current_key)}")


def _get_window_geometry(widget):
    g = widget.saveGeometry()
    return g.toBase64().data().decode("ascii") if g.size() else None


def _set_window_geometry(widget, value):
    if not value:
        return
    data = QByteArray.fromBase64(value.encode("ascii"))
    if not data.isEmpty():
        widget.restoreGeometry(data)


def _set_save_log_to_file(widget, value):
    widget.log_save_to_file_check.setChecked(value)
    if value:
        widget.add_log_message(f"Log is being saved to: {widget._get_log_file_path()}")


def _set_log_level(widget, value):
    if not value:
        return
    level = str(value).upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        level = "INFO"
    if widget.log_level_combo.currentText() != level:
        widget.log_level_combo.blockSignals(True)
        widget.log_level_combo.setCurrentText(level)
        widget.log_level_combo.blockSignals(False)
    jukebox_logger.set_level(level)


class MainWindow(QMainWindow):
    """Tabs: Playback (file, tracks, humanization), Visualizer (timeline + piano), Settings (hotkey, overlay), Output (log). Saves/loads config.json; optional log to file."""

    # (level: str, message: str) -> emitted from any thread, handled on GUI thread.
    log_record_received = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} ({APP_VERSION})" if APP_VERSION else APP_NAME)
        self.setMinimumSize(780, 520)
        self.player_thread = None
        self.player = None
        self.midi_input_thread = None
        self.midi_input_worker = None
        self.midi_input_active = False
        self.config_repo = ConfigRepository()
        self.config_dir = self.config_repo.config_dir
        self.config_path = self.config_repo.config_path
        self.config_repo.ensure_config_dir()
        self.selected_tracks_info = None 
        self.parsed_tempo_map = None
        self.current_notes = [] 
        self.total_song_duration_sec = 1.0
        self._log_entries = []

        self.hotkey_manager = HotkeyManager()
        self.hotkey_manager.toggle_requested.connect(self.toggle_playback_state)
        self.hotkey_manager.bound_updated.connect(self._on_hotkey_bound)

        # Bridge central logger into the GUI via a Qt signal so that all
        # widget updates happen on the main thread.
        self.log_record_received.connect(self._on_log_record)

        def _gui_log_callback(level: str, message: str) -> None:
            # This callback may be invoked from any thread; emitting a
            # Qt signal ensures the actual UI work is performed safely
            # on the main thread.
            self.log_record_received.emit(level, message)

        jukebox_logger.set_gui_callback(_gui_log_callback)
        
        self.pedal_mapping = {
            "Original (from MIDI)": "original",
            "Automatic": "hybrid",
            "Always Sustain": "legato",
            "Rhythmic Only": "rhythmic",
            "No Pedal": "none"
        }
        self.pedal_mapping_inv = {v: k for k, v in self.pedal_mapping.items()}

        self.live_backend = None

        self._setup_ui()
        self._load_config()
        self.use_88_key_check.toggled.connect(self._on_key_layout_changed)

        ver_tag = f" ({APP_VERSION})" if APP_VERSION else ""
        self.add_log_message(f'{APP_NAME}{ver_tag} — <a href="{APP_URL}">{APP_URL}</a>')
        self._log_startup_capabilities()
        QTimer.singleShot(0, self._check_macos_accessibility)

    def _setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(10, 10, 10, 5)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        controls_tab, visual_tab, log_tab = QWidget(), QWidget(), QWidget()
        self.tabs.addTab(controls_tab, "Playback")
        self.tabs.addTab(visual_tab, "Visualizer")
        self.tabs.addTab(log_tab, "Output")

        # Visualizer tab: scrollable timeline + piano strip.
        vis_layout = QVBoxLayout(visual_tab)
        vis_layout.setContentsMargins(5, 5, 5, 5)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True) 
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.timeline_widget = TimelineWidget()
        self.timeline_widget.seek_requested.connect(self._on_timeline_seek)
        self.timeline_widget.scrub_position_changed.connect(self._on_visual_scrub)
        
        self.scroll_area.setWidget(self.timeline_widget)
        vis_layout.addWidget(self.scroll_area)
        
        self.piano_widget = PianoWidget()
        vis_layout.addWidget(self.piano_widget)

        # Playback tab: left column = Input/Output + Humanization, right column = Settings (wider, less tall).
        controls_main = QHBoxLayout(controls_tab)
        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self._create_input_output_group())
        self.humanization_group = self._create_humanization_group()
        left_layout.addWidget(self.humanization_group)
        left_layout.addStretch()
        controls_main.addWidget(left_column, 1)
        self.settings_group = self._create_settings_group()
        self.settings_group.setMinimumWidth(260)
        controls_main.addWidget(self.settings_group, 0)

        self.log_output = QTextBrowser()
        self.log_output.setOpenExternalLinks(True)
        self.log_output.setFont(QFont("Courier", 9))
        log_layout = QVBoxLayout(log_tab)
        log_layout.addWidget(self.log_output)
        
        # Top row: log actions, level, and persistence
        log_btn_layout = QHBoxLayout()
        clear_btn = QPushButton("Clear")
        copy_btn = QPushButton("Copy to Clipboard")
        log_level_label = QLabel("Log level:")
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_combo.setCurrentText("INFO")
        self.log_level_combo.setToolTip("Minimum level to show in console and log file.")
        self.log_level_combo.currentTextChanged.connect(self._on_log_level_changed)
        self.log_save_to_file_check = QCheckBox("Save log to file")
        self.log_save_to_file_check.setChecked(False)
        self.log_save_to_file_check.toggled.connect(self._on_log_save_to_file_toggled)
        clear_btn.clicked.connect(self.log_output.clear)
        copy_btn.clicked.connect(self._copy_log_to_clipboard)
        log_btn_layout.addWidget(clear_btn)
        log_btn_layout.addWidget(copy_btn)
        log_btn_layout.addWidget(log_level_label)
        log_btn_layout.addWidget(self.log_level_combo)
        log_btn_layout.addWidget(self.log_save_to_file_check)
        log_btn_layout.addStretch()
        log_layout.addLayout(log_btn_layout)

        # Second row: text filter for log contents (separated from persistence controls)
        filter_layout = QHBoxLayout()
        filter_label = QLabel("Filter:")
        self.log_filter_edit = QLineEdit()
        self.log_filter_edit.setPlaceholderText("Filter log text...")
        self.log_filter_edit.textChanged.connect(self._apply_log_filter)
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.log_filter_edit)
        filter_layout.addStretch()
        log_layout.addLayout(filter_layout)

        # Bottom: time display, Play/Stop, Reset.
        media_layout = QHBoxLayout()
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        media_layout.addWidget(self.time_label)

        button_layout = QHBoxLayout()
        self.play_button = QPushButton("Play") 
        self.stop_button = QPushButton("Stop")
        self.reset_button = QPushButton("Reset")
        button_layout.addWidget(self.play_button)
        button_layout.addWidget(self.stop_button)
        button_layout.addWidget(self.reset_button)
        button_layout.addStretch()
        self.current_file_bottom_label = QLabel("No file selected.")
        self.current_file_bottom_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        button_layout.addWidget(self.current_file_bottom_label)

        main_layout.addLayout(media_layout)
        main_layout.addLayout(button_layout)
        
        self._update_play_stop_labels()
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        self.play_button.clicked.connect(self.handle_play)
        self.stop_button.clicked.connect(self.handle_stop)
        self.reset_button.clicked.connect(self.handle_reset)
        self.play_button.setEnabled(False) 
        self.stop_button.setEnabled(False)
        self.reset_button.setEnabled(False)

    def _toggle_always_on_top(self, checked):
        flags = self.windowFlags()
        if checked: self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        else: self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
        self.show()

    def _change_opacity(self, value):
        self.setWindowOpacity(value / 100.0)

    def _change_hotkey(self):
        self.hk_btn.setText("Listening...")
        self.hk_btn.setEnabled(False)
        self.hotkey_manager.start_binding()
        QMessageBox.information(self, "Bind Key", "Press the key you want to bind now.")

    def _on_hotkey_bound(self, key_str):
        self.hk_label.setText(f"Start/Stop Hotkey: {key_str}")
        self.hk_btn.setText("Change")
        self.hk_btn.setEnabled(True)
        self._update_play_stop_labels()

    def _update_play_stop_labels(self):
        key_str = self.hotkey_manager._format_key_string(self.hotkey_manager.current_key)
        if not self.player: self.play_button.setText(f"Play ({key_str})")
        self.stop_button.setText(f"Stop")

    def toggle_playback_state(self):
        if self.player and self.player.pause_event.is_set(): pass 
        else: self.piano_widget.clear()

        if self.player_thread and self.player_thread.isRunning():
            self.player.toggle_pause()
            self._update_pause_ui_state()
            if not self.player.pause_event.is_set():
                current_t = self.timeline_widget.current_time
                self._on_visual_scrub(current_t)
        elif self.play_button.isEnabled():
            self.handle_play()

    def _update_pause_ui_state(self):
        key_str = self.hotkey_manager._format_key_string(self.hotkey_manager.current_key)
        if self.player and self.player.pause_event.is_set():
            self.play_button.setText(f"Resume ({key_str})")
        else:
            self.play_button.setText(f"Pause ({key_str})")

    def _on_auto_paused(self):
        self._update_pause_ui_state()
        self.piano_widget.clear()
        self.stop_button.setEnabled(True)

    def _on_timeline_seek(self, time):
        self.add_log_message(f"Seeking to {time:.2f}s...")
        if self.player: self.player.seek(time)
    
    def _on_visual_scrub(self, time):
        active_pitches = set()
        for note in self.current_notes:
            if note.start_time <= time < note.end_time: active_pitches.add(note.pitch)
        self.piano_widget.set_active_pitches(active_pitches)
        self._update_time_label(time, self.total_song_duration_sec)

    def update_progress(self, current_time):
        if self.player and self.player.total_duration > 0:
            self.total_song_duration_sec = self.player.total_duration
        if not self.timeline_widget.is_dragging:
            self.timeline_widget.set_position(current_time)
            self.piano_widget.update()
            self._update_time_label(current_time, self.total_song_duration_sec)
            timeline_width = self.timeline_widget.width()
            scroll_width = self.scroll_area.width()
            if self.total_song_duration_sec > 0:
                ratio = current_time / self.total_song_duration_sec
                cursor_x = ratio * timeline_width
                target_scroll = cursor_x - (scroll_width / 2)
                self.scroll_area.horizontalScrollBar().setValue(int(target_scroll))

    def _update_time_label(self, current, total):
        def fmt(s):
            m = int(s // 60); sec = int(s % 60)
            return f"{m:02d}:{sec:02d}"
        self.time_label.setText(f"{fmt(current)} / {fmt(total)}")

    def _copy_log_to_clipboard(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.log_output.toPlainText())
        self.statusBar().showMessage("Log copied to clipboard!", 2000)

    def _create_info_icon(self, tooltip_text: str) -> QLabel:
        label = QLabel("\u24D8")
        label.setStyleSheet("color: gray; font-weight: bold;")
        label.setToolTip(tooltip_text)
        return label

    def _create_slider_and_spinbox(self, min_val, max_val, default_val, text_suffix="", factor=10000.0, decimals=4):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(int(min_val * factor), int(max_val * factor))
        spinbox = QDoubleSpinBox()
        spinbox.setDecimals(decimals)
        spinbox.setRange(0.0, 9999.9999)
        spinbox.setSingleStep(1.0 / factor)
        spinbox.setSuffix(text_suffix)
        slider.setValue(int(default_val * factor))
        spinbox.setValue(default_val)
        slider.valueChanged.connect(lambda v: spinbox.setValue(v / factor))
        spinbox.valueChanged.connect(lambda v: slider.setValue(int(v * factor)))
        return slider, spinbox

    def _create_input_output_group(self):
        group = QGroupBox("Input / Output")
        layout = QVBoxLayout(group)

        mode_row = QHBoxLayout()
        mode_label = QLabel("Input Mode:")
        self.input_mode_file_radio = QRadioButton("File (MIDI)")
        self.input_mode_piano_radio = QRadioButton("Piano (MIDI In)")
        self.input_mode_file_radio.setChecked(True)
        self.input_mode_file_radio.toggled.connect(self._on_input_mode_changed)
        self.input_mode_piano_radio.toggled.connect(self._on_input_mode_changed)
        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.input_mode_file_radio)
        mode_row.addWidget(self.input_mode_piano_radio)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.file_input_widget = QWidget()
        file_layout = QVBoxLayout(self.file_input_widget)
        self.file_path_label = QLabel("No file selected.")
        self.file_path_label.setStyleSheet("font-style: italic; color: grey;")
        browse_button = QPushButton("Browse for MIDI File")
        browse_button.clicked.connect(self.select_file)
        file_layout.addWidget(self.file_path_label)
        file_layout.addWidget(browse_button)
        layout.addWidget(self.file_input_widget)

        self.piano_input_widget = QWidget()
        piano_layout = QVBoxLayout(self.piano_input_widget)
        device_row = QHBoxLayout()
        device_label = QLabel("MIDI Input Device:")
        self.midi_input_combo = QComboBox()
        self.midi_input_refresh_btn = QPushButton("Refresh")
        self.midi_input_refresh_btn.clicked.connect(self._refresh_midi_inputs)
        device_row.addWidget(device_label)
        device_row.addWidget(self.midi_input_combo)
        device_row.addWidget(self.midi_input_refresh_btn)
        piano_layout.addLayout(device_row)

        control_row = QHBoxLayout()
        self.midi_input_connect_btn = QPushButton("Connect")
        self.midi_input_disconnect_btn = QPushButton("Disconnect")
        self.midi_input_disconnect_btn.setEnabled(False)
        self.midi_input_connect_btn.clicked.connect(self._connect_midi_input)
        self.midi_input_disconnect_btn.clicked.connect(self._disconnect_midi_input)
        control_row.addWidget(self.midi_input_connect_btn)
        control_row.addWidget(self.midi_input_disconnect_btn)
        control_row.addStretch(1)
        piano_layout.addLayout(control_row)

        self.midi_input_status_label = QLabel("Piano input disabled.")
        self.midi_input_status_label.setStyleSheet("font-style: italic; color: grey;")
        piano_layout.addWidget(self.midi_input_status_label)

        layout.addWidget(self.piano_input_widget)
        self.piano_input_widget.hide()

        output_row = QHBoxLayout()
        output_label = QLabel("Output Mode:")
        self.output_mode_combo = QComboBox()
        self.output_mode_combo.addItem("KEY Mode", userData="key")
        self.output_mode_combo.addItem("MIDI Numpad Mode", userData="midi_numpad")
        self.output_mode_combo.currentIndexChanged.connect(self._on_output_mode_changed)
        output_row.addWidget(output_label)
        output_row.addWidget(self.output_mode_combo)
        output_row.addStretch(1)
        layout.addLayout(output_row)

        self.use_88_key_check = QCheckBox("Use 88-Key Extended Layout")
        layout.addWidget(self.use_88_key_check)

        return group

    def _on_input_mode_changed(self):
        use_piano = self.input_mode_piano_radio.isChecked()
        self.file_input_widget.setVisible(not use_piano)
        self.piano_input_widget.setVisible(use_piano)
        self._playback_file_only_widget.setVisible(not use_piano)
        self.humanization_group.setVisible(not use_piano)
        self.settings_group.setVisible(not use_piano)
        # Visualizer tab is only relevant for file playback; grey out when using Piano input.
        self.tabs.setTabEnabled(1, not use_piano)
        if use_piano and self.tabs.currentIndex() == 1:
            self.tabs.setCurrentIndex(0)

        if use_piano:
            self._refresh_midi_inputs()
        else:
            if self.midi_input_active:
                self._disconnect_midi_input()

    def _refresh_midi_inputs(self):
        try:
            names = mido.get_input_names()
        except Exception as e:
            jukebox_logger.error(f"Failed to list MIDI input devices: {e}", exc_info=True)
            self._log_error("Failed to list MIDI input devices: " + str(e), show_dialog=True, dialog_title="Error")
            return
        self.midi_input_combo.clear()
        self.midi_input_combo.addItems(names)

    def _connect_midi_input(self):
        if self.midi_input_active:
            return

        if self.player_thread and self.player_thread.isRunning():
            self.handle_stop()

        port_name = self.midi_input_combo.currentText()
        if not port_name:
            self._log_warning("MIDI connect skipped: no device selected.")
            QMessageBox.warning(self, "No Device", "No MIDI input device selected.")
            return

        self.live_backend = create_backend(
            self._current_output_mode(),
            self.use_88_key_check.isChecked(),
            log_message=self.add_log_message)

        self.midi_input_thread = QThread()
        self.midi_input_worker = MidiInputWorker(port_name)
        self.midi_input_worker.moveToThread(self.midi_input_thread)
        self.midi_input_thread.started.connect(self.midi_input_worker.run)
        self.midi_input_worker.message_received.connect(self._handle_live_midi_message)
        self.midi_input_worker.connected.connect(lambda: self._on_midi_input_connected(port_name))
        self.midi_input_worker.connection_error.connect(self._on_midi_input_error)
        self.midi_input_worker.warning.connect(self._on_midi_input_warning)
        self.midi_input_worker.finished.connect(self.midi_input_thread.quit)
        self.midi_input_worker.finished.connect(self._on_midi_input_finished)

        self.midi_input_thread.start()
        self.midi_input_active = True
        self.midi_input_connect_btn.setEnabled(False)
        self.midi_input_disconnect_btn.setEnabled(True)
        self.midi_input_status_label.setText(f"Connecting to: {port_name}...")

    def _on_midi_input_connected(self, port_name):
        self.midi_input_status_label.setText(f"Connected to: {port_name}")
        self.add_log_message(f"Connected to MIDI input: {port_name}")

    def _on_midi_input_error(self, error_msg):
        self._log_error(f"MIDI input connection failed: {error_msg}",
                        show_dialog=True,
                        dialog_title="Connection Failed")

    def _on_midi_input_warning(self, warning_msg: str):
        self._log_warning(f"MIDI input worker: {warning_msg}")

    def _release_all_live_keys(self):
        if self.live_backend:
            self.live_backend.shutdown()

    def _disconnect_midi_input(self):
        if not self.midi_input_active:
            return
        self._release_all_live_keys()
        if self.midi_input_worker is not None:
            try:
                self.midi_input_worker.stop()
            except Exception as e:
                self.add_log_message(f"Error stopping MIDI input worker: {e}")
        if self.midi_input_thread is not None:
            self.midi_input_thread.quit()
            self.midi_input_thread.wait(2000)

    def _on_midi_input_finished(self):
        self.midi_input_active = False
        self.midi_input_thread = None
        self.midi_input_worker = None
        self.midi_input_connect_btn.setEnabled(True)
        self.midi_input_disconnect_btn.setEnabled(False)
        self.midi_input_status_label.setText("Piano input disconnected.")
        self.add_log_message("MIDI input disconnected.")

    def _current_output_mode(self) -> str:
        if hasattr(self, "output_mode_combo"):
            data = self.output_mode_combo.currentData()
            if data:
                return data
        return "key"

    def _update_88_key_visibility(self):
        """88-key layout only applies to KEY Mode; hide the option when using MIDI Numpad."""
        if hasattr(self, "use_88_key_check"):
            self.use_88_key_check.setVisible(self._current_output_mode() == "key")

    def _on_output_mode_changed(self):
        self._update_88_key_visibility()
        if self.live_backend and self.midi_input_active:
            self.live_backend.shutdown()
            self.live_backend = create_backend(
                self._current_output_mode(),
                self.use_88_key_check.isChecked(),
                log_message=self.add_log_message)

    def _on_key_layout_changed(self, _checked: bool = False):
        if self.live_backend and self.midi_input_active:
            self.live_backend.shutdown()
            self.live_backend = create_backend(
                self._current_output_mode(),
                self.use_88_key_check.isChecked(),
                log_message=self.add_log_message)

    def _handle_live_midi_message(self, msg):
        if not self.live_backend:
            return

        msg_type = getattr(msg, "type", None)

        if msg_type in ("note_on", "note_off"):
            note = getattr(msg, "note", None)
            velocity = getattr(msg, "velocity", 0)
            if note is None:
                return
            is_off = (msg_type == "note_off"
                      or (msg_type == "note_on" and velocity == 0))
            if is_off:
                self.live_backend.note_off(note)
            else:
                self.live_backend.note_on(note, velocity)
            return

        if (msg_type == "control_change"
                and getattr(msg, "control", None) == 64):
            value = getattr(msg, "value", 0)
            if value >= 64:
                self.live_backend.pedal_on()
            else:
                self.live_backend.pedal_off()

    def _create_settings_group(self):
        group = QGroupBox("Settings")
        main_layout = QVBoxLayout(group)

        self._playback_file_only_widget = QWidget()
        file_grid = QGridLayout(self._playback_file_only_widget)
        tempo_label = QLabel("Tempo")
        self.tempo_slider, self.tempo_spinbox = self._create_slider_and_spinbox(10.0, 200.0, 100.0, "%", factor=10.0, decimals=1)
        file_grid.addWidget(tempo_label, 0, 0)
        file_grid.addWidget(self.tempo_slider, 0, 2)
        file_grid.addWidget(self.tempo_spinbox, 0, 3)

        pedal_label = QLabel("Pedal Style")
        self.pedal_style_combo = QComboBox()
        self.pedal_style_combo.addItems(list(self.pedal_mapping.keys()))
        self.pedal_style_combo.setItemData(0, "Uses sustain pedal data from the MIDI file. Falls back to Automatic if none found.", Qt.ItemDataRole.ToolTipRole)
        self.pedal_style_combo.setItemData(1, "Analyzes song sections to switch between Rhythmic and Sustain.", Qt.ItemDataRole.ToolTipRole)
        self.pedal_style_combo.setItemData(2, "Ignores note length. Holds pedal until harmony changes.", Qt.ItemDataRole.ToolTipRole)
        self.pedal_style_combo.setItemData(3, "Presses pedal only while keys are held down.", Qt.ItemDataRole.ToolTipRole)
        self.pedal_style_combo.setItemData(4, "Disables auto-pedal entirely.", Qt.ItemDataRole.ToolTipRole)
        file_grid.addWidget(pedal_label, 1, 0)
        file_grid.addWidget(self.pedal_style_combo, 1, 2, 1, 2)

        countdown_row = QHBoxLayout()
        self.countdown_check = QCheckBox("3 second countdown")
        countdown_row.addWidget(self.countdown_check)
        countdown_row.addStretch()
        self.reset_defaults_btn = QPushButton("Reset Defaults")
        self.reset_defaults_btn.clicked.connect(self._reset_controls_to_default)
        countdown_row.addWidget(self.reset_defaults_btn)
        file_grid.addLayout(countdown_row, 2, 0, 1, 4)
        file_grid.setColumnStretch(2, 1)
        main_layout.addWidget(self._playback_file_only_widget)

        hk_group = QGroupBox("Hotkey")
        hk_layout = QHBoxLayout(hk_group)
        self.hk_label = QLabel(f"Start/Stop Hotkey: {self.hotkey_manager._format_key_string(self.hotkey_manager.current_key)}")
        self.hk_btn = QPushButton("Change")
        self.hk_btn.clicked.connect(self._change_hotkey)
        hk_layout.addWidget(self.hk_label)
        hk_layout.addWidget(self.hk_btn)
        main_layout.addWidget(hk_group)

        overlay_group = QGroupBox("Overlay Mode")
        ov_layout = QGridLayout(overlay_group)
        self.always_top_check = QCheckBox("Window Always on Top")
        self.always_top_check.toggled.connect(self._toggle_always_on_top)
        opacity_label = QLabel("Window Opacity:")
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(20, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self._change_opacity)
        ov_layout.addWidget(self.always_top_check, 0, 0, 1, 2)
        ov_layout.addWidget(opacity_label, 1, 0)
        ov_layout.addWidget(self.opacity_slider, 1, 1)
        main_layout.addWidget(overlay_group)

        self._reset_playback_group_to_default()
        return group

    def _create_humanization_group(self):
        group = QGroupBox("Humanization")
        main_v_layout = QVBoxLayout(group)
        self.select_all_humanization_check = QCheckBox("Select/Deselect All")
        main_v_layout.addWidget(self.select_all_humanization_check)
        self.all_humanization_checks = {}
        self.all_humanization_spinboxes = {}
        self.all_humanization_sliders = {}

        simple_toggles_layout = QHBoxLayout()
        self.all_humanization_checks['simulate_hands'] = QCheckBox("Simulate Hands")
        self.all_humanization_checks['enable_chord_roll'] = QCheckBox("Chord Rolling")
        simple_toggles_layout.addWidget(self.all_humanization_checks['simulate_hands'])
        simple_toggles_layout.addStretch(1)
        simple_toggles_layout.addWidget(self.all_humanization_checks['enable_chord_roll'])
        main_v_layout.addLayout(simple_toggles_layout)
        
        detailed_layout = QGridLayout()
        detailed_layout.setColumnStretch(2, 1) 
        
        def add_detailed_row(row_idx, name, key, min_val, max_val, def_val, suffix, factor=1.0, decimals=3):
            check = QCheckBox(name)
            slider, spinbox = self._create_slider_and_spinbox(min_val, max_val, def_val, suffix, factor=factor, decimals=decimals)
            check.toggled.connect(slider.setEnabled)
            check.toggled.connect(spinbox.setEnabled)
            detailed_layout.addWidget(check, row_idx, 0)
            detailed_layout.addWidget(slider, row_idx, 2)
            detailed_layout.addWidget(spinbox, row_idx, 3)
            self.all_humanization_checks[key] = check
            self.all_humanization_sliders[key] = slider
            self.all_humanization_spinboxes[key] = spinbox

        add_detailed_row(0, "Vary Timing", "vary_timing", 0, 0.1, 0.01, " s", factor=10000.0)
        add_detailed_row(1, "Vary Articulation", "vary_articulation", 50, 100, 95, "%", factor=100.0, decimals=1)
        add_detailed_row(2, "Hand Drift", "hand_drift", 0, 100, 25, "%", factor=100.0, decimals=1)
        add_detailed_row(3, "Mistake Chance", "mistake_chance", 0, 10, 0, "%", factor=100.0, decimals=1)
        add_detailed_row(4, "Tempo Sway", "tempo_sway", 0, 0.1, 0, " s", factor=10000.0)

        self.invert_sway_check = QCheckBox("Invert tempo sway")
        self.all_humanization_checks['invert_tempo_sway'] = self.invert_sway_check
        self.all_humanization_checks['tempo_sway'].toggled.connect(self.invert_sway_check.setEnabled)
        detailed_layout.addWidget(self.invert_sway_check, 5, 0)
        main_v_layout.addLayout(detailed_layout)
        
        self.all_humanization_checks['vary_velocity'] = QCheckBox() # Dummy for logic compatibility if needed
        self.select_all_humanization_check.toggled.connect(self._toggle_all_humanization)
        for check in self.all_humanization_checks.values():
            if check.text(): check.toggled.connect(self._update_select_all_state)
        self._reset_humanization_group_to_default()
        return group

    def _reset_controls_to_default(self):
        self.add_log_message("All settings have been reset to their default values.")
        self._reset_playback_group_to_default()
        self._reset_humanization_group_to_default()

    def _reset_playback_group_to_default(self):
        self.tempo_spinbox.setValue(100)
        self.pedal_style_combo.setCurrentText("Original (from MIDI)")
        self.use_88_key_check.setChecked(False)
        self.countdown_check.setChecked(True)

    def _reset_humanization_group_to_default(self):
        self.all_humanization_spinboxes['vary_timing'].setValue(0.010)
        self.all_humanization_spinboxes['vary_articulation'].setValue(95.0)
        self.all_humanization_spinboxes['hand_drift'].setValue(25.0)
        self.all_humanization_spinboxes['mistake_chance'].setValue(0.5)
        self.all_humanization_spinboxes['tempo_sway'].setValue(0.015)
        for check in self.all_humanization_checks.values(): 
            if check.text(): check.setChecked(False)
        self._update_enabled_states()

    def _toggle_all_humanization(self, checked):
        for check in self.all_humanization_checks.values(): 
            if check.text(): check.setChecked(checked)

    def _update_select_all_state(self):
        checks = [c for c in self.all_humanization_checks.values() if c.text()]
        is_all_checked = all(c.isChecked() for c in checks)
        self.select_all_humanization_check.blockSignals(True)
        self.select_all_humanization_check.setChecked(is_all_checked)
        self.select_all_humanization_check.blockSignals(False)

    def _get_log_file_path(self):
        return self.config_dir / LOG_FILENAME

    def _log_startup_capabilities(self) -> None:
        """Log platform and runtime capabilities (timer, pydirectinput) for user visibility."""
        caps = get_capabilities()
        timer_status = "available" if caps.get("high_res_timer") else "not available (using standard timing)"
        jukebox_logger.info(f"Platform: {caps.get('platform', 'unknown')}; high-resolution timer: {timer_status}.")
        if caps.get("platform") == "win32":
            pdi = "available" if caps.get("pydirectinput") else "not available (using pynput)"
            jukebox_logger.info(f"MIDI Numpad mode: pydirectinput {pdi}.")

    def _check_macos_accessibility(self) -> None:
        """On macOS, check Accessibility trust; if not trusted, show a dialog and offer to open System Settings."""
        if sys.platform != "darwin":
            return
        if is_macos_accessibility_trusted():
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("Accessibility Permission Required")
        msg.setText(
            "Jukebox needs Accessibility permission to send key presses to the game (e.g. Roblox piano). "
            "In System Settings, open Privacy & Security → Accessibility, then add and enable: "
            "Terminal or iTerm if you launched from a terminal; Python (or Python 3.x) if you use Python from python.org; "
            "or the IDE (e.g. PyCharm) if you run from an IDE."
        )
        open_btn = msg.addButton("Open System Settings", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        msg.exec()
        if msg.clickedButton() == open_btn:
            open_macos_accessibility_preferences()

    def _log_message_to_plain(self, message: str) -> str:
        if not message:
            return ""
        text = re.sub(r"<[^>]+>", "", message)
        try:
            import html
            text = html.unescape(text)
        except Exception:
            return text.strip()
        return text.strip()

    def _log_warning(self, message: str) -> None:
        """Log a warning-level message (delegates to central logger)."""
        jukebox_logger.warning(message)

    def _log_error(
        self,
        message: str,
        show_dialog: bool = False,
        dialog_title: str = "Error",
    ) -> None:
        """Log an error-level message; optionally also show a modal dialog."""
        jukebox_logger.error(message)
        if show_dialog:
            QMessageBox.critical(self, dialog_title, message)

    def _on_log_level_changed(self, level: str) -> None:
        """Apply log level to central logger and persist to config."""
        if level:
            jukebox_logger.set_level(level)
            self._save_config()

    def _on_log_save_to_file_toggled(self, checked: bool):
        path = self._get_log_file_path()
        if checked:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            jukebox_logger.enable_file_logging(str(path))
            self.add_log_message(f"Log is being saved to: {path}")
        else:
            jukebox_logger.disable_file_logging()
            self.add_log_message("Log file saving disabled.")

    def add_log_message(self, message):
        """High-level INFO log entry; safe to call from any thread."""
        jukebox_logger.info(message)
    
    def _append_log(self, level: str, message: str) -> None:
        """Internal helper to append a colored log entry with timestamp and level. ERROR with newlines gets collapsible details."""
        if not hasattr(self, "_log_entries"):
            self._log_entries = []

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        plain = f"[{timestamp}] [{level}] {message}"

        if level == "ERROR":
            color = "#F56C6C"
        elif level == "WARNING":
            color = "#E6A23C"
        else:
            color = "#CCCCCC"

        import html as html_module
        if level == "ERROR" and "\n" in message:
            first_line, _, rest = message.partition("\n")
            rest = rest.strip()
            if rest:
                escaped_first = html_module.escape(first_line)
                escaped_rest = html_module.escape(rest)
                html = (
                    f'<span style="color:{color}">[{timestamp}] [ERROR] {escaped_first} '
                    f'<details><summary>Details</summary><pre style="margin:0; white-space:pre-wrap;">{escaped_rest}</pre></details></span>'
                )
            else:
                html = f'<span style="color:{color}">[{timestamp}] [ERROR] {html_module.escape(message)}</span>'
        else:
            if level in ("WARNING", "ERROR"):
                line_content = f"[{timestamp}] [{level}] {html_module.escape(message)}"
            else:
                line_content = f"[{timestamp}] [{level}] {message}"
            html = f'<span style="color:{color}">{line_content}</span>'
        self._log_entries.append({"level": level, "plain": plain, "html": html})

        # Keep the in-memory buffer bounded to avoid unbounded growth.
        if len(self._log_entries) > MAX_LOG_ENTRIES:
            self._log_entries = self._log_entries[-MAX_LOG_ENTRIES:]

        # Update visible log according to current filter
        self._apply_log_filter()

    def _apply_log_filter(self) -> None:
        """Rebuild the log view based on the current text filter."""
        query = ""
        if hasattr(self, "log_filter_edit"):
            query = self.log_filter_edit.text().strip().lower()

        self.log_output.clear()
        for entry in getattr(self, "_log_entries", []):
            plain = entry.get("plain", "")
            if query and query not in plain.lower():
                continue
            self.log_output.append(entry["html"])

    def _on_log_record(self, level: str, message: str) -> None:
        """Qt slot invoked on the GUI thread for every log record."""
        self._append_log(level, message)

    def set_controls_enabled(self, enabled):
        for groupbox in self.findChildren(QGroupBox): groupbox.setEnabled(enabled)

    def _config_from_ui(self) -> Config:
        """Build Config from current UI state using CONFIG_UI_BINDINGS."""
        data = {}
        for key, get_fn, _ in CONFIG_UI_BINDINGS:
            data[key] = get_fn(self)
        return Config.from_dict(data)

    def _save_config(self) -> None:
        """Persist UI state to config.json via ConfigRepository."""
        try:
            config = self._config_from_ui()
            self.config_repo.save(config)
        except OSError as e:
            jukebox_logger.error(f"Error saving config: {e}", exc_info=True)
            self._log_error("Error saving config: " + str(e), show_dialog=True, dialog_title="Error Saving Config")

    def _update_enabled_states(self):
        for key, check in self.all_humanization_checks.items():
            if not check.text(): continue
            is_checked = check.isChecked()
            if key in self.all_humanization_sliders: self.all_humanization_sliders[key].setEnabled(is_checked)
            if key in self.all_humanization_spinboxes: self.all_humanization_spinboxes[key].setEnabled(is_checked)
        self.invert_sway_check.setEnabled(self.all_humanization_checks['tempo_sway'].isChecked())

    def _apply_config_to_ui(self, config: Config) -> None:
        """Apply a loaded Config to UI widgets using CONFIG_UI_BINDINGS."""
        for key, _, set_fn in CONFIG_UI_BINDINGS:
            if hasattr(config, key):
                set_fn(self, getattr(config, key))

    def _load_config(self) -> None:
        """Restore UI from config.json via ConfigRepository. On load error, log and reset to defaults."""
        try:
            config = self.config_repo.load()
        except ConfigLoadError as e:
            jukebox_logger.error(f"Failed to load config from {e.path}: {e.cause}", exc_info=True)
            self._log_error("Config file could not be loaded; using defaults. You may delete or backup the file and restart.")
            self._reset_controls_to_default()
            self._update_enabled_states()
            return
        self._apply_config_to_ui(config)
        self._update_enabled_states()

    def gather_config(self):
        if not self.selected_tracks_info:
             self._log_error("Play aborted: no MIDI file or tracks selected.",
                             show_dialog=True,
                             dialog_title="No Tracks")
             QMessageBox.warning(self, "No Tracks", "Please select a MIDI file and choose tracks first."); return None
        display_text = self.pedal_style_combo.currentText()
        internal_style = self.pedal_mapping.get(display_text, 'hybrid')
        return {
            'midi_file': self.file_path_label.toolTip(), 
            'tempo': self.tempo_spinbox.value(), 
            'countdown': self.countdown_check.isChecked(),
            'use_88_key_layout': self.use_88_key_check.isChecked(),
            'pedal_style': internal_style,
            'output_mode': self._current_output_mode(),
            'simulate_hands': self.all_humanization_checks['simulate_hands'].isChecked(),
            'vary_velocity': False,
            'enable_chord_roll': self.all_humanization_checks['enable_chord_roll'].isChecked(),
            'vary_timing': self.all_humanization_checks['vary_timing'].isChecked(), 
            'timing_variance': self.all_humanization_spinboxes['vary_timing'].value(),
            'vary_articulation': self.all_humanization_checks['vary_articulation'].isChecked(), 
            'articulation': self.all_humanization_spinboxes['vary_articulation'].value() / 100.0,
            'enable_drift_correction': self.all_humanization_checks['hand_drift'].isChecked(), 
            'drift_decay_factor': self.all_humanization_spinboxes['hand_drift'].value() / 100.0,
            'enable_mistakes': self.all_humanization_checks['mistake_chance'].isChecked(), 
            'mistake_chance': self.all_humanization_spinboxes['mistake_chance'].value(),
            'enable_tempo_sway': self.all_humanization_checks['tempo_sway'].isChecked(), 
            'tempo_sway_intensity': self.all_humanization_spinboxes['tempo_sway'].value(),
            'invert_tempo_sway': self.all_humanization_checks['invert_tempo_sway'].isChecked(),
        }

    def select_file(self):
        if self.player_thread and self.player_thread.isRunning(): return
        filepath, _ = QFileDialog.getOpenFileName(self, "Select MIDI File", "", "MIDI Files (*.mid *.midi)")
        if filepath:
            self.file_path_label.setText(os.path.basename(filepath))
            self.file_path_label.setToolTip(filepath)
            self.current_file_bottom_label.setText(os.path.basename(filepath))
            self.add_log_message(f"Selected file: {filepath}")
            self._parse_and_select_tracks(filepath)

    def _parse_and_select_tracks(self, filepath):
        self.add_log_message("Parsing MIDI structure...")
        try:
            tracks, tempo_map = MidiParser.parse_structure(filepath, 1.0)
        except Exception as e:
            jukebox_logger.error(f"Failed to parse MIDI: {e}", exc_info=True)
            self._log_error("Failed to parse MIDI: " + str(e), show_dialog=True, dialog_title="Error")
            return
        dialog = TrackSelectionDialog(tracks, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.selected_tracks_info = dialog.get_selection()
            self.parsed_tempo_map = tempo_map 
            self.add_log_message(f"Tracks selected: {len(self.selected_tracks_info)}")
            self.play_button.setEnabled(True)
            self.reset_button.setEnabled(True)

            preview_notes = []
            for track, role in self.selected_tracks_info:
                for note in track.notes:
                    n = copy.deepcopy(note)
                    if role == "Left Hand": n.hand = 'left'
                    elif role == "Right Hand": n.hand = 'right'
                    else: n.hand = 'left' if n.pitch < 60 else 'right'
                    preview_notes.append(n)
            preview_notes.sort(key=lambda n: n.start_time)
            self.current_notes = preview_notes
            total_dur = max(n.end_time for n in preview_notes) if preview_notes else 1.0
            self.total_song_duration_sec = total_dur
            self.timeline_widget.set_data(preview_notes, total_dur, tempo_map)
            self.timeline_widget.set_position(0)
            self._on_visual_scrub(0)
            self._update_time_label(0, total_dur)
            self.tabs.setCurrentIndex(1)
        else:
            self.add_log_message("Track selection cancelled.")
            self.selected_tracks_info = None
            self.current_file_bottom_label.setText("No file selected.")
            self.play_button.setEnabled(False)
            self.reset_button.setEnabled(False)

    def handle_play(self):
        if self.player_thread and self.player_thread.isRunning():
            self.toggle_playback_state()
            return
        config = self.gather_config()
        if not config:
            return
        self._save_config()
        self.add_log_message("Preparing playback...")
        try:
            final_notes, sections, compiled_events, total_dur, tempo_map = PlaybackService.prepare_playback(
                config["midi_file"], self.selected_tracks_info, config
            )
        except Exception as e:
            jukebox_logger.error(f"Error preparing playback: {e}", exc_info=True)
            self._log_error("Error preparing playback: " + str(e), show_dialog=True, dialog_title="Error")
            return

        self.current_notes = final_notes
        seek_ratio = 0.0
        if self.timeline_widget.total_duration > 0:
            seek_ratio = self.timeline_widget.current_time / self.timeline_widget.total_duration
        config["start_offset"] = seek_ratio * total_dur

        self.timeline_widget.set_data(final_notes, total_dur, tempo_map)
        self.total_song_duration_sec = total_dur

        self.set_controls_enabled(False)
        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        key_str = self.hotkey_manager._format_key_string(self.hotkey_manager.current_key)
        self.play_button.setText(f"Pause ({key_str})")

        self.tabs.setCurrentIndex(1)

        backend = create_backend(
            config["output_mode"],
            config.get("use_88_key_layout", False),
            log_message=self.add_log_message,
        )

        self.player_thread = QThread()
        self.player = Player(compiled_events, backend, config, total_dur)
        self.player.moveToThread(self.player_thread)
        self.player_thread.started.connect(self.player.play)
        self.player.playback_finished.connect(self.on_playback_finished)
        self.player.status_updated.connect(self.add_log_message)
        self.player.progress_updated.connect(self.update_progress)
        self.player.visualizer_updated.connect(self.piano_widget.set_active_pitches)
        self.player_thread.start()

    def handle_stop(self):
        if self.player: self.player.stop()

    def handle_reset(self):
        """Reset song progress to 0: update timeline, time label, piano highlight; if playing, seek to start."""
        self.timeline_widget.set_position(0)
        self._update_time_label(0, self.total_song_duration_sec)
        self._on_visual_scrub(0)
        if self.player and self.player_thread and self.player_thread.isRunning():
            self.player.seek(0)

    def on_playback_finished(self):
        self.add_log_message("Playback process finished.\n" + "="*50 + "\n")
        self.piano_widget.clear()
        self.set_controls_enabled(True)
        self.stop_button.setEnabled(False)
        self.play_button.setText(f"Play ({self.hotkey_manager._format_key_string(self.hotkey_manager.current_key)})")
        if self.player_thread:
            self.player_thread.quit()
            self.player_thread.wait()
        self.player = None
        self.player_thread = None

    def closeEvent(self, event):
        self._save_config()
        if self.midi_input_active:
            self._disconnect_midi_input()
        if self.live_backend:
            self.live_backend.shutdown()
        if self.player and self.player_thread and self.player_thread.isRunning():
            self.player.stop()
            self.player_thread.wait(1000)
        event.accept()

if __name__ == "__main__":
    set_app_user_model_id(APP_ID)

    app = QApplication(sys.argv)
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())