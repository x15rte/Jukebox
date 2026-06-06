import mido
import pytest

from core.midi_parser import (
    MidiParser,
    _decode_midi_text,
    _repair_utf8_mojibake,
    _strip_control_chars,
)
from tests.helpers.midi_fixtures import midi_fixture_path


class DummyMsg:
    def __init__(self, data=None, name=""):
        self.data = data
        self.name = name


@pytest.mark.parametrize(
    ("input_text", "expected"),
    [
        pytest.param("ab\x00c\n", "abc\n", id="removes_nulls"),
        pytest.param("", "", id="empty_input"),
    ],
)
def test_strip_control_chars(input_text, expected):
    assert _strip_control_chars(input_text) == expected


@pytest.mark.parametrize(
    ("input_text", "expected"),
    [
        pytest.param("hello", "hello", id="normal_text"),
        pytest.param("", "", id="empty_input"),
        pytest.param("ã\x81\x82", "あ", id="japanese_mojibake"),
        pytest.param("ÿ", "ÿ", id="decode_error_returns_original"),
    ],
)
def test_repair_utf8_mojibake(input_text, expected):
    assert _repair_utf8_mojibake(input_text) == expected


@pytest.mark.parametrize(
    ("msg", "expected"),
    [
        pytest.param(DummyMsg(data=None, name="Track\x00Name"), "TrackName", id="no_data_uses_name"),
        pytest.param(DummyMsg(data=b"Piano"), "Piano", id="ascii_fast_path"),
        pytest.param(DummyMsg(data=b"", name="ignored"), "ignored", id="empty_bytes_uses_name"),
        pytest.param(
            type("Msg", (), {"data": object(), "name": "Name\x00X"})(),
            "NameX",
            id="invalid_data_object_uses_name",
        ),
    ],
)
def test_decode_midi_text_simple_cases(msg, expected):
    assert _decode_midi_text(msg) == expected


def test_decode_midi_text_latin_fallback():
    msg = DummyMsg(data=bytes([0xFF, 0xFE]))
    out = _decode_midi_text(msg)
    assert isinstance(out, str)
    assert len(out) > 0


def test_parse_structure_raises_ioerror_on_bad_file(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("bad")

    monkeypatch.setattr("core.midi_parser.mido.MidiFile", boom)
    with pytest.raises(IOError):
        MidiParser.parse_structure("x.mid")


def test_parse_structure_builds_notes_and_pedal(monkeypatch):
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("track_name", name="Main", time=0))
    tr.append(mido.Message("program_change", program=1, channel=0, time=0))
    tr.append(mido.Message("note_on", note=60, velocity=100, channel=0, time=0))
    tr.append(mido.Message("control_change", control=64, value=127, channel=0, time=120))
    tr.append(mido.Message("note_off", note=60, velocity=0, channel=0, time=360))

    monkeypatch.setattr("core.midi_parser.mido.MidiFile", lambda *a, **k: mid)

    tracks, tempo_map = MidiParser.parse_structure("ok.mid", tempo_scale=1.0)

    assert len(tracks) == 1
    assert tracks[0].name == "Main"
    assert len(tracks[0].notes) == 1
    assert tracks[0].notes[0].pitch == 60
    assert len(tracks[0].pedal_events) == 1
    assert tempo_map is not None


def test_parse_structure_treats_note_on_zero_velocity_as_note_off(monkeypatch):
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.Message("note_on", note=60, velocity=100, channel=0, time=0))
    tr.append(mido.Message("note_on", note=60, velocity=0, channel=0, time=480))

    monkeypatch.setattr("core.midi_parser.mido.MidiFile", lambda *a, **k: mid)
    tracks, _ = MidiParser.parse_structure("ok.mid")
    assert len(tracks[0].notes) == 1


def test_decode_midi_text_data_object_invalid_uses_name():
    msg = type("Msg", (), {"data": object(), "name": "Name\x00X"})()
    assert _decode_midi_text(msg) == "NameX"


def test_decode_midi_text_empty_bytes_uses_name_fallback():
    msg = DummyMsg(data=b"", name="ignored")
    assert _decode_midi_text(msg) == "ignored"


def test_decode_midi_text_ascii_decode_error_falls_through():
    class BadBytes(bytes):
        def decode(self, enc, *args, **kwargs):
            if enc == "ascii":
                raise UnicodeDecodeError("ascii", b"x", 0, 1, "bad")
            return super().decode(enc, *args, **kwargs)

    class Data:
        def __bytes__(self):
            return BadBytes(b"ABC")

    out = _decode_midi_text(DummyMsg(data=Data(), name="n"))
    assert out == "ABC"


def test_decode_midi_text_encoding_fallback_to_name_on_latin1_error():
    class BadBytes(bytes):
        def decode(self, enc, *args, **kwargs):
            raise UnicodeDecodeError(enc, b"x", 0, 1, "bad")

    class Data:
        def __bytes__(self):
            return BadBytes(b"\xff")

    out = _decode_midi_text(DummyMsg(data=Data(), name="Fallback"))
    assert out == "Fallback"


def test_parse_structure_program_channel_9_marks_drum_and_scales(monkeypatch):
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.Message("program_change", program=1, channel=9, time=0))
    tr.append(mido.Message("note_on", note=60, velocity=100, channel=0, time=0))
    tr.append(mido.Message("note_off", note=60, velocity=0, channel=0, time=480))

    monkeypatch.setattr("core.midi_parser.mido.MidiFile", lambda *a, **k: mid)
    tracks, _ = MidiParser.parse_structure("ok.mid", tempo_scale=2.0)

    assert tracks[0].is_drum is True
    assert tracks[0].notes[0].duration == pytest.approx(0.25)


def test_parse_structure_notes_channel_9_marks_drum(monkeypatch):
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.Message("note_on", note=60, velocity=100, channel=9, time=0))
    tr.append(mido.Message("note_off", note=60, velocity=0, channel=9, time=480))

    monkeypatch.setattr("core.midi_parser.mido.MidiFile", lambda *a, **k: mid)
    tracks, _ = MidiParser.parse_structure("ok.mid")

    assert tracks[0].is_drum is True


def test_parse_structure_skips_too_short_notes(monkeypatch):
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.Message("note_on", note=60, velocity=100, channel=0, time=0))
    tr.append(mido.Message("note_off", note=60, velocity=0, channel=0, time=1))

    monkeypatch.setattr("core.midi_parser.mido.MidiFile", lambda *a, **k: mid)
    tracks, _ = MidiParser.parse_structure("ok.mid")

    assert tracks == []


def test_parse_structure_ignores_note_off_without_open_note(monkeypatch):
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.Message("note_off", note=60, velocity=0, channel=0, time=100))

    monkeypatch.setattr("core.midi_parser.mido.MidiFile", lambda *a, **k: mid)
    tracks, _ = MidiParser.parse_structure("ok.mid")
    assert tracks == []


def test_repair_utf8_mojibake_repairs_japanese_text():
    assert _repair_utf8_mojibake("ã\x81\x82") == "あ"


def test_repair_utf8_mojibake_decode_errors_return_original_text():
    assert _repair_utf8_mojibake("ÿ") == "ÿ"


def test_decode_midi_text_true_but_empty_bytes_returns_empty_string():
    class EmptyBytes:
        def __bool__(self):
            return True

        def __bytes__(self):
            return b""

    msg = DummyMsg(data=EmptyBytes(), name="fallback")
    assert _decode_midi_text(msg) == ""


def test_decode_midi_text_appends_environment_encodings(monkeypatch):
    monkeypatch.setattr("core.midi_parser.sys.getfilesystemencoding", lambda: "utf-16")
    monkeypatch.setattr("core.midi_parser.sys.getdefaultencoding", lambda: "koi8-r")

    msg = DummyMsg(data=b"\xff\xfeA\x00", name="n")
    out = _decode_midi_text(msg)
    assert isinstance(out, str)


def test_decode_midi_text_latin1_fallback_deterministic():
    class BadBytes(bytes):
        def decode(self, enc, *args, **kwargs):
            if enc == "latin1":
                return "latin-fallback"
            raise UnicodeDecodeError(enc, b"x", 0, 1, "bad")

    class Data:
        def __bytes__(self):
            return BadBytes(b"\xff")

    out = _decode_midi_text(DummyMsg(data=Data(), name="n"))
    assert out == "latin-fallback"


def test_parse_structure_real_fixture_extracts_track_name_notes_and_pedal():
    tracks, tempo_map = MidiParser.parse_structure(
        str(midi_fixture_path("basic_pedal.mid"))
    )

    assert tempo_map is not None
    assert len(tracks) == 1

    track = tracks[0]
    note = track.notes[0]

    assert track.name == "Main"
    assert track.program_change == 0
    assert track.is_drum is False
    assert len(track.notes) == 1
    assert note.pitch == 60
    assert note.velocity == 90
    assert note.channel == 0
    assert note.start_time == pytest.approx(0.0)
    assert note.duration == pytest.approx(0.5)
    assert track.pedal_events == [(0.0, 127), (0.5, 0)]


def test_parse_structure_real_fixture_applies_tempo_changes():
    tracks, tempo_map = MidiParser.parse_structure(
        str(midi_fixture_path("tempo_changes.mid"))
    )

    assert len(tracks) == 1
    assert tempo_map.has_explicit_time_signatures is True
    assert tempo_map.get_tempo_at(0.0) == 500_000
    assert tempo_map.get_tempo_at(0.5) == 250_000
    assert tempo_map.time_to_beat(0.75) == pytest.approx(2.0)
    assert tempo_map.beat_to_time(2.0) == pytest.approx(0.75)

    track = tracks[0]
    assert track.name == "Tempo Lead"
    assert [note.pitch for note in track.notes] == [60, 62]
    assert [note.start_time for note in track.notes] == pytest.approx([0.0, 0.5])
    assert [note.duration for note in track.notes] == pytest.approx([0.5, 0.25])


def test_parse_structure_real_fixture_detects_drum_channel():
    tracks, _ = MidiParser.parse_structure(str(midi_fixture_path("drum_channel_10.mid")))

    assert len(tracks) == 1

    track = tracks[0]
    assert track.name == "Drums"
    assert track.is_drum is True
    assert track.instrument_name == "Drums/Percussion"
    assert len(track.notes) == 1
    assert track.notes[0].channel == 9


def test_parse_structure_real_fixture_treats_zero_velocity_note_on_as_release():
    tracks, _ = MidiParser.parse_structure(
        str(midi_fixture_path("zero_velocity_release.mid"))
    )

    assert len(tracks) == 1

    track = tracks[0]
    assert track.name == "Zero Velocity Release"
    assert len(track.notes) == 1
    assert track.notes[0].pitch == 67
    assert track.notes[0].start_time == pytest.approx(0.0)
    assert track.notes[0].duration == pytest.approx(0.25)
