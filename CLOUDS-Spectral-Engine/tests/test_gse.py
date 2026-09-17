"""GSE: receiver decode/gaps, commander interlock + arm handshake, logging.

The commander is tested against the real FSW-PI CommandServer - the actual
protocol partner - so this doubles as an interop test.
"""
import json
import socket
import time

import pytest

from clouds_link import frames, hk
from clouds_link.commands import Command, DisperseKey
from clouds_link.frames import AckResult, Frame, PacketType, SeqCounter
from clouds_fsw.command_server import CommandServer, CommandState
from clouds_gse.commander import Commander, CommandError, InterlockError
from clouds_gse.receiver import Receiver
from clouds_gse.session_log import SessionLog


def _wait(predicate, timeout=2.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def receiver():
    rx = Receiver(bind="127.0.0.1", port=0)
    rx.start()
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    yield rx, lambda raw: tx.sendto(raw, ("127.0.0.1", rx.port))
    tx.close()
    rx.stop()


def _hk_frame(seq, **kw):
    return Frame(type=PacketType.HK, payload=hk.Housekeeping(**kw).pack(),
                 seq=seq).stamp().encode()


class TestReceiver:
    def test_hk_decoded_and_latest_kept(self, receiver):
        rx, send = receiver
        send(_hk_frame(0, state=hk.SeqState.ASCENT, p_amb_pa=30_000))
        send(_hk_frame(1, state=hk.SeqState.SEAL, p_amb_pa=5_400))
        assert _wait(lambda: rx.gaps.received == 2)
        assert rx.last_hk.state_name == "SEAL"
        assert rx.hk_age_s() < 1.0

    def test_gap_counted(self, receiver):
        rx, send = receiver
        for seq in (0, 1, 4):
            send(_hk_frame(seq))
        assert _wait(lambda: rx.gaps.received == 3)
        assert rx.gaps.lost == 2

    def test_corrupt_packet_survives(self, receiver):
        rx, send = receiver
        send(b"\xba\xad")
        send(_hk_frame(0))
        assert _wait(lambda: rx.gaps.received == 1)
        assert rx.decode_errors == 1

    def test_an_hk_of_the_wrong_length_is_named_not_just_counted(self,
                                                                receiver):
        """An MCU running a different firmware version sends an HK this build
        cannot unpack. Everything else on the downlink still decodes, so the
        link reads healthy while every sensor row, valve bit and actuator
        readout stays blank - which on the bench looks like dead hardware.

        This is not hypothetical: on 2026-09-17 a carrier two commits behind
        sent 56 B against a ground that reads 64 B, and a whole session's HK
        was dropped without a word while the dispersion motor was being
        blamed. The receiver says which packet and which lengths, so the next
        one is a reflash and not an afternoon.
        """
        rx, send = receiver
        # An older *known* layout: decoded, because the packet only ever grew
        # by appending and those 56 bytes are all at the offsets this build
        # expects. Dropping them would leave the panel blank under a correct
        # diagnosis, which is the half-fix this test also guards against.
        # Distinctive values, so this proves the older layout's fields really
        # survive the decode rather than matching a dataclass default.
        short = hk.Housekeeping(state=hk.SeqState.MEASURE_1,
                                p_amb_pa=5_300).pack()[:hk.SIZE_PRE_CHAMBER]
        send(Frame(type=PacketType.HK, payload=short, seq=0).stamp().encode())
        assert _wait(lambda: rx.last_hk is not None)
        assert rx.hk_rejected == 0                 # decoded, not discarded
        assert rx.last_hk.state_name == "MEASURE_1"
        assert rx.last_hk.p_amb_pa == 5_300
        # ...and the fields that layout cannot carry are declared unsourced
        # rather than defaulted onto the panel as readings.
        assert rx.last_hk.error_flags & hk.HkErrors.BME280_CHM_FAIL
        assert rx.last_hk.chm_p_pa == 0
        # The operator is still told to reflash: the missing rows would
        # otherwise look like dead sensors.
        assert f"{len(short)} B" in rx.hk_reject_reason
        assert f"{hk.SIZE} B" in rx.hk_reject_reason

        # A length no layout ever had is a different thing: discarded, named,
        # and never half-read onto the panel.
        junk = short[:hk.SIZE_PRE_CHAMBER - 3]
        send(Frame(type=PacketType.HK, payload=junk, seq=1).stamp().encode())
        assert _wait(lambda: rx.hk_rejected == 1)
        assert rx.decode_errors == 1
        assert f"{len(junk)} B" in rx.hk_reject_reason

        # And it clears when the versions agree again, so a reflash mid
        # session does not leave a stale accusation on the panel.
        send(_hk_frame(2, state=hk.SeqState.ASCENT))
        assert _wait(lambda: rx.last_hk is not None
                     and rx.last_hk.state_name == "ASCENT")
        assert rx.hk_reject_reason is None

    def test_wire_bytes_counted_even_when_undecodable(self, receiver):
        """The traffic indicator's Down lane. Bytes are charged where the
        datagram lands, not after decode: a link delivering nothing but
        garbage spent the same budget and must not read as idle."""
        rx, send = receiver
        good = _hk_frame(0)
        send(b"\xba\xad\xf0\x0d")
        send(good)
        assert _wait(lambda: rx.rx_packets == 2)
        assert rx.rx_bytes == len(good) + 4
        assert rx.last_rx_time > 0

    def test_quicklook_and_event_state(self, receiver):
        rx, send = receiver
        ql = Frame(type=PacketType.QUICKLOOK,
                   payload=frames.pack_quicklook(1, 8, 100, [5, 6, 7]),
                   seq=0).stamp().encode()
        ev = Frame(type=PacketType.EVENT,
                   payload=frames.pack_event(7, 2, "seal fail"),
                   seq=0).stamp().encode()
        send(ql)
        send(ev)
        assert _wait(lambda: rx.gaps.received == 2)
        assert rx.quicklook[1]["counts"] == [5, 6, 7]
        assert rx.events[0]["text"] == "seal fail"


@pytest.fixture
def cmd_link():
    """Real FSW-PI command server + GSE commander, wired over localhost."""
    forwarded = []
    server = CommandServer("127.0.0.1", 0,
                           forward=lambda *a: forwarded.append(a),
                           state=CommandState())
    server.start()
    commander = Commander("127.0.0.1", server.port, timeout=2.0)
    yield commander, forwarded
    commander.close()
    server.stop()


class TestCommander:
    def test_ping_acked(self, cmd_link):
        commander, forwarded = cmd_link
        assert commander.ping() == AckResult.OK
        assert forwarded == [(Command.PING, 0, 0)]
        assert commander.last_rtt_s is not None

    def test_uplink_bytes_counted_per_direction(self, cmd_link):
        """The traffic indicator's Up lane. Commands out and ACKs back are
        counted apart: the ACK bytes are not downlink telemetry and must not
        be added to the lane that carries the 2 kbit/s budget."""
        commander, _ = cmd_link
        commander.ping()
        assert commander.tx_frames == 1
        assert commander.tx_bytes > 0
        assert commander.rx_bytes > 0
        assert commander.last_tx_time > 0 and commander.last_rx_time > 0
        before = commander.tx_bytes
        commander.ping()
        assert commander.tx_bytes == 2 * before   # same frame size twice
        assert commander.peer.endswith(f":{commander._port}")

    def test_interlocked_command_costs_no_uplink(self, cmd_link):
        """S.10 refuses locally, so the bytes never leave - and the indicator
        must not show traffic for a command that was never sent."""
        commander, _ = cmd_link
        with pytest.raises(InterlockError):
            commander.send(Command.START)
        assert commander.tx_bytes == 0 and commander.tx_frames == 0

    def test_ground_interlock_blocks_release(self, cmd_link):
        commander, forwarded = cmd_link
        assert not commander.flight_mode        # engaged by default (S.10)
        with pytest.raises(InterlockError):
            commander.release(1)
        with pytest.raises(InterlockError):
            commander.send(Command.START)
        assert forwarded == []                   # nothing left the laptop

    def test_flight_mode_release_does_arm_handshake(self, cmd_link):
        commander, forwarded = cmd_link
        commander.flight_mode = True
        assert commander.release(2) == AckResult.OK
        # Both halves reach the MCU: it keeps its own arm latch (core/link),
        # so an ARM the Pi swallowed would leave the RELEASE unarmed there.
        assert forwarded == [(Command.ARM, int(Command.RELEASE), 0),
                             (Command.RELEASE, 2, 0)]

    def test_hold_allowed_on_ground(self, cmd_link):
        commander, forwarded = cmd_link
        assert commander.send(Command.HOLD) == AckResult.OK
        assert forwarded == [(Command.HOLD, 0, 0)]

    def test_bad_valve_number(self, cmd_link):
        commander, _ = cmd_link
        commander.flight_mode = True
        with pytest.raises(ValueError):
            commander.release(3)

    def test_command_error_on_dead_link(self, cmd_link):
        commander, _ = cmd_link
        commander._sock.close()
        with pytest.raises(CommandError):
            commander.ping()

    def test_starts_disconnected_when_pi_unreachable(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                      # freed again - nothing listens on it
        commander = Commander("127.0.0.1", port, timeout=0.2)
        try:
            assert not commander.connected
            with pytest.raises(CommandError, match="not connected"):
                commander.ping()
        finally:
            commander.close()

    def test_transact_fails_fast_when_disconnected(self, cmd_link):
        commander, _ = cmd_link
        commander._disconnect()
        with pytest.raises(CommandError, match="not connected"):
            commander.ping()

    def test_reconnects_after_link_drop(self, cmd_link):
        """What the heartbeat does on its next tick after a dropped link -
        _transact() marks it down, _connect_once() (same call it retries
        with) brings the same server back within reach."""
        commander, _ = cmd_link
        assert commander.connected
        commander._sock.close()        # simulate the TCP link dying underfoot
        with pytest.raises(CommandError):
            commander.ping()
        assert not commander.connected
        commander._connect_once()
        assert commander.connected
        assert commander.ping() == AckResult.OK


class TestManualActuators:
    """G-03 operator drives of the dispersion hardware (M-07), against the
    real Pi command server."""

    def test_membrane_drive_and_stop_need_no_arm_or_flight_mode(self, cmd_link):
        commander, forwarded = cmd_link
        assert not commander.flight_mode      # bench: the interlock is on
        assert commander.membrane(60) == AckResult.OK
        assert commander.membrane(0) == AckResult.OK
        assert forwarded == [(Command.MEMBRANE, 60, 0),
                             (Command.MEMBRANE, 0, 0)]

    def test_disperse_asks_for_exactly_one_pulse(self, cmd_link):
        commander, forwarded = cmd_link
        assert commander.disperse() == AckResult.OK
        assert forwarded == [(Command.DISPERSE, 1, 0)]

    def test_motor_run_and_stop_are_the_disperse_keys(self, cmd_link):
        """Start/Stop on the panel: the same command with the key naming the
        request (2 run, 0 stop) - never a speed, which is SET_PARAM."""
        commander, forwarded = cmd_link
        assert commander.disperse_run() == AckResult.OK
        assert commander.disperse_stop() == AckResult.OK
        assert forwarded == [(Command.DISPERSE, int(DisperseKey.RUN), 0),
                             (Command.DISPERSE, int(DisperseKey.STOP), 0)]
        assert (DisperseKey.STOP, DisperseKey.PULSE, DisperseKey.RUN) \
            == (0, 1, 2)

    def test_duty_out_of_range_never_leaves_the_laptop(self, cmd_link):
        commander, forwarded = cmd_link
        for bad in (-1, 101):
            with pytest.raises(ValueError):
                commander.membrane(bad)
        assert forwarded == []

    def test_mcu_refusal_is_reported_not_swallowed(self):
        """The drives are refused in TERMINATION/SAFE. The MCU decides that,
        so the panel must show its verdict rather than a bare OK."""
        server = CommandServer("127.0.0.1", 0,
                               forward=lambda *a: AckResult.REJECTED,
                               state=CommandState())
        server.start()
        commander = Commander("127.0.0.1", server.port, timeout=2.0)
        try:
            assert commander.membrane(60) == AckResult.REJECTED
            assert commander.disperse() == AckResult.REJECTED
        finally:
            commander.close()
            server.stop()


class TestSessionLog:
    def test_hk_events_quicklook_logged_and_exported(self, tmp_path):
        log = SessionLog(str(tmp_path), stamp="test")
        seq = SeqCounter()
        f = Frame(type=PacketType.HK, seq=seq.next()).stamp()
        log.log_hk(f, hk.Housekeeping(state=2, p_amb_pa=30_000))
        log.log_event(Frame(type=PacketType.EVENT, seq=seq.next()).stamp(),
                      {"code": 1, "severity": 0, "text": "hello"})
        log.log_quicklook(Frame(type=PacketType.QUICKLOOK,
                                seq=seq.next()).stamp(),
                          {"channel": 0, "bin": 8, "exposure_ms": 100,
                           "counts": [1, 2, 3]})
        out = tmp_path / "summary.json"
        log.export_summary(str(out))
        log.close()

        hk_lines = (tmp_path / "session_test_hk.csv").read_text().splitlines()
        assert len(hk_lines) == 2 and "state_name" in hk_lines[0]
        assert "ASCENT" in hk_lines[1]
        ev_lines = (tmp_path / "session_test_events.csv").read_text().splitlines()
        assert "hello" in ev_lines[1]
        ql = json.loads((tmp_path / "session_test_quicklook.jsonl")
                        .read_text().splitlines()[0])
        assert ql["counts"] == [1, 2, 3]
        summary = json.loads(out.read_text())
        assert summary["packets"] == {"hk": 1, "events": 1, "quicklook": 1}
