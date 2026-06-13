"""MIDI file parsing: reads .mid files into MidiTrack objects with tempo/beat mapping."""

import sys
from collections import defaultdict
from typing import List, Tuple, Dict

import mido

from models import Note, MidiTrack
from .tempo_map import TempoMap, GlobalTickMap


def _strip_control_chars(text: str) -> str:
    """Strip control characters like U+0000 from text."""
    if not text:
        return text
    return "".join(ch for ch in text if (ord(ch) >= 32) or ch in ("\t", "\n", "\r"))


def _repair_utf8_mojibake(text: str) -> str:
    """Repair common UTF-8 mojibake (latin1/cp1252 decoded)."""
    if not text:
        return text

    def looks_like_cjk_or_emoji(s: str) -> bool:
        for ch in s:
            code = ord(ch)
            if (
                0x3040 <= code <= 0x30FF  # Hiragana/Katakana
                or 0x3400 <= code <= 0x4DBF  # CJK Extension A
                or 0x4E00 <= code <= 0x9FFF  # CJK Unified
                or 0xAC00 <= code <= 0xD7AF  # Hangul syllables
                or 0x0400 <= code <= 0x04FF  # Cyrillic (e.g., Russian)
                or code >= 0x1F300  # emoji and symbols
            ):
                return True
        return False

    for enc in ("latin1", "cp1252"):
        try:
            raw = text.encode(enc, errors="replace")
            fixed = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if looks_like_cjk_or_emoji(fixed):
            return fixed
    return text


def _decode_midi_text(msg) -> str:
    """Decode MIDI text meta events with encoding guesses and cleanup."""
    data = getattr(msg, "data", None)
    if not data:
        base = getattr(msg, "name", "")
        return _strip_control_chars(_repair_utf8_mojibake(base))

    try:
        data_bytes = bytes(data)
    except Exception:
        base = getattr(msg, "name", "")
        return _strip_control_chars(_repair_utf8_mojibake(base))

    if not data_bytes:
        return ""

    if all((32 <= b <= 126) or b in (9, 10, 13) for b in data_bytes):
        return data_bytes.decode("ascii")

    encodings = ["utf-8", "cp932", "shift_jis"]

    for env_enc in (sys.getfilesystemencoding(), sys.getdefaultencoding()):
        if env_enc and env_enc.lower() not in {e.lower() for e in encodings}:
            encodings.append(env_enc)

    for enc in encodings:
        try:
            decoded = data_bytes.decode(enc)
            return _strip_control_chars(_repair_utf8_mojibake(decoded))
        except UnicodeDecodeError:
            continue

    try:
        decoded = data_bytes.decode("latin1", errors="replace")
        return _strip_control_chars(_repair_utf8_mojibake(decoded))
    except Exception:
        base = getattr(msg, "name", "")
        return _strip_control_chars(_repair_utf8_mojibake(base))


class MidiParser:
    """Parse a MIDI file into :class:`MidiTrack` objects and a :class:`TempoMap`."""

    @staticmethod
    def parse_structure(
        filepath: str, tempo_scale: float = 1.0
    ) -> Tuple[List[MidiTrack], TempoMap]:
        try:
            mid = mido.MidiFile(filepath, clip=True)
        except Exception as e:
            raise IOError(f"Could not read MIDI file: {e}")

        gmap = GlobalTickMap(mid)
        tempo_map = TempoMap(
            [(entry[1], entry[2]) for entry in gmap._entries],
            gmap.time_signatures,
        )

        tracks: List[MidiTrack] = []
        note_id = 0

        for i, track in enumerate(mid.tracks):
            name = f"Track {i}"
            program = 0
            is_drum = False
            notes: List[Note] = []
            pedal_events: List[Tuple[float, int]] = []
            open_notes: Dict[int, List[Dict]] = defaultdict(list)
            abs_tick = 0

            for msg in track:
                abs_tick += msg.time
                if msg.type == "track_name":
                    name = _decode_midi_text(msg)
                if msg.type == "program_change":
                    program = msg.program
                    if msg.channel == 9:
                        is_drum = True

                if msg.type == "note_on" and msg.velocity > 0:
                    open_notes[msg.note].append({"tick": abs_tick, "vel": msg.velocity})
                elif msg.type == "note_off" or (
                    msg.type == "note_on" and msg.velocity == 0
                ):
                    if open_notes[msg.note]:
                        nd = open_notes[msg.note].pop(0)
                        s = gmap.tick_to_time(nd["tick"])
                        e = gmap.tick_to_time(abs_tick)
                        dur = e - s
                        if dur > 0.01:
                            notes.append(
                                Note(
                                    note_id,
                                    msg.note,
                                    nd["vel"],
                                    s / tempo_scale,
                                    dur / tempo_scale,
                                    "unknown",
                                    i,
                                    msg.channel,
                                )
                            )
                            note_id += 1

                if msg.type == "control_change" and msg.control == 64:
                    t = gmap.tick_to_time(abs_tick) / tempo_scale
                    pedal_events.append((t, msg.value))

            if any(n.channel == 9 for n in notes):
                is_drum = True
            if notes:
                notes.sort(key=lambda n: n.start_time)
                tracks.append(MidiTrack(i, name, program, is_drum, notes, pedal_events))

        return tracks, tempo_map
