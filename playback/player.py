"""Event compilation and timed playback engine."""

import sys
import time
import copy
import heapq
import math

import random
import bisect
import threading
from typing import List, Dict, Set, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal as Signal

from models import Note, KeyEvent, MusicalSection
from core import TempoMap, KeyMapper
from analysis import Humanizer, PedalGenerator
from output import OutputBackend
from native import set_timer_resolution, restore_timer_resolution, precise_sleep
from logger_core import jukebox_logger


# ---------------------------------------------------------------------------
# Event compiler
# ---------------------------------------------------------------------------


class EventCompiler:
    """Compile a list of :class:`Note` objects into a time-sorted list of
    :class:`KeyEvent` objects ready for the playback engine.

    This is a stateless helper — call :meth:`compile` as a static method.
    """

    @staticmethod
    def compile(
        notes: List[Note], sections: List[MusicalSection], config: Dict
    ) -> List[KeyEvent]:
        work = copy.deepcopy(notes)

        # --- optional humanization (delegates to analysis.py) ---
        humanization_enabled = EventCompiler._humanization_enabled(config)
        if humanization_enabled:
            humanizer = Humanizer(config)
            left = [n for n in work if n.hand == "left"]
            right = [n for n in work if n.hand == "right"]
            resync = {round(n.start_time, 2) for n in left} & {
                round(n.start_time, 2) for n in right
            }
            humanizer.prepare_shared_offsets(work)
            humanizer.apply_to_hand(left, "left", resync)
            humanizer.apply_to_hand(right, "right", resync)
            work = sorted(left + right, key=lambda n: n.start_time)
            humanizer.apply_tempo_rubato(work, sections)

        effective_pedal_style = EventCompiler._effective_pedal_style(config)
        pedal_config = config
        if effective_pedal_style == "none":
            pedal_notes = notes
            pedal_sections = sections
        elif effective_pedal_style == "original":
            pedal_notes = notes
            pedal_sections = sections
            if humanization_enabled and config.get("raw_pedal_events"):
                pedal_config = dict(config)
                pedal_config["raw_pedal_events"] = (
                    EventCompiler._remap_raw_pedal_events(
                        config["raw_pedal_events"],
                        notes,
                        work,
                    )
                )
        else:
            pedal_notes = EventCompiler._build_pedal_notes(
                notes,
                work,
                effective_pedal_style,
            )
            pedal_sections = EventCompiler._build_pedal_sections(
                sections, pedal_notes, notes
            )

        # --- build press / release events ---
        heap: list = []
        use_mistakes = config.get("enable_mistakes", False)
        mistake_chance = config.get("mistake_chance", 0) / 100.0
        played_in_section: Set[int] = set()
        sec_idx = 0

        for note in work:
            # Advance section index monotonically; sections are time-ordered.
            while (
                sec_idx < len(sections)
                and note.start_time >= sections[sec_idx].end_time
            ):
                sec_idx += 1
                played_in_section.clear()

            pitch = note.pitch
            did_mistake = False

            if (
                use_mistakes
                and pitch not in played_in_section
                and random.random() < mistake_chance  # nosec B311: non-crypto randomness for musical mistakes only
            ):
                mp = EventCompiler._mistake_pitch(pitch)
                if mp is not None:
                    heapq.heappush(
                        heap,
                        KeyEvent(
                            note.start_time,
                            2,
                            "press",
                            "",
                            pitch=mp,
                            velocity=note.velocity,
                        ),
                    )
                    heapq.heappush(
                        heap,
                        KeyEvent(note.end_time, 4, "release", "", pitch=mp, velocity=0),
                    )
                    did_mistake = True

            if not did_mistake:
                heapq.heappush(
                    heap,
                    KeyEvent(
                        note.start_time,
                        2,
                        "press",
                        "",
                        pitch=pitch,
                        velocity=note.velocity,
                    ),
                )
                heapq.heappush(
                    heap,
                    KeyEvent(note.end_time, 4, "release", "", pitch=pitch, velocity=0),
                )

            played_in_section.add(pitch)

        # --- pedal events (from analysis.py) ---
        for pe in PedalGenerator.generate_events(
            pedal_config, pedal_notes, pedal_sections
        ):
            heapq.heappush(heap, pe)

        events: List[KeyEvent] = []
        while heap:
            events.append(heapq.heappop(heap))
        return events

    @staticmethod
    def _effective_pedal_style(config: Dict) -> Optional[str]:
        style = config.get("pedal_style")
        if style == "original" and not config.get("raw_pedal_events"):
            return "hybrid"
        return style

    @staticmethod
    def _humanization_enabled(config: Dict) -> bool:
        humanize_keys = (
            "enable_vary_timing",
            "enable_vary_articulation",
            "enable_drift_correction",
            "enable_chord_roll",
            "enable_tempo_sway",
        )
        return any(config.get(k) for k in humanize_keys)

    @staticmethod
    def _build_pedal_notes(
        original_notes: List[Note],
        humanized_notes: List[Note],
        effective_pedal_style: Optional[str],
    ) -> List[Note]:
        pedal_notes = copy.deepcopy(original_notes)
        humanized_by_id = {note.id: note for note in humanized_notes}

        for note in pedal_notes:
            humanized = humanized_by_id.get(note.id)
            if humanized is not None:
                note.start_time = humanized.start_time
                if effective_pedal_style == "rhythmic":
                    note.duration = humanized.duration

        pedal_notes.sort(key=lambda note: note.start_time)
        return pedal_notes

    @staticmethod
    def _build_pedal_sections(
        sections: List[MusicalSection],
        pedal_notes: List[Note],
        original_notes: List[Note],
    ) -> List[MusicalSection]:
        pedal_by_id = {note.id: note for note in pedal_notes}
        original_by_id = {note.id: note for note in original_notes}
        pedal_sections: List[MusicalSection] = []

        for section in sections:
            remapped_notes: List[Note] = []
            for note in section.notes:
                pedal_note = pedal_by_id.get(note.id)
                if pedal_note is not None:
                    remapped_notes.append(pedal_note)
                    continue

                remapped_notes.append(
                    copy.deepcopy(original_by_id.get(note.id, note))
                )
            remapped_notes.sort(key=lambda note: note.start_time)

            start_time = section.start_time
            end_time = section.end_time
            if remapped_notes:
                start_time = remapped_notes[0].start_time
                end_time = max(note.end_time for note in remapped_notes)

            pedal_sections.append(
                MusicalSection(
                    start_time=start_time,
                    end_time=end_time,
                    notes=remapped_notes,
                    articulation_label=section.articulation_label,
                    pace_label=section.pace_label,
                    start_beat=section.start_beat,
                    end_beat=section.end_beat,
                )
            )

        pedal_sections.sort(key=lambda section: section.start_time)
        return pedal_sections

    @staticmethod
    def _normalize_raw_pedal_transitions(
        raw_events: List[Tuple[float, int]],
    ) -> List[Tuple[float, int]]:
        transitions: List[Tuple[float, int]] = []
        pedal_down = False

        for event_time, value in raw_events:
            is_down = value >= 64
            if is_down and not pedal_down:
                transitions.append((event_time, 127))
                pedal_down = True
            elif not is_down and pedal_down:
                transitions.append((event_time, 0))
                pedal_down = False

        return transitions

    @staticmethod
    def _collapse_anchor_deltas(
        anchor_deltas: List[Tuple[float, float]],
        *,
        prefer_latest: bool,
    ) -> List[Tuple[float, float]]:
        if not anchor_deltas:
            return []

        collapsed: List[Tuple[float, float]] = []
        for original_time, delta in sorted(anchor_deltas, key=lambda item: item[0]):
            remapped_time = original_time + delta
            if collapsed and collapsed[-1][0] == original_time:
                prior_original, prior_delta = collapsed[-1]
                prior_remapped = prior_original + prior_delta
                should_replace = remapped_time > prior_remapped
                if not prefer_latest:
                    should_replace = remapped_time < prior_remapped
                if should_replace:
                    collapsed[-1] = (original_time, delta)
                continue

            collapsed.append((original_time, delta))

        return collapsed

    @staticmethod
    def _build_note_timing_deltas(
        original_notes: List[Note],
        humanized_notes: List[Note],
    ) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
        humanized_by_id = {note.id: note for note in humanized_notes}
        onset_deltas: List[Tuple[float, float]] = []
        release_deltas: List[Tuple[float, float]] = []

        for note in original_notes:
            humanized = humanized_by_id.get(note.id)
            if humanized is None:
                continue

            onset_deltas.append(
                (note.start_time, humanized.start_time - note.start_time)
            )
            release_deltas.append((note.end_time, humanized.end_time - note.end_time))

        return (
            EventCompiler._collapse_anchor_deltas(
                onset_deltas,
                prefer_latest=False,
            ),
            EventCompiler._collapse_anchor_deltas(
                release_deltas,
                prefer_latest=True,
            ),
        )

    @staticmethod
    def _find_anchor_delta(
        anchor_deltas: List[Tuple[float, float]],
        raw_time: float,
        prefer_nearest: bool = True,
    ) -> float:
        match = EventCompiler._find_anchor_match(
            anchor_deltas,
            raw_time,
            prefer_nearest,
        )
        if match is None:
            return 0.0
        return match[1]

    @staticmethod
    def _find_anchor_match(
        anchor_deltas: List[Tuple[float, float]],
        raw_time: float,
        prefer_nearest: bool = True,
    ) -> Optional[Tuple[float, float]]:
        if not anchor_deltas:
            return None

        anchor_times = [time for time, _delta in anchor_deltas]
        idx = bisect.bisect_left(anchor_times, raw_time)

        if idx <= 0:
            return anchor_deltas[0]
        if idx >= len(anchor_deltas):
            return anchor_deltas[-1]
        if not prefer_nearest:
            return anchor_deltas[idx - 1]

        prev_time, prev_delta = anchor_deltas[idx - 1]
        next_time, next_delta = anchor_deltas[idx]
        prev_distance = raw_time - prev_time
        next_distance = next_time - raw_time

        if next_distance <= prev_distance:
            return next_time, next_delta
        return prev_time, prev_delta

    @staticmethod
    def _find_raw_pedal_up_delta(
        raw_time: float,
        onset_deltas: List[Tuple[float, float]],
        release_deltas: List[Tuple[float, float]],
    ) -> float:
        release_match = EventCompiler._find_anchor_match(
            release_deltas,
            raw_time,
        )
        if release_match is None:
            return EventCompiler._find_anchor_delta(onset_deltas, raw_time)

        onset_match = EventCompiler._find_anchor_match(
            onset_deltas,
            raw_time,
        )
        if onset_match is None:
            return release_match[1]

        onset_time, onset_delta = onset_match
        release_time, release_delta = release_match
        onset_distance = onset_time - raw_time
        release_distance = abs(release_time - raw_time)

        if onset_time > raw_time and onset_distance < release_distance:
            return onset_delta
        return release_delta

    @staticmethod
    def _pair_raw_pedal_spans(
        normalized_events: List[Tuple[float, int]],
    ) -> Tuple[List[Tuple[float, float]], Optional[float]]:
        spans: List[Tuple[float, float]] = []
        trailing_down_time: Optional[float] = None
        idx = 0

        while idx < len(normalized_events):
            down_time, _value = normalized_events[idx]
            if idx + 1 >= len(normalized_events):
                trailing_down_time = down_time
                break

            up_time, _next_value = normalized_events[idx + 1]
            spans.append((down_time, up_time))
            idx += 2

        return spans, trailing_down_time

    @staticmethod
    def _normalize_remapped_pedal_spans(
        spans: List[Tuple[float, float]],
        trailing_down_time: Optional[float] = None,
    ) -> Tuple[List[Tuple[float, float]], Optional[float]]:
        normalized = [[down_time, up_time] for down_time, up_time in spans]

        for idx, current in enumerate(normalized):
            down_time, up_time = current
            if up_time <= down_time:
                up_time = math.nextafter(down_time, math.inf)
                current[1] = up_time

            if idx + 1 >= len(normalized):
                continue

            next_span = normalized[idx + 1]
            next_down = next_span[0]
            if up_time < next_down:
                continue

            earlier_up = math.nextafter(next_down, -math.inf)
            if earlier_up > down_time:
                current[1] = earlier_up
                continue

            current[1] = math.nextafter(down_time, math.inf)
            next_span[0] = math.nextafter(current[1], math.inf)

        if trailing_down_time is not None and normalized:
            last_down, last_up = normalized[-1]
            if last_up >= trailing_down_time:
                earlier_up = math.nextafter(trailing_down_time, -math.inf)
                if earlier_up > last_down:
                    normalized[-1][1] = earlier_up
                else:
                    normalized[-1][1] = math.nextafter(last_down, math.inf)
                    trailing_down_time = math.nextafter(normalized[-1][1], math.inf)

        return [(down_time, up_time) for down_time, up_time in normalized], trailing_down_time

    @staticmethod
    def _remap_raw_pedal_events(
        raw_events: List[Tuple[float, int]],
        original_notes: List[Note],
        humanized_notes: List[Note],
    ) -> List[Tuple[float, int]]:
        normalized = EventCompiler._normalize_raw_pedal_transitions(raw_events)
        if not normalized:
            return raw_events

        onset_deltas, release_deltas = EventCompiler._build_note_timing_deltas(
            original_notes,
            humanized_notes,
        )

        spans, trailing_down_time = EventCompiler._pair_raw_pedal_spans(normalized)
        remapped_spans = [
            (
                down_time
                + EventCompiler._find_anchor_delta(
                    onset_deltas,
                    down_time,
                ),
                up_time
                + EventCompiler._find_raw_pedal_up_delta(
                    up_time,
                    onset_deltas,
                    release_deltas,
                ),
            )
            for down_time, up_time in spans
        ]

        remapped_trailing_down = None
        if trailing_down_time is not None:
            remapped_trailing_down = trailing_down_time + EventCompiler._find_anchor_delta(
                onset_deltas,
                trailing_down_time,
            )

        normalized_spans, normalized_trailing_down = (
            EventCompiler._normalize_remapped_pedal_spans(
                remapped_spans,
                remapped_trailing_down,
            )
        )

        remapped: List[Tuple[float, int]] = []
        for down_time, up_time in normalized_spans:
            remapped.append((down_time, 127))
            remapped.append((up_time, 0))

        if normalized_trailing_down is not None:
            remapped.append((normalized_trailing_down, 127))

        return remapped

    @staticmethod
    def _mistake_pitch(original: int) -> Optional[int]:
        if KeyMapper.is_black_key(original):
            offsets = [-2, -1, 1, 2]
            random.shuffle(offsets)  # nosec B311: non-crypto randomness for musical mistakes only
            for offset in offsets:
                candidate = original + offset
                if 0 <= candidate <= 127:
                    return candidate
            return None
        candidates = [
            p
            for p in (original - 2, original - 1, original + 1, original + 2)
            if 0 <= p <= 127 and not KeyMapper.is_black_key(p)
        ]
        return random.choice(candidates) if candidates else None  # nosec B311: non-crypto randomness for musical mistakes only


# ---------------------------------------------------------------------------
# Playback engine
# ---------------------------------------------------------------------------


class Player(QObject):
    """Time-accurate playback engine that dispatches compiled
    :class:`KeyEvent` objects through an :class:`OutputBackend`.

    The player knows *nothing* about the concrete output method; switching
    between keyboard and numpad mode is achieved by passing a different
    backend instance.
    """

    status_updated = Signal(str)
    progress_updated = Signal(float)
    playback_finished = Signal()
    # Emits the full set of currently active MIDI pitches whenever it changes.
    visualizer_updated = Signal(list)

    def __init__(
        self,
        compiled_events: List[KeyEvent],
        backend: OutputBackend,
        config: Dict,
        total_duration: float,
    ):
        super().__init__()
        self.events = compiled_events
        self.backend = backend
        self.config = config
        self.total_duration = total_duration

        self.event_index = 0
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self._pause_lock = threading.Lock()
        self._pending_pause = False

        self.start_time = 0.0
        self.total_paused_time = 0.0
        self._pause_ts = 0.0
        self._pending_shutdown = False

        # Precompute event times for fast seeking / resume logic.
        self._event_times: List[float] = [e.time for e in self.events]

        # Track currently active MIDI pitches for the visualizer; updated in
        # batches and emitted as a list via visualizer_updated.
        self._active_pitches: Set[int] = set()

    # -- public API (called from main thread) --

    def play(self):
        """Entry point — run from a QThread."""
        try:
            if self.config.get("countdown"):
                self._countdown()
            if self.stop_event.is_set():
                return

            start_offset = self.config.get("start_offset", 0.0)
            self.status_updated.emit("Playing!")
            self.start_time = time.perf_counter() - start_offset
            self.total_paused_time = 0.0
            if start_offset > 0 and self._event_times:
                self.event_index = bisect.bisect_left(self._event_times, start_offset)
            else:
                self.event_index = 0
            self._run_loop()
        except Exception as e:
            jukebox_logger.error(f"Playback thread failed: {e}", exc_info=True)
            self.status_updated.emit(f"Error: {e}")
        finally:
            try:
                self.backend.shutdown()
            except Exception as e:
                jukebox_logger.error(
                    f"Playback output shutdown failed: {e}", exc_info=True
                )
                self.status_updated.emit(f"Error: {e}")
            finally:
                self.playback_finished.emit()

    def stop(self):
        if not self.stop_event.is_set():
            self.status_updated.emit("Stopping playback...")
            self.stop_event.set()
            self.pause_event.clear()

    def toggle_pause(self):
        if self.pause_event.is_set():
            if self.event_index >= len(self.events):
                self.seek(0.0)
            pause_dur = time.perf_counter() - self._pause_ts
            self.total_paused_time += pause_dur
            self.pause_event.clear()
            self.status_updated.emit("Resuming...")
        else:
            self._pause_ts = time.perf_counter()
            with self._pause_lock:
                self._pending_pause = True
            self.pause_event.set()
            self.status_updated.emit("Paused.")

    def seek(self, target_time: float):
        self._pending_shutdown = True
        self._active_pitches.clear()
        self.visualizer_updated.emit([])
        if self._event_times:
            self.event_index = bisect.bisect_left(self._event_times, target_time)
        else:
            self.event_index = 0
        now = time.perf_counter()
        if self.pause_event.is_set():
            self.total_paused_time = 0.0
            self.start_time = now - target_time
            self._pause_ts = now
        else:
            self.start_time = now - target_time - self.total_paused_time
        self.progress_updated.emit(target_time)

    # -- internal --

    def _countdown(self):
        self.status_updated.emit("Get ready...")
        for i in range(3, 0, -1):
            if self.stop_event.is_set():
                return
            self.status_updated.emit(f"{i}...")
            time.sleep(1)

    def _run_loop(self):
        _old_switch = sys.getswitchinterval()
        sys.setswitchinterval(0.0005)
        set_timer_resolution(1)
        try:
            self._loop_body()
        finally:
            restore_timer_resolution(1)
            sys.setswitchinterval(_old_switch)

    def _loop_body(self):
        last_progress = 0.0
        progress_iv = 1.0 / 30.0

        while not self.stop_event.is_set():
            if self._pending_shutdown:
                self._pending_shutdown = False
                self.backend.shutdown()

            if self.pause_event.is_set():
                with self._pause_lock:
                    if self._pending_pause:
                        self._pending_pause = False
                        self.backend.shutdown()
                        self._active_pitches.clear()
                        self.visualizer_updated.emit([])
                time.sleep(0.05)
                continue

            now = time.perf_counter()
            pt = (now - self.start_time) - self.total_paused_time

            if self.event_index >= len(self.events):
                if pt > self.total_duration + 0.1:
                    self.status_updated.emit("Playback finished.")
                    break
                time.sleep(0.005)
                continue

            nxt = self.events[self.event_index]
            wait = nxt.time - pt

            if wait > 0:
                precise_sleep(wait)

            batch: List[KeyEvent] = []
            batch_time = nxt.time
            while self.event_index < len(self.events):
                e = self.events[self.event_index]
                if e.time <= batch_time + 0.0005:
                    batch.append(e)
                    self.event_index += 1
                else:
                    break

            if batch:
                self._execute_batch(batch)

            now = time.perf_counter()
            pt = (now - self.start_time) - self.total_paused_time
            if now - last_progress >= progress_iv:
                self.progress_updated.emit(pt)
                last_progress = now

    def _execute_batch(self, events: List[KeyEvent]):
        """Execute a batch of events that fall within the same time-slice.

        Order within a batch: pedal → release → press.
        """
        if self.stop_event.is_set():
            return

        self.backend.execute_batch(events)

        state_changed = False

        for e in events:
            if e.action != "release":
                continue
            pitch = e.pitch
            if pitch is None:
                continue
            if pitch in self._active_pitches:
                self._active_pitches.discard(pitch)
                state_changed = True

        for e in events:
            if e.action != "press":
                continue
            pitch = e.pitch
            if pitch is None:
                continue
            if pitch not in self._active_pitches:
                self._active_pitches.add(pitch)
                state_changed = True

        if state_changed:
            self.visualizer_updated.emit(list(self._active_pitches))
