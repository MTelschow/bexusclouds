"""FSW-PI side of the RP2350 link (`clouds_fsw.mcu_link`).

What is being guarded: the Pi must never turn "I wrote to the UART" into
"the MCU did it". Every command in MCU_CONFIRMED is answered by the RP2350
with its own verdict, and this module correlates that ACK to the command's
sequence number, times out honestly, and keeps the housekeeping copy the
ground interlock reads (S.8, S.10).
"""
import threading
import time

import pytest

from clouds_link import cobs, frames, hk
from clouds_link.commands import Command
from clouds_link.frames import AckResult, Frame, PacketType
from clouds_fsw.mcu_link import McuLink
from clouds_fsw.uart_link import PipeTransport


class FarEnd:
    """The MCU end of the pipe: reads frames, replies with ACKs on demand."""

    def __init__(self, transport):
        self._t = transport
        self._buf = bytearray()
        self._seq = frames.SeqCounter()
        self.frames = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._read, daemon=True)
        self.auto_ack = None          # AckResult to answer commands with
        self._thread.start()

    def stop(self):
        self._stop.set()

    def send(self, frame):
        self._t.write(cobs.encode(frame.encode()) + b"\x00")

    def ack(self, cmd_seq, cmd=0, result=AckResult.OK):
        self.send(Frame(type=PacketType.ACK,
                        payload=frames.pack_ack(cmd_seq, cmd, result),
                        seq=self._seq.next()).stamp())

    def send_hk(self, state, **kw):
        h = hk.Housekeeping(state=state, **kw)
        self.send(Frame(type=PacketType.HK, payload=h.pack(),
                        seq=self._seq.next()).stamp())

    def _read(self):
        while not self._stop.is_set():
            chunk = self._t.read(timeout=0.1)
            if not chunk:
                continue
            self._buf.extend(chunk)
            while b"\x00" in self._buf:
                raw, _, rest = self._buf.partition(b"\x00")
                self._buf = bytearray(rest)
                if not raw:
                    continue
                try:
                    frame = frames.decode(cobs.decode(bytes(raw)))
                except (cobs.CobsError, frames.FrameError):
                    continue
                self.frames.append(frame)
                if self.auto_ack is not None and frame.type == PacketType.CMD:
                    cmd, _key, _v = frames.unpack_cmd(frame.payload)
                    self.ack(frame.seq, cmd, self.auto_ack)


def _wait(predicate, timeout=2.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def link():
    near, far = PipeTransport.pair()
    received = []
    mcu = McuLink(near, on_frame=received.append, ack_timeout_s=0.3,
                  silent_s=0.5)
    mcu.start()
    end = FarEnd(far)
    yield mcu, end, received
    end.stop()
    mcu.stop()


class TestCommandAcks:
    def test_verdict_comes_from_the_mcu(self, link):
        mcu, end, _ = link
        end.auto_ack = AckResult.NOT_ARMED
        assert mcu.send_command(Command.RELEASE, key=1) == AckResult.NOT_ARMED
        end.auto_ack = AckResult.OK
        assert mcu.send_command(Command.HOLD) == AckResult.OK

    def test_missing_ack_is_a_rejection(self, link):
        mcu, end, _ = link
        t0 = time.time()
        assert mcu.send_command(Command.HOLD) == AckResult.REJECTED
        assert 0.3 <= time.time() - t0 < 2.0       # waited, then gave up
        assert mcu.acks_missed == 1
        assert end.frames and end.frames[0].type == PacketType.CMD

    def test_ack_for_another_command_does_not_release_the_waiter(self, link):
        mcu, end, _ = link
        end.ack(cmd_seq=9999)                      # unsolicited / stale
        assert mcu.send_command(Command.HOLD) == AckResult.REJECTED

    def test_acks_are_matched_by_sequence_number(self, link):
        mcu, end, _ = link
        results = {}

        def fire(name):
            results[name] = mcu.send_command(Command.HOLD)

        threads = [threading.Thread(target=fire, args=(n,)) for n in "ab"]
        for t in threads:
            t.start()
        assert _wait(lambda: len(end.frames) == 2)
        # answer them in reverse order, with distinct results
        end.ack(end.frames[1].seq, Command.HOLD, AckResult.INVALID)
        end.ack(end.frames[0].seq, Command.HOLD, AckResult.OK)
        for t in threads:
            t.join(timeout=2.0)
        assert sorted(results.values()) == [AckResult.OK, AckResult.INVALID]

    def test_unconfirmed_send_does_not_wait(self, link):
        mcu, end, _ = link
        t0 = time.time()
        assert mcu.send_command(Command.PING, await_ack=False) == AckResult.OK
        assert time.time() - t0 < 0.2               # no ACK, no delay
        assert _wait(lambda: len(end.frames) == 1)

    def test_stop_releases_a_blocked_caller(self):
        near, far = PipeTransport.pair()
        mcu = McuLink(near, ack_timeout_s=30.0)
        mcu.start()
        result = []
        t = threading.Thread(target=lambda: result.append(
            mcu.send_command(Command.HOLD)), daemon=True)
        t.start()
        time.sleep(0.1)
        mcu.stop()                                  # must not hang for 30 s
        t.join(timeout=3.0)
        assert result == [AckResult.REJECTED]

    def test_heartbeat_acks_are_not_logged_as_unsolicited(self, link):
        """The MCU acks every command, heartbeat included, so those ACKs
        arrive with no waiter - one log line per heartbeat would bury the
        comms log and hide the late ACK that does mean something."""
        near, far = PipeTransport.pair()
        logged = []
        mcu = McuLink(near, ack_timeout_s=0.3,
                      log=lambda where, msg: logged.append(msg))
        mcu.start()
        end = FarEnd(far)
        end.auto_ack = AckResult.OK
        try:
            mcu.send_command(Command.PING, await_ack=False)
            assert _wait(lambda: end.frames)
            time.sleep(0.2)
            assert not any("unsolicited" in m for m in logged)

            end.auto_ack = None                  # a real late/stale ACK
            end.ack(cmd_seq=4242)
            assert _wait(lambda: any("unsolicited" in m for m in logged))
        finally:
            end.stop()
            mcu.stop()

    def test_acks_are_not_relayed_to_the_app(self, link):
        mcu, end, received = link
        end.auto_ack = AckResult.OK
        mcu.send_command(Command.HOLD)
        end.send_hk(hk.SeqState.STANDBY)
        assert _wait(lambda: received)
        # the ACK answered this class's own command; only real telemetry goes on
        assert [f.type for f in received] == [PacketType.HK]


class TestHousekeepingCache:
    def test_hk_is_decoded_and_relayed(self, link):
        mcu, end, received = link
        end.send_hk(hk.SeqState.MEASURE_1, uptime_s=77)
        assert _wait(lambda: mcu.last_hk is not None)
        assert mcu.last_hk.uptime_s == 77
        assert len(received) == 1                   # relay still sees it

    def test_short_hk_payload_does_not_break_the_relay(self, link):
        mcu, end, received = link
        end.send(Frame(type=PacketType.HK, payload=b"\x01\x02").stamp())
        assert _wait(lambda: received)
        assert mcu.last_hk is None                  # not decodable, not cached


class TestInFlight:
    """What the ground interlock reads. Every uncertainty means "on ground"."""

    def test_no_housekeeping_is_not_in_flight(self, link):
        mcu, _end, _ = link
        assert not mcu.in_flight

    @pytest.mark.parametrize("state,expected", [
        (hk.SeqState.INIT, False),
        (hk.SeqState.STANDBY, False),
        (hk.SeqState.ASCENT, True),
        (hk.SeqState.SEAL, True),
        (hk.SeqState.MEASURE_2, True),
        (hk.SeqState.TERMINATION, False),
        (hk.SeqState.SAFE, False),
    ])
    def test_state_decides(self, link, state, expected):
        mcu, end, _ = link
        end.send_hk(state)
        assert _wait(lambda: mcu.last_hk is not None
                     and mcu.last_hk.state == state)
        assert mcu.in_flight is expected

    def test_stale_housekeeping_is_not_in_flight(self, link):
        mcu, end, _ = link
        end.send_hk(hk.SeqState.ASCENT)
        assert _wait(lambda: mcu.in_flight)
        time.sleep(0.6)                             # silent_s = 0.5
        assert not mcu.in_flight


class TestTimesync:
    def test_timesync_carries_the_pi_clock(self, link):
        mcu, end, _ = link
        mcu.send_timesync(1_750_000_000.5)
        assert _wait(lambda: end.frames)
        f = end.frames[0]
        assert f.type == PacketType.TIMESYNC
        assert frames.unpack_timesync(f.payload) == pytest.approx(
            1_750_000_000.5, abs=0.002)

    def test_liveness_follows_received_frames(self, link):
        mcu, end, _ = link
        assert not mcu.alive()
        end.send_hk(hk.SeqState.STANDBY)
        assert _wait(mcu.alive)
        time.sleep(0.6)
        assert not mcu.alive()                      # silent_s = 0.5
