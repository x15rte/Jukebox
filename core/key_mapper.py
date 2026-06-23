"""Pitch-to-key mapping for the Roblox piano game."""

from typing import Dict, Optional

from pynput.keyboard import Key


class KeyMapper:
    """Map a MIDI pitch to the Roblox piano keyboard key + modifier combination.

    The mapping tables below are defined by the game client and **must not** be
    altered; doing so will cause the game to misinterpret input.
    """


    # --- game-defined key tables ---
    LEFT_CTRL_KEYS = "1234567890qwert"
    MIDDLE_WHITE_KEYS = "1234567890qwertyuiopasdfghjklzxcvbnm"
    RIGHT_CTRL_KEYS = "yuiopasdfghj"

    PITCH_START_LEFT = 21  # A0
    PITCH_START_MIDDLE = 36  # C2
    PITCH_START_RIGHT = 97  # high range (88-key)

    def __init__(self, use_88_key_layout: bool = False):
        self.use_88_key_layout = use_88_key_layout
        self.min_pitch = 21 if use_88_key_layout else 36
        self.max_pitch = 108 if use_88_key_layout else 96
        self.key_map: Dict[int, Dict] = {}
        self._build()

    def _build(self):
        if self.use_88_key_layout:
            p = self.PITCH_START_LEFT
            for ch in self.LEFT_CTRL_KEYS:
                mods = [Key.ctrl]
                if self.is_black_key(p):
                    mods.append(Key.shift)
                self.key_map[p] = {"key": ch, "modifiers": mods}
                p += 1
            p = self.PITCH_START_RIGHT
            for ch in self.RIGHT_CTRL_KEYS:
                mods = [Key.ctrl]
                if self.is_black_key(p):
                    mods.append(Key.shift)
                self.key_map[p] = {"key": ch, "modifiers": mods}
                p += 1

        wi = 0
        p = self.PITCH_START_MIDDLE
        while p <= 108 and wi < len(self.MIDDLE_WHITE_KEYS):
            ch = self.MIDDLE_WHITE_KEYS[wi]
            if p not in self.key_map:
                self.key_map[p] = {"key": ch, "modifiers": []}
            nxt = p + 1
            if self.is_black_key(nxt):
                if nxt not in self.key_map:
                    self.key_map[nxt] = {"key": ch, "modifiers": [Key.shift]}
                p += 2
            else:
                p += 1
            wi += 1

    def get_key_data(self, pitch: int) -> Optional[Dict]:
        if pitch < self.min_pitch:
            pitch = self.min_pitch
        elif pitch > self.max_pitch:
            pitch = self.max_pitch
        return self.key_map.get(pitch)


    @staticmethod
    def is_black_key(pitch: int) -> bool:
        return (pitch % 12) in {1, 3, 6, 8, 10}
