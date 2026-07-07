"""Native platform utilities: Windows timer, macOS CGEvent.

Submodules:
- timer_utils: set_timer_resolution, restore_timer_resolution, precise_sleep, has_high_res_timer
- macos_cgevent: macOS CGEvent key injection and Accessibility helpers
"""

from .timer_utils import (
    set_timer_resolution,
    restore_timer_resolution,
    precise_sleep,
    has_high_res_timer,
)
from .macos_cgevent import (
    is_macos_accessibility_trusted,
    open_macos_accessibility_preferences,
    get_macos_vk_for_key,
    get_macos_vk_for_modifier,
    post_macos_key_event,
    MACOS_CGFLAG_SHIFT,
    MACOS_CGFLAG_CONTROL,
    MACOS_CGFLAG_ALT,
)

__all__ = [
    "set_timer_resolution",
    "restore_timer_resolution",
    "precise_sleep",
    "has_high_res_timer",
    "is_macos_accessibility_trusted",
    "open_macos_accessibility_preferences",
    "get_macos_vk_for_key",
    "get_macos_vk_for_modifier",
    "post_macos_key_event",
    "MACOS_CGFLAG_SHIFT",
    "MACOS_CGFLAG_CONTROL",
    "MACOS_CGFLAG_ALT",
]
