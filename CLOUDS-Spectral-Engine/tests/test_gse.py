"""GSE: receiver decode/gaps, commander interlock + arm handshake, logging.

The commander is tested against the real FSW-PI CommandServer - the actual
protocol partner - so this doubles as an interop test.
"""
import json
import socket
import time

import pytest

from clouds_link import frames, hk
from clouds_link.commands import Command
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
        assert forwarded == [(Command.RELEASE, 2, 0)]   # ARM handled Pi-side

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
