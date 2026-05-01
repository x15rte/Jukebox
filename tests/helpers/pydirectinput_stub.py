from __future__ import annotations

import builtins
import ctypes
from types import SimpleNamespace
from typing import Any


class _PDIKeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _PDIInputUnion(ctypes.Union):
    _fields_ = [("ki", _PDIKeyBdInput)]


class _PDIInput(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", _PDIInputUnion)]


class FakePydirectInput:
    def __init__(self) -> None:
        self.PAUSE = 1
        self.FAILSAFE = True
        self.KEYBOARD_MAPPING: dict[str, int] = {}
        self.Input = _PDIInput
        self.down: list[str] = []
        self.up: list[str] = []
        self.sent_batches: list[list[tuple[str, bool]]] = []
        self.send_result: int | None = None
        self.send_exception: Exception | None = None
        self.fail_down: Exception | None = None
        self.fail_up: Exception | None = None

    def keyDown(self, name: str, _pause: bool = False) -> None:  # noqa: N802
        if self.fail_down is not None:
            raise self.fail_down
        self.down.append(name)

    def keyUp(self, name: str, _pause: bool = False) -> None:  # noqa: N802
        if self.fail_up is not None:
            raise self.fail_up
        self.up.append(name)

    def SendInput(self, n: int, inputs: Any, _size: int) -> int:  # noqa: N802
        if self.send_exception is not None:
            raise self.send_exception

        reverse_mapping = {v: k for k, v in self.KEYBOARD_MAPPING.items()}
        batch: list[tuple[str, bool]] = []
        for i in range(n):
            key_input = inputs[i].ii.ki
            scan_code = int(key_input.wScan)
            is_down = not bool(int(key_input.dwFlags) & 0x0002)
            key_name = reverse_mapping.get(scan_code, f"scan:{scan_code}")
            batch.append((key_name, is_down))
            if is_down:
                self.down.append(key_name)
            else:
                self.up.append(key_name)
        self.sent_batches.append(batch)

        return self.send_result if self.send_result is not None else n


def install(monkeypatch: Any, module: FakePydirectInput | None = None) -> FakePydirectInput:
    fake = module or FakePydirectInput()
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pydirectinput":
            return fake
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(user32=SimpleNamespace(SendInput=fake.SendInput)),
        raising=False,
    )
    return fake


def block(monkeypatch: Any, exc: Exception | None = None) -> None:
    real_import = builtins.__import__
    blocked_exc = exc or ImportError("missing pydirectinput")

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pydirectinput":
            raise blocked_exc
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
