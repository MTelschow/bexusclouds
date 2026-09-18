"""``clouds_ui --mock``: the flag's rules, and the chain it stands up.

No Qt here - the window itself is exercised by verify_qt.py. What this
covers is the wiring underneath it, where the mistakes would be silent: a
mock that quietly kept a real detector, a mock downlink that squatted on the
real GSE's UDP 4000, or a mock session that left flight-shaped data behind.
"""
import socket
import time

import pytest

from clouds_link import hk
from clouds_link.commands import Command
from clouds_link.frames import AckResult


def _parse(*argv):
    from clouds_ui.main import _parse
    return _parse(list(argv))


def test_mock_opens_no_detector_anywhere(monkeypatch):
    """Even on macOS, where the detector default is the bench Pi."""
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setenv("CLOUDS_SPECTRO_HOST", "10.0.0.9")
    assert _parse("--mock").net is None
    assert _parse().net == "10.0.0.9"        # the default is otherwise intact


def test_mock_and_net_are_refused_together():
    with pytest.raises(SystemExit):
        _parse("--mock", "--net", "192.168.100.10")


@pytest.fixture
def stack(tmp_path):
    from clouds_gse.receiver import Receiver
    from clouds_ui.mock_stack import MockStack

    rx = Receiver(bind="127.0.0.1", port=0)
    rx.start()
    st = MockStack(rx.port, log=lambda *_: None)
    st.start()
    try:
        yield rx, st
    finally:
        st.stop()
        rx.stop()


def _wait(predicate, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_the_whole_chain_downlinks(stack):
    """HK from the sim MCU, quick-look from the mock spectrometer, both
    through the real FSW and the real receiver."""
    rx, st = stack
    assert _wait(lambda: rx.last_hk is not None), "no housekeeping downlinked"
    assert rx.last_hk.state == hk.SeqState.STANDBY
    # Both channels: a quick-look cycle is one packet per channel.
    assert _wait(lambda: len(rx.quicklook) == 2), "no quick-look downlinked"
    assert rx.decode_errors == 0


def test_commands_are_confirmed_end_to_end(stack):
    """GSE -> Pi -> sim MCU and back, with the MCU's own verdict."""
    from clouds_gse.commander import Commander

    rx, st = stack
    cmd = Commander("127.0.0.1", st.cmd_port,
                    log=lambda *_: None)
    try:
        assert cmd.ping() == AckResult.OK
        assert cmd.send(Command.START) == AckResult.OK
        assert _wait(lambda: rx.last_hk is not None
                     and rx.last_hk.state == hk.SeqState.RUNNING)
        # Nothing gates the release any more: one frame, no ARM, no
        # interlock, and the MCU's own OK comes back through the Pi.
        assert cmd.release(1) == AckResult.OK
        assert _wait(lambda: rx.last_hk.fired & 1)
    finally:
        cmd.close()


def test_the_command_port_is_loopback_only(stack):
    """Anything can open TCP 4001; under --mock nothing off this machine
    should even reach it."""
    rx, st = stack
    host = socket.gethostbyname(socket.gethostname())
    if host.startswith("127."):
        pytest.skip("no non-loopback address on this machine")
    s = socket.socket()
    s.settimeout(1.0)
    with pytest.raises(OSError):
        s.connect((host, st.cmd_port))
    s.close()


def test_stop_removes_the_mock_data_directory(stack):
    import os

    rx, st = stack
    data_dir = st._data_dir
    assert os.path.isdir(data_dir)
    st.stop()
    assert not os.path.exists(data_dir), \
        "a mock run must not leave flight data behind"
