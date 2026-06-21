"""MIDI file parsing: reads .mid files into MidiTrack objects with tempo/beat mapping."""

import sys
import math
from collections import defaultdict, deque
from typing import List, Tuple, Dict, Deque

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
    # If any char is > U+00FF, the text is already proper Unicode
    # and was never latin1-misdecoded — return as-is.
    if any(ord(c) > 0x00FF for c in text):
        return text
    for enc in ("latin1", "cp1252"):
        try:
            raw = text.encode(enc, errors="strict")
            fixed = raw.decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        # Only skip when the ENTIRE text was consumed as a single latin1 character.
        # This catches the exact false positive (e.g., "Ã¿" → "ÿ") without blocking
        # partial repairs (e.g., "cafÃ©" → "café") or non-latin1 results (e.g., Japanese).
        if fixed == text:
            continue
        return fixed
    return text


def _decode_midi_text(msg) -> str:
    """Decode MIDI text meta events with encoding guesses and cleanup."""
    data = getattr(msg, "data", None)
    if not data:
        base = getattr(msg, "name", "")
        return _strip_control_chars(_repair_utf8_mojibake(base))

    try:
        data_bytes = data if isinstance(data, bytes) else bytes(data)
    except Exception:
        base = getattr(msg, "name", "")
        return _strip_control_chars(_repair_utf8_mojibake(base))

    if not data_bytes:
        return _strip_control_chars(getattr(msg, "name", ""))

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

        if tempo_scale <= 0 or math.isnan(tempo_scale) or math.isinf(tempo_scale):
            raise ValueError(f"tempo_scale must be positive and finite, got {tempo_scale}")
        gmap = GlobalTickMap(mid)
        tempo_map = TempoMap(
            [(entry[1], entry[2]) for entry in gmap.get_entries()],
            gmap.time_signatures,
            tempo_scale,
        )

        tracks: List[MidiTrack] = []

        note_id = 0

        for i, track in enumerate(mid.tracks):
            name = f"Track {i}"
            program = 0
            is_drum = False
            notes: List[Note] = []
            pedal_events: List[Tuple[float, int]] = []
            open_notes: Dict[Tuple[int, int], Deque[Dict]] = defaultdict(deque)
            abs_tick = 0

            for msg in track:
                abs_tick += msg.time
                if msg.type == "track_name":
                    name = _decode_midi_text(msg)
                if msg.type == "program_change":
                    if msg.channel == 9:
                        is_drum = True
                    program = msg.program

                if msg.type == "note_on" and msg.velocity > 0:
                    key = (msg.note, msg.channel)
                    if open_notes.get(key):
                        # Legato re-strike: close the prior note at this tick first
                        prior = open_notes[key].popleft()
                        prior_s = gmap.tick_to_time(prior["tick"])
                        prior_e = gmap.tick_to_time(abs_tick)
                        prior_dur = prior_e - prior_s
                        if prior_dur > 0.01 * tempo_scale:
                            notes.append(
                                Note(note_id, msg.note, prior["vel"],
                                     prior_s / tempo_scale, prior_dur / tempo_scale,
                                     "unknown", i, msg.channel)
                            )
                            note_id += 1
                    open_notes[key].append({"tick": abs_tick, "vel": msg.velocity})
                elif msg.type == "note_off" or (
                    msg.type == "note_on" and msg.velocity == 0
                ):
                    key = (msg.note, msg.channel)
                    if not open_notes.get(key):
                        continue
                    s = gmap.tick_to_time(open_notes[key][0]["tick"])
                    e = gmap.tick_to_time(abs_tick)
                    dur = e - s
                    if dur > 0.01 * tempo_scale:
                        nd = open_notes[key].popleft()
                        notes.append(
                            Note(note_id, msg.note, nd["vel"],
                                 s / tempo_scale, dur / tempo_scale,
                                 "unknown", i, msg.channel)
                        )
                        note_id += 1
                    elif dur > 0:
                        # Short note (trill/staccato < threshold) — still pop the entry
                        open_notes[key].popleft()
                    else:  # dur == 0: same tick note_off — pop the entry with no note emitted
                        open_notes[key].popleft()

                if msg.type == "control_change" and msg.control == 64:
                    t = gmap.tick_to_time(abs_tick) / tempo_scale
                    pedal_events.append((t, msg.value))
            # Flush any unclosed notes (note_on without matching note_off)
            for key, note_deque in list(open_notes.items()):
                while note_deque:
                    nd = note_deque.popleft()
                    nd_tick = nd["tick"]
                    nd_abs_tick = max(nd_tick, abs_tick)
                    nd_s = gmap.tick_to_time(nd_tick)
                    nd_e = gmap.tick_to_time(nd_abs_tick)
                    nd_dur = nd_e - nd_s
                    if nd_dur > 0.01 * tempo_scale:
                        notes.append(
                            Note(note_id, key[0], nd["vel"],
                                 nd_s / tempo_scale, nd_dur / tempo_scale,
                                 "unknown", i, key[1])
                        )
                        note_id += 1

            if any(n.channel == 9 for n in notes):
                is_drum = True
            if notes or pedal_events:
                if notes:
                    notes.sort(key=lambda n: n.start_time)
                tracks.append(MidiTrack(i, name, program, is_drum, notes, pedal_events))

        return tracks, tempo_map
