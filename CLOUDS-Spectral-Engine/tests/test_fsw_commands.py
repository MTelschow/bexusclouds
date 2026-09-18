"""FSW-PI command server: forwarding, heartbeat, framing on TCP.

The arm/execute rule and the ground interlock this file used to police are
gone (2026-09-18): every command the Pi can parse is forwarded and answered
with the MCU's own verdict.
"""
import socket
import time

import pytest

from clouds_link import frames
from clouds_link.commands import Command
from clouds_link.frames import AckResult, Frame, PacketType, SeqCounter
from clouds_link.frames import try_parse_stream as _try_parse
from clouds_fsw.command_server import CommandServer, CommandState


class Harness:
    def __init__(self):
        self.forwarded = []
        self.status_reqs = 0
        self.forward_result = None      # None = "sent, nothing to report"
        self.state = CommandState()
        self.server = CommandServer(
            "127.0.0.1", 0, forward=self._fwd, state=self.state,
            on_status_req=self._status)
        self.server.start()
        self.sock = socket.create_connection(
            ("127.0.0.1", self.server.port), timeout=2.0)
        self.sock.settimeout(2.0)
        self._seq = SeqCounter()
        self._buf = b""   # survives across recv_ack calls, see below

    def _fwd(self, cmd, key, value):
        self.forwarded.append((cmd, key, value))
        return self.forward_result

    def _status(self):
        self.status_reqs += 1

    def send(self, cmd, key=0, value=0):
        f = Frame(type=PacketType.CMD, payload=frames.pack_cmd(cmd, key, value),
                  seq=self._seq.next()).stamp()
        self.sock.sendall(f.encode())
        return self.recv_ack()

    def recv_ack(self):
        """One ACK, keeping any surplus bytes for the next call.

        The buffer must outlive the call and `used` must be honoured: the
        server is free to put two ACKs in one TCP segment, and an earlier
        version of this helper parsed the first, dropped the rest and then
        blocked forever waiting for an ACK it had already thrown away. That
        made TestStreamFraming flaky exactly where it coalesced.
        """
        while True:
            frame, used = _try_parse(self._buf)
            if frame is not None:
                self._buf = self._buf[used:]
                return frames.unpack_ack(frame.payload)
            chunk = self.sock.recv(4096)
            if not chunk:
                raise AssertionError("server closed the connection mid-ACK")
            self._buf += chunk

    def close(self):
        self.sock.close()
        self.server.stop()


@pytest.fixture
def harness():
    h = Harness()
    yield h
    h.close()


class TestNothingIsGated:
    """The arm/execute latch and the ground interlock both lived here and are
    gone: while ground is connected every command is forwarded as sent."""

    def test_release_needs_no_arm(self, harness):
        _, cmd, result = harness.send(Command.RELEASE, key=1)
        assert (cmd, result) == (Command.RELEASE, AckResult.OK)
        assert harness.forwarded == [(Command.RELEASE, 1, 0)]

    def test_every_command_reaches_the_mcu(self, harness):
        for c in (Command.START, Command.HOLD, Command.RESUME, Command.ABORT,
                  Command.RELEASE, Command.MEMBRANE, Command.DISPERSE):
            assert harness.send(c)[2] == AckResult.OK
        assert [f[0] for f in harness.forwarded] == [
            Command.START, Command.HOLD, Command.RESUME, Command.ABORT,
            Command.RELEASE, Command.MEMBRANE, Command.DISPERSE]

    def test_a_stale_arm_is_forwarded_and_harmless(self, harness):
        """An older ground station still sends ARM. It is passed on like
        anything else and the MCU answers it OK."""
        assert harness.send(Command.ARM,
                            key=int(Command.RELEASE))[2] == AckResult.OK
        assert harness.forwarded == [(Command.ARM, int(Command.RELEASE), 0)]


class TestMcuVerdict:
    """The ACK a client gets carries what the MCU said, not the Pi's
    optimism: ``forward`` returns the RP2350's AckResult."""

    def test_forward_result_reaches_the_client(self, harness):
        harness.forward_result = AckResult.REJECTED
        assert harness.send(Command.HOLD)[2] == AckResult.REJECTED
        harness.forward_result = AckResult.NOT_ARMED
        assert harness.send(Command.ABORT)[2] == AckResult.NOT_ARMED

    def test_none_means_nothing_to_report(self, harness):
        harness.forward_result = None
        assert harness.send(Command.HOLD)[2] == AckResult.OK

    def test_ping_is_answered_even_when_the_mcu_is_gone(self, harness):
        def boom(*_):
            raise OSError("uart gone")
        harness.server._forward = boom
        # PING is addressed to the Pi; a silent MCU is
        # reported through PISTATUS.uart_ok, not by failing the heartbeat.
        assert harness.send(Command.PING)[2] == AckResult.OK


class TestPlainCommands:
    def test_ping_heartbeat_and_forward(self, harness):
        before = harness.state.last_heartbeat
        _, cmd, r = harness.send(Command.PING)
        assert (cmd, r) == (Command.PING, AckResult.OK)
        assert harness.state.last_heartbeat > before
        assert harness.forwarded == [(Command.PING, 0, 0)]

    def test_hold_abort_forwarded(self, harness):
        for c in (Command.HOLD, Command.RESUME, Command.ABORT):
            _, _, r = harness.send(c)
            assert r == AckResult.OK
        assert [f[0] for f in harness.forwarded] == \
            [Command.HOLD, Command.RESUME, Command.ABORT]

    def test_status_req_triggers_pistatus(self, harness):
        _, _, r = harness.send(Command.STATUS_REQ)
        assert r == AckResult.OK
        assert harness.status_reqs == 1

    def test_set_param_forwarded(self, harness):
        _, _, r = harness.send(Command.SET_PARAM, key=3, value=5500)
        assert r == AckResult.OK
        assert harness.forwarded == [(Command.SET_PARAM, 3, 5500)]

    def test_forward_failure_rejected(self, harness):
        def boom(*_):
            raise OSError("uart gone")
        harness.server._forward = boom
        _, _, r = harness.send(Command.HOLD)
        assert r == AckResult.REJECTED


class TestStreamFraming:
    def test_two_frames_in_one_segment(self, harness):
        f1 = Frame(type=PacketType.CMD, payload=frames.pack_cmd(Command.PING),
                   seq=1).stamp()
        f2 = Frame(type=PacketType.CMD, payload=frames.pack_cmd(Command.HOLD),
                   seq=2).stamp()
        harness.sock.sendall(f1.encode() + f2.encode())
        acks = [harness.recv_ack(), harness.recv_ack()]
        assert [a[1] for a in acks] == [Command.PING, Command.HOLD]

    def test_garbage_before_frame_resyncs(self, harness):
        f = Frame(type=PacketType.CMD, payload=frames.pack_cmd(Command.PING),
                  seq=9).stamp()
        harness.sock.sendall(b"\xde\xad\xbe\xef" + f.encode())
        assert harness.recv_ack()[1] == Command.PING

    def test_try_parse_split_delivery(self):
        f = Frame(type=PacketType.CMD, payload=frames.pack_cmd(Command.PING),
                  seq=5).stamp()
        raw = f.encode()
        assert _try_parse(raw[:10]) == (None, 0)         # header incomplete
        assert _try_parse(raw[:-1]) == (None, 0)         # body incomplete
        frame, used = _try_parse(raw + b"extra")
        assert used == len(raw) and frame.seq == 5

    def test_malformed_payload_acked_invalid(self, harness):
        f = Frame(type=PacketType.CMD, payload=b"\x01", seq=3).stamp()
        harness.sock.sendall(f.encode())
        _, _, r = harness.recv_ack()
        assert r == AckResult.INVALID
