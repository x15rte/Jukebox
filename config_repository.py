"""Configuration persistence for Jukebox.

Config is stored as JSON; versioning is git-based (no version field in the file).
Defaults and key names are backward-compatible so old configs still load.

Field metadata system
---------------------
Each dataclass field can carry metadata keys that control serialization,
migration, coercion, and runtime mapping:

    ``old_names``      tuple[str, ...]   Names used in previous config versions
    ``range``          (min, max)        Clamp numeric values on load
    ``choices``        set[str]          Allowed string values (sanitized on load)
    ``omit_if_none``   bool              Skip field in JSON when None (default False)
    ``runtime_alias``  str               Name to use in the runtime playback config
    ``runtime_scale``  float             Multiplier for the runtime value (default 1.0)

Adding a new config field is a single-line dataclass field declaration with
optional metadata — no manual from_dict/to_dict glue required.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Dict, Iterator, Optional, Set, Tuple, Union, get_type_hints


CONFIG_DIR_NAME = ".jukebox_piano"
CONFIG_FILENAME = "config.json"


# ---------------------------------------------------------------------------
# Field metadata helpers
# ---------------------------------------------------------------------------


class _FieldMeta:
    """Resolved metadata for one Config field, built from field annotations and field() metadata."""

    __slots__ = (
        "old_names",
        "cls_type",
        "range_",
        "choices",
        "is_optional",
        "omit_if_none",
        "runtime_alias",
        "runtime_scale",
    )

    def __init__(
        self,
        *,
        old_names: Tuple[str, ...] = (),
        cls_type: type = str,
        range_: Optional[Tuple[float, float]] = None,
        choices: Optional[Set[str]] = None,
        is_optional: bool = False,
        omit_if_none: bool = False,
        runtime_alias: Optional[str] = None,
        runtime_scale: float = 1.0,
    ) -> None:
        self.old_names = old_names
        self.cls_type = cls_type
        self.range_ = range_
        self.choices = choices
        self.is_optional = is_optional
        self.omit_if_none = omit_if_none
        self.runtime_alias = runtime_alias
        self.runtime_scale = runtime_scale


def _resolve_type(tp: type) -> type:
    """Resolve a type annotation to a simple type, unwrapping Optional."""
    origin = getattr(tp, "__origin__", None)
    if origin is Union:
        args = getattr(tp, "__args__", ())
        non_none = [a for a in args if a is not type(None)]
        return non_none[0] if non_none else str
    if origin is list or origin is dict:
        return str
    return tp


def _build_field_meta(cls: type) -> Dict[str, _FieldMeta]:
    """Build a dict of field_name → _FieldMeta from dataclass field metadata and annotations."""
    meta: Dict[str, _FieldMeta] = {}
    try:
        hints = get_type_hints(cls)
    except Exception:
        hints = {}
    for f in fields(cls):
        if f.name.startswith("_"):
            continue
        raw = f.metadata or {}
        resolved_type = _resolve_type(hints.get(f.name, str))
        meta[f.name] = _FieldMeta(
            old_names=raw.get("old_names", ()),
            cls_type=resolved_type,
            range_=raw.get("range"),
            choices=raw.get("choices"),
            is_optional=raw.get("optional", False),
            omit_if_none=raw.get("omit_if_none", False),
            runtime_alias=raw.get("runtime_alias"),
            runtime_scale=raw.get("runtime_scale", 1.0),
        )
    return meta


# ---------------------------------------------------------------------------
# Coercion helpers  (kept as module-level for testability)
# ---------------------------------------------------------------------------


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



def _coerce_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _coerce_field(value: Any, meta: _FieldMeta, default: Any) -> Any:
    """Coerce *value* according to the field's type metadata, falling back to *default*."""
    tp = meta.cls_type

    if tp is bool:
        return _coerce_bool(value, default)

    if tp is float:
        result = _coerce_float(value, default)
        if meta.range_:
            result = _clamp(result, meta.range_[0], meta.range_[1])
        return result

    if tp is int:
        result = _coerce_int(value, default)
        if meta.range_:
            result = int(_clamp(float(result), meta.range_[0], meta.range_[1]))
        return result

    if tp is str:
        if isinstance(value, str):
            val = value.strip()
            if meta.choices:
                # Case-fold for choice matching (e.g. "warning" → "WARNING")
                for choice in meta.choices:
                    if val.upper() == choice.upper():
                        return choice
                return default
            if meta.is_optional:
                return val if val else None
            return val
        return default

    # Optional[str] — resolved type is str but we handle None separately
    if tp is type(None):
        coerced = _coerce_optional_str(value)
        return coerced if coerced is not None else default

    return value if isinstance(value, tp) else default


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


@dataclass
class Config:
    """All user preferences persisted to config.json.

    Each field can carry metadata that drives loading, coercion, migration,
    and runtime-export behaviour.  See module docstring for the metadata keys.
    """

    _field_meta: ClassVar[Optional[Dict[str, _FieldMeta]]] = None

    # Playback / file
    tempo: float = field(default=100.0, metadata={"range": (10.0, 200.0)})
    pedal_style: str = field(
        default="original",
        metadata={"choices": {"original", "hybrid", "legato", "rhythmic", "none"}},
    )
    use_88_key_layout: bool = field(default=True)
    countdown: bool = field(default=True)
    output_mode: str = field(
        default="key",
        metadata={"choices": {"key", "midi_numpad"}},
    )
    input_mode: str = field(
        default="file",
        metadata={"choices": {"file", "piano"}},
    )
    midi_input_device: Optional[str] = field(
        default=None,
        metadata={"omit_if_none": True, "optional": True},
    )

    # Autoplay
    autoplay_folder: Optional[str] = field(
        default=None,
        metadata={"omit_if_none": True, "optional": True},
    )
    autoplay_mode: bool = field(default=False)
    autoplay_delay: float = field(default=0.0, metadata={"range": (0.0, 600.0)})
    autoplay_random_delay: float = field(
        default=0.0, metadata={"range": (0.0, 60.0)}
    )

    # Humanization
    select_all_humanization: bool = field(default=False)
    simulate_hands: bool = field(default=False)
    enable_chord_roll: bool = field(default=False)
    enable_vary_timing: bool = field(
        default=False,
        metadata={
            "old_names": ("vary_timing",),
            "runtime_alias": "vary_timing",
        },
    )
    value_timing_variance: float = field(
        default=0.01,
        metadata={
            "old_names": ("timing_variance",),
            "range": (0.0, 0.1),
            "runtime_alias": "timing_variance",
        },
    )
    enable_vary_articulation: bool = field(
        default=False,
        metadata={
            "old_names": ("vary_articulation",),
            "runtime_alias": "vary_articulation",
        },
    )
    value_articulation: float = field(
        default=95.0,
        metadata={
            "old_names": ("articulation",),
            "range": (50.0, 100.0),
            "runtime_alias": "articulation",
            "runtime_scale": 0.01,
        },
    )
    enable_hand_drift: bool = field(
        default=False,
        metadata={
            "old_names": ("enable_drift_correction",),
            "runtime_alias": "enable_drift_correction",
        },
    )
    value_hand_drift_decay: float = field(
        default=25.0,
        metadata={
            "old_names": ("drift_decay_factor",),
            "range": (0.0, 100.0),
            "runtime_alias": "drift_decay_factor",
            "runtime_scale": 0.01,
        },
    )
    enable_mistakes: bool = field(default=False)
    value_mistake_chance: float = field(
        default=0.5,
        metadata={
            "old_names": ("mistake_chance",),
            "range": (0.0, 10.0),
            "runtime_alias": "mistake_chance",
        },
    )
    enable_tempo_sway: bool = field(default=False)
    value_tempo_sway_intensity: float = field(
        default=0.015,
        metadata={
            "old_names": ("tempo_sway_intensity",),
            "range": (0.0, 0.1),
            "runtime_alias": "tempo_sway_intensity",
        },
    )
    invert_tempo_sway: bool = field(default=False)

    # Window / overlay
    always_on_top: bool = field(default=False)
    opacity: int = field(default=100, metadata={"range": (20, 100)})
    hotkey: str = field(default="f8")
    window_geometry: Optional[str] = field(
        default=None,
        metadata={"omit_if_none": True, "optional": True},
    )

    # Log
    save_log_to_file: bool = field(default=False)
    log_level: str = field(
        default="INFO",
        metadata={"choices": {"DEBUG", "INFO", "WARNING", "ERROR"}},
    )

    # ------------------------------------------------------------------
    # Metadata access
    # ------------------------------------------------------------------

    @classmethod
    def field_meta(cls) -> Dict[str, _FieldMeta]:
        """Lazily build and cache the field-metadata dict."""
        if cls._field_meta is None:
            cls._field_meta = _build_field_meta(cls)
        return cls._field_meta

    @classmethod
    def known_field_names(cls) -> Set[str]:
        """Return the set of all known Config field names."""
        return set(cls.field_meta().keys())

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Export for JSON; omit fields whose metadata marks them omit_if_none when None."""
        d = asdict(self)
        meta = self.field_meta()
        to_pop = [k for k, v in d.items() if v is None and meta.get(k, _FieldMeta()).omit_if_none]
        for k in to_pop:
            d.pop(k, None)
        return d

    def to_runtime_playback_dict(self) -> "PlaybackConfig":
        """Build a typed PlaybackConfig suitable for the analysis / playback pipeline.

        Fields with a ``runtime_alias`` in their metadata are renamed, scaled,
        and included alongside the original fields so both old and new consumers
        work without changes.
        """
        raw = self.to_dict()
        meta = self.field_meta()

        # Apply runtime aliases and scaling
        runtime_overrides: Dict[str, Any] = {}
        for key, fm in meta.items():
            if fm.runtime_alias:
                val = raw.get(key, getattr(self, key))
                if fm.runtime_scale != 1.0 and isinstance(val, (int, float)):
                    val = val * fm.runtime_scale
                runtime_overrides[fm.runtime_alias] = val

        # Merge and return as a PlaybackConfig (which behaves like a dict)
        merged = dict(raw)
        merged.update(runtime_overrides)
        return PlaybackConfig(**merged)

    # ------------------------------------------------------------------
    # Deserialization
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        """Build Config from dict; unknown keys are ignored, missing keys use defaults.

        Handles:
        - Migration of old key names
        - Type coercion (bool, float, int, str, Optional[str])
        - Range clamping
        - Choice sanitization
        - Optional-string stripping
        """
        if not isinstance(data, dict):
            raise TypeError("Config JSON must be an object")

        meta = cls.field_meta()
        migrated = dict(data)
        original_keys: Set[str] = set(data.keys())

        # Phase 1: migrate old key names
        for key, fm in meta.items():
            for old_name in fm.old_names:
                if old_name in migrated and key not in original_keys:
                    migrated[key] = migrated[old_name]

        # Phase 2: handle backward-compat scaling for articulation & drift_decay
        # (old persisted values might be 0-1 range rather than our new 0-100)
        # Only applies when the new key was NOT in the original data (i.e. the
        # value came from an old-name migration above or was the raw old key).
        if "articulation" in migrated and "value_articulation" not in original_keys:
            val = migrated["articulation"]
            if isinstance(val, (int, float)) and val <= 1.0:
                migrated["value_articulation"] = val * 100.0
            else:
                migrated["value_articulation"] = val
        if "drift_decay_factor" in migrated and "value_hand_drift_decay" not in original_keys:
            val = migrated["drift_decay_factor"]
            if isinstance(val, (int, float)):
                migrated["value_hand_drift_decay"] = val * 100.0

        # Phase 3: filter to known fields only
        known = cls.known_field_names()
        filtered: Dict[str, Any] = {}
        for k, v in migrated.items():
            if k in known:
                filtered[k] = v

        # Phase 4: coerce each field
        defaults = cls()
        coerced: Dict[str, Any] = {}
        for k, v in filtered.items():
            default_val = getattr(defaults, k)
            coerced[k] = _coerce_field(v, meta[k], default_val)

        # Phase 5: build instance
        config = cls(**coerced)

        # Phase 6: post-coercion clamping for hotkey
        if "hotkey" in coerced and not coerced["hotkey"]:
            config.hotkey = defaults.hotkey

        return config


# ---------------------------------------------------------------------------
# PlaybackConfig — typed runtime config with dict-like compatibility
# ---------------------------------------------------------------------------


class PlaybackConfig(Mapping[str, Any]):  # type: ignore[type-arg]
    """Typed runtime playback configuration with Mapping backward compatibility.

    This is the return type of ``Config.to_runtime_playback_dict()`` and flows
    through the analysis and playback pipeline (Humanizer, PedalGenerator,
    EventCompiler, Player).

    Because it inherits from ``collections.abc.Mapping``, it can be passed to
    any function annotated with ``Mapping[str, Any]`` and ``dict(config)``
    produces a plain dict copy.
    """

    # ---- All known runtime fields (with defaults) ----
    tempo: float = 100.0
    pedal_style: str = "original"
    use_88_key_layout: bool = True
    countdown: bool = True
    output_mode: str = "key"
    input_mode: str = "file"
    midi_input_device: Optional[str] = None

    autoplay_folder: Optional[str] = None
    autoplay_mode: bool = False
    autoplay_delay: float = 0.0
    autoplay_random_delay: float = 0.0

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

    always_on_top: bool = False
    opacity: int = 100
    hotkey: str = "f8"
    window_geometry: Optional[str] = None

    # Runtime aliases
    vary_timing: bool = False
    vary_articulation: bool = False
    timing_variance: float = 0.01
    articulation: float = 0.95
    enable_drift_correction: bool = False
    drift_decay_factor: float = 0.25
    mistake_chance: float = 0.5
    tempo_sway_intensity: float = 0.015

    # Runtime-only keys (not persisted, injected during playback setup).
    midi_file: str = ""
    start_offset: float = 0.0
    raw_pedal_events: Optional[list] = None

    def __init__(self, **kwargs: Any) -> None:
        """Accept arbitrary keyword arguments, including non-annotated extras."""
        known = set(type(self).__annotations__)
        for k, v in kwargs.items():
            if k in known:
                setattr(self, k, v)
            else:
                object.__setattr__(self, k, v)
        if self.raw_pedal_events is None:
            object.__setattr__(self, 'raw_pedal_events', [])

    # ---- Mapping protocol ----

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError as e:
            raise KeyError(key) from e

    def __iter__(self) -> Iterator[str]:
        return (k for k in self.__annotations__ if hasattr(self, k))

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        return hasattr(self, key)

    # ---- Mutability ----

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    # ---- Additional helpers ----

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default


    def __repr__(self) -> str:
        items = ", ".join(
            f"{k}={getattr(self, k)!r}"
            for k in self.__annotations__
            if hasattr(self, k)
        )
        return f"PlaybackConfig({items})"


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


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
        tmp_path = self.config_path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=4)
        os.replace(str(tmp_path), str(self.config_path))


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
