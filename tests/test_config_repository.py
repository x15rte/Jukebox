import json
from pathlib import Path
from typing import Any, cast

import pytest

from config_repository import (
    Config,
    ConfigLoadError,
    ConfigRepository,
    PlaybackConfig,
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_optional_str,
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
    assert cfg.value_hand_drift_decay == 1.5
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
    assert cfg.use_88_key_layout is True
    assert cfg.hotkey == "f8"


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
    assert not hasattr(cfg, "macos_use_pynput")
    assert cfg.save_log_to_file is True
    assert cfg.pedal_style == "none"
    assert cfg.input_mode == "piano"
    assert cfg.log_level == "WARNING"
    assert cfg.hotkey == "f8"
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


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (True, False, True),
        (1, False, True),
        (0, True, False),
        (2, False, False),
        ("true", False, True),
        ("false", True, False),
        ("maybe", True, True),
        ([], False, False),
    ],
)
def test_coerce_bool_fallback_branches(value, default, expected):
    assert _coerce_bool(value, default) is expected


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [(True, 1.2, 1.2), ("  bad  ", 1.2, 1.2), ([], 1.2, 1.2)],
)
def test_coerce_float_fallback_branches(value, default, expected):
    assert _coerce_float(value, default) == expected


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [(True, 7, 7), (3.9, 7, 4), ("bad", 7, 7), ([], 7, 7)],
)
def test_coerce_int_fallback_branches(value, default, expected):
    assert _coerce_int(value, default) == expected



@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (1, None), ("  ", None), (" x ", "x")],
)
def test_coerce_optional_str_branches(value, expected):
    assert _coerce_optional_str(value) == expected


# ---------------------------------------------------------------------------
# PlaybackConfig tests
# ---------------------------------------------------------------------------


def test_playback_config_dict_access():
    pc = PlaybackConfig(tempo=120.0, output_mode="midi_numpad")
    assert pc["tempo"] == 120.0
    assert pc["output_mode"] == "midi_numpad"
    assert pc.get("tempo") == 120.0
    assert pc.get("missing_key", "fallback") == "fallback"
    assert "tempo" in pc
    assert "missing_key" not in pc


def test_playback_config_attribute_access():
    pc = PlaybackConfig(tempo=80.0, countdown=False)
    assert pc.tempo == 80.0
    assert pc.countdown is False
    pc.tempo = 150.0
    assert pc.tempo == 150.0


def test_playback_config_dict_setitem():
    pc = PlaybackConfig()
    pc["vary_timing"] = True
    assert pc.vary_timing is True
    pc["unknown_extra"] = 42
    assert pc["unknown_extra"] == 42




def test_playback_config_len():
    pc = PlaybackConfig(tempo=100.0)
    assert len(pc) > 0


def test_playback_config_repr():
    pc = PlaybackConfig(tempo=120.0)
    r = repr(pc)
    assert "tempo=120.0" in r


def test_playback_config_contains_extra():
    pc = PlaybackConfig(output_mode="key")
    pc["runtime_only"] = "value"
    assert "runtime_only" in pc
    assert pc["runtime_only"] == "value"


def test_playback_config_from_roundtrip():
    cfg = Config(tempo=150.0, enable_vary_timing=True, value_articulation=80.0)
    pc = cfg.to_runtime_playback_dict()
    assert pc.tempo == 150.0
    assert pc.vary_timing is True
    assert pc.articulation == 0.8
    assert pc.enable_vary_timing is True
    assert pc["articulation"] == 0.8


# ---------------------------------------------------------------------------
# Edge-case coverage: _resolve_type with list/dict (line 85)
# ---------------------------------------------------------------------------


def test_resolve_type_list_dict_returns_origin():
    """_resolve_type returns list/dict origin types for list[...] and dict[...]."""
    from config_repository import _resolve_type
    assert _resolve_type(list[int]) == list
    assert _resolve_type(dict[str, int]) == dict

# ---------------------------------------------------------------------------
# Edge-case coverage: _build_field_meta failures (lines 94-98)
# ---------------------------------------------------------------------------


def test_build_field_meta_get_type_hints_fails(monkeypatch):
    """_build_field_meta catches get_type_hints failure and uses empty hints."""
    from config_repository import _build_field_meta

    def _raise(*_a, **_kw):
        raise Exception("boom")

    monkeypatch.setattr("config_repository.get_type_hints", _raise)

    import dataclasses

    @dataclasses.dataclass
    class _GoodClass:
        name: str = "default"

    meta = _build_field_meta(_GoodClass)
    assert "name" in meta


def test_build_field_meta_skips_private_fields():
    """_build_field_meta skips fields starting with underscore."""
    from config_repository import _build_field_meta
    import dataclasses

    @dataclasses.dataclass
    class _WithPrivate:
        name: str = "val"
        _hidden: int = 42

    meta = _build_field_meta(_WithPrivate)
    assert "name" in meta
    assert "_hidden" not in meta


# ---------------------------------------------------------------------------
# Edge-case coverage: _coerce_field with type(None) (lines 215-219)
# ---------------------------------------------------------------------------



def test_coerce_field_str_returns_default_for_non_string():
    """_coerce_field with str type returns default when value is not a string."""
    cfg = Config.from_dict({"hotkey": 123})
    assert cfg.hotkey == "f8"


def test_coerce_field_catch_all_type():
    """_coerce_field catch-all (line 219) handles unhandled types."""
    from config_repository import _coerce_field, _FieldMeta

    meta_list = _FieldMeta(cls_type=list)
    # value matches tp -> returns value
    assert _coerce_field([1, 2], meta_list, "default") == [1, 2]
    # value doesn't match tp -> returns default
    assert _coerce_field("not_a_list", meta_list, "default") == "default"

    meta_dict = _FieldMeta(cls_type=dict)
    assert _coerce_field({"a": 1}, meta_dict, None) == {"a": 1}
    assert _coerce_field(42, meta_dict, None) is None


# ---------------------------------------------------------------------------
# Edge-case coverage: articulation migration > 1.0 (line 446)
# ---------------------------------------------------------------------------


def test_from_dict_migrates_articulation_above_one():
    """Migration copies articulation as-is when its value is > 1.0."""
    cfg = Config.from_dict({"articulation": 99.0})
    assert cfg.value_articulation == 99.0


# ---------------------------------------------------------------------------
# Edge-case coverage: PlaybackConfig.__contains__ non-string (line 568)
# ---------------------------------------------------------------------------


def test_playback_config_contains_non_string():
    """PlaybackConfig.__contains__ returns False for non-string keys."""
    pc = PlaybackConfig(tempo=120.0)
    assert (1 in pc) is False
    assert (None in pc) is False
    assert (0.5 in pc) is False



def test_runtime_playback_dict_keys_cover_pipeline_consumers():
    """All keys consumed by pipeline stages exist in PlaybackConfig."""
    cfg = Config()
    # Set non-default values to ensure keys are populated
    cfg.enable_vary_timing = True
    cfg.value_timing_variance = 0.05
    cfg.enable_vary_articulation = True
    cfg.value_articulation = 90.0
    cfg.enable_hand_drift = True
    cfg.value_hand_drift_decay = 50.0
    cfg.enable_mistakes = True
    cfg.value_mistake_chance = 3.0
    cfg.enable_tempo_sway = True
    cfg.value_tempo_sway_intensity = 0.05
    cfg.invert_tempo_sway = True
    cfg.enable_chord_roll = True

    runtime = cfg.to_runtime_playback_dict()

    humanizer_keys = {
        "vary_timing", "timing_variance", "vary_articulation", "articulation",
        "enable_drift_correction", "drift_decay_factor", "enable_chord_roll",
        "drift_shared_factor", "drift_noise_sigma", "enable_tempo_sway",
        "tempo_sway_intensity", "invert_tempo_sway",
    }
    event_compiler_keys = {
        "pedal_style", "raw_pedal_events", "enable_mistakes", "mistake_chance",
        "enable_vary_timing", "enable_vary_articulation", "enable_drift_correction",
        "enable_chord_roll", "enable_tempo_sway",
    }
    player_keys = {"countdown", "start_offset"}
    pedal_generator_keys = {"pedal_style", "raw_pedal_events"}

    union_keys = humanizer_keys | event_compiler_keys | player_keys | pedal_generator_keys

    for key in sorted(union_keys):
        if key in ("drift_shared_factor", "drift_noise_sigma"):
            assert key not in runtime, (
                f"{key} should not exist in to_runtime_playback_dict()"
            )
        else:
            assert key in runtime, (
                f"Pipeline consumer key '{key}' missing from to_runtime_playback_dict()"
            )
