"""Jukebox main window: tabs, UI construction, playback orchestration, config persistence."""

import sys
import os
import re
import copy
import random
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QCheckBox,
    QSlider,
    QLabel,
    QFileDialog,
    QGroupBox,
    QTabWidget,
    QComboBox,
    QDoubleSpinBox,
    QMessageBox,
    QGridLayout,
    QStatusBar,
    QScrollArea,
    QRadioButton,
    QLineEdit,
    QTextBrowser,
    QDialog,
    QListWidget,
    QAbstractItemView,
)
from PyQt6.QtCore import QThread, QTimer, pyqtSignal as Signal, Qt
from PyQt6.QtGui import QFont, QIcon, QColor, QCloseEvent
import mido

from models import Note
from core import MidiParser
from ui import (
    PianoWidget,
    TimelineWidget,
    HotkeyManager,
    TrackSelectionDialog,
    MidiInputWorker,
)
from output import OutputBackendError, OutputBackendUnavailableError, create_backend
from playback import PlaybackController, PlaybackService
from logger_core import jukebox_logger
from config_repository import Config, ConfigRepository, ConfigLoadError
from native import (
    is_macos_accessibility_trusted,
    open_macos_accessibility_preferences,
)
from platform_utils import get_capabilities
from config_bindings import (
    CONFIG_UI_BINDINGS,
    effectful_keys,
    apply_config_effects,
    validate_config_ui_bindings,
)
import theme

APP_NAME = "Jukebox"
APP_ID = "jukebox.piano"
APP_URL = "https://github.com/x15rte/Jukebox"
LOG_FILENAME = "log.txt"
MAX_LOG_ENTRIES = 5000


class MainWindow(QMainWindow):
    """Tabs: Playback (file, input/output), Humanization (humanization settings), Visualizer (timeline + piano), Settings (hotkey, overlay, playback defaults), Output (log). Saves/loads config.json; optional log to file."""

    log_record_received = Signal(str, str)

    def __init__(self, app_version: str = ""):
        super().__init__()
        self._app_version = app_version
        self.setWindowTitle(f"{APP_NAME} ({app_version})" if app_version else APP_NAME)
        self.setMinimumSize(780, 520)
        self.setStyleSheet(
            "QWidget { background-color: rgb(18, 18, 20); color: rgb(235, 235, 240); }"
            "QGroupBox { border: 1px solid rgb(60,60,70); border-radius: 6px; margin-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; font-weight: 600; }"
        )

        self.midi_input_thread = None
        self.midi_input_worker = None
        self.midi_input_active = False
        self.config_repo = ConfigRepository()
        self.config_dir = self.config_repo.config_dir
        self.config_path = self.config_repo.config_path
        self.config_repo.ensure_config_dir()
        self._config_dirty: bool = False
        self._config_save_timer: QTimer = QTimer()
        self._config_save_timer.setSingleShot(True)
        self._config_save_timer.timeout.connect(self._save_config)
        self.selected_tracks_info = None
        self.parsed_tempo_map = None
        self.parsed_tracks = None
        self.parsed_tempo_scale = 1.0
        self.current_notes = []
        self.total_song_duration_sec = 1.0
        self.autoplay_folder: str | None = None
        self.autoplay_file_list: list[str] = []
        self.autoplay_current_index: int = -1
        self.autoplay_next_timer: QTimer = QTimer()
        self.autoplay_next_timer.setSingleShot(True)
        self.autoplay_next_timer.timeout.connect(self._autoplay_play_current)
        self._autoplay_stopping: bool = False
        self.playback_state = "stopped"
        self._log_entries = []

        self.hotkey_manager = HotkeyManager()
        self.hotkey_manager.toggle_requested.connect(self.toggle_playback_state)
        self.hotkey_manager.bound_updated.connect(self._on_hotkey_bound)

        self.log_record_received.connect(self._on_log_record)

        def _gui_log_callback(level: str, message: str) -> None:
            self.log_record_received.emit(level, message)

        jukebox_logger.set_gui_callback(_gui_log_callback)

        self.pedal_mapping = {
            "Original (from MIDI)": "original",
            "Automatic": "hybrid",
            "Always Sustain": "legato",
            "Rhythmic Only": "rhythmic",
            "No Pedal": "none",
        }
        self.pedal_mapping_inv = {v: k for k, v in self.pedal_mapping.items()}

        self.live_backend = None

        self._setup_ui()

        try:
            validate_config_ui_bindings()
        except ValueError as e:
            raise RuntimeError(f"Invalid config UI bindings: {e}") from e

        self._last_tab_index = 0

        self.playback_controller = PlaybackController(self)
        self.playback_controller.status_updated.connect(self._on_status_updated)
        self.playback_controller.progress_updated.connect(self.update_progress)
        self.playback_controller.visualizer_updated.connect(
            self.piano_widget.set_active_pitches
        )
        self.playback_controller.playback_finished.connect(self.on_playback_finished)
        self.playback_controller.state_changed.connect(self._on_playback_state_changed)

        self._load_config()
        self.use_88_key_check.toggled.connect(self._on_key_layout_changed)

        ver_tag = f" ({self._app_version})" if self._app_version else ""
        self.add_log_message(f"{APP_NAME}{ver_tag} — {APP_URL}")
        self._log_startup_capabilities()
        QTimer.singleShot(0, self._check_macos_accessibility)

    def _setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(10, 10, 10, 5)
        main_layout.setSpacing(theme.SECTION_SPACING)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        controls_tab = QWidget()
        humanization_tab = QWidget()
        visual_tab = QWidget()
        settings_tab = QWidget()
        log_tab = QWidget()
        self.tabs.addTab(controls_tab, "Playback")
        self.tabs.addTab(visual_tab, "Visualizer")
        self.tabs.addTab(humanization_tab, "Humanization")
        self.tabs.addTab(settings_tab, "Settings")
        self.tabs.addTab(log_tab, "Output")

        self.tabs.currentChanged.connect(self._on_tab_changed)

        vis_layout = QVBoxLayout(visual_tab)
        vis_layout.setContentsMargins(5, 5, 5, 5)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.timeline_widget = TimelineWidget()
        self.timeline_widget.seek_requested.connect(self._on_timeline_seek)
        self.timeline_widget.scrub_position_changed.connect(self._on_visual_scrub)

        self.scroll_area.setWidget(self.timeline_widget)
        vis_layout.addWidget(self.scroll_area)

        self.piano_widget = PianoWidget()
        vis_layout.addWidget(self.piano_widget)

        controls_main_layout = QVBoxLayout(controls_tab)
        controls_main_layout.setContentsMargins(5, 5, 5, 5)
        controls_main_layout.setSpacing(theme.SECTION_SPACING)
        controls_main_layout.addWidget(self._create_input_output_group())
        controls_main_layout.addStretch()

        humanization_layout = QVBoxLayout(humanization_tab)
        humanization_layout.setContentsMargins(5, 5, 5, 5)
        humanization_layout.setSpacing(theme.SECTION_SPACING)
        self.humanization_group = self._create_humanization_group()
        humanization_layout.addWidget(self.humanization_group)
        humanization_layout.addStretch()

        settings_layout = QVBoxLayout(settings_tab)
        settings_layout.setContentsMargins(5, 5, 5, 5)
        settings_layout.setSpacing(theme.SECTION_SPACING)
        self.settings_group = self._create_settings_group()
        settings_layout.addWidget(self.settings_group)
        settings_layout.addStretch()

        self.log_output = QTextBrowser()
        self.log_output.setObjectName("LogOutput")
        self.log_output.setOpenExternalLinks(True)
        self.log_output.setFont(QFont("Courier", 9))
        log_layout = QVBoxLayout(log_tab)
        log_layout.setContentsMargins(8, 8, 8, 8)
        log_layout.setSpacing(theme.SECTION_SPACING)

        toolbar_layout = QHBoxLayout()
        clear_btn = QPushButton("Clear")
        copy_btn = QPushButton("Copy")
        log_level_label = QLabel("Level:")
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_combo.setCurrentText("INFO")
        self.log_level_combo.setToolTip(
            "Minimum level to show in console and log file."
        )
        self.log_level_combo.currentTextChanged.connect(self._on_log_level_changed)
        self.log_save_to_file_check = QCheckBox("Save to file")
        self.log_save_to_file_check.setChecked(False)
        self.log_save_to_file_check.toggled.connect(self._on_log_save_to_file_toggled)
        filter_label = QLabel("Filter:")
        self.log_filter_edit = QLineEdit()
        self.log_filter_edit.setPlaceholderText("Type to filter log...")
        self.log_filter_edit.textChanged.connect(self._on_log_filter_text_changed)
        self.log_filter_status = QLabel("")
        self.log_filter_status.setStyleSheet("color: gray;")
        self.log_auto_scroll_check = QCheckBox("Auto-scroll")
        self.log_auto_scroll_check.setChecked(True)
        self.log_wrap_check = QCheckBox("Wrap")
        self.log_wrap_check.setChecked(False)
        self.log_wrap_check.toggled.connect(self._on_log_wrap_toggled)
        self._log_filter_timer = QTimer()
        self._log_filter_timer.setSingleShot(True)
        self._log_filter_timer.timeout.connect(self._render_log)
        clear_btn.clicked.connect(self._clear_log)
        copy_btn.clicked.connect(self._copy_log_to_clipboard)
        toolbar_layout.addWidget(clear_btn)
        toolbar_layout.addWidget(copy_btn)
        toolbar_layout.addSpacing(8)
        toolbar_layout.addWidget(log_level_label)
        toolbar_layout.addWidget(self.log_level_combo)
        toolbar_layout.addWidget(self.log_save_to_file_check)
        toolbar_layout.addSpacing(8)
        toolbar_layout.addWidget(self.log_auto_scroll_check)
        toolbar_layout.addWidget(self.log_wrap_check)
        toolbar_layout.addSpacing(8)
        toolbar_layout.addWidget(filter_label)
        toolbar_layout.addWidget(self.log_filter_edit, 1)
        toolbar_layout.addWidget(self.log_filter_status)
        log_layout.addLayout(toolbar_layout)
        log_layout.addWidget(self.log_output, 1)

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
        self.current_file_bottom_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        button_layout.addWidget(self.current_file_bottom_label)

        main_layout.addLayout(media_layout)
        main_layout.addLayout(button_layout)

        self._update_play_stop_labels()
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        self.play_button.clicked.connect(self.handle_play)
        self.stop_button.clicked.connect(self.handle_stop)
        self.reset_button.clicked.connect(self.handle_reset)
        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.reset_button.setEnabled(False)

    def _toggle_always_on_top(self, checked):
        was_visible = self.isVisible()
        state = self.windowState()
        flags = self.windowFlags()
        if checked:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
        if was_visible:
            self.show()
            self.setWindowState(state)
            self.activateWindow()
            self.raise_()

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

    def _is_playback_locked(self) -> bool:
        state = getattr(self, "playback_state", "stopped")
        return state != "stopped"

    def _update_playback_tab_appearance(self) -> None:
        if not hasattr(self, "tabs"):
            return
        tab_bar = self.tabs.tabBar()
        if tab_bar is None:
            return
        locked = self._is_playback_locked()
        color = QColor(150, 150, 150) if locked else QColor(235, 235, 240)
        tooltip = (
            "Settings are locked while the song is playing or paused. "
            "Press Stop to adjust settings."
            if locked
            else ""
        )
        for idx in (0, 2, 3):
            tab_bar.setTabTextColor(idx, color)
            self.tabs.setTabToolTip(idx, tooltip)

    def _on_tab_changed(self, index: int) -> None:
        # All tabs are safe to browse during playback — editable controls are
        # already disabled by set_controls_enabled(False) while playback runs.
        self._last_tab_index = index

    def _on_playback_state_changed(self, state: str) -> None:
        self.playback_state = state
        self._update_play_stop_labels()
        self._update_playback_tab_appearance()

    def _update_play_stop_labels(self):
        key_str = self.hotkey_manager.format_key_string(self.hotkey_manager.current_key)
        state = getattr(self, "playback_state", "stopped")
        if state == "stopped":
            self.play_button.setText(f"Play ({key_str})")
        elif state == "paused":
            self.play_button.setText(f"Resume ({key_str})")
        else:
            self.play_button.setText(f"Pause ({key_str})")
        self.stop_button.setText("Stop")

    def toggle_playback_state(self):
        controller = getattr(self, "playback_controller", None)
        if controller is None:
            return

        state = getattr(controller, "state", "stopped")
        if state != "paused":
            self.piano_widget.clear()

        resuming = state == "paused"
        if controller.is_running:
            controller.toggle_pause()
            if resuming:
                current_t = self.timeline_widget.current_time
                self._on_visual_scrub(current_t)
        else:
            self.handle_play()

    def _on_timeline_seek(self, time):
        self.add_log_message(f"Seeking to {time:.2f}s...")
        if self.playback_controller.is_running:
            self.playback_controller.seek(time)

    def _on_visual_scrub(self, time):
        active_pitches = set()
        for note in self.current_notes:
            if note.start_time <= time < note.end_time:
                active_pitches.add(note.pitch)
        self.piano_widget.set_active_pitches(active_pitches)
        self._update_time_label(time, self.total_song_duration_sec)

    def update_progress(self, current_time):
        total_dur = self.playback_controller.total_duration
        if total_dur > 0:
            self.total_song_duration_sec = total_dur
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
                hbar = self.scroll_area.horizontalScrollBar()
                if hbar is not None:
                    hbar.setValue(int(target_scroll))

    def _update_time_label(self, current, total):
        def fmt(s):
            m = int(s // 60)
            sec = int(s % 60)
            return f"{m:02d}:{sec:02d}"

        self.time_label.setText(f"{fmt(current)} / {fmt(total)}")

    def _copy_log_to_clipboard(self):
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.log_output.toPlainText())
        sb = self.statusBar()
        if sb is not None:
            sb.showMessage("Log copied to clipboard!", 2000)

    def _create_info_icon(self, tooltip_text: str) -> QLabel:
        label = QLabel("\u24d8")
        label.setStyleSheet("color: gray; font-weight: bold;")
        label.setToolTip(tooltip_text)
        return label

    def _create_slider_and_spinbox(
        self, min_val, max_val, default_val, text_suffix="", factor=10000.0, decimals=4
    ):
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
        group = QGroupBox("Input & Output")
        layout = QVBoxLayout(group)
        layout.setSpacing(theme.CONTROL_SPACING)

        mode_row = QHBoxLayout()
        mode_label = QLabel("Input mode:")
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
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(theme.CONTROL_SPACING)

        # Sub-mode: single file vs playlist folder
        sub_row = QHBoxLayout()
        self.input_mode_single_radio = QRadioButton("Single file")
        self.input_mode_playlist_radio = QRadioButton("Playlist (Folder)")
        self.input_mode_single_radio.setChecked(True)
        self.input_mode_single_radio.toggled.connect(self._on_file_submode_changed)
        self.input_mode_playlist_radio.toggled.connect(self._on_file_submode_changed)
        sub_row.addWidget(self.input_mode_single_radio)
        sub_row.addWidget(self.input_mode_playlist_radio)
        sub_row.addStretch(1)
        file_layout.addLayout(sub_row)

        # Single-file panel
        self.file_single_widget = QWidget()
        single_layout = QVBoxLayout(self.file_single_widget)
        single_layout.setContentsMargins(0, 0, 0, 0)
        single_layout.setSpacing(theme.CONTROL_SPACING)
        self.file_path_label = QLabel("No file selected.")
        self.file_path_label.setStyleSheet("font-style: italic; color: grey;")
        browse_button = QPushButton("Browse MIDI file…")
        browse_button.clicked.connect(self.select_file)
        single_layout.addWidget(self.file_path_label)
        single_layout.addWidget(browse_button)
        file_layout.addWidget(self.file_single_widget)

        # Playlist panel
        self.file_playlist_widget = QWidget()
        pl_layout = QVBoxLayout(self.file_playlist_widget)
        pl_layout.setContentsMargins(0, 0, 0, 0)
        pl_layout.setSpacing(theme.CONTROL_SPACING)

        folder_row = QHBoxLayout()
        self.autoplay_folder_label = QLabel("No folder selected.")
        self.autoplay_folder_label.setStyleSheet("font-style: italic; color: grey;")
        self.autoplay_browse_btn = QPushButton("Browse Folder…")
        self.autoplay_browse_btn.clicked.connect(self._autoplay_browse_folder)
        self.autoplay_reload_btn = QPushButton("Reload")
        self.autoplay_reload_btn.setEnabled(False)
        self.autoplay_reload_btn.clicked.connect(self._autoplay_scan_folder)
        self.autoplay_shuffle_btn = QPushButton("Shuffle")
        self.autoplay_shuffle_btn.setEnabled(False)
        self.autoplay_shuffle_btn.clicked.connect(self._autoplay_shuffle)
        folder_row.addWidget(self.autoplay_folder_label, 1)
        folder_row.addWidget(self.autoplay_browse_btn)
        folder_row.addWidget(self.autoplay_reload_btn)
        folder_row.addWidget(self.autoplay_shuffle_btn)
        pl_layout.addLayout(folder_row)

        self.autoplay_file_listbox = QListWidget()
        self.autoplay_file_listbox.setMaximumHeight(120)
        self.autoplay_file_listbox.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.autoplay_file_listbox.itemDoubleClicked.connect(
            self._autoplay_jump_to_song
        )
        pl_layout.addWidget(self.autoplay_file_listbox)

        self.autoplay_info_label = QLabel("")
        self.autoplay_info_label.setStyleSheet("font-style: italic; color: grey;")
        pl_layout.addWidget(self.autoplay_info_label)

        delay_row = QHBoxLayout()
        delay_label = QLabel("Delay:")
        self.autoplay_delay_spinbox = QDoubleSpinBox()
        self.autoplay_delay_spinbox.setRange(0.0, 600.0)
        self.autoplay_delay_spinbox.setSingleStep(0.5)
        self.autoplay_delay_spinbox.setSuffix(" s")
        self.autoplay_delay_spinbox.setDecimals(1)
        self.autoplay_delay_spinbox.setValue(0.0)
        self.autoplay_delay_spinbox.setToolTip("Fixed delay between songs")
        random_label = QLabel("Random:")
        self.autoplay_random_delay_spinbox = QDoubleSpinBox()
        self.autoplay_random_delay_spinbox.setRange(0.0, 60.0)
        self.autoplay_random_delay_spinbox.setSingleStep(0.5)
        self.autoplay_random_delay_spinbox.setSuffix(" s")
        self.autoplay_random_delay_spinbox.setDecimals(1)
        self.autoplay_random_delay_spinbox.setValue(0.0)
        self.autoplay_random_delay_spinbox.setToolTip(
            "Extra random delay added on top of the fixed delay"
        )
        delay_row.addWidget(delay_label)
        delay_row.addWidget(self.autoplay_delay_spinbox)
        delay_row.addSpacing(12)
        delay_row.addWidget(random_label)
        delay_row.addWidget(self.autoplay_random_delay_spinbox)
        delay_row.addStretch(1)
        pl_layout.addLayout(delay_row)

        file_layout.addWidget(self.file_playlist_widget)
        self.file_playlist_widget.hide()

        layout.addWidget(self.file_input_widget)

        self.piano_input_widget = QWidget()
        piano_layout = QVBoxLayout(self.piano_input_widget)
        piano_layout.setContentsMargins(0, 0, 0, 0)
        piano_layout.setSpacing(theme.CONTROL_SPACING)
        device_row = QHBoxLayout()
        device_label = QLabel("MIDI input device:")
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
        output_label = QLabel("Output mode:")
        self.output_mode_combo = QComboBox()
        self.output_mode_combo.addItem("KEY mode (keyboard)", userData="key")
        self.output_mode_combo.addItem(
            "MIDI Numpad (Roblox MIDI Connect)", userData="midi_numpad"
        )
        self.output_mode_combo.currentIndexChanged.connect(self._on_output_mode_changed)
        output_row.addWidget(output_label)
        output_row.addWidget(self.output_mode_combo)
        output_row.addStretch(1)
        layout.addLayout(output_row)

        self.use_88_key_check = QCheckBox("Use 88-key extended layout")
        layout.addWidget(self.use_88_key_check)

        return group

    # ------------------------------------------------------------------
    # Autoplay group (playlist / sequential folder playback)
    # ------------------------------------------------------------------

    def _autoplay_browse_folder(self):
        if self.playback_controller.is_running:
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder with MIDI Files"
        )
        if folder:
            self._set_autoplay_folder_path(folder)
            self._autoplay_scan_folder()

    def _set_autoplay_folder_path(self, folder_path: str | None):
        self.autoplay_folder = folder_path
        if folder_path:
            self.autoplay_folder_label.setText(os.path.basename(folder_path))
            self.autoplay_folder_label.setToolTip(folder_path)
            self.autoplay_reload_btn.setEnabled(True)
            self.autoplay_shuffle_btn.setEnabled(True)
        else:
            self.autoplay_folder_label.setText("No folder selected.")
            self.autoplay_folder_label.setToolTip("")
            self.autoplay_reload_btn.setEnabled(False)
            self.autoplay_shuffle_btn.setEnabled(False)
        self._mark_config_dirty()

    def _autoplay_scan_folder(self):
        self.autoplay_next_timer.stop()
        folder = self.autoplay_folder
        if not folder:
            return
        folder_path = Path(folder)
        midi_files = list(folder_path.glob("*.mid")) + list(folder_path.glob("*.midi"))
        seen: set[str] = set()
        unique: list[str] = []
        for f in midi_files:
            key = str(f).casefold()
            if key not in seen:
                seen.add(key)
                unique.append(str(f.resolve()))
        self.autoplay_file_list = sorted(unique, key=str.casefold)
        self.autoplay_current_index = -1

        self.autoplay_file_listbox.clear()
        for fpath in self.autoplay_file_list:
            self.autoplay_file_listbox.addItem(os.path.basename(fpath))

        count = len(self.autoplay_file_list)
        if count == 0:
            self.autoplay_info_label.setText("No MIDI files found in folder.")
            self.autoplay_info_label.setStyleSheet("font-style: italic; color: grey;")
            self.play_button.setEnabled(bool(self.selected_tracks_info))
            self._set_current_file_labels(None)
        else:
            self.autoplay_info_label.setText(f"{count} MIDI file(s) found.")
            self.autoplay_info_label.setStyleSheet("font-style: italic; color: grey;")
            self.play_button.setEnabled(True)
            # Show the first file in the playlist on the bottom label
            self._set_current_file_labels(self.autoplay_file_list[0])
        self.add_log_message(
            f"Autoplay: found {count} MIDI file(s) in folder."
        )

    def _autoplay_jump_to_song(self, item):
        """Select a song in the playlist and preview it in the visualizer."""
        row = self.autoplay_file_listbox.row(item)
        if row < 0 or row >= len(self.autoplay_file_list):
            return

        # Cancel any pending auto-advance timer and stop current playback
        self.autoplay_next_timer.stop()
        self._autoplay_stopping = True
        if self.playback_controller.is_running:
            self.playback_controller.stop_and_wait(timeout_ms=3000)
            QApplication.processEvents()
        self._autoplay_stopping = False

        self.autoplay_current_index = row
        self._update_autoplay_highlight()
        self._set_current_file_labels(self.autoplay_file_list[row])

        # Parse and show visualizer preview (same as selecting a single file)
        filepath = self.autoplay_file_list[row]
        try:
            if self._autoplay_select_tracks(filepath):
                if self.selected_tracks_info is None:
                    return
                preview_notes = []
                for track, role in self.selected_tracks_info:
                    for note in track.notes:
                        n = copy.deepcopy(note)
                        if role == "Left Hand":
                            n.hand = "left"
                        elif role == "Right Hand":
                            n.hand = "right"
                        else:
                            n.hand = "left" if n.pitch < 60 else "right"
                        preview_notes.append(n)
                preview_notes.sort(key=lambda n: n.start_time)
                self.current_notes = preview_notes
                total_dur = max(n.end_time for n in preview_notes) if preview_notes else 1.0
                self.total_song_duration_sec = total_dur
                self.timeline_widget.set_data(preview_notes, total_dur, self.parsed_tempo_map)
                self.timeline_widget.set_position(0)
                self._on_visual_scrub(0)
                self._update_time_label(0, total_dur)
                self.add_log_message(f"Selected: {os.path.basename(filepath)}")
        except Exception as e:
            self.add_log_message(f"Could not preview '{os.path.basename(filepath)}': {e}")

    def _autoplay_shuffle(self):
        self.autoplay_next_timer.stop()
        if len(self.autoplay_file_list) < 2:
            return
        random.shuffle(self.autoplay_file_list)
        self.autoplay_current_index = -1
        self.autoplay_file_listbox.clear()
        for fpath in self.autoplay_file_list:
            self.autoplay_file_listbox.addItem(os.path.basename(fpath))
        self._update_autoplay_highlight()
        # Update bottom file label to the new first song
        self._set_current_file_labels(self.autoplay_file_list[0])
        self.add_log_message(
            f"Playlist shuffled: {len(self.autoplay_file_list)} song(s)."
        )

    def _autoplay_select_tracks(self, filepath: str) -> bool:
        """Parse a MIDI file and auto-select all non-drum tracks with Auto-Detect hand.
        Returns True if at least one track was selected."""
        tempo_scale = self.tempo_spinbox.value() / 100.0
        tracks, tempo_map = MidiParser.parse_structure(filepath, tempo_scale)
        self.parsed_tracks = tracks
        self.parsed_tempo_map = tempo_map
        self.parsed_tempo_scale = tempo_scale

        selected = [(t, "Auto-Detect") for t in tracks if not t.is_drum]
        if not selected:
            self.add_log_message(
                f"Autoplay: no playable tracks found in '{os.path.basename(filepath)}'."
            )
            return False

        self.selected_tracks_info = selected
        self.add_log_message(
            f"Autoplay: selected {len(selected)} track(s) from '{os.path.basename(filepath)}'."
        )
        return True

    def _autoplay_play_current(self) -> bool:
        """Play the current song in the autoplay file list.
        Skips files that fail to parse or prepare. Returns True if playback started."""
        # Cancel any pending timer — this function is the handler itself, so if
        # called manually while a timer is queued, prevent the timer from
        # firing a duplicate run.
        self.autoplay_next_timer.stop()

        # If stop was pressed just before the timer fired, bail out.
        if self._autoplay_stopping:
            self._autoplay_stopping = False
            return False
        # Use a while-loop (not recursion) to skip past files that fail to parse.
        while True:
            if not (0 <= self.autoplay_current_index < len(self.autoplay_file_list)):
                self.autoplay_current_index = -1
                self._update_autoplay_highlight()
                self.add_log_message("Autoplay: no more songs to play.")
                return False

            filepath = self.autoplay_file_list[self.autoplay_current_index]
            filename = os.path.basename(filepath)

            self._set_current_file_labels(filepath)

            try:
                if not self._autoplay_select_tracks(filepath):
                    self.autoplay_current_index += 1
                    continue
            except Exception as e:
                jukebox_logger.error(
                    f"Autoplay: error parsing '{filename}': {e}", exc_info=True
                )
                self.add_log_message(
                    f"Autoplay: skipping '{filename}' — parse error: {e}"
                )
                self.autoplay_current_index += 1
                continue

            config = self.gather_config()
            if config is None:
                return False

            try:
                if self.selected_tracks_info is None:  # pragma: no cover
                    raise RuntimeError("selected_tracks_info should have been set by _autoplay_select_tracks")
                final_notes, sections, compiled_events, total_dur, tempo_map = (
                    PlaybackService.prepare_playback(
                        filepath,
                        self.selected_tracks_info,
                        config,
                        preparsed=(self.parsed_tracks, self.parsed_tempo_map)
                        if self.parsed_tracks is not None
                        and self.parsed_tempo_map is not None
                        else None,
                        preparsed_tempo_scale=self.parsed_tempo_scale,
                    )
                )
            except Exception as e:
                jukebox_logger.error(
                    f"Autoplay: error preparing playback for '{filename}': {e}",
                    exc_info=True,
                )
                self.add_log_message(
                    f"Autoplay: skipping '{filename}' — prepare error: {e}"
                )
                self.autoplay_current_index += 1
                continue

            self.add_log_message(
                f"Autoplay: playing ({self.autoplay_current_index + 1}"
                f"/{len(self.autoplay_file_list)}) '{filename}'"
            )
            self.autoplay_info_label.setText(
                f"▶ Playing {self.autoplay_current_index + 1}"
                f"/{len(self.autoplay_file_list)}: {filename}"
            )
            self.autoplay_info_label.setStyleSheet("font-style: normal; color: #4FC3F7;")

            self.current_notes = final_notes
            config["start_offset"] = 0.0
            self.timeline_widget.set_data(final_notes, total_dur, tempo_map)
            self.total_song_duration_sec = total_dur
            self.timeline_widget.set_position(0)
            self._on_visual_scrub(0)

            self.set_controls_enabled(False)
            self.play_button.setEnabled(True)
            self.stop_button.setEnabled(True)
            self._update_autoplay_highlight()

            started = self.playback_controller.start(
                compiled_events,
                config,
                total_dur,
                config.get("output_mode", "key"),
                config.get("use_88_key_layout", False),
                log_message=self.add_log_message,
            )
            if started:
                return True
            else:
                self.set_controls_enabled(True)
                return False

    def _update_autoplay_highlight(self):
        """Bold the currently-playing item in the playlist listbox."""
        for i in range(self.autoplay_file_listbox.count()):
            item = self.autoplay_file_listbox.item(i)
            if item is not None:
                font = item.font()
                font.setBold(i == self.autoplay_current_index)
                item.setFont(font)

    def _on_file_submode_changed(self):
        """Toggle between single-file and playlist sub-panels inside File (MIDI) mode."""
        is_playlist = self.input_mode_playlist_radio.isChecked()
        self.file_single_widget.setVisible(not is_playlist)
        self.file_playlist_widget.setVisible(is_playlist)
        self.autoplay_next_timer.stop()
        # Reset autoplay state when switching away
        if not is_playlist:
            self.autoplay_current_index = -1
            self._update_autoplay_highlight()
        self._mark_config_dirty()

    def _on_input_mode_changed(self):
        use_piano = self.input_mode_piano_radio.isChecked()
        self.file_input_widget.setVisible(not use_piano)
        self.piano_input_widget.setVisible(use_piano)
        self._playback_file_only_widget.setVisible(not use_piano)
        self.tabs.setTabEnabled(1, not use_piano)
        self.tabs.setTabEnabled(2, not use_piano)
        if use_piano and self.tabs.currentIndex() in (1, 2):
            self.tabs.setCurrentIndex(0)

        if use_piano:
            self._refresh_midi_inputs()
        else:
            if self.midi_input_active:
                self._disconnect_midi_input()

    def _refresh_midi_inputs(self, show_dialog: bool = True):
        try:
            names = mido.get_input_names()  # type: ignore[attr-defined]
        except Exception as e:
            jukebox_logger.error(
                f"Failed to list MIDI input devices: {e}", exc_info=True
            )
            self._log_error(
                "Failed to list MIDI input devices: " + str(e),
                show_dialog=show_dialog,
                dialog_title="Error",
                exc_info=True,
            )
            return
        self.midi_input_combo.clear()
        self.midi_input_combo.addItems(names)

    def _connect_midi_input(self):
        if self.midi_input_active:
            return

        if self.playback_controller.is_running:
            self.handle_stop()

        port_name = self.midi_input_combo.currentText()
        if not port_name:
            self._log_warning("MIDI connect skipped: no device selected.")
            QMessageBox.warning(self, "No Device", "No MIDI input device selected.")
            return

        try:
            self.live_backend = create_backend(
                self._current_output_mode(),
                self.use_88_key_check.isChecked(),
                log_message=self.add_log_message,
            )
        except OutputBackendUnavailableError as e:
            self.live_backend = None
            self.midi_input_status_label.setText("Piano input disconnected.")
            self._log_error(
                f"MIDI input could not start: {e}",
                show_dialog=True,
                dialog_title="Output Unavailable",
            )
            return

        self.midi_input_thread = QThread()
        self.midi_input_worker = MidiInputWorker(port_name)
        self.midi_input_worker.moveToThread(self.midi_input_thread)
        self.midi_input_thread.started.connect(self.midi_input_worker.run)
        self.midi_input_worker.message_received.connect(self._handle_live_midi_message)
        self.midi_input_worker.connected.connect(
            lambda: self._on_midi_input_connected(port_name)
        )
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
        self._log_error(
            f"MIDI input connection failed: {error_msg}",
            show_dialog=True,
            dialog_title="Connection Failed",
        )

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
        if hasattr(self, "use_88_key_check"):
            self.use_88_key_check.setVisible(self._current_output_mode() == "key")

    def _on_output_mode_changed(self):
        self._update_88_key_visibility()
        if self.live_backend and self.midi_input_active:
            self.live_backend.shutdown()
            try:
                self.live_backend = create_backend(
                    self._current_output_mode(),
                    self.use_88_key_check.isChecked(),
                    log_message=self.add_log_message,
                )
            except OutputBackendUnavailableError as e:
                self.live_backend = None
                self._log_error(
                    f"MIDI input output unavailable: {e}",
                    show_dialog=True,
                    dialog_title="Output Unavailable",
                )
                self._disconnect_midi_input()

    def _on_key_layout_changed(self, _checked: bool = False):
        if self.live_backend and self.midi_input_active:
            self.live_backend.shutdown()
            try:
                self.live_backend = create_backend(
                    self._current_output_mode(),
                    self.use_88_key_check.isChecked(),
                    log_message=self.add_log_message,
                )
            except OutputBackendUnavailableError as e:
                self.live_backend = None
                self._log_error(
                    f"MIDI input output unavailable: {e}",
                    show_dialog=True,
                    dialog_title="Output Unavailable",
                )
                self._disconnect_midi_input()

    def _handle_live_midi_message(self, msg):
        if not self.live_backend:
            return

        msg_type = getattr(msg, "type", None)

        try:
            if msg_type in ("note_on", "note_off"):
                note = getattr(msg, "note", None)
                velocity = getattr(msg, "velocity", 0)
                if note is None:
                    return
                is_off = msg_type == "note_off" or (
                    msg_type == "note_on" and velocity == 0
                )
                if is_off:
                    self.live_backend.note_off(note)
                else:
                    self.live_backend.note_on(note, velocity)
                return

            if msg_type == "control_change" and getattr(msg, "control", None) == 64:
                value = getattr(msg, "value", 0)
                if value >= 64:
                    self.live_backend.pedal_on()
                else:
                    self.live_backend.pedal_off()
        except OutputBackendError as e:
            self._log_error(
                f"Live MIDI output failed: {e}",
                show_dialog=True,
                dialog_title="Output Error",
            )
            self._disconnect_midi_input()

    def _create_settings_group(self):
        group = QGroupBox("Settings")
        main_layout = QVBoxLayout(group)

        self._playback_file_only_widget = QWidget()
        file_grid = QGridLayout(self._playback_file_only_widget)
        tempo_label = QLabel("Tempo")
        self.tempo_slider, self.tempo_spinbox = self._create_slider_and_spinbox(
            10.0, 200.0, 100.0, "%", factor=10.0, decimals=1
        )
        file_grid.addWidget(tempo_label, 0, 0)
        file_grid.addWidget(self.tempo_slider, 0, 2)
        file_grid.addWidget(self.tempo_spinbox, 0, 3)

        pedal_label = QLabel("Pedal Style")
        self.pedal_style_combo = QComboBox()
        self.pedal_style_combo.addItems(list(self.pedal_mapping.keys()))
        self.pedal_style_combo.setItemData(
            0,
            "Uses sustain pedal data from the MIDI file when present. With Humanizer off, existing MIDI pedal events keep their original timing. With Humanizer on, the same pedal pattern follows the humanized performance. Falls back to Automatic if none found.",
            Qt.ItemDataRole.ToolTipRole,
        )
        self.pedal_style_combo.setItemData(
            1,
            "Analyzes song sections to switch between Rhythmic and Sustain.",
            Qt.ItemDataRole.ToolTipRole,
        )
        self.pedal_style_combo.setItemData(
            2,
            "Ignores note length. Holds pedal until harmony changes.",
            Qt.ItemDataRole.ToolTipRole,
        )
        self.pedal_style_combo.setItemData(
            3,
            "Presses pedal only while keys are held down.",
            Qt.ItemDataRole.ToolTipRole,
        )
        self.pedal_style_combo.setItemData(
            4, "Disables auto-pedal entirely.", Qt.ItemDataRole.ToolTipRole
        )
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
        self.hk_label = QLabel(
            f"Start/Stop Hotkey: {self.hotkey_manager.format_key_string(self.hotkey_manager.current_key)}"
        )
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
        self.all_humanization_checks["simulate_hands"] = QCheckBox("Simulate Hands")
        self.all_humanization_checks["enable_chord_roll"] = QCheckBox("Chord Rolling")
        simple_toggles_layout.addWidget(self.all_humanization_checks["simulate_hands"])
        simple_toggles_layout.addStretch(1)
        simple_toggles_layout.addWidget(
            self.all_humanization_checks["enable_chord_roll"]
        )
        main_v_layout.addLayout(simple_toggles_layout)

        detailed_layout = QGridLayout()
        detailed_layout.setColumnStretch(2, 1)

        def add_detailed_row(
            row_idx,
            name,
            key,
            min_val,
            max_val,
            def_val,
            suffix,
            factor=1.0,
            decimals=3,
        ):
            check = QCheckBox(name)
            slider, spinbox = self._create_slider_and_spinbox(
                min_val, max_val, def_val, suffix, factor=factor, decimals=decimals
            )
            check.toggled.connect(slider.setEnabled)
            check.toggled.connect(spinbox.setEnabled)
            detailed_layout.addWidget(check, row_idx, 0)
            detailed_layout.addWidget(slider, row_idx, 2)
            detailed_layout.addWidget(spinbox, row_idx, 3)
            self.all_humanization_checks[key] = check
            self.all_humanization_sliders[key] = slider
            self.all_humanization_spinboxes[key] = spinbox

        add_detailed_row(
            0, "Vary Timing", "vary_timing", 0, 0.1, 0.01, " s", factor=10000.0
        )
        add_detailed_row(
            1,
            "Vary Articulation",
            "vary_articulation",
            50,
            100,
            95,
            "%",
            factor=100.0,
            decimals=1,
        )
        add_detailed_row(
            2, "Hand Drift", "hand_drift", 0, 100, 25, "%", factor=100.0, decimals=1
        )
        add_detailed_row(
            3,
            "Mistake Chance",
            "mistake_chance",
            0,
            10,
            0,
            "%",
            factor=100.0,
            decimals=1,
        )
        add_detailed_row(4, "Tempo Sway", "tempo_sway", 0, 0.1, 0, " s", factor=10000.0)

        self.invert_sway_check = QCheckBox("Invert tempo sway")
        self.all_humanization_checks["invert_tempo_sway"] = self.invert_sway_check
        self.all_humanization_checks["tempo_sway"].toggled.connect(
            self.invert_sway_check.setEnabled
        )
        detailed_layout.addWidget(self.invert_sway_check, 5, 0)
        main_v_layout.addLayout(detailed_layout)

        self.select_all_humanization_check.toggled.connect(
            self._toggle_all_humanization
        )
        for check in self.all_humanization_checks.values():
            if check.text():
                check.toggled.connect(self._update_select_all_state)
        self._reset_humanization_group_to_default()
        return group

    def _reset_controls_to_default(self):
        self.add_log_message("All settings have been reset to their default values.")
        self._reset_playback_group_to_default()
        self._reset_humanization_group_to_default()

    def _reset_playback_group_to_default(self):
        defaults = Config()
        self.tempo_spinbox.setValue(defaults.tempo)
        self.pedal_style_combo.setCurrentText(
            self.pedal_mapping_inv.get(defaults.pedal_style, "Original (from MIDI)")
        )
        self.use_88_key_check.setChecked(defaults.use_88_key_layout)
        default_output_index = self.output_mode_combo.findData(defaults.output_mode)
        if default_output_index >= 0:
            self.output_mode_combo.setCurrentIndex(default_output_index)
        self._update_88_key_visibility()
        self.countdown_check.setChecked(defaults.countdown)

    def _reset_humanization_group_to_default(self):
        self.all_humanization_spinboxes["vary_timing"].setValue(0.010)
        self.all_humanization_spinboxes["vary_articulation"].setValue(95.0)
        self.all_humanization_spinboxes["hand_drift"].setValue(25.0)
        self.all_humanization_spinboxes["mistake_chance"].setValue(0.5)
        self.all_humanization_spinboxes["tempo_sway"].setValue(0.015)
        for check in self.all_humanization_checks.values():
            if check.text():
                check.setChecked(False)
        self._update_enabled_states()

    def _toggle_all_humanization(self, checked):
        for check in self.all_humanization_checks.values():
            if check.text():
                check.setChecked(checked)

    def _update_select_all_state(self):
        checks = [c for c in self.all_humanization_checks.values() if c.text()]
        is_all_checked = all(c.isChecked() for c in checks)
        self.select_all_humanization_check.blockSignals(True)
        self.select_all_humanization_check.setChecked(is_all_checked)
        self.select_all_humanization_check.blockSignals(False)

    def _get_log_file_path(self):
        return self.config_dir / LOG_FILENAME

    def _log_startup_capabilities(self) -> None:
        caps = get_capabilities()
        timer_status = (
            "available"
            if caps.get("high_res_timer")
            else "not available (using standard timing)"
        )
        jukebox_logger.info(
            f"Platform: {caps.get('platform', 'unknown')}; high-resolution timer: {timer_status}."
        )
        if caps.get("platform") == "win32":
            direct = (
                "available"
                if caps.get("direct_input")
                else "not available"
            )
            jukebox_logger.info(f"Windows direct input (pydirectinput): {direct}.")

    def _check_macos_accessibility(self) -> None:
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
            "the IDE (e.g. PyCharm) if you run from an IDE; or the Jukebox app if you run the frozen executable (freeze to exe)."
        )
        open_btn = msg.addButton(
            "Open System Settings", QMessageBox.ButtonRole.ActionRole
        )
        msg.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        msg.exec()
        if msg.clickedButton() == open_btn:
            open_macos_accessibility_preferences()

    def _log_warning(self, message: str) -> None:
        jukebox_logger.warning(message)

    def _log_error(
        self,
        message: str,
        show_dialog: bool = False,
        dialog_title: str = "Error",
        exc_info: bool = False,
    ) -> None:
        jukebox_logger.error(message, exc_info=exc_info)
        if show_dialog:
            QMessageBox.critical(self, dialog_title, message)

    def _on_log_level_changed(self, level: str) -> None:
        if level:
            jukebox_logger.set_level(level)
            self._mark_config_dirty()

    def _on_log_save_to_file_toggled(self, checked: bool):
        path = self._get_log_file_path()
        if checked:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            jukebox_logger.enable_file_logging(str(path))
            self.add_log_message(f"Log is being saved to: {path}")
        else:
            jukebox_logger.disable_file_logging()
            self.add_log_message("Log file saving disabled.")
        self._mark_config_dirty()

    def _on_status_updated(self, message: str) -> None:
        lowered = message.lstrip().lower()
        if lowered.startswith("error:"):
            jukebox_logger.error(message[message.index(":") + 1:].strip())
            return
        if lowered.startswith("warning:"):
            jukebox_logger.warning(message[message.index(":") + 1:].strip())
            return
        self.add_log_message(message)

    def add_log_message(self, message, level="INFO"):
        jukebox_logger.log(level, message)

    def _append_log(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        plain = f"[{timestamp}] [{level}] {message}"

        log_colors = theme.get_dark_cyber_theme().logs
        color_map = {
            "DEBUG": log_colors.debug,
            "INFO": log_colors.info,
            "WARNING": log_colors.warning,
            "ERROR": log_colors.error,
        }
        color = color_map.get(level, log_colors.info)

        import html as html_module

        if level == "ERROR" and "\n" in message:
            first_line, _, rest = message.partition("\n")
            rest = rest.strip()
            if rest:
                escaped_first = html_module.escape(first_line)
                escaped_rest = html_module.escape(rest)
                html = (
                    f'<div style="color:{color}">[{timestamp}] [{level}] {escaped_first} '
                    f'<details><summary>Details</summary>'
                    f'<pre style="margin:0; white-space:pre-wrap;">{escaped_rest}</pre>'
                    f'</details></div>'
                )
            else:
                html = f'<div style="color:{color}">[{timestamp}] [{level}] {html_module.escape(message)}</div>'
        else:
            escaped = html_module.escape(message)
            html = f'<div style="color:{color}">[{timestamp}] [{level}] {escaped}</div>'

        self._log_entries.append({"level": level, "plain": plain, "html": html})
        if len(self._log_entries) > MAX_LOG_ENTRIES:
            self._log_entries = self._log_entries[-MAX_LOG_ENTRIES:]

        self._render_log()

    def _render_log(self) -> None:
        """Rebuild the QTextBrowser content from filtered entries."""
        query = self.log_filter_edit.text().strip().lower()

        parts: list[str] = []
        match_count = 0
        for entry in self._log_entries:
            if query and query not in entry["plain"].lower():
                continue
            parts.append(entry["html"])
            match_count += 1

        self.log_output.setHtml("\n".join(parts))
        total = len(self._log_entries)
        if query:
            self.log_filter_status.setText(f"{match_count}/{total}")
        else:
            self.log_filter_status.setText("")

        if self.log_auto_scroll_check.isChecked():
            sb = self.log_output.verticalScrollBar()
            if sb is not None:
                sb.setValue(sb.maximum())

    def _on_log_filter_text_changed(self) -> None:
        """Debounced filter: restart the 200 ms timer on each keystroke."""
        self._log_filter_timer.start(200)

    def _clear_log(self) -> None:
        """Clear all log entries from both storage and display."""
        self._log_entries.clear()
        self.log_output.clear()
        self.log_filter_status.setText("")

    def _on_log_wrap_toggled(self, checked: bool) -> None:
        if checked:
            self.log_output.setLineWrapMode(
                QTextBrowser.LineWrapMode.WidgetWidth
            )
        else:
            self.log_output.setLineWrapMode(
                QTextBrowser.LineWrapMode.NoWrap
            )

    def _on_log_record(self, level: str, message: str) -> None:
        self._append_log(level, message)

    def set_controls_enabled(self, enabled):
        for groupbox in self.findChildren(QGroupBox):
            groupbox.setEnabled(enabled)

    def _mark_config_dirty(self) -> None:
        """Debounce-triggered save: marks config dirty and starts a 500 ms timer.

        Multiple rapid UI changes (slider drags, checkbox clicks) coalesce into
        a single disk write.  Call ``_flush_config()`` before any operation that
        needs the saved config to be current (e.g. playback start, window close).
        """
        self._config_dirty = True
        if not self._config_save_timer.isActive():
            self._config_save_timer.start(500)

    def _flush_config(self) -> None:
        """Immediately persist the current UI state if it is dirty."""
        if self._config_dirty:
            self._config_save_timer.stop()
            self._save_config()
            self._config_dirty = False

    def _config_from_ui(self) -> Config:
        data = {}
        for binding in CONFIG_UI_BINDINGS:
            data[binding.key] = binding.getter(self)
        return Config.from_dict(data)

    def _save_config(self) -> None:
        """Immediate config persist to disk."""
        self._config_dirty = False
        try:
            config = self._config_from_ui()
            self.config_repo.save(config)
        except OSError as e:
            jukebox_logger.error(f"Error saving config: {e}", exc_info=True)
            self._log_error(
                "Error saving config: " + str(e),
                show_dialog=True,
                dialog_title="Error Saving Config",
            )

    def _update_enabled_states(self):
        for key, check in self.all_humanization_checks.items():
            if not check.text():
                continue
            is_checked = check.isChecked()
            if key in self.all_humanization_sliders:
                self.all_humanization_sliders[key].setEnabled(is_checked)
            if key in self.all_humanization_spinboxes:
                self.all_humanization_spinboxes[key].setEnabled(is_checked)
        self.invert_sway_check.setEnabled(
            self.all_humanization_checks["tempo_sway"].isChecked()
        )

    def _apply_config_to_ui(self, config: Config) -> None:
        effectful = effectful_keys()
        for binding in CONFIG_UI_BINDINGS:
            if binding.key in effectful:
                continue
            if hasattr(config, binding.key):
                binding.setter(self, getattr(config, binding.key))

    def _load_config(self) -> None:
        try:
            config = self.config_repo.load()
        except ConfigLoadError as e:
            jukebox_logger.error(
                f"Failed to load config from {e.path}: {e.cause}", exc_info=True
            )
            backup_note = (
                f" Corrupt config was moved to: {e.backup_path}."
                if e.backup_path is not None
                else ""
            )
            self._log_error(
                "Config file could not be loaded; using defaults."
                + backup_note
            )
            self._reset_controls_to_default()
            self._update_enabled_states()
            self._config_save_timer.stop()
            self._config_dirty = False
            return
        self._apply_config_to_ui(config)
        apply_config_effects(self, config)
        self._update_enabled_states()
        self._update_88_key_visibility()
        self._update_play_stop_labels()
        self._config_save_timer.stop()
        self._config_dirty = False  # loading config doesn't count as "dirty"

    def _set_current_file_labels(self, filepath: str | None) -> None:
        if filepath:
            name = os.path.basename(filepath)
            self.file_path_label.setText(name)
            self.file_path_label.setToolTip(filepath)
            self.current_file_bottom_label.setText(name)
        else:
            self.file_path_label.setText("No file selected.")
            self.file_path_label.setToolTip("")
            self.current_file_bottom_label.setText("No file selected.")

    def gather_config(self):
        if not self.selected_tracks_info:
            self._log_error(
                "Play aborted: no MIDI file or tracks selected.",
                show_dialog=False,
                dialog_title="No Tracks",
            )
            QMessageBox.warning(
                self,
                "No Tracks",
                "Please select a MIDI file and choose tracks first.",
            )
            return None
        config = self._config_from_ui().to_runtime_playback_dict()
        config["midi_file"] = self.file_path_label.toolTip()
        return config

    def select_file(self):
        if self.playback_controller.is_running:
            return
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select MIDI File", "", "MIDI Files (*.mid *.midi)"
        )
        if filepath:
            self._set_current_file_labels(filepath)
            self.add_log_message(f"Selected file: {filepath}")
            self._parse_and_select_tracks(filepath)

    def _parse_and_select_tracks(self, filepath):
        self.add_log_message("Parsing MIDI structure...")
        try:
            tempo_scale = self.tempo_spinbox.value() / 100.0
            tracks, tempo_map = MidiParser.parse_structure(filepath, tempo_scale)
        except Exception as e:
            jukebox_logger.error(f"Failed to parse MIDI: {e}", exc_info=True)
            self._log_error(
                "Failed to parse MIDI: " + str(e),
                show_dialog=True,
                dialog_title="Error",
            )
            return
        self.parsed_tracks = tracks
        self.parsed_tempo_map = tempo_map
        self.parsed_tempo_scale = tempo_scale
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
                    if role == "Left Hand":
                        n.hand = "left"
                    elif role == "Right Hand":
                        n.hand = "right"
                    else:
                        n.hand = "left" if n.pitch < 60 else "right"
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
            self._set_current_file_labels(None)

    def handle_play(self):
        if self.playback_controller.is_running:
            self.toggle_playback_state()
            return

        # Autoplay mode: start sequential folder playback
        if self.input_mode_playlist_radio.isChecked() and self.autoplay_file_list:
            # If a song was selected via double-click, start from there;
            # otherwise, start from the beginning.
            if self.autoplay_current_index < 0:
                self.autoplay_current_index = 0
            self._update_autoplay_highlight()
            self._autoplay_play_current()
            return

        config = self.gather_config()
        if not config:
            return
        self._save_config()
        self.add_log_message("Preparing playback...")
        if self.selected_tracks_info is None:
            return
        try:
            final_notes, sections, compiled_events, total_dur, tempo_map = (
                PlaybackService.prepare_playback(
                    config["midi_file"],
                    self.selected_tracks_info,
                    config,
                    preparsed=(self.parsed_tracks, self.parsed_tempo_map)
                    if self.parsed_tracks is not None
                    and self.parsed_tempo_map is not None
                    else None,
                    preparsed_tempo_scale=self.parsed_tempo_scale,
                )
            )
        except Exception as e:
            jukebox_logger.error(f"Error preparing playback: {e}", exc_info=True)
            self._log_error(
                "Error preparing playback: " + str(e),
                show_dialog=True,
                dialog_title="Error",
            )
            return

        self.current_notes = final_notes
        seek_ratio = 0.0
        if self.timeline_widget.total_duration > 0:
            seek_ratio = (
                self.timeline_widget.current_time / self.timeline_widget.total_duration
            )
        config["start_offset"] = seek_ratio * total_dur

        self.timeline_widget.set_data(final_notes, total_dur, tempo_map)
        self.total_song_duration_sec = total_dur

        if config.get("output_mode") == "key":
            self.add_log_message(
                "KEY mode does not preserve MIDI velocity dynamics. Use MIDI Numpad mode for full velocity expression."
            )

        self.set_controls_enabled(False)
        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(True)

        self.tabs.setCurrentIndex(1)

        started = self.playback_controller.start(
            compiled_events,
            config,
            total_dur,
            config["output_mode"],
            config.get("use_88_key_layout", False),
            log_message=self.add_log_message,
        )
        if started is False:
            self.set_controls_enabled(True)
            self.stop_button.setEnabled(False)
            self.play_button.setEnabled(True)

    def handle_stop(self):
        self._autoplay_stopping = self.playback_controller.is_running
        if self.playback_controller.is_running:
            self.playback_controller.stop()
        # Cancel any pending auto-advance timer
        self.autoplay_next_timer.stop()
        if self.input_mode_playlist_radio.isChecked():
            count = len(self.autoplay_file_list)
            if count and self.autoplay_current_index >= 0:
                name = os.path.basename(self.autoplay_file_list[self.autoplay_current_index])
                self.autoplay_info_label.setText(f"Stopped: {name}")
                self.autoplay_info_label.setStyleSheet("font-style: italic; color: grey;")
            elif count:
                self.autoplay_info_label.setText(f"{count} MIDI file(s) found.")
                self.autoplay_info_label.setStyleSheet("font-style: italic; color: grey;")

    def handle_reset(self):
        self.timeline_widget.set_position(0)
        self._update_time_label(0, self.total_song_duration_sec)
        self._on_visual_scrub(0)
        if self.playback_controller.is_running:
            self.playback_controller.seek(0)

    def on_playback_finished(self):
        self.add_log_message("Playback process finished.\n" + "=" * 50 + "\n")
        self.piano_widget.clear()
        self.set_controls_enabled(True)
        self.stop_button.setEnabled(False)

        # Don't auto-advance if Stop was pressed or a song jump was triggered
        if self._autoplay_stopping:
            self._autoplay_stopping = False
            return

        # Autoplay: advance to next song
        if (
            self.input_mode_playlist_radio.isChecked()
            and self.autoplay_file_list
            and self.autoplay_current_index >= 0
        ):
            self.autoplay_current_index += 1
            if self.autoplay_current_index < len(self.autoplay_file_list):
                delay = self.autoplay_delay_spinbox.value()
                rand_delay = self.autoplay_random_delay_spinbox.value()
                total_delay = delay + (random.uniform(0, rand_delay) if rand_delay > 0 else 0.0)  # nosec
                if total_delay > 0:
                    next_name = os.path.basename(
                        self.autoplay_file_list[self.autoplay_current_index]
                    )
                    self.autoplay_info_label.setText(
                        f"Next song in {total_delay:.1f}s: {next_name}"
                    )
                    self.autoplay_info_label.setStyleSheet(
                        "font-style: normal; color: grey;"
                    )
                    self.autoplay_next_timer.start(int(total_delay * 1000))
                else:
                    self._autoplay_play_current()
            else:
                self.add_log_message("Autoplay: all songs played.")
                self.autoplay_info_label.setText("All songs played.")
                self.autoplay_info_label.setStyleSheet("font-style: italic; color: grey;")
                self.autoplay_current_index = -1
                self._update_autoplay_highlight()

    def closeEvent(self, a0: QCloseEvent) -> None:  # type: ignore[override]  # noqa: N802
        self.autoplay_next_timer.stop()
        try:
            self._flush_config()
        except Exception as e:
            jukebox_logger.error(f"Error during closeEvent cleanup: {e}", exc_info=True)
        if self.midi_input_active:
            self._disconnect_midi_input()
        if self.live_backend:
            self.live_backend.shutdown()
        if self.playback_controller.is_running:
            self.playback_controller.stop_and_wait(timeout_ms=1000)
        self.hotkey_manager.stop()
        a0.accept()
