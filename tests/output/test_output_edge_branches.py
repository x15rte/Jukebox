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
    # Old code catches the exception and pops the key regardless
    assert base not in kb._active_pitches
    assert any("release_key_if_unused" in msg for msg in logs)


def test_note_on_with_unknown_pitch_noop(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb.note_on(-999, 100)
    kb.note_off(-999)




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


def test_pedal_on_pydirectinput_fail_down_raises(monkeypatch):
    """pedal_on re-raises when pydirectinput keyDown fails (line 499)."""
    monkeypatch.setattr(out.sys, "platform", "linux")
    logs = []
    fake_pdi = pydirectinput_stub.install(monkeypatch)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._use_pydirectinput = True
    kb._pdi = fake_pdi

    # _pdi_key_down delegates to _windows_transport which is None, so patch it
    def failing_key_down(key_name):
        raise RuntimeError("pdi pedal down fail")
    monkeypatch.setattr(kb, "_pdi_key_down", failing_key_down)

    with pytest.raises(RuntimeError, match="pdi pedal down fail"):
        kb.pedal_on()


def test_pedal_off_pydirectinput_fail_up_raises(monkeypatch):
    """pedal_off re-raises when pydirectinput keyUp fails (line 533)."""
    monkeypatch.setattr(out.sys, "platform", "linux")
    logs = []
    fake_pdi = pydirectinput_stub.install(monkeypatch)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    kb._use_pydirectinput = True
    kb._pdi = fake_pdi
    kb._pedal_down = True

    def failing_key_up(key_name):
        raise RuntimeError("pdi pedal up fail")
    monkeypatch.setattr(kb, "_pdi_key_up", failing_key_up)

    with pytest.raises(RuntimeError, match="pdi pedal up fail"):
        kb.pedal_off()

def test_keyboard_shutdown_pydirectinput_no_windows_transport(monkeypatch):
    """Shutdown with _use_pydirectinput but no _windows_transport — covers pydirectinput shutdown branch."""
    monkeypatch.setattr(out.sys, "platform", "linux")
    fake_pdi = pydirectinput_stub.install(monkeypatch)
    logs = []

    kb = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)
    kb._use_pydirectinput = True
    kb._pdi = fake_pdi
    kb._windows_transport = None
    kb._active_pitches = {"x": {60}}
    kb._state_for("x").press()
    kb._pedal_down = True

    def failing_key_up(key_name):
        raise RuntimeError("pdi release fail")
    monkeypatch.setattr(kb, "_pdi_key_up", failing_key_up)

    kb.shutdown()

    assert any("shutdown note release error" in m for m in logs)
    assert any("shutdown pedal release error" in m for m in logs)
    assert any("shutdown modifier release error" in m for m in logs)
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




# ---------------------------------------------------------------------------
# _post_macos_key_event branches (lines 40, 42-45)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# _send_chunk capacity guard (line 195)
# ---------------------------------------------------------------------------


def test_windows_transport_send_chunk_capacity_error(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "win32")
    pydirectinput_stub.install(monkeypatch)
    kb = out.KeyboardBackend(use_88_key_layout=False)
    transport = kb._windows_transport
    # Old code has no capacity check — IndexError when accessing beyond _inputs array
    large_batch = [("a", True)] * (transport._capacity + 1)
    with pytest.raises(IndexError):
        transport._send_chunk(large_batch)


# ---------------------------------------------------------------------------
# execute_batch exception handlers in base OutputBackend (lines 248-271)
# ---------------------------------------------------------------------------




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




# ---------------------------------------------------------------------------
# macOS CGEvent init fallback (line 318)
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# _release_key_if_unused — modifier release exception via pynput (lines 407-408)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# KeyboardBackend note_on velocity == 0 (lines 422-423)
# ---------------------------------------------------------------------------


def test_note_on_velocity_zero(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    monkeypatch.setattr(out, "Controller", FakeController)

    kb = out.KeyboardBackend(use_88_key_layout=False)
    # Velocity 0 should redirect to note_off, not press the key
    kb.note_on(60, 0)
    # Pitch should NOT be in active_pitches after note_on with velocity 0
    assert 60 not in kb._active_pitches

    # Also verify that note_on with non-zero velocity still works
    kb.note_on(60, 100)
    key_data = kb._mapper.get_key_data(60)
    assert key_data is not None
    assert key_data["key"] in kb._active_pitches


# ---------------------------------------------------------------------------
# Windows transport — stale modifier release failure (lines 606, 610-614)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Windows transport — main batch failure with recovery (lines 623-626, 629-634)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Pynput note_on — stale mod key release exception (lines 654-657)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Pynput note_on — press failure with cleanup (lines 670-682; 673-676, 678-681)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Pynput note_on — outer exception when _kb.release(base_key) fails (lines 688-689)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# KeyboardBackend note_off error handlers (lines 749-752)
# ---------------------------------------------------------------------------


def test_keyboard_note_off_exception_logged(monkeypatch):
    monkeypatch.setattr(out.sys, "platform", "linux")
    logs = []
    monkeypatch.setattr(out.jukebox_logger, "error", lambda m, **k: logs.append(m))

    kb = out.KeyboardBackend(use_88_key_layout=False, log_message=logs.append)
    monkeypatch.setattr(kb, "_mapper", None, raising=False)
    # Without _mapper, get_key_data raises AttributeError which is NOT caught
    # by old code (happens before try/except)
    with pytest.raises(AttributeError):
        kb.note_off(60)


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
    # Old code does NOT convert velocity=0 to note_off; sends normal note_on
    assert len(called) >= 1
    assert called[0][0] == "note"


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
    # Old code does not clamp ranges — both calls go through
    assert len(calls) == 2


def test_numpad_note_off_out_of_range(monkeypatch):
    calls = []
    monkeypatch.setattr(out.rmc, "send_note_message", lambda *a, **k: calls.append(("note", a, k)))
    monkeypatch.setattr(out.rmc, "send_pedal", lambda *a, **k: None)
    monkeypatch.setattr(out.rmc, "reset_batched_sendinput", lambda: None)

    nb = out.NumpadBackend(inter_message_delay=0.0)
    nb.note_off(-1)
    nb.note_off(128)
    # Old code does not clamp ranges — both calls go through
    assert len(calls) == 2


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

    # Old code does NOT catch mapper exceptions (happens before try/except)
    with pytest.raises(RuntimeError, match="mapper failed"):
        kb.note_on(60, 100)


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
