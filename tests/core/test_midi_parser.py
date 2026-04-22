import mido
import pytest

from core.midi_parser import (
    MidiParser,
    _decode_midi_text,
    _repair_utf8_mojibake,
    _strip_control_chars,
)


class DummyMsg:
    def __init__(self, data=None, name=""):
        self.data = data
        self.name = name


def test_strip_control_chars_removes_nulls():
    if not (_strip_control_chars("ab\x00c\n") == "abc\n"):
        raise AssertionError("Assertion failed")


def test_repair_utf8_mojibake_keeps_normal_text():
    if not (_repair_utf8_mojibake("hello") == "hello"):
        raise AssertionError("Assertion failed")


def test_decode_midi_text_uses_name_when_data_missing():
    msg = DummyMsg(data=None, name="Track\x00Name")
    if not (_decode_midi_text(msg) == "TrackName"):
        raise AssertionError("Assertion failed")


def test_decode_midi_text_ascii_fast_path():
    msg = DummyMsg(data=b"Piano")
    if not (_decode_midi_text(msg) == "Piano"):
        raise AssertionError("Assertion failed")


def test_decode_midi_text_latin_fallback():
    msg = DummyMsg(data=bytes([0xFF, 0xFE]))
    out = _decode_midi_text(msg)
    if not (isinstance(out, str)):
        raise AssertionError("Assertion failed")
    if not (len(out) > 0):
        raise AssertionError("Assertion failed")


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

    if not (len(tracks) == 1):
        raise AssertionError("Assertion failed")
    if not (tracks[0].name == "Main"):
        raise AssertionError("Assertion failed")
    if not (len(tracks[0].notes) == 1):
        raise AssertionError("Assertion failed")
    if not (tracks[0].notes[0].pitch == 60):
        raise AssertionError("Assertion failed")
    if not (len(tracks[0].pedal_events) == 1):
        raise AssertionError("Assertion failed")
    if not (tempo_map is not None):
        raise AssertionError("Assertion failed")


def test_parse_structure_treats_note_on_zero_velocity_as_note_off(monkeypatch):
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.Message("note_on", note=60, velocity=100, channel=0, time=0))
    tr.append(mido.Message("note_on", note=60, velocity=0, channel=0, time=480))

    monkeypatch.setattr("core.midi_parser.mido.MidiFile", lambda *a, **k: mid)
    tracks, _ = MidiParser.parse_structure("ok.mid")
    if not (len(tracks[0].notes) == 1):
        raise AssertionError("Assertion failed")


def test_strip_and_repair_empty_inputs():
    if not (_strip_control_chars("") == ""):
        raise AssertionError("Assertion failed")
    if not (_repair_utf8_mojibake("") == ""):
        raise AssertionError("Assertion failed")


def test_decode_midi_text_data_object_invalid_uses_name():
    msg = type("Msg", (), {"data": object(), "name": "Name\x00X"})()
    if not (_decode_midi_text(msg) == "NameX"):
        raise AssertionError("Assertion failed")


def test_decode_midi_text_empty_bytes_uses_name_fallback():
    msg = DummyMsg(data=b"", name="ignored")
    if not (_decode_midi_text(msg) == "ignored"):
        raise AssertionError("Assertion failed")


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
    if not (out == "ABC"):
        raise AssertionError("Assertion failed")


def test_decode_midi_text_encoding_fallback_to_name_on_latin1_error():
    class BadBytes(bytes):
        def decode(self, enc, *args, **kwargs):
            raise UnicodeDecodeError(enc, b"x", 0, 1, "bad")

    class Data:
        def __bytes__(self):
            return BadBytes(b"\xff")

    out = _decode_midi_text(DummyMsg(data=Data(), name="Fallback"))
    if not (out == "Fallback"):
        raise AssertionError("Assertion failed")


def test_parse_structure_program_channel_9_marks_drum_and_scales(monkeypatch):
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.Message("program_change", program=1, channel=9, time=0))
    tr.append(mido.Message("note_on", note=60, velocity=100, channel=0, time=0))
    tr.append(mido.Message("note_off", note=60, velocity=0, channel=0, time=480))

    monkeypatch.setattr("core.midi_parser.mido.MidiFile", lambda *a, **k: mid)
    tracks, _ = MidiParser.parse_structure("ok.mid", tempo_scale=2.0)

    if not (tracks[0].is_drum is True):
        raise AssertionError("Assertion failed")
    if not (tracks[0].notes[0].duration == pytest.approx(0.25)):
        raise AssertionError("Assertion failed")


def test_parse_structure_notes_channel_9_marks_drum(monkeypatch):
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.Message("note_on", note=60, velocity=100, channel=9, time=0))
    tr.append(mido.Message("note_off", note=60, velocity=0, channel=9, time=480))

    monkeypatch.setattr("core.midi_parser.mido.MidiFile", lambda *a, **k: mid)
    tracks, _ = MidiParser.parse_structure("ok.mid")

    if not (tracks[0].is_drum is True):
        raise AssertionError("Assertion failed")


def test_parse_structure_skips_too_short_notes(monkeypatch):
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.Message("note_on", note=60, velocity=100, channel=0, time=0))
    tr.append(mido.Message("note_off", note=60, velocity=0, channel=0, time=1))

    monkeypatch.setattr("core.midi_parser.mido.MidiFile", lambda *a, **k: mid)
    tracks, _ = MidiParser.parse_structure("ok.mid")

    if not (tracks == []):
        raise AssertionError("Assertion failed")


def test_parse_structure_ignores_note_off_without_open_note(monkeypatch):
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.Message("note_off", note=60, velocity=0, channel=0, time=100))

    monkeypatch.setattr("core.midi_parser.mido.MidiFile", lambda *a, **k: mid)
    tracks, _ = MidiParser.parse_structure("ok.mid")
    if not (tracks == []):
        raise AssertionError("Assertion failed")


def test_repair_utf8_mojibake_repairs_japanese_text():
    if not (_repair_utf8_mojibake("ã\x81\x82") == "あ"):
        raise AssertionError("Assertion failed")

def test_repair_utf8_mojibake_decode_errors_return_original_text():
    if not (_repair_utf8_mojibake("ÿ") == "ÿ"):
        raise AssertionError("Assertion failed")
def test_decode_midi_text_true_but_empty_bytes_returns_empty_string():
    class EmptyBytes:
        def __bool__(self):
            return True

        def __bytes__(self):
            return b""

    msg = DummyMsg(data=EmptyBytes(), name="fallback")
    if not (_decode_midi_text(msg) == ""):
        raise AssertionError("Assertion failed")


def test_decode_midi_text_appends_environment_encodings(monkeypatch):
    monkeypatch.setattr("core.midi_parser.sys.getfilesystemencoding", lambda: "utf-16")
    monkeypatch.setattr("core.midi_parser.sys.getdefaultencoding", lambda: "koi8-r")

    msg = DummyMsg(data=b"\xff\xfeA\x00", name="n")
    out = _decode_midi_text(msg)
    if not (isinstance(out, str)):
        raise AssertionError("Assertion failed")


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
    if not (out == "latin-fallback"):
        raise AssertionError("Assertion failed")
