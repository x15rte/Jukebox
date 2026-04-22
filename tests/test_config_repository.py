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

    assert cfg.enable_vary_timing is True
    assert cfg.enable_vary_articulation is True
    assert cfg.enable_hand_drift is True
    assert cfg.value_timing_variance == 0.1
    assert cfg.value_articulation == 50.0
    assert cfg.value_hand_drift_decay == 100.0
    assert cfg.value_mistake_chance == 10.0
    assert cfg.value_tempo_sway_intensity == 0.1
    assert cfg.tempo == 200.0
    assert cfg.opacity == 20
    assert cfg.output_mode == "key"
    assert cfg.log_level == "DEBUG"
    assert cfg.window_geometry is None


def test_config_to_runtime_playback_dict_exports_runtime_aliases():
    cfg = Config(enable_vary_timing=True, enable_vary_articulation=True, value_articulation=90)
    d = cfg.to_runtime_playback_dict()
    assert d["vary_timing"] is True
    assert d["vary_articulation"] is True
    assert d["articulation"] == 0.9


def test_repository_load_returns_defaults_when_missing(tmp_path: Path):
    repo = ConfigRepository(config_dir=tmp_path)
    cfg = repo.load()
    assert isinstance(cfg, Config)


def test_repository_load_backs_up_corrupt_json(tmp_path: Path):
    repo = ConfigRepository(config_dir=tmp_path)
    repo.ensure_config_dir()
    repo.config_path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc:
        repo.load()

    assert exc.value.backup_path is not None
    assert exc.value.backup_path.exists()
    assert not repo.config_path.exists()


def test_repository_save_and_load_roundtrip(tmp_path: Path):
    repo = ConfigRepository(config_dir=tmp_path)
    cfg = Config(tempo=123.0, pedal_style="rhythmic", hotkey="k")
    repo.save(cfg)

    loaded = repo.load()
    assert loaded.tempo == 123.0
    assert loaded.pedal_style == "rhythmic"
    assert loaded.hotkey == "k"

    raw = json.loads(repo.config_path.read_text(encoding="utf-8"))
    assert raw["tempo"] == 123.0


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

    assert cfg.countdown is False
    assert cfg.use_88_key_layout is True
    assert cfg.macos_use_pynput is False
    assert cfg.save_log_to_file is True
    assert cfg.pedal_style == "none"
    assert cfg.input_mode == "piano"
    assert cfg.log_level == "WARNING"
    assert cfg.hotkey == "f6"
    assert cfg.midi_input_device is None


def test_config_to_dict_omits_none_fields():
    cfg = Config(window_geometry=None, midi_input_device=None)
    d = cfg.to_dict()
    assert "window_geometry" not in d
    assert "midi_input_device" not in d


def test_runtime_playback_dict_contains_expected_aliases():
    cfg = Config(
        enable_hand_drift=True,
        value_hand_drift_decay=25.0,
        value_mistake_chance=1.5,
        value_tempo_sway_intensity=0.02,
    )
    d = cfg.to_runtime_playback_dict()
    assert d["enable_drift_correction"] is True
    assert d["drift_decay_factor"] == 0.25
    assert d["mistake_chance"] == 1.5
    assert d["tempo_sway_intensity"] == 0.02


def test_repository_load_raises_when_backup_fails(monkeypatch, tmp_path: Path):
    repo = ConfigRepository(config_dir=tmp_path)
    repo.ensure_config_dir()
    repo.config_path.write_text("{bad", encoding="utf-8")
    monkeypatch.setattr(repo, "_backup_corrupt_config", lambda: None)

    with pytest.raises(ConfigLoadError) as exc:
        repo.load()

    assert exc.value.backup_path is None


def test_backup_corrupt_config_missing_file_returns_none(tmp_path: Path):
    repo = ConfigRepository(config_dir=tmp_path)
    assert repo._backup_corrupt_config() is None


def test_backup_corrupt_config_handles_oserror(monkeypatch, tmp_path: Path):
    repo = ConfigRepository(config_dir=tmp_path)
    repo.ensure_config_dir()
    repo.config_path.write_text("{}", encoding="utf-8")

    def bad_replace(_path):
        raise OSError("boom")

    monkeypatch.setattr(type(repo.config_path), "replace", lambda self, p: bad_replace(p))
    out = repo._backup_corrupt_config()
    assert out is None


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

    assert "read fail" in str(exc.value)


def test_coerce_helpers_fallback_branches():
    assert _coerce_bool("maybe", True) is True

    assert _coerce_float(True, 1.2) == 1.2
    assert _coerce_float("  bad  ", 1.2) == 1.2
    assert _coerce_float([], 1.2) == 1.2

    assert _coerce_int(True, 7) == 7
    assert _coerce_int(3.9, 7) == 3
    assert _coerce_int("bad", 7) == 7
    assert _coerce_int([], 7) == 7


def test_sanitize_and_optional_str_branches():
    assert _sanitize_choice(1, {"a"}, "d") == "d"
    assert _sanitize_choice(" x ", {"x"}, "d") == "x"

    assert _coerce_optional_str(None) is None
    assert _coerce_optional_str(1) is None
    assert _coerce_optional_str("  ") is None
    assert _coerce_optional_str(" x ") == "x"
