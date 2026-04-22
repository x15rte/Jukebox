import json
from pathlib import Path
from typing import Any, cast

import pytest

from config_repository import (
    Config,
    ConfigLoadError,
    ConfigRepository,
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_optional_str,
    _sanitize_choice,
)


def test_config_from_dict_migrates_and_clamps_values():
    data = {
        "vary_timing": True,
        "vary_articulation": True,
        "enable_drift_correction": True,
        "timing_variance": "0.2",
        "articulation": 0.5,
        "drift_decay_factor": 1.5,
        "mistake_chance": 12,
        "tempo_sway_intensity": "0.2",
        "tempo": 999,
        "opacity": "10",
        "output_mode": "invalid",
        "log_level": "debug",
        "window_geometry": "  ",
    }

    cfg = Config.from_dict(data)

    if not (cfg.enable_vary_timing is True):
        raise AssertionError("Assertion failed")
    if not (cfg.enable_vary_articulation is True):
        raise AssertionError("Assertion failed")
    if not (cfg.enable_hand_drift is True):
        raise AssertionError("Assertion failed")
    if not (cfg.value_timing_variance == 0.1):
        raise AssertionError("Assertion failed")
    if not (cfg.value_articulation == 50.0):
        raise AssertionError("Assertion failed")
    if not (cfg.value_hand_drift_decay == 100.0):
        raise AssertionError("Assertion failed")
    if not (cfg.value_mistake_chance == 10.0):
        raise AssertionError("Assertion failed")
    if not (cfg.value_tempo_sway_intensity == 0.1):
        raise AssertionError("Assertion failed")
    if not (cfg.tempo == 200.0):
        raise AssertionError("Assertion failed")
    if not (cfg.opacity == 20):
        raise AssertionError("Assertion failed")
    if not (cfg.output_mode == "key"):
        raise AssertionError("Assertion failed")
    if not (cfg.log_level == "DEBUG"):
        raise AssertionError("Assertion failed")
    if not (cfg.window_geometry is None):
        raise AssertionError("Assertion failed")


def test_config_to_runtime_playback_dict_exports_runtime_aliases():
    cfg = Config(enable_vary_timing=True, enable_vary_articulation=True, value_articulation=90)
    d = cfg.to_runtime_playback_dict()
    if not (d["vary_timing"] is True):
        raise AssertionError("Assertion failed")
    if not (d["vary_articulation"] is True):
        raise AssertionError("Assertion failed")
    if not (d["articulation"] == 0.9):
        raise AssertionError("Assertion failed")


def test_repository_load_returns_defaults_when_missing(tmp_path: Path):
    repo = ConfigRepository(config_dir=tmp_path)
    cfg = repo.load()
    if not (isinstance(cfg, Config)):
        raise AssertionError("Assertion failed")


def test_repository_load_backs_up_corrupt_json(tmp_path: Path):
    repo = ConfigRepository(config_dir=tmp_path)
    repo.ensure_config_dir()
    repo.config_path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc:
        repo.load()

    if not (exc.value.backup_path is not None):
        raise AssertionError("Assertion failed")
    if not (exc.value.backup_path.exists()):
        raise AssertionError("Assertion failed")
    if not (not repo.config_path.exists()):
        raise AssertionError("Assertion failed")


def test_repository_save_and_load_roundtrip(tmp_path: Path):
    repo = ConfigRepository(config_dir=tmp_path)
    cfg = Config(tempo=123.0, pedal_style="rhythmic", hotkey="k")
    repo.save(cfg)

    loaded = repo.load()
    if not (loaded.tempo == 123.0):
        raise AssertionError("Assertion failed")
    if not (loaded.pedal_style == "rhythmic"):
        raise AssertionError("Assertion failed")
    if not (loaded.hotkey == "k"):
        raise AssertionError("Assertion failed")

    raw = json.loads(repo.config_path.read_text(encoding="utf-8"))
    if not (raw["tempo"] == 123.0):
        raise AssertionError("Assertion failed")


def test_config_from_dict_rejects_non_object():
    with pytest.raises(TypeError):
        Config.from_dict(cast(Any, []))


def test_config_from_dict_bool_coercions_and_sanitizers():
    cfg = Config.from_dict(
        {
            "countdown": "off",
            "use_88_key_layout": "yes",
            "macos_use_pynput": 0,
            "save_log_to_file": 1,
            "pedal_style": "none",
            "input_mode": "piano",
            "log_level": "warning",
            "hotkey": "   ",
            "midi_input_device": "   ",
        }
    )

    if not (cfg.countdown is False):
        raise AssertionError("Assertion failed")
    if not (cfg.use_88_key_layout is True):
        raise AssertionError("Assertion failed")
    if not (cfg.macos_use_pynput is False):
        raise AssertionError("Assertion failed")
    if not (cfg.save_log_to_file is True):
        raise AssertionError("Assertion failed")
    if not (cfg.pedal_style == "none"):
        raise AssertionError("Assertion failed")
    if not (cfg.input_mode == "piano"):
        raise AssertionError("Assertion failed")
    if not (cfg.log_level == "WARNING"):
        raise AssertionError("Assertion failed")
    if not (cfg.hotkey == "f6"):
        raise AssertionError("Assertion failed")
    if not (cfg.midi_input_device is None):
        raise AssertionError("Assertion failed")


def test_config_to_dict_omits_none_fields():
    cfg = Config(window_geometry=None, midi_input_device=None)
    d = cfg.to_dict()
    if not ("window_geometry" not in d):
        raise AssertionError("Assertion failed")
    if not ("midi_input_device" not in d):
        raise AssertionError("Assertion failed")


def test_runtime_playback_dict_contains_expected_aliases():
    cfg = Config(
        enable_hand_drift=True,
        value_hand_drift_decay=25.0,
        value_mistake_chance=1.5,
        value_tempo_sway_intensity=0.02,
    )
    d = cfg.to_runtime_playback_dict()
    if not (d["enable_drift_correction"] is True):
        raise AssertionError("Assertion failed")
    if not (d["drift_decay_factor"] == 0.25):
        raise AssertionError("Assertion failed")
    if not (d["mistake_chance"] == 1.5):
        raise AssertionError("Assertion failed")
    if not (d["tempo_sway_intensity"] == 0.02):
        raise AssertionError("Assertion failed")


def test_repository_load_raises_when_backup_fails(monkeypatch, tmp_path: Path):
    repo = ConfigRepository(config_dir=tmp_path)
    repo.ensure_config_dir()
    repo.config_path.write_text("{bad", encoding="utf-8")
    monkeypatch.setattr(repo, "_backup_corrupt_config", lambda: None)

    with pytest.raises(ConfigLoadError) as exc:
        repo.load()

    if not (exc.value.backup_path is None):
        raise AssertionError("Assertion failed")


def test_backup_corrupt_config_missing_file_returns_none(tmp_path: Path):
    repo = ConfigRepository(config_dir=tmp_path)
    if not (repo._backup_corrupt_config() is None):
        raise AssertionError("Assertion failed")


def test_backup_corrupt_config_handles_oserror(monkeypatch, tmp_path: Path):
    repo = ConfigRepository(config_dir=tmp_path)
    repo.ensure_config_dir()
    repo.config_path.write_text("{}", encoding="utf-8")

    def bad_replace(_path):
        raise OSError("boom")

    monkeypatch.setattr(type(repo.config_path), "replace", lambda self, p: bad_replace(p))
    out = repo._backup_corrupt_config()
    if not (out is None):
        raise AssertionError("Assertion failed")


def test_repository_load_wraps_oserror(monkeypatch, tmp_path: Path):
    repo = ConfigRepository(config_dir=tmp_path)
    repo.ensure_config_dir()
    repo.config_path.write_text("{}", encoding="utf-8")

    import builtins

    real_open = builtins.open

    def bad_open(*args, **kwargs):
        if args and str(args[0]).endswith("config.json"):
            raise OSError("read fail")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", bad_open)

    with pytest.raises(ConfigLoadError) as exc:
        repo.load()

    if not ("read fail" in str(exc.value)):
        raise AssertionError("Assertion failed")


def test_coerce_helpers_fallback_branches():
    if not (_coerce_bool("maybe", True) is True):
        raise AssertionError("Assertion failed")

    if not (_coerce_float(True, 1.2) == 1.2):
        raise AssertionError("Assertion failed")
    if not (_coerce_float("  bad  ", 1.2) == 1.2):
        raise AssertionError("Assertion failed")
    if not (_coerce_float([], 1.2) == 1.2):
        raise AssertionError("Assertion failed")

    if not (_coerce_int(True, 7) == 7):
        raise AssertionError("Assertion failed")
    if not (_coerce_int(3.9, 7) == 3):
        raise AssertionError("Assertion failed")
    if not (_coerce_int("bad", 7) == 7):
        raise AssertionError("Assertion failed")
    if not (_coerce_int([], 7) == 7):
        raise AssertionError("Assertion failed")


def test_sanitize_and_optional_str_branches():
    if not (_sanitize_choice(1, {"a"}, "d") == "d"):
        raise AssertionError("Assertion failed")
    if not (_sanitize_choice(" x ", {"x"}, "d") == "x"):
        raise AssertionError("Assertion failed")

    if not (_coerce_optional_str(None) is None):
        raise AssertionError("Assertion failed")
    if not (_coerce_optional_str(1) is None):
        raise AssertionError("Assertion failed")
    if not (_coerce_optional_str("  ") is None):
        raise AssertionError("Assertion failed")
    if not (_coerce_optional_str(" x ") == "x"):
        raise AssertionError("Assertion failed")
