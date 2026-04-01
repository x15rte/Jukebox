"""Platform-specific utilities: Windows app user model ID, capability detection."""

from __future__ import annotations

import sys
from typing import Any, Dict

from native import has_high_res_timer


def set_app_user_model_id(app_id: str) -> None:
    """Set the application user model ID on Windows so the taskbar groups the icon correctly. No-op on other platforms."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (OSError, AttributeError, ImportError):
        pass


def get_capabilities() -> Dict[str, Any]:
    """Return a small dict of runtime capabilities (timer, pydirectinput) for logging or UI."""
    caps: Dict[str, Any] = {
        "high_res_timer": has_high_res_timer(),
        "platform": sys.platform,
    }
    if sys.platform == "win32":
        caps["pydirectinput"] = _check_pydirectinput()
    else:
        caps["pydirectinput"] = False
    return caps


def _check_pydirectinput() -> bool:
    """Check if pydirectinput is available for numpad input.

    Uses a deferred import to avoid creating a dependency cycle between
    platform_utils and the output package.
    """
    try:
        import importlib

        rmc_mod = importlib.import_module("output.RobloxMidiConnect_encoder")
        return bool(rmc_mod.is_using_pydirectinput())
    except Exception:
        return False
