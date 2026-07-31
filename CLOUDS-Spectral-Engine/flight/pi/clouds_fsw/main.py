"""FSW-PI entry point: wires acquisition, storage, telemetry, uplink, UART.

Run on the Pi:      python -m clouds_fsw.main --config /etc/clouds/fsw.json
Bench, no hardware: python -m clouds_fsw.main --mock
Bench, real spectrometer but no MCU wired: python -m clouds_fsw.main --no-uart
Bench + live panel at the same time:       ... --no-uart --bench-stream
(from flight/pi/, with clouds_link + spectro on PYTHONPATH - see README)

Design rule (S.7): nothing here gates the RP2350 sequence. Every component
degrades independently: spectrometer loss -> comms keep running (P-10); MCU
silence -> downlink alarm, no takeover; ground silence -> nothing (the MCU
handles autonomy).
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import threading
import time

from clouds_link import frames
from clouds_link.frames import EventSeverity, PacketType
from spectro.calibration import Calibration
from spectro.driver import open_driver

from .bench_stream import BenchStream
from .command_server import CommandServer, CommandState
from .config import FswConfig
from .spectro_source import SpectroSource
from .storage import CommLog, FrameStore
from .telemetry import Downlink, QuicklookSender
from .uart_link import PipeTransport, SerialTransport, UartLink
from .watchdog import SystemdWatchdog

_EV_MCU_SILENT = 0x10
_EV_SPECTRO = 0x11


class FlightApp:
    def __init__(self, cfg: FswConfig, transport=None, bench_port=None):
        self.cfg = cfg
        self.cal = Calibration.load(cfg.calibration_path)
        self.stop_event = threading.Event()

        self.store = FrameStore(cfg.data_dir, cfg.rotate_s, cfg.flush_every)
        self.comm_log = CommLog(cfg.data_dir, cfg.rotate_s)
        self.down = Downlink(cfg.ground_host, cfg.ground_port,
                             cfg.budget_kbit_s)
        self.quicklook = QuicklookSender(self.down, self.cal,
                                         cfg.quicklook_bin,
                                         cfg.quicklook_interval_s)

        if transport is None:
            transport = SerialTransport(cfg.uart_port, cfg.uart_baud)
        self.uart = UartLink(transport, on_frame=self._on_mcu_frame)
        self._uart_seq = frames.SeqCounter()

        self.cmd_state = CommandState()
        self.cmd_server = CommandServer(
            cfg.cmd_bind, cfg.cmd_port, forward=self._forward_to_mcu,
            state=self.cmd_state, on_status_req=self._send_pistatus,
            log=self.comm_log.log)

        self.source = SpectroSource(
            driver_factory=lambda: open_driver(mock=cfg.mock,
                                               kind=cfg.spectro_kind),
            calibration=self.cal, on_frame=self._on_spectrum,
            interval_s=cfg.sample_interval_s, exposure_us=cfg.exposure_us,
            auto_exposure=cfg.auto_exposure, reconnect_s=cfg.reconnect_s,
            on_status=self._on_spectro_status)

        # Optional bench frame stream (off in flight). Serves the frames this
        # app already acquired, so the live panel and the GSE dashboard can run
        # at the same time on one detector - see bench_stream.py.
        self.bench = None
        if bench_port is not None:
            self.bench = BenchStream(
                info_provider=lambda: self.source.info,
                exposure_setter=self.source.request_exposure_us,
                log=self.comm_log.log, port=bench_port,
                flight_exposure_us=cfg.exposure_us)

        self.watchdog = SystemdWatchdog()
        self._latest_frame = None
        self._latest_lock = threading.Lock()
        self._mcu_alarmed = False
        self._shutdown_done = threading.Event()

    # -- data paths ----------------------------------------------------------

    def _on_spectrum(self, t, counts, exposure_us, flags) -> None:
        self.store.write(t, counts, exposure_us, flags)   # storage first, O.3
        with self._latest_lock:
            self._latest_frame = (t, counts, exposure_us)
        if self.bench is not None:                        # bench mirror, O.3 first
            self.bench.publish(counts, exposure_us)

    def _on_mcu_frame(self, frame: frames.Frame) -> None:
        if frame.type in (PacketType.HK, PacketType.EVENT):
            self.down.relay(frame.encode())               # byte-identical
        if frame.type == PacketType.EVENT:
            ev = frames.unpack_event(frame.payload)
            self.comm_log.log("mcu", f"event {ev['code']}: {ev['text']}")

    def _forward_to_mcu(self, cmd: int, key: int, value: int) -> None:
        f = frames.Frame(type=PacketType.CMD,
                         payload=frames.pack_cmd(cmd, key, value),
                         seq=self._uart_seq.next()).stamp()
        self.uart.send(f)

    def _on_spectro_status(self, ok: bool) -> None:
        sev = EventSeverity.INFO if ok else EventSeverity.WARNING
        text = "spectrometer connected" if ok else "spectrometer lost"
        self._send_event(_EV_SPECTRO, sev, text)
        self.comm_log.log("pi", text)

    # -- periodic tasks ------------------------------------------------------

    def _send_event(self, code: int, severity: int, text: str) -> None:
        self.down.send(PacketType.EVENT,
                       frames.pack_event(code, severity, text))

    def _send_pistatus(self) -> None:
        try:
            free_mb = shutil.disk_usage(self.cfg.data_dir).free // 2**20
        except OSError:
            free_mb = 0
        self.down.send(PacketType.PISTATUS, frames.pack_pistatus(
            free_mb, self.store.count,
            self.uart.alive(self.cfg.mcu_silent_alarm_s),
            self.source.connected, _cpu_temp_cc()))

    def _send_timesync(self) -> None:
        f = frames.Frame(type=PacketType.TIMESYNC,
                         payload=frames.pack_timesync(time.time()),
                         seq=self._uart_seq.next()).stamp()
        self.uart.send(f)

    def _check_mcu_liveness(self) -> None:
        alive = self.uart.alive(self.cfg.mcu_silent_alarm_s)
        if not alive and self.uart.last_rx > 0 and not self._mcu_alarmed:
            self._mcu_alarmed = True   # alarm only, never take over (S.7)
            self._send_event(_EV_MCU_SILENT, EventSeverity.ERROR,
                             "MCU silent on UART")
            self.comm_log.log("pi", "ALARM: MCU silent on UART")
        elif alive:
            self._mcu_alarmed = False

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self.uart.start()
        self.cmd_server.start()
        self.source.start()
        if self.bench is not None:
            self.bench.start()
        self.watchdog.ready()

    def run(self) -> None:
        self.start()
        nxt = {"quicklook": 0.0, "pistatus": 0.0, "timesync": 0.0,
               "watchdog": 0.0}
        period = {"quicklook": 1.0,   # QuicklookSender rate-limits itself
                  "pistatus": self.cfg.pistatus_interval_s,
                  "timesync": self.cfg.timesync_interval_s,
                  "watchdog": 5.0}
        while not self.stop_event.is_set():
            now = time.time()
            if now >= nxt["quicklook"]:
                with self._latest_lock:
                    latest = self._latest_frame
                self.quicklook.maybe_send(latest, now)
                nxt["quicklook"] = now + period["quicklook"]
            if now >= nxt["pistatus"]:
                self._send_pistatus()
                nxt["pistatus"] = now + period["pistatus"]
            if now >= nxt["timesync"]:
                self._send_timesync()                      # S.4
                nxt["timesync"] = now + period["timesync"]
            if now >= nxt["watchdog"]:
                self.watchdog.kick()                       # S.9
                nxt["watchdog"] = now + period["watchdog"]
            self._check_mcu_liveness()
            self.stop_event.wait(0.2)
        self.shutdown()

    def stop(self) -> None:
        self.stop_event.set()

    def shutdown(self) -> None:
        if self._shutdown_done.is_set():   # idempotent: run() + caller
            return
        self._shutdown_done.set()
        self.watchdog.stopping()
        if self.bench is not None:
            self.bench.stop()
        self.source.stop()
        self.cmd_server.stop()
        self.uart.stop()
        self.store.close()
        self.comm_log.close()
        self.down.close()


def _cpu_temp_cc() -> int:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) // 10   # millideg -> centideg
    except (OSError, ValueError):
        return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CLOUDS FSW-PI flight software")
    ap.add_argument("--config", help="JSON config file")
    ap.add_argument("--mock", action="store_true",
                    help="synthetic spectrometer + loopback UART (bench)")
    ap.add_argument("--no-uart", action="store_true",
                    help="stub the UART only: real spectrometer, no RP2350 "
                         "attached (bench). Implied by --mock.")
    ap.add_argument("--data-dir", help="override data directory")
    ap.add_argument("--bench-stream", nargs="?", type=int, const=4010,
                    default=None, metavar="PORT",
                    help="bench only: also serve acquired frames on PORT "
                         "(default 4010) so `clouds_spectral.py --net HOST` "
                         "runs live alongside the GSE dashboard. Off in flight.")
    args = ap.parse_args(argv)

    overrides = {}
    if args.mock:
        overrides["mock"] = True
        overrides.setdefault("data_dir", os.path.abspath("./clouds_data"))
    if args.data_dir:
        overrides["data_dir"] = args.data_dir
    cfg = FswConfig.load(args.config, **overrides)

    transport = None
    if cfg.mock or args.no_uart:
        # UART loopback stub. SerialTransport opens cfg.uart_port eagerly, so
        # without this there is no way to run on a bench with no MCU wired up.
        transport, _ = PipeTransport.pair()

    app = FlightApp(cfg, transport=transport, bench_port=args.bench_stream)
    signal.signal(signal.SIGTERM, lambda *_: app.stop())
    try:
        app.run()
    except KeyboardInterrupt:
        app.stop()
        app.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
