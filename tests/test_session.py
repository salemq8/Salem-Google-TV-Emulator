from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from salem_tv_box_emulator.services.session import EmulatorSession, RemoteService, RemoteSessionUnavailable, SessionBinder, SessionState, parse_devices


def binder_for(session, transports, boot="1"):
    def query(args, timeout):
        if args == ["devices", "-l"]:
            return 0, "List of devices attached\n" + "\n".join(f"{s} {state}" for s, (state, avd) in transports.items())
        state, avd = transports[args[1]]
        if args[2:] == ["emu", "avd", "name"]:
            return 0, avd + "\nOK\n"
        return 0, boot
    return SessionBinder(session, query)


def test_existing_unrelated_restart_serial_change():
    session = EmulatorSession()
    session.begin("Salem_Google_TV", 100, {"emulator-5554"})
    transports = {"emulator-5554": ("device", "Other"), "emulator-5556": ("device", "Salem_Google_TV")}
    binder = binder_for(session, transports)
    assert binder.poll() == "emulator-5556"
    previous = session.generation
    session.begin("Salem_Google_TV", 200, {"emulator-5554", "emulator-5556"})
    transports["emulator-5558"] = ("device", "Salem_Google_TV")
    assert binder.poll() == "emulator-5558"
    with pytest.raises(RemoteSessionUnavailable, match="changed"):
        session.require(previous)


@pytest.mark.parametrize("state", ["offline", "unauthorized", "unknown"])
def test_unready_transport_never_enabled(state):
    session = EmulatorSession()
    session.begin("Salem_Google_TV", 100, set())
    assert binder_for(session, {"emulator-5556": (state, "Salem_Google_TV")}).poll() is None
    assert not session.ready


def test_booting_disables_controls():
    session = EmulatorSession()
    session.begin("Salem_Google_TV", 100, set())
    assert binder_for(session, {"emulator-5556": ("device", "Salem_Google_TV")}, boot="0").poll() is None
    assert session.state == SessionState.BOOTING
    with pytest.raises(RemoteSessionUnavailable):
        session.require()


def test_disconnect_and_reconnect():
    session = EmulatorSession()
    session.begin("Salem_Google_TV", 100, set())
    transports = {"emulator-5556": ("device", "Salem_Google_TV")}
    binder = binder_for(session, transports)
    assert binder.poll() == "emulator-5556"
    transports["emulator-5556"] = ("offline", "Salem_Google_TV")
    assert binder.poll() is None
    assert not session.ready and session.serial is None
    transports.clear()
    transports["emulator-5558"] = ("device", "Salem_Google_TV")
    assert binder.poll() == "emulator-5558"


def test_ambiguous_same_avd_fails_closed():
    session = EmulatorSession()
    session.begin("Salem_Google_TV", 100, set())
    transports = {s: ("device", "Salem_Google_TV") for s in ("emulator-5556", "emulator-5558")}
    assert binder_for(session, transports).poll() is None
    assert "Multiple" in session.message


def test_no_first_device_fallback():
    session = EmulatorSession()
    session.begin("Salem_Google_TV", 100, set())
    assert binder_for(session, {"emulator-5554": ("device", "Phone")}).poll() is None


def test_shared_remote_text_audio_and_stale_queue():
    session = EmulatorSession()
    session.begin("Salem_Google_TV", 100, set())
    binder_for(session, {"emulator-5556": ("device", "Salem_Google_TV")}).poll()
    controller = SimpleNamespace(session=session, send_remote_key=Mock(), send_text=Mock(), test_sound=Mock())
    main = RemoteService(controller)
    popout = main
    generation = session.generation
    main.key("up", generation)
    popout.key("down", generation)
    main.text("Hello", generation)
    main.sound(generation)
    assert main.session is popout.session is controller.session
    session.invalidate(SessionState.STOPPING)
    with pytest.raises(RemoteSessionUnavailable):
        main.key("ok", generation)
    assert controller.send_remote_key.call_count == 2


def test_parse_devices_does_not_bind_phone_or_daemon_messages():
    devices = parse_devices("* daemon started successfully *\nList of devices attached\nphone1 device\nemulator-5580 device product:tv\n")
    assert len(devices) == 1 and devices[0].serial == "emulator-5580"


def test_stop_invalidates_queued_input_but_preserves_graceful_shutdown_identity():
    session = EmulatorSession()
    session.begin("Salem_Google_TV", 100, set())
    binder_for(session, {"emulator-5556": ("device", "Salem_Google_TV")}).poll()
    generation = session.generation
    session.stopping()
    assert session.serial == "emulator-5556" and not session.ready
    with pytest.raises(RemoteSessionUnavailable):
        session.require(generation)


def test_disconnect_invalidates_old_queue_even_after_reconnection():
    session = EmulatorSession()
    session.begin("Salem_Google_TV", 100, set())
    transports = {"emulator-5556": ("device", "Salem_Google_TV")}
    binder = binder_for(session, transports)
    binder.poll()
    generation = session.generation
    transports.clear()
    binder.poll()
    transports["emulator-5558"] = ("device", "Salem_Google_TV")
    binder.poll()
    assert session.ready
    with pytest.raises(RemoteSessionUnavailable):
        session.require(generation)
