from __future__ import annotations

import os
import random

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
    from tests.helpers.fakes import FakeListener

    if request.node.get_closest_marker("rmc_low_level") is None:
        monkeypatch.setattr("output.RobloxMidiConnect_encoder._tap_key", lambda *a, **k: None)
        monkeypatch.setattr(
            "output.RobloxMidiConnect_encoder._send_frame_batched",
            lambda *a, **k: True,
        )
        monkeypatch.setattr(
            "output.RobloxMidiConnect_encoder.ensure_numlock_on",
            lambda *a, **k: None,
        )

    monkeypatch.setattr("mido.open_input", lambda *a, **k: None)
    monkeypatch.setattr("mido.get_input_names", lambda: [])
    monkeypatch.setattr("ui.hotkey_manager.keyboard.Listener", FakeListener)
