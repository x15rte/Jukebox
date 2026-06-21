from __future__ import annotations

import os
import random
import sys
from typing import Any, cast

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _setup_pynput_stub():
    """Ensure pynput is stubbed out for all tests."""
    try:
        import pynput.keyboard  # noqa: F401
    except Exception:
        for module_name in list(sys.modules):
            if module_name == "pynput" or module_name.startswith("pynput."):
                sys.modules.pop(module_name, None)
        from tests.helpers import pynput_stub

        pynput_stub.install()


try:
    import numpy as _np
except Exception:
    _np = None


@pytest.fixture(autouse=True)
def deterministic_random_seed():
    random.seed(1337)
    if _np is not None:
        _np.random.seed(1337)


@pytest.fixture(autouse=True)
def no_real_io(monkeypatch, request):
    if request.node.get_closest_marker("rmc_low_level") is None:
        try:
            import output.RobloxMidiConnect_encoder as rmc_encoder
            monkeypatch.setattr(rmc_encoder, "_tap_key", lambda *a, **k: None)
            monkeypatch.setattr(rmc_encoder, "_send_frame_batched", lambda *a, **k: True)
            monkeypatch.setattr(rmc_encoder, "ensure_numlock_on", lambda *a, **k: None)
        except ImportError:
            pass  # Module unavailable — patches already handled by stub

@pytest.fixture
def window_factory(qtbot, monkeypatch, tmp_path):
    from config_repository import ConfigRepository
    from main_window import MainWindow

    def factory(**kwargs) -> Any:
        repo = ConfigRepository(config_dir=tmp_path)
        monkeypatch.setattr("main_window.ConfigRepository", lambda: repo)
        monkeypatch.setattr("main_window.QTimer.singleShot", lambda ms, cb=None, **_: (
            cb() if cb and ms == 0
            else (print(f"QTimer.singleShot({ms}, ...) skipped during test") if ms > 0 else None)
        ))
        window = cast(Any, MainWindow(app_version=kwargs.pop("app_version", "test"), **kwargs))
        qtbot.addWidget(window)
        return window

    return factory
