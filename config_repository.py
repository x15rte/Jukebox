"""Configuration persistence for Jukebox.

Config is stored as JSON; versioning is git-based (no version field in the file).
Defaults and key names are backward-compatible so old configs still load.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Dict, Optional


CONFIG_DIR_NAME = ".jukebox_piano"
CONFIG_FILENAME = "config.json"


@dataclass
class Config:
    """All user preferences persisted to config.json.

    Version is tracked by git; users re-pull to get updates. No in-file version migration.
    """

    # Playback / file
    tempo: float = 100.0
    pedal_style: str = "original"
    use_88_key_layout: bool = False
    countdown: bool = True
    output_mode: str = "key"
    input_mode: str = "file"
    midi_input_device: Optional[str] = None

    # Humanization
    select_all_humanization: bool = False
    simulate_hands: bool = False
    enable_chord_roll: bool = False
    enable_vary_timing: bool = False
    value_timing_variance: float = 0.01
    enable_vary_articulation: bool = False
    value_articulation: float = 95.0
    enable_hand_drift: bool = False
    value_hand_drift_decay: float = 25.0
    enable_mistakes: bool = False
    value_mistake_chance: float = 0.5
    enable_tempo_sway: bool = False
    value_tempo_sway_intensity: float = 0.015
    invert_tempo_sway: bool = False

    # Window / overlay
    always_on_top: bool = False
    opacity: int = 100
    hotkey: str = "f6"
    window_geometry: Optional[str] = None

    # Log
    save_log_to_file: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Export for JSON; omit None geometry so we don't store empty."""
        d = asdict(self)
        if d.get("window_geometry") is None:
            d.pop("window_geometry", None)
        if d.get("midi_input_device") is None:
            d.pop("midi_input_device", None)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Config:
        """Build Config from dict; unknown keys are ignored, missing keys use defaults."""
        # Map legacy keys to current names for backward compatibility
        if "enable_vary_timing" not in data and "vary_timing" in data:
            data = {**data, "enable_vary_timing": data["vary_timing"]}
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


class ConfigRepository:
    """Load and save Config to a JSON file under user config dir."""

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or (Path.home() / CONFIG_DIR_NAME)
        self.config_path = self.config_dir / CONFIG_FILENAME

    def ensure_config_dir(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> Config:
        """Load config from disk. On missing file or parse error, return default Config."""
        if not self.config_path.exists():
            return Config()
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Config.from_dict(data)
        except (json.JSONDecodeError, OSError, TypeError) as e:
            # Caller can log and optionally reset UI to defaults
            raise ConfigLoadError(self.config_path, e) from e

    def save(self, config: Config) -> None:
        """Persist config to disk. Raises on I/O error."""
        self.ensure_config_dir()
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=4)


class ConfigLoadError(Exception):
    """Raised when config file exists but could not be loaded (corrupt or invalid)."""

    def __init__(self, path: Path, cause: Exception):
        self.path = path
        self.cause = cause
        super().__init__(f"Failed to load config from {path}: {cause}")
