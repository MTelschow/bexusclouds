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
    """Far end of the UART pipe: emits HK at 10 Hz, records commands."""

    def __init__(self, transport):
        self._t = transport
        self._seq = SeqCounter()
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

    def _emit(self):
        while not self._stop.is_set():
            h = hk.Housekeeping(state=hk.SeqState.STANDBY, p_amb_pa=101_000,
                                uptime_s=int(time.time()) & 0xFFFF)
            f = Frame(type=PacketType.HK, payload=h.pack(),
                      seq=self._seq.next()).stamp()
            self._t.write(cobs.encode(f.encode()) + b"\x00")
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
                    self.commands.append(frames.unpack_cmd(frame.payload))
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

        # 4. ground command path: PING then ARM+RELEASE reach the MCU
        assert commander.ping() == AckResult.OK
        assert commander.release(1) == AckResult.OK
        assert _wait(lambda: (Command.RELEASE, 1, 0) in mcu.commands)
        assert (Command.PING, 0, 0) in mcu.commands

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

    def test_session_log_from_live_downlink(self, stack):
        app, _mcu, ground_rx, _commander, tmp_path = stack
        session = SessionLog(str(tmp_path / "gse"), stamp="e2e")
        ground_rx._cb["hk"] = session.log_hk
        assert _wait(lambda: session.counts["hk"] >= 3)
        session.close()
        lines = (tmp_path / "gse" / "session_e2e_hk.csv").read_text() \
            .splitlines()
        assert len(lines) >= 4 and "STANDBY" in lines[1]
