"""Configuration persistence for Jukebox.

Config is stored as JSON; versioning is git-based (no version field in the file).
Defaults and key names are backward-compatible so old configs still load.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import datetime
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
    use_88_key_layout: bool = True
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
    hotkey: str = "f8"
    window_geometry: Optional[str] = None

    # Log
    save_log_to_file: bool = False
    log_level: str = "INFO"

    def to_dict(self) -> Dict[str, Any]:
        """Export for JSON; omit None geometry so we don't store empty."""
        d = asdict(self)
        if d.get("window_geometry") is None:
            d.pop("window_geometry", None)
        if d.get("midi_input_device") is None:
            d.pop("midi_input_device", None)
        return d

    def to_runtime_playback_dict(self) -> Dict[str, Any]:
        config = self.to_dict()
        config["vary_timing"] = bool(self.enable_vary_timing)
        config["vary_articulation"] = bool(self.enable_vary_articulation)
        config["timing_variance"] = self.value_timing_variance
        config["articulation"] = self.value_articulation / 100.0
        config["enable_drift_correction"] = bool(self.enable_hand_drift)
        config["drift_decay_factor"] = self.value_hand_drift_decay / 100.0
        config["mistake_chance"] = self.value_mistake_chance
        config["tempo_sway_intensity"] = self.value_tempo_sway_intensity
        return config

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Config:
        """Build Config from dict; unknown keys are ignored, missing keys use defaults."""
        if not isinstance(data, dict):
            raise TypeError("Config JSON must be an object")

        migrated = dict(data)
        if "enable_vary_timing" not in migrated and "vary_timing" in migrated:
            migrated["enable_vary_timing"] = migrated["vary_timing"]
        if "enable_vary_articulation" not in migrated and "vary_articulation" in migrated:
            migrated["enable_vary_articulation"] = migrated["vary_articulation"]
        if "enable_hand_drift" not in migrated and "enable_drift_correction" in migrated:
            migrated["enable_hand_drift"] = migrated["enable_drift_correction"]
        if "value_timing_variance" not in migrated and "timing_variance" in migrated:
            migrated["value_timing_variance"] = migrated["timing_variance"]
        if "value_articulation" not in migrated and "articulation" in migrated:
            articulation = migrated["articulation"]
            migrated["value_articulation"] = (
                articulation * 100.0
                if isinstance(articulation, (int, float)) and articulation <= 1.0
                else articulation
            )
        if "value_hand_drift_decay" not in migrated and "drift_decay_factor" in migrated:
            drift_decay_factor = migrated["drift_decay_factor"]
            migrated["value_hand_drift_decay"] = (
                drift_decay_factor * 100.0
                if isinstance(drift_decay_factor, (int, float))
                else drift_decay_factor
            )
        if "value_mistake_chance" not in migrated and "mistake_chance" in migrated:
            migrated["value_mistake_chance"] = migrated["mistake_chance"]
        if "value_tempo_sway_intensity" not in migrated and "tempo_sway_intensity" in migrated:
            migrated["value_tempo_sway_intensity"] = migrated["tempo_sway_intensity"]

        defaults = cls()
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in migrated.items() if k in known}

        bool_fields = {
            "use_88_key_layout",
            "countdown",
            "select_all_humanization",
            "simulate_hands",
            "enable_chord_roll",
            "enable_vary_timing",
            "enable_vary_articulation",
            "enable_hand_drift",
            "enable_mistakes",
            "enable_tempo_sway",
            "invert_tempo_sway",
            "always_on_top",
            "save_log_to_file",
        }
        for key in bool_fields:
            if key in filtered:
                filtered[key] = _coerce_bool(filtered[key], getattr(defaults, key))

        float_fields = {
            "tempo",
            "value_timing_variance",
            "value_articulation",
            "value_hand_drift_decay",
            "value_mistake_chance",
            "value_tempo_sway_intensity",
        }
        for key in float_fields:
            if key in filtered:
                filtered[key] = _coerce_float(filtered[key], getattr(defaults, key))

        if "opacity" in filtered:
            filtered["opacity"] = _coerce_int(filtered["opacity"], defaults.opacity)

        if "pedal_style" in filtered:
            filtered["pedal_style"] = _sanitize_choice(
                filtered["pedal_style"],
                {"original", "hybrid", "legato", "rhythmic", "none"},
                defaults.pedal_style,
            )
        if "output_mode" in filtered:
            filtered["output_mode"] = _sanitize_choice(
                filtered["output_mode"],
                {"key", "midi_numpad"},
                defaults.output_mode,
            )
        if "input_mode" in filtered:
            filtered["input_mode"] = _sanitize_choice(
                filtered["input_mode"],
                {"file", "piano"},
                defaults.input_mode,
            )
        if "log_level" in filtered:
            filtered["log_level"] = _sanitize_choice(
                str(filtered["log_level"]).upper(),
                {"DEBUG", "INFO", "WARNING", "ERROR"},
                defaults.log_level,
            )

        if "hotkey" in filtered:
            hotkey = str(filtered["hotkey"]).strip()
            filtered["hotkey"] = hotkey or defaults.hotkey

        if "window_geometry" in filtered:
            filtered["window_geometry"] = _coerce_optional_str(filtered["window_geometry"])
        if "midi_input_device" in filtered:
            filtered["midi_input_device"] = _coerce_optional_str(
                filtered["midi_input_device"]
            )

        config = cls(**filtered)
        config.tempo = _clamp(config.tempo, 10.0, 200.0)
        config.value_timing_variance = _clamp(config.value_timing_variance, 0.0, 0.1)
        config.value_articulation = _clamp(config.value_articulation, 50.0, 100.0)
        config.value_hand_drift_decay = _clamp(config.value_hand_drift_decay, 0.0, 100.0)
        config.value_mistake_chance = _clamp(config.value_mistake_chance, 0.0, 10.0)
        config.value_tempo_sway_intensity = _clamp(
            config.value_tempo_sway_intensity, 0.0, 0.1
        )
        config.opacity = int(_clamp(config.opacity, 20, 100))
        return config


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_float(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return default
    return default


def _sanitize_choice(value: Any, allowed: set[str], default: str) -> str:
    if not isinstance(value, str):
        return default
    candidate = value.strip()
    return candidate if candidate in allowed else default


def _coerce_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


class ConfigRepository:
    """Load and save Config to a JSON file under user config dir."""

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or (Path.home() / CONFIG_DIR_NAME)
        self.config_path = self.config_dir / CONFIG_FILENAME

    def ensure_config_dir(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> Config:
        """Load config from disk. Missing file returns defaults; invalid files raise ConfigLoadError."""
        if not self.config_path.exists():
            return Config()
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Config.from_dict(data)
        except (json.JSONDecodeError, TypeError) as e:
            backup_path = self._backup_corrupt_config()
            raise ConfigLoadError(self.config_path, e, backup_path=backup_path) from e
        except OSError as e:
            raise ConfigLoadError(self.config_path, e) from e

    def _backup_corrupt_config(self) -> Optional[Path]:
        try:
            if not self.config_path.exists():
                return None
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = self.config_dir / f"config.corrupt.{stamp}.json"
            self.config_path.replace(backup_path)
            return backup_path
        except OSError:
            return None

    def save(self, config: Config) -> None:
        """Persist config to disk. Raises on I/O error."""
        self.ensure_config_dir()
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=4)


class ConfigLoadError(Exception):
    """Raised when config file exists but could not be loaded (corrupt or invalid)."""

    def __init__(
        self,
        path: Path,
        cause: Exception,
        backup_path: Optional[Path] = None,
    ):
        self.path = path
        self.cause = cause
        self.backup_path = backup_path
        super().__init__(f"Failed to load config from {path}: {cause}")
