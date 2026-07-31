"""FSW-PI command server: arm/execute, heartbeat, framing on TCP (S.8)."""
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
        self.state = CommandState()
        self.server = CommandServer(
            "127.0.0.1", 0, forward=self._fwd, state=self.state,
            on_status_req=self._status)
        self.server.start()
        self.sock = socket.create_connection(
            ("127.0.0.1", self.server.port), timeout=2.0)
        self.sock.settimeout(2.0)
        self._seq = SeqCounter()

    def _fwd(self, cmd, key, value):
        self.forwarded.append((cmd, key, value))

    def _status(self):
        self.status_reqs += 1

    def send(self, cmd, key=0, value=0):
        f = Frame(type=PacketType.CMD, payload=frames.pack_cmd(cmd, key, value),
                  seq=self._seq.next()).stamp()
        self.sock.sendall(f.encode())
        return self.recv_ack()

    def recv_ack(self):
        buf = b""
        while True:
            buf += self.sock.recv(4096)
            frame, used = _try_parse(buf)
            if frame is not None:
                return frames.unpack_ack(frame.payload)

    def close(self):
        self.sock.close()
        self.server.stop()


@pytest.fixture
def harness():
    h = Harness()
    yield h
    h.close()


class TestArmExecute:
    def test_release_without_arm_refused(self, harness):
        _, cmd, result = harness.send(Command.RELEASE, key=1)
        assert cmd == Command.RELEASE and result == AckResult.NOT_ARMED
        assert harness.forwarded == []           # never reaches the MCU

    def test_armed_release_forwarded(self, harness):
        _, _, r = harness.send(Command.ARM, key=int(Command.RELEASE))
        assert r == AckResult.OK
        _, _, r = harness.send(Command.RELEASE, key=2)
        assert r == AckResult.OK
        assert harness.forwarded == [(Command.RELEASE, 2, 0)]

    def test_arm_is_one_shot(self, harness):
        harness.send(Command.ARM, key=int(Command.RELEASE))
        harness.send(Command.RELEASE, key=1)
        _, _, r = harness.send(Command.RELEASE, key=2)   # second without arm
        assert r == AckResult.NOT_ARMED
        assert len(harness.forwarded) == 1

    def test_arm_window_expires(self, harness):
        harness.state.arm(int(Command.RELEASE), now=1000.0)
        assert not harness.state.consume_arm(int(Command.RELEASE),
                                             now=1000.0 + 10.1)

    def test_arm_of_non_actuator_rejected(self, harness):
        _, _, r = harness.send(Command.ARM, key=int(Command.HOLD))
        assert r == AckResult.INVALID


class TestPlainCommands:
    def test_ping_heartbeat_and_forward(self, harness):
        before = harness.state.last_heartbeat
        _, cmd, r = harness.send(Command.PING)
        assert (cmd, r) == (Command.PING, AckResult.OK)
        assert harness.state.last_heartbeat > before
        assert harness.forwarded == [(Command.PING, 0, 0)]

    def test_hold_abort_forwarded_without_arm(self, harness):
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
