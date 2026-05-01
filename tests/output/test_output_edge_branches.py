from typing import Any, cast

import pytest
from pynput.keyboard import Key

import output.output as out
from output.output import OutputBackend
from tests.helpers import pydirectinput_stub
from tests.helpers.fakes import FakeController, FakeEvent

out = cast(Any, out)


class _PDITypeFallback:
    def __init__(self):
        self.down = []
        self.up = []

    def keyDown(self, name, _pause=None):
        if _pause is False:
            raise TypeError("no _pause")
        self.down.append(name)

    def keyUp(self, name, _pause=None):
        if _pause is False:
            raise TypeError("no _pause")
        self.up.append(name)


class _PDITypeFallbackFailure:
    def keyDown(self, _name, _pause=None):
        if _pause is False:
            raise TypeError("no _pause")
        raise RuntimeError("fallback down failed")

    def keyUp(self, _name, _pause=None):
        if _pause is False:
            raise TypeError("no _pause")
        raise RuntimeError("fallback up failed")


class _PDINormal:
    def __init__(self):
        self.down = []
        self.up = []

    def keyDown(self, name, _pause=False):
        self.down.append(name)

    def keyUp(self, name, _pause=False):
        self.up.append(name)



def test_pdi_key_down_up_typeerror_fallback(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._pdi = cast(Any, _PDITypeFallback())

    kb._pdi_key_down("x")
    kb._pdi_key_up("x")

    assert kb._pdi.down == ["x"]
    assert kb._pdi.up == ["x"]


def test_pdi_key_down_up_typeerror_fallback_errors_raise(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._pdi = cast(Any, _PDITypeFallbackFailure())

    with pytest.raises(out.OutputBackendSendError, match="fallback down failed"):
        kb._pdi_key_down("x")
    with pytest.raises(out.OutputBackendSendError, match="fallback up failed"):
        kb._pdi_key_up("x")


def test_release_key_if_unused_handles_backend_exception(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    logs = []
    kb = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)

    key_data = kb._mapper.get_key_data(60)
    assert key_data is not None
    base = key_data["key"]
    kb._active_pitches[base] = set()
    kb._state_for(base)

    class BadKB:
        def release(self, _k):
            raise RuntimeError("release failed")

    kb._kb = cast(Any, BadKB())
    kb._release_key_if_unused(base)

    assert base not in kb._active_pitches
    assert any("release_key_if_unused" in msg for msg in logs)


def test_note_on_with_unknown_pitch_noop(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb.note_on(-999, 100)
    kb.note_off(-999)


def test_note_on_pydirectinput_modifier_none_branch(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._pdi = cast(Any, _PDINormal())
    kb._use_pydirectinput = True
    kb._kb = None

    monkeypatch.setattr(kb, "_modifier_name", lambda mod: None)
    kb.note_on(61, 100)

    key_data = kb._mapper.get_key_data(61)
    assert key_data is not None
    base = key_data["key"]
    assert base in kb._pdi.down


def test_note_on_pydirectinput_modifier_branch_releases_modifier(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._pdi = cast(Any, _PDINormal())
    kb._use_pydirectinput = True
    kb._kb = None

    kb.note_on(61, 100)

    key_data = kb._mapper.get_key_data(61)
    assert key_data is not None
    base = key_data["key"]
    assert kb._pdi.down == ["shiftleft", base]
    assert kb._pdi.up == ["shiftleft"]


def test_note_off_macos_releases_only_when_no_active_pitches(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "darwin")

    vk_by_key = {}

    def _vk_for_key(k):
        name = getattr(k, "char", None)
        if name is None:
            name = str(k)
        if name not in vk_by_key:
            vk_by_key[name] = len(vk_by_key) + 100
        return vk_by_key[name]

    monkeypatch.setattr(out, "get_macos_vk_for_key", _vk_for_key)
    monkeypatch.setattr(out, "get_macos_vk_for_modifier", lambda _m: 50)
    events = []
    monkeypatch.setattr(out, "post_macos_key_event", lambda vk, down, flags: events.append((vk, down, flags)) or True)

    kb = out.KeyboardBackend(use_88_key_layout=False)

    p1 = 37
    p2 = 36
    key_data_1 = kb._mapper.get_key_data(p1)
    key_data_2 = kb._mapper.get_key_data(p2)
    assert key_data_1 is not None
    assert key_data_2 is not None
    assert key_data_1["key"] == key_data_2["key"]

    base_key = key_data_1["key"]
    base_vk = _vk_for_key(base_key)

    kb.note_on(p1, 100)
    kb.note_on(p2, 100)
    kb.note_off(p1)

    release_calls_after_first = [e for e in events if e[0] == base_vk and e[1] is False]
    assert not release_calls_after_first

    kb.note_off(p2)
    release_calls_after_second = [e for e in events if e[0] == base_vk and e[1] is False]
    assert release_calls_after_second


def test_numpad_backend_logs_note_and_pedal_exceptions(monkeypatch):
    logs = []

    def bad_note(*_a, **_k):
        raise RuntimeError("note error")

    def bad_pedal(*_a, **_k):
        raise RuntimeError("pedal error")

    monkeypatch.setattr(out.rmc, "send_note_message", bad_note)
    monkeypatch.setattr(out.rmc, "send_pedal", bad_pedal)
    monkeypatch.setattr(out.rmc, "reset_batched_sendinput", lambda: None)

    nb = out.NumpadBackend(inter_message_delay=0.0, log_message=logs.append)
    nb.note_on(60, 100)
    nb.note_off(60)
    nb.pedal_on()
    nb.pedal_off()

    assert any("note_on error" in m for m in logs)
    assert any("note_off error" in m for m in logs)
    assert any("pedal_on error" in m for m in logs)


def test_numpad_backend_shutdown_logs_errors(monkeypatch):
    logs = []

    def bad_note(*_a, **_k):
        raise RuntimeError("note shutdown error")

    def bad_pedal(*_a, **_k):
        raise RuntimeError("pedal shutdown error")

    monkeypatch.setattr(out.rmc, "send_note_message", bad_note)
    monkeypatch.setattr(out.rmc, "send_pedal", bad_pedal)
    monkeypatch.setattr(out.rmc, "reset_batched_sendinput", lambda: None)

    nb = out.NumpadBackend(inter_message_delay=0.0, log_message=logs.append)
    nb._active_notes = {60}
    nb._pedal_down = True
    nb.shutdown()

    assert any("shutdown note release error" in m for m in logs)
    assert any("shutdown pedal release error" in m for m in logs)


def test_keyboard_backend_windows_missing_pydirectinput_raises(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    pydirectinput_stub.block(monkeypatch, ImportError("missing"))

    with pytest.raises(out.OutputBackendUnavailableError):
        out.KeyboardBackend(use_88_key_layout=False)


def test_keyboard_backend_windows_import_uses_pydirectinput(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)
    logs = []

    kb = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)

    assert kb._pdi is fake_pdi
    assert kb._use_pydirectinput is True
    assert kb._kb is None
    assert fake_pdi.PAUSE == 0
    assert fake_pdi.FAILSAFE is False
    assert any("scan-code transport" in m.lower() for m in logs)


def test_keyboard_backend_windows_mapping_failure_is_unavailable(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)
    fake_pdi.KEYBOARD_MAPPING = cast(Any, None)

    with pytest.raises(out.OutputBackendUnavailableError, match="configure"):
        out.KeyboardBackend(use_88_key_layout=False)


def test_keyboard_backend_windows_missing_sendinput_is_unavailable(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    pydirectinput_stub.install(monkeypatch)
    monkeypatch.setattr(out.ctypes, "windll", None, raising=False)

    with pytest.raises(out.OutputBackendUnavailableError, match="SendInput"):
        out.KeyboardBackend(use_88_key_layout=False)


def test_windows_transport_unknown_scan_code_raises(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    pydirectinput_stub.install(monkeypatch)

    kb = out.KeyboardBackend(use_88_key_layout=False)

    assert kb._windows_transport is not None
    with pytest.raises(out.OutputBackendSendError, match="no scan code"):
        kb._windows_transport.send_batch([("unknown", True)])


@pytest.mark.parametrize(
    ("modifier", "expected"),
    [(Key.ctrl, "ctrlleft"), (Key.alt, "altleft"), (object(), None)],
)
def test_modifier_name_branches(monkeypatch, modifier, expected):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    assert kb._modifier_name(modifier) == expected


def test_pdi_key_down_up_noop_when_missing(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._pdi = None
    kb._pdi_key_down("x")
    kb._pdi_key_up("x")


def test_note_on_macos_returns_when_vk_missing(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "darwin")
    monkeypatch.setattr(out, "get_macos_vk_for_key", lambda _k: None)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb.note_on(60, 100)


def test_note_on_off_macos_ctrl_alt_and_none_modifier(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "darwin")
    monkeypatch.setattr(out, "get_macos_vk_for_key", lambda _k: 42)

    def _mod_vk(mod):
        if getattr(mod, "name", None) == "skip":
            return None
        return 50

    monkeypatch.setattr(out, "get_macos_vk_for_modifier", _mod_vk)
    events = []
    monkeypatch.setattr(
        out,
        "post_macos_key_event",
        lambda vk, down, flags: events.append((vk, down, flags)) or True,
    )

    kb = out.KeyboardBackend(use_88_key_layout=False)

    class Skip:
        name = "skip"

    kb._mapper.get_key_data = lambda pitch: {
        "key": "x",
        "modifiers": [Key.ctrl, Key.alt, Skip()],
    }

    kb.note_on(60, 100)
    kb.note_off(60)

    assert kb._macos_modifier_refcount == (0, 0, 0)
    assert events


def test_note_on_logs_exception_when_backend_press_fails(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")

    class BadController(FakeController):
        def press(self, key):
            raise RuntimeError("press boom")

    monkeypatch.setattr(out, "Controller", BadController)
    logs = []

    kb = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)
    kb.note_on(60, 100)

    assert any("note_on error" in m for m in logs)


def test_note_off_returns_when_no_mapping(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._mapper.get_key_data = lambda pitch: None
    kb.note_off(60)


def test_pedal_on_off_extra_branches(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    logs = []
    kb = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)

    class BadKB:
        def press(self, _k):
            raise RuntimeError("pedal press boom")

        def release(self, _k):
            raise RuntimeError("pedal release boom")

    kb._kb = cast(Any, BadKB())
    kb.pedal_on()
    kb.pedal_on()
    kb.pedal_off()
    kb.pedal_off()

    assert any("pedal_on error" in m for m in logs)
    assert any("pedal_off error" in m for m in logs)


def test_pedal_on_off_pydirectinput_errors_raise(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    class BadPDI:
        def keyDown(self, *_a, **_k):
            raise RuntimeError("down boom")

        def keyUp(self, *_a, **_k):
            raise RuntimeError("up boom")

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._use_pydirectinput = True
    kb._pdi = cast(Any, BadPDI())
    kb._kb = None

    with pytest.raises(out.OutputBackendSendError, match="down boom"):
        kb.pedal_on()

    kb._pedal_down = True
    with pytest.raises(out.OutputBackendSendError, match="up boom"):
        kb.pedal_off()


def test_pedal_off_releases_empty_active_keys(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._pedal_down = True
    key_data = kb._mapper.get_key_data(60)
    assert key_data is not None
    base = key_data["key"]
    kb._active_pitches[base] = set()
    kb._state_for(base)

    calls = []
    monkeypatch.setattr(kb, "_release_key_if_unused", lambda k: calls.append(k))
    kb.pedal_off()

    assert calls == [base]


def test_keyboard_shutdown_macos_releases_keys_pedal_and_modifiers(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "darwin")
    monkeypatch.setattr(out, "get_macos_vk_for_key", lambda _k: 40)
    monkeypatch.setattr(out, "get_macos_vk_for_modifier", lambda _k: 50)
    events = []
    monkeypatch.setattr(
        out,
        "post_macos_key_event",
        lambda vk, down, flags: events.append((vk, down, flags)) or True,
    )

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._active_pitches = {"x": {60}}
    kb._state_for("x").press()
    kb._pedal_down = True
    kb._macos_modifiers = (True, True, True)

    kb.shutdown()

    assert kb._macos_modifiers == (False, False, False)
    assert kb._macos_modifier_refcount == (0, 0, 0)
    assert any(ev[1] is False for ev in events)


def test_keyboard_shutdown_pdi_and_pynput_exception_branches(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    logs = []
    kb = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)

    class BadPDI:
        def keyUp(self, *_a, **_k):
            raise RuntimeError("keyup boom")

    kb._use_pydirectinput = True
    kb._pdi = cast(Any, BadPDI())
    kb._kb = None
    kb._active_pitches = {"x": {60}}
    kb._state_for("x")
    kb._pedal_down = True

    kb.shutdown()

    assert any("shutdown note release error" in m for m in logs)
    assert any("shutdown pedal release error" in m for m in logs)
    assert any("shutdown modifier release error" in m for m in logs)

    monkeypatch.setattr(out.sys, "platform", "linux")

    class BadKB:
        def release(self, _k):
            raise RuntimeError("release boom")

    kb2 = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)
    kb2._kb = cast(Any, BadKB())
    kb2.shutdown()

    assert any("shutdown modifier release error" in m for m in logs)


def test_keyboard_shutdown_windows_transport_failure_is_logged(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)
    logs = []

    kb = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)
    kb._active_pitches = {"x": {60}}
    kb._state_for("x").press()
    kb._pedal_down = True
    fake_pdi.send_exception = RuntimeError("shutdown boom")

    kb.shutdown()

    assert any("shutdown release error" in m for m in logs)
    assert kb._active_pitches == {}
    assert kb._pedal_down is False


def test_output_backend_execute_batch_pedal_up_and_empty_branch():
    class B(OutputBackend):
        def __init__(self):
            self.calls = []

        def note_on(self, pitch, velocity):
            self.calls.append(("note_on", pitch, velocity))

        def note_off(self, pitch):
            self.calls.append(("note_off", pitch))

        def pedal_on(self):
            self.calls.append(("pedal_on",))

        def pedal_off(self):
            self.calls.append(("pedal_off",))

        def shutdown(self):
            self.calls.append(("shutdown",))

    b = B()
    events = [
        FakeEvent(0.0, 0, "pedal", key_char="up", pitch=None, velocity=0),
    ]
    b.execute_batch(events)

    keyboard_backend = out.KeyboardBackend(use_88_key_layout=False)
    keyboard_backend.execute_batch([])

    assert b.calls == [("pedal_off",)]


def test_create_backend_macos_numpad_does_not_use_toggle(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "darwin")

    backend = out.create_backend("midi_numpad")

    assert backend.__class__.__name__ == "NumpadBackend"


def test_note_on_returns_when_mapper_has_no_data(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._mapper.get_key_data = lambda pitch: None

    kb.note_on(60, 100)

    assert kb._active_pitches == {}


@pytest.mark.parametrize(
    ("vk_for_key", "expected_releases"),
    [
        (lambda k: 99 if k == Key.space else None, {99}),
        (lambda k: 50 if k == "x" else (99 if k == Key.space else None), {50, 99}),
    ],
    ids=["without-base-vk", "with-base-vk"],
)
def test_pedal_off_macos_releases_empty_keys(monkeypatch, vk_for_key, expected_releases):
    monkeypatch.setattr(out.sys, "platform", "darwin")

    calls = []
    monkeypatch.setattr(out, "post_macos_key_event", lambda vk, down, flags: calls.append((vk, down, flags)) or True)
    monkeypatch.setattr(out, "get_macos_vk_for_key", vk_for_key)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._pedal_down = True
    kb._active_pitches["x"] = set()
    kb._state_for("x").press()

    kb.pedal_off()

    assert kb._active_pitches == {}
    assert kb._states == {}
    released_vks = {vk for vk, down, _ in calls if down is False}
    assert expected_releases <= released_vks


def test_execute_batch_non_empty_delegates_to_super(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    called = {"count": 0}

    def _execute(_self, _events):
        called["count"] += 1

    monkeypatch.setattr(out.OutputBackend, "execute_batch", _execute)

    kb.execute_batch([FakeEvent(0.0, 0, "pedal", key_char="up", pitch=None, velocity=0)])

    assert called["count"] == 1


def test_shutdown_releases_note_and_pedal_with_keyboard_backend(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._active_pitches = {"x": {60}}
    kb._state_for("x").press()
    kb._pedal_down = True

    kb.shutdown()

    kb_impl = cast(Any, kb._kb)
    assert "x" in kb_impl.releases
    assert Key.space in kb_impl.releases
