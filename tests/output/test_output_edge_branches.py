# pyright: reportOptionalMemberAccess=false, reportOptionalSubscript=false

from typing import Any, cast

import pytest
from pynput.keyboard import Key

import output.output as out
from output.output import OutputBackend
from tests.helpers import pydirectinput_stub
from tests.helpers.fakes import FakeController, FakeEvent

out = cast(Any, out)







def test_release_key_if_unused_handles_backend_exception(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)
    logs = []
    monkeypatch.setattr(
        out.jukebox_logger, "error",
        lambda m, **k: logs.append(m),
    )
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
    # Pop-on-failure fix: key tracking preserved when release fails
    assert base in kb._active_pitches
    assert any("release_key_if_unused" in msg for msg in logs)


def test_note_on_with_unknown_pitch_noop(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb.note_on(-999, 100)
    kb.note_off(-999)




def test_note_off_macos_releases_only_when_no_active_pitches(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "darwin")
    monkeypatch.setattr(out, "_init_macos_cgevent", lambda: True)

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
    n_events_before_off = len(events)
    kb.note_off(p1)

    # Bug 1 repress fix: second note_on already added a repress release for the
    # base key. note_off(p1) should NOT add another release since p2 is still active.
    new_events = events[n_events_before_off:]
    new_releases = [e for e in new_events if e[0] == base_vk and e[1] is False]
    assert not new_releases, f"note_off(p1) should not release base key: {new_releases}"

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
    monkeypatch.setattr(
        out.jukebox_logger, "error",
        lambda m, **k: logs.append(m),
    )

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
    monkeypatch.setattr(
        out.jukebox_logger, "error",
        lambda m, **k: logs.append(m),
    )

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
    monkeypatch.setattr(out, "_init_macos_cgevent", lambda: True)
    monkeypatch.setattr(out, "get_macos_vk_for_key", lambda _k: None)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb.note_on(60, 100)


def test_note_on_off_macos_ctrl_alt_and_none_modifier(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "darwin")
    monkeypatch.setattr(out, "_init_macos_cgevent", lambda: True)
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
    monkeypatch.setattr(
        out.jukebox_logger, "error",
        lambda m, **k: logs.append(m),
    )

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
    monkeypatch.setattr(
        out.jukebox_logger, "error",
        lambda m, **k: logs.append(m),
    )
    kb = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)

    class BadKB:
        def press(self, _k):
            raise RuntimeError("pedal press boom")

        def release(self, _k):
            raise RuntimeError("pedal release boom")

    kb._kb = cast(Any, BadKB())
    kb.pedal_on()
    kb.pedal_on()
    kb._pedal_down = True
    kb.pedal_off()
    kb._pedal_down = True
    kb.pedal_off()

    assert any("pedal_on error" in m for m in logs)
    assert any("pedal_off error" in m for m in logs)




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
    monkeypatch.setattr(out, "_init_macos_cgevent", lambda: True)
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


def test_keyboard_shutdown_pynput_exception_branches(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    logs = []
    monkeypatch.setattr(
        out.jukebox_logger, "error",
        lambda m, **k: logs.append(m),
    )

    class BadKB:
        def release(self, _k):
            raise RuntimeError("release boom")

    kb = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)
    kb._kb = cast(Any, BadKB())
    kb.shutdown()

    assert any("shutdown modifier release error" in m for m in logs)


def test_keyboard_shutdown_windows_transport_failure_is_logged(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)
    logs = []
    monkeypatch.setattr(
        out.jukebox_logger, "error",
        lambda m, **k: logs.append(m),
    )

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
    assert keyboard_backend._pedal_down is False
    assert keyboard_backend._active_pitches == {}


def test_create_backend_macos_numpad_does_not_use_toggle(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "darwin")
    monkeypatch.setattr(out, "_init_macos_cgevent", lambda: True)

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
    monkeypatch.setattr(out, "_init_macos_cgevent", lambda: True)
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
    assert expected_releases == released_vks


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


def test_keyboard_windows_pydirectinput_exception_branches(monkeypatch):
    """Cover KeyboardBackend pydirectinput error branches (pedal_on/off raise, shutdown individual release errors)."""
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)
    logs = []

    # --- pedal_on re-raises pydirectinput errors (line 499) ---
    kb = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)
    transport = cast(Any, kb._windows_transport)
    transport.key_down = lambda key_name: (_ for _ in ()).throw(
        RuntimeError("pdi key_down failed")
    )
    with pytest.raises(RuntimeError, match="pdi key_down failed"):
        kb.pedal_on()

    # --- pedal_off re-raises pydirectinput errors (line 533) ---
    kb2 = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)
    transport2 = cast(Any, kb2._windows_transport)
    transport2.key_up = lambda key_name: (_ for _ in ()).throw(
        RuntimeError("pdi key_up failed")
    )
    kb2._pedal_down = True
    with pytest.raises(RuntimeError, match="pdi key_up failed"):
        kb2.pedal_off()
    # --- shutdown individual pydirectinput error path ---
    # Force _windows_transport=None so shutdown takes the per-key pydirectinput branch
    kb3 = out.KeyboardBackend(use_88_key_layout=False, log_message=None)
    kb3._windows_transport = None
    kb3._active_pitches = {"a": {60}, "b": {62}}
    kb3._state_for("a").press()
    kb3._state_for("b").press()

    def failing_key_up(key_char):
        raise RuntimeError("pdi key_up boom")
    monkeypatch.setattr(kb3, "_pdi_key_up", failing_key_up)

    kb3._pedal_down = True
    # M12: _log_exception now uses jukebox_logger.error directly; monkeypatch to capture
    import logger_core
    monkeypatch.setattr(logger_core.jukebox_logger, "error", logs.append)
    kb3.shutdown()

    assert any("note release error" in m for m in logs)
    assert any("pedal release error" in m for m in logs)
    assert any("modifier release error" in m for m in logs)


# ---------------------------------------------------------------------------
# _post_macos_key_event branches (lines 40, 42-45)
# ---------------------------------------------------------------------------


def test_post_macos_key_event_no_func(monkeypatch):
    monkeypatch.setattr(out, "post_macos_key_event", None)
    assert out._post_macos_key_event(0, True, 0) is False


def test_post_macos_key_event_func_fails(monkeypatch):
    monkeypatch.setattr(out, "post_macos_key_event", lambda vk, down, flags: False)
    logs = []
    monkeypatch.setattr(out.jukebox_logger, "warning", lambda m, **k: logs.append(m))
    assert out._post_macos_key_event(0, True, 0) is False
    assert any("macOS key event failed" in m for m in logs)


# ---------------------------------------------------------------------------
# _send_chunk capacity guard (line 195)
# ---------------------------------------------------------------------------


def test_windows_transport_send_chunk_capacity_error(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    pydirectinput_stub.install(monkeypatch)
    kb = out.KeyboardBackend(use_88_key_layout=False)
    transport = kb._windows_transport
    large_batch = [("a", True)] * (transport._capacity + 1)
    with pytest.raises(ValueError, match="_send_chunk capacity"):
        transport._send_chunk(large_batch)


# ---------------------------------------------------------------------------
# execute_batch exception handlers in base OutputBackend (lines 248-271)
# ---------------------------------------------------------------------------


def test_execute_batch_pedal_logs_exception(monkeypatch):
    logs = []
    monkeypatch.setattr(out.jukebox_logger, "error", lambda m, **k: logs.append(m))

    class B(OutputBackend):
        def note_on(self, pitch, velocity): pass
        def note_off(self, pitch): pass
        def pedal_on(self): raise RuntimeError("pedal failed")
        def pedal_off(self): pass
        def shutdown(self): pass

    b = B()
    b.execute_batch([FakeEvent(0.0, 0, "pedal", key_char="down")])
    assert any("execute_batch pedal" in m for m in logs)


def test_execute_batch_pedal_re_raises_backend_error(monkeypatch):
    class B(OutputBackend):
        def note_on(self, pitch, velocity): pass
        def note_off(self, pitch): pass
        def pedal_on(self): raise out.OutputBackendError("pedal backend err")
        def pedal_off(self): pass
        def shutdown(self): pass

    b = B()
    with pytest.raises(out.OutputBackendError, match="pedal backend err"):
        b.execute_batch([FakeEvent(0.0, 0, "pedal", key_char="down")])


def test_execute_batch_note_off_logs_exception(monkeypatch):
    logs = []
    monkeypatch.setattr(out.jukebox_logger, "error", lambda m, **k: logs.append(m))

    class B(OutputBackend):
        def note_on(self, pitch, velocity): pass
        def note_off(self, pitch): raise RuntimeError("note_off failed")
        def pedal_on(self): pass
        def pedal_off(self): pass
        def shutdown(self): pass

    b = B()
    b.execute_batch([FakeEvent(0.0, 0, "release", pitch=60)])
    assert any("execute_batch note_off" in m for m in logs)


def test_execute_batch_note_off_re_raises_backend_error(monkeypatch):
    class B(OutputBackend):
        def note_on(self, pitch, velocity): pass
        def note_off(self, pitch): raise out.OutputBackendError("note_off backend err")
        def pedal_on(self): pass
        def pedal_off(self): pass
        def shutdown(self): pass

    b = B()
    with pytest.raises(out.OutputBackendError, match="note_off backend err"):
        b.execute_batch([FakeEvent(0.0, 0, "release", pitch=60)])


def test_execute_batch_note_on_logs_exception(monkeypatch):
    logs = []
    monkeypatch.setattr(out.jukebox_logger, "error", lambda m, **k: logs.append(m))

    class B(OutputBackend):
        def note_on(self, pitch, velocity): raise RuntimeError("note_on failed")
        def note_off(self, pitch): pass
        def pedal_on(self): pass
        def pedal_off(self): pass
        def shutdown(self): pass

    b = B()
    b.execute_batch([FakeEvent(0.0, 0, "press", pitch=60)])
    assert any("execute_batch note_on" in m for m in logs)


def test_execute_batch_note_on_re_raises_backend_error(monkeypatch):
    class B(OutputBackend):
        def note_on(self, pitch, velocity): raise out.OutputBackendError("note_on backend err")
        def note_off(self, pitch): pass
        def pedal_on(self): pass
        def pedal_off(self): pass
        def shutdown(self): pass

    b = B()
    with pytest.raises(out.OutputBackendError, match="note_on backend err"):
        b.execute_batch([FakeEvent(0.0, 0, "press", pitch=60)])


# ---------------------------------------------------------------------------
# base OutputBackend._log_exception (line 280)
# ---------------------------------------------------------------------------


def test_base_output_backend_log_exception(monkeypatch):
    logs = []
    monkeypatch.setattr(out.jukebox_logger, "error", lambda m, **k: logs.append(m))

    class B(OutputBackend):
        def note_on(self, pitch, velocity): pass
        def note_off(self, pitch): pass
        def pedal_on(self): pass
        def pedal_off(self): pass
        def shutdown(self): pass

    b = B()
    b._log_exception("test_ctx", RuntimeError("boom"))
    assert any("test_ctx" in m for m in logs)


# ---------------------------------------------------------------------------
# macOS CGEvent init fallback (line 318)
# ---------------------------------------------------------------------------


def test_macos_cgevent_fallback_to_pynput(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "darwin")
    monkeypatch.setattr(out, "_init_macos_cgevent", lambda: False)
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    assert kb._use_macos_cgevent is False
    assert kb._kb is not None


# ---------------------------------------------------------------------------
# _release_key_if_unused — pydirectinput exception (lines 383-384)
# ---------------------------------------------------------------------------


def test_release_key_if_unused_pydirectinput_exception(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    pydirectinput_stub.install(monkeypatch)
    logs = []
    monkeypatch.setattr(out.jukebox_logger, "error", lambda m, **k: logs.append(m))

    kb = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)
    key_data = kb._mapper.get_key_data(60)
    base = key_data["key"]
    kb._active_pitches[base] = set()
    kb._state_for(base)

    def failing_key_up(key_name):
        raise RuntimeError("pdi release failed")
    monkeypatch.setattr(kb, "_pdi_key_up", failing_key_up)

    kb._release_key_if_unused(base)
    assert any("_release_key_if_unused" in msg for msg in logs)


# ---------------------------------------------------------------------------
# _release_key_if_unused — modifier release exception via pynput (lines 407-408)
# ---------------------------------------------------------------------------


def test_release_key_if_unused_modifier_release_exception(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)
    logs = []
    monkeypatch.setattr(out.jukebox_logger, "error", lambda m, **k: logs.append(m))

    kb = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)
    key_data = kb._mapper.get_key_data(60)
    base = key_data["key"]
    kb._active_pitches[base] = set()
    kb._state_for(base)
    kb._held_modifier_keys[base] = [Key.shift, Key.ctrl]

    class ReleaseFailController(FakeController):
        def release(self, key):
            if key in (Key.shift, Key.ctrl):
                raise RuntimeError("mod release failed")
            super().release(key)
    kb._kb = cast(Any, ReleaseFailController())

    kb._release_key_if_unused(base)
    assert any("modifier release error" in msg for msg in logs)


# ---------------------------------------------------------------------------
# KeyboardBackend note_on velocity == 0 (lines 422-423)
# ---------------------------------------------------------------------------


def test_note_on_velocity_zero(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    called = []
    kb = out.KeyboardBackend(use_88_key_layout=False)
    monkeypatch.setattr(kb, "note_off", lambda p: called.append(p))
    kb.note_on(60, 0)
    assert 60 in called


# ---------------------------------------------------------------------------
# Windows transport — stale modifier release failure (lines 606, 610-614)
# ---------------------------------------------------------------------------


def test_windows_note_on_stale_mod_release_failure(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    pydirectinput_stub.install(monkeypatch)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    transport = kb._windows_transport
    key_data = kb._mapper.get_key_data(60)
    base_key = key_data["key"]

    # Simulate active note with stale modifiers
    kb._state_for(base_key)
    kb._active_pitches[base_key] = {99}
    kb._held_modifiers[base_key] = ["shiftleft"]

    original_send_batch = transport.send_batch
    call_count = [0]

    def failing_send_batch(actions):
        call_count[0] += 1
        if call_count[0] == 1:
            raise out.OutputBackendSendError("stale release failed")
        return original_send_batch(actions)

    monkeypatch.setattr(transport, "send_batch", failing_send_batch)

    kb.note_on(60, 100)
    # State was cleared: held_modifiers entry removed
    assert base_key not in kb._held_modifiers


# ---------------------------------------------------------------------------
# Windows transport — main batch failure with recovery (lines 623-626, 629-634)
# ---------------------------------------------------------------------------


def test_windows_note_on_main_batch_failure(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    pydirectinput_stub.install(monkeypatch)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    transport = kb._windows_transport
    # Pitch with modifiers to enable modifier recovery
    key_data = kb._mapper.get_key_data(61)
    base_key = key_data["key"]

    # Simulate active note with stale modifiers that differ from pitch 61's modifiers
    kb._state_for(base_key)
    kb._active_pitches[base_key] = {99}
    # Pitch 61 has shift modifier; add ctrlleft as a stale that won't be in the new note
    kb._held_modifiers[base_key] = ["shiftleft", "ctrlleft"]

    original_send_batch = transport.send_batch
    call_count = [0]

    def failing_send_batch(actions):
        call_count[0] += 1
        # Call 1: stale mod release  Call 2: base_key release  Call 3: main batch
        if call_count[0] == 3:
            raise out.OutputBackendSendError("main batch failed")
        # Calls 4+ are recovery actions — also fail to hit the pass branches
        if call_count[0] >= 4:
            raise out.OutputBackendSendError("recovery also failed")
        return original_send_batch(actions)

    monkeypatch.setattr(transport, "send_batch", failing_send_batch)

    kb.note_on(61, 100)
    assert base_key not in kb._held_modifiers
    assert base_key not in kb._active_pitches


# ---------------------------------------------------------------------------
# Pynput note_on — stale mod key release exception (lines 654-657)
# ---------------------------------------------------------------------------


def test_pynput_note_on_stale_mod_release_exception(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    # Use a pitch with modifiers so stale_mod_keys can be non-empty
    key_data = kb._mapper.get_key_data(61)
    base_key = key_data["key"]

    # Activate the key with modifiers
    kb.note_on(61, 100)

    # Add stale modifier keys that won't be in the new note's modifiers
    kb._held_modifier_keys[base_key] = [Key.shift, Key.alt]

    # Make release fail for the stale mod keys (alt is stale)
    class FailOnStale(FakeController):
        def release(self, key):
            if key == Key.alt:
                raise RuntimeError("stale release failed")
            super().release(key)

    kb._kb = cast(Any, FailOnStale())
    # note_on(61, 100) again — was_active=True, stale_mod_keys contains Key.alt
    kb.note_on(61, 100)
    # After successful note_on the key should be tracked
    assert base_key in kb._held_modifier_keys


# ---------------------------------------------------------------------------
# Pynput note_on — press failure with cleanup (lines 670-682; 673-676, 678-681)
# ---------------------------------------------------------------------------


def test_pynput_note_on_press_failure_cleanup(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)
    logs = []
    import logger_core
    monkeypatch.setattr(logger_core.jukebox_logger, "error", logs.append)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    key_data = kb._mapper.get_key_data(61)
    base_key = key_data["key"]

    # First note_on succeeds; key is now active with modifiers
    kb.note_on(61, 100)
    assert base_key in kb._active_pitches

    # Replace _kb so base_key press fails but modifier press succeeds;
    # also make modifier releases (during cleanup) fail.
    class KeepActive(FakeController):
        def press(self, key):
            if isinstance(key, str):  # base_key is a string, modifiers are Key objects
                raise RuntimeError("base press failed")
            super().press(key)

        def release(self, key):
            if not isinstance(key, str):  # modifier Key objects
                raise RuntimeError("mod release failed")
            super().release(key)

    kb._kb = cast(Any, KeepActive())

    # Second note_on — was_active=True, press of base_key fails
    kb.note_on(61, 100)

    assert any("note_on error" in m for m in logs)


# ---------------------------------------------------------------------------
# Pynput note_on — outer exception when _kb.release(base_key) fails (lines 688-689)
# ---------------------------------------------------------------------------


def test_pynput_note_on_outer_exception(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)
    logs = []
    import logger_core
    monkeypatch.setattr(logger_core.jukebox_logger, "error", logs.append)

    kb = out.KeyboardBackend(use_88_key_layout=False)

    # Activate a key
    key_data = kb._mapper.get_key_data(60)
    base_key = key_data["key"]
    kb._state_for(base_key)
    kb._active_pitches[base_key] = {99}

    # Make _kb.release fail (called at line 658 for was_active re-press)
    class FailRelease(FakeController):
        def release(self, key):
            raise RuntimeError("release failed in note_on")
    kb._kb = cast(Any, FailRelease())

    kb.note_on(60, 100)
    assert any("note_on error" in m for m in logs)


# ---------------------------------------------------------------------------
# KeyboardBackend note_off error handlers (lines 749-752)
# ---------------------------------------------------------------------------


def test_keyboard_note_off_exception_logged(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    logs = []
    monkeypatch.setattr(out.jukebox_logger, "error", lambda m, **k: logs.append(m))

    kb = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)
    monkeypatch.setattr(kb, "_mapper", None, raising=False)
    # Without _mapper, get_key_data raises AttributeError
    kb.note_off(60)
    assert any("note_off error" in m for m in logs)


def test_keyboard_note_off_re_raises_backend_error(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    key_data = kb._mapper.get_key_data(60)
    base_key = key_data["key"]
    kb._active_pitches[base_key] = {60}
    kb._pedal_down = False

    # Make _release_key_if_unused raise OutputBackendError
    def failing_release(key):
        raise out.OutputBackendError("release failed")
    monkeypatch.setattr(kb, "_release_key_if_unused", failing_release)

    with pytest.raises(out.OutputBackendError, match="release failed"):
        kb.note_off(60)


# ---------------------------------------------------------------------------
# NumpadBackend — note_on velocity zero (lines 967-968)
# ---------------------------------------------------------------------------


def test_numpad_note_on_velocity_zero(monkeypatch):
    called = []
    monkeypatch.setattr(out.rmc, "send_note_message", lambda *a, **k: called.append(("note", a, k)))
    monkeypatch.setattr(out.rmc, "send_pedal", lambda *a, **k: None)
    monkeypatch.setattr(out.rmc, "reset_batched_sendinput", lambda: None)

    nb = out.NumpadBackend(inter_message_delay=0.0)
    nb.note_on(60, 0)
    # Should have called note_off which calls send_note_message with is_note_off=True
    assert any(c[0] == "note" and c[2].get("is_note_off") for c in called)


# ---------------------------------------------------------------------------
# NumpadBackend — note_on / note_off out of range (lines 970, 981)
# ---------------------------------------------------------------------------


def test_numpad_note_on_out_of_range(monkeypatch):
    calls = []
    monkeypatch.setattr(out.rmc, "send_note_message", lambda *a, **k: calls.append(("note", a, k)))
    monkeypatch.setattr(out.rmc, "send_pedal", lambda *a, **k: None)
    monkeypatch.setattr(out.rmc, "reset_batched_sendinput", lambda: None)

    nb = out.NumpadBackend(inter_message_delay=0.0)
    nb.note_on(-1, 100)
    nb.note_on(128, 100)
    assert len(calls) == 0


def test_numpad_note_off_out_of_range(monkeypatch):
    calls = []
    monkeypatch.setattr(out.rmc, "send_note_message", lambda *a, **k: calls.append(("note", a, k)))
    monkeypatch.setattr(out.rmc, "send_pedal", lambda *a, **k: None)
    monkeypatch.setattr(out.rmc, "reset_batched_sendinput", lambda: None)

    nb = out.NumpadBackend(inter_message_delay=0.0)
    nb.note_off(-1)
    nb.note_off(128)
    assert len(calls) == 0


# ---------------------------------------------------------------------------
# NumpadBackend — pedal_off exception (lines 1013-1014)
# ---------------------------------------------------------------------------


def test_numpad_pedal_off_exception(monkeypatch):
    logs = []

    def bad_pedal(*_a, **_k):
        raise RuntimeError("pedal_off error")

    monkeypatch.setattr(out.rmc, "send_pedal", bad_pedal)
    monkeypatch.setattr(out.rmc, "reset_batched_sendinput", lambda: None)
    monkeypatch.setattr(out.jukebox_logger, "error", lambda m, **k: logs.append(m))

    nb = out.NumpadBackend(inter_message_delay=0.0, log_message=logs.append)
    nb._pedal_down = True
    nb.pedal_off()
    assert any("pedal_off error" in m for m in logs)


# ---------------------------------------------------------------------------
# NumpadBackend — shutdown pedal released successfully (line 1030)
# ---------------------------------------------------------------------------


def test_numpad_shutdown_pedal_released(monkeypatch):
    calls = []
    monkeypatch.setattr(out.rmc, "send_note_message", lambda *a, **k: calls.append(("note", a, k)))
    monkeypatch.setattr(out.rmc, "send_pedal", lambda *a, **k: calls.append(("pedal", a, k)))
    monkeypatch.setattr(out.rmc, "reset_batched_sendinput", lambda: calls.append(("reset", (), {})))

    nb = out.NumpadBackend(inter_message_delay=0.0)
    nb._active_notes = {60}
    nb._pedal_down = True
    nb.shutdown()

    pedal_calls = [c for c in calls if c[0] == "pedal"]
    assert len(pedal_calls) >= 1
    # _pedal_down should have been set to False after successful send_pedal(0)
    assert nb._pedal_down is False


# ---------------------------------------------------------------------------
# create_backend — macOS numpad without CGEvent (line 1053)
# ---------------------------------------------------------------------------


def test_create_backend_macos_numpad_requires_cgevent(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "darwin")
    monkeypatch.setattr(out, "_init_macos_cgevent", lambda: False)

    with pytest.raises(out.OutputBackendUnavailableError, match="Accessibility"):
        out.create_backend("midi_numpad")


# ---------------------------------------------------------------------------
# _send_chunk — partial SendInput (line 213)
# ---------------------------------------------------------------------------


def test_windows_transport_send_input_partial(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    fake_pdi = pydirectinput_stub.install(monkeypatch)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    transport = kb._windows_transport
    fake_pdi.send_result = 0  # SendInput returns 0 (fewer than count)

    with pytest.raises(out.OutputBackendSendError, match="sent 0 of"):
        transport.send_batch([("a", True)])


# ---------------------------------------------------------------------------
# note_on — outer exception from mapper (lines 690-693)
# ---------------------------------------------------------------------------


def test_note_on_outer_exception_from_mapper(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)
    logs = []
    import logger_core
    monkeypatch.setattr(logger_core.jukebox_logger, "error", logs.append)

    kb = out.KeyboardBackend(use_88_key_layout=False)

    def bad_mapper(pitch):
        raise RuntimeError("mapper failed")
    monkeypatch.setattr(kb._mapper, "get_key_data", bad_mapper)

    kb.note_on(60, 100)
    assert any("note_on error" in m for m in logs)


def test_note_on_outer_output_backend_error_re_raised(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)

    def bad_mapper(pitch):
        raise out.OutputBackendError("mapper backend error")
    monkeypatch.setattr(kb._mapper, "get_key_data", bad_mapper)

    with pytest.raises(out.OutputBackendError, match="mapper backend error"):
        kb.note_on(60, 100)


# ---------------------------------------------------------------------------
# pedal_on — success on pynput path (lines 773-774)
# ---------------------------------------------------------------------------


def test_pedal_on_pynput_success(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb.pedal_on()
    assert kb._pedal_down is True


# ---------------------------------------------------------------------------
# pedal_on — idempotent on pydirectinput path (line 765)
# ---------------------------------------------------------------------------


def test_pedal_on_windows_idempotent(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    pydirectinput_stub.install(monkeypatch)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._pedal_down = True
    kb.pedal_on()
    assert kb._pedal_down is True


# ---------------------------------------------------------------------------
# pedal_off — early return when not down (line 784)
# ---------------------------------------------------------------------------


def test_pedal_off_early_return(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb.pedal_off()
    assert kb._pedal_down is False
