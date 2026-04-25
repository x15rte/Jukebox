from pathlib import Path


def midi_fixture_path(name: str) -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "midi" / name
