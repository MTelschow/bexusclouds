"""End-to-end (feature X-04, bench version of T-10): fake MCU <-> real
FSW-PI app <-> real GSE, over the real transports (pipe UART, UDP, TCP).

Verifies the full chain: MCU housekeeping relayed byte-identical to the
GSE; mock spectrometer frames stored with valid CRCs and quick-looked to
the GSE; a ground ARM+RELEASE traverses GSE -> Pi -> MCU; timesync reaches
the MCU (S.4).
"""
import glob
import threading
import time

import pytest

from clouds_link import cobs, frames, hk
from clouds_link.commands import Command
from clouds_link.frames import AckResult, Frame, PacketType, SeqCounter
from clouds_fsw.config import FswConfig
from clouds_fsw.main import FlightApp
from clouds_fsw.storage import read_spectra
from clouds_fsw.uart_link import PipeTransport
from clouds_gse.commander import Commander
from clouds_gse.receiver import Receiver
from clouds_gse.session_log import SessionLog


class FakeMcu:
    """Far end of the UART pipe: emits HK at 10 Hz, records commands, and
    answers each one with an ACK the way the RP2350 does (its own verdict,
    naming the command's sequence number). ``state`` is what its housekeeping
    reports, which is what the Pi's ground interlock reads."""

    def __init__(self, transport, state=hk.SeqState.STANDBY):
        self._t = transport
        self._seq = SeqCounter()
        self._ack_seq = SeqCounter()
        self.state = state
        self.ack_result = AckResult.OK
        self.commands = []
        self.timesyncs = []
        self._stop = threading.Event()
        self._buf = bytearray()
        self._threads = [threading.Thread(target=f, daemon=True)
                         for f in (self._emit, self._listen)]

    def start(self):
        for t in self._threads:
            t.start()

    def stop(self):
        self._stop.set()

    def _send(self, frame):
        self._t.write(cobs.encode(frame.encode()) + b"\x00")

    def _emit(self):
        while not self._stop.is_set():
            h = hk.Housekeeping(state=self.state, p_amb_pa=101_000,
                                uptime_s=int(time.time()) & 0xFFFF)
            self._send(Frame(type=PacketType.HK, payload=h.pack(),
                             seq=self._seq.next()).stamp())
            time.sleep(0.1)

    def _listen(self):
        while not self._stop.is_set():
            chunk = self._t.read(timeout=0.2)
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
                if frame.type == PacketType.CMD:
                    cmd, key, value = frames.unpack_cmd(frame.payload)
                    self.commands.append((cmd, key, value))
                    self._send(Frame(type=PacketType.ACK,
                                     payload=frames.pack_ack(frame.seq, cmd,
                                                             self.ack_result),
                                     seq=self._ack_seq.next()).stamp())
                elif frame.type == PacketType.TIMESYNC:
                    self.timesyncs.append(
                        frames.unpack_timesync(frame.payload))


def _wait(predicate, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def stack(tmp_path):
    """Full stack on localhost with accelerated timers."""
    ground_rx = Receiver(bind="127.0.0.1", port=0)
    ground_rx.start()

    near, far = PipeTransport.pair()
    mcu = FakeMcu(far)

    cfg = FswConfig(ground_host="127.0.0.1", ground_port=ground_rx.port,
                    cmd_bind="127.0.0.1", cmd_port=0,
                    data_dir=str(tmp_path / "data"), rotate_s=3600,
                    sample_interval_s=0.05, quicklook_interval_s=0.3,
                    pistatus_interval_s=0.3, timesync_interval_s=0.3,
                    # accelerated link timers: 10 s of silence and a 1 s ACK
                    # wait are flight numbers, and would idle the suite
                    mcu_silent_alarm_s=1.0, mcu_ack_timeout_s=0.5,
                    mock=True)
    app = FlightApp(cfg, transport=near)
    app_thread = threading.Thread(target=app.run, daemon=True)

    mcu.start()
    app_thread.start()
    assert _wait(lambda: app.cmd_server.port != 0)

    commander = Commander("127.0.0.1", app.cmd_server.port,
                          flight_mode=True, timeout=3.0)

    yield app, mcu, ground_rx, commander, tmp_path

    commander.close()
    app.stop()
    app_thread.join(timeout=5.0)
    mcu.stop()
    ground_rx.stop()


class TestEndToEnd:
    def test_full_chain(self, stack):
        app, mcu, ground_rx, commander, tmp_path = stack

        # 1. MCU HK reaches the ground receiver, decoded + gap-tracked
        assert _wait(lambda: ground_rx.last_hk is not None)
        assert ground_rx.last_hk.state_name == "STANDBY"
        assert ground_rx.last_hk.p_amb_pa == 101_000

        # 2. mock spectrometer -> quick-look spectra on the ground
        assert _wait(lambda: len(ground_rx.quicklook) == 2)
        ql = ground_rx.quicklook[0]
        assert ql["bin"] == 8 and len(ql["counts"]) > 0

        # 3. Pi status telemetry present and healthy
        assert _wait(lambda: ground_rx.last_pistatus is not None)
        assert _wait(lambda: ground_rx.last_pistatus["spectro_ok"])
        assert ground_rx.last_pistatus["uart_ok"]

        # 4. ground command path. A release on the pad is refused by the Pi's
        # own interlock (S.10) - the MCU is reporting STANDBY.
        assert commander.ping() == AckResult.OK
        assert (Command.PING, 0, 0) in mcu.commands
        assert commander.release(1) == AckResult.INTERLOCK
        assert (Command.RELEASE, 1, 0) not in mcu.commands

        # ...and goes through once the MCU says it is flying. ARM reaches the
        # MCU too, so its own arm latch is in step with the Pi's.
        mcu.state = hk.SeqState.ASCENT
        assert _wait(lambda: app.mcu.in_flight)
        assert commander.release(1) == AckResult.OK
        assert _wait(lambda: (Command.RELEASE, 1, 0) in mcu.commands)
        assert (Command.ARM, int(Command.RELEASE), 0) in mcu.commands

        # 5. timesync flows to the MCU (S.4)
        assert _wait(lambda: len(mcu.timesyncs) >= 2)
        assert abs(mcu.timesyncs[-1] - time.time()) < 5.0

        # 6. shutdown, then verify stored spectra integrity (O.3, S.5)
        app.stop()
        assert _wait(lambda: app.stop_event.is_set())
        time.sleep(0.3)
        app.shutdown()
        files = glob.glob(str(tmp_path / "data" / "spectra_*.csb"))
        assert files
        recs = [r for p in files for r in read_spectra(p)]
        assert len(recs) >= 5
        t, exp_us, _flags, counts = recs[0]
        assert len(counts) == 2048 and exp_us == 100_000
        assert abs(t - time.time()) < 60.0

        # 7. comms log recorded uplink traffic
        logs = glob.glob(str(tmp_path / "data" / "comms_*.log"))
        content = "".join(open(p, encoding="utf-8").read() for p in logs)
        assert "cmd=RELEASE" in content

    def test_ground_hears_the_mcu_verdict_not_the_pi_optimism(self, stack):
        """A command the MCU refuses must not reach ground as OK (S.8)."""
        app, mcu, _rx, commander, _tmp = stack
        mcu.state = hk.SeqState.ASCENT
        assert _wait(lambda: app.mcu.in_flight)

        mcu.ack_result = AckResult.REJECTED
        assert commander.send(Command.HOLD) == AckResult.REJECTED

        mcu.ack_result = AckResult.OK
        assert commander.send(Command.HOLD) == AckResult.OK

    def test_silent_mcu_rejects_commands_and_keeps_the_heartbeat(self, stack):
        """The Pi answers its own heartbeat while reporting the MCU gone."""
        app, mcu, ground_rx, commander, _tmp = stack
        assert _wait(lambda: app.mcu.alive())
        mcu.stop()
        assert _wait(lambda: not app.mcu.alive(), timeout=15.0)

        assert commander.send(Command.HOLD) == AckResult.REJECTED  # no ACK
        assert commander.ping() == AckResult.OK                    # Pi is up
        assert _wait(lambda: ground_rx.last_pistatus is not None
                     and not ground_rx.last_pistatus["uart_ok"])

    def test_session_log_from_live_downlink(self, stack):
        app, _mcu, ground_rx, _commander, tmp_path = stack
        session = SessionLog(str(tmp_path / "gse"), stamp="e2e")
        ground_rx._cb["hk"] = session.log_hk
        assert _wait(lambda: session.counts["hk"] >= 3)
        session.close()
        lines = (tmp_path / "gse" / "session_e2e_hk.csv").read_text() \
            .splitlines()
        assert len(lines) >= 4 and "STANDBY" in lines[1]
