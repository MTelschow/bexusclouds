"""Entry point for the one CLOUDS operator interface.

    python -m clouds_ui                       # bench: the Duo on this machine
                                              # (macOS: the Duo on the Pi, see
                                              # below)
    python -m clouds_ui --net 192.168.100.10  # detector on the Pi (bench-stream)
    python -m clouds_ui --flight              # downlink only: HK, quick-look,
                                              # commanding. No detector.

There is no synthetic detector here and no second instrument family: the
operator interface either talks to the Duo (locally, or over the cable via
``--net``) or it does not open a detector at all (``--flight``). A spectrum on
this screen is therefore always a real measurement of real light. The mock
driver still exists for the hardware-free checks (``tests/``, ``verify.py``,
``verify_qt.py``, ``clouds_fsw.main --mock``) - it is reachable from code, not
from this command line.

This replaces both `clouds_spectral.py` (bench panel) and
`clouds_gse.main --gui` (ground dashboard). The two halves are the same window
now; what the flags choose is which data paths exist and which sections start
expanded, not which application you get.

`--flight` opens no driver at all. That is the honest shape of a ground
station: the detector is on the far end of a 2 kbit/s downlink, and the only
reason the bench can see it live is the Pi's `--bench-stream`, which is off in
flight.
"""
from __future__ import annotations

import argparse
import os
import sys

from PyQt5 import QtGui, QtWidgets

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The bench Pi (docs/BENCH.md): the same address FswConfig.ground_host and the
# GSE's --experiment already default to.
BENCH_PI = "192.168.100.10"


def _default_net() -> str | None:
    """Where the detector is when nobody said.

    On Windows and Linux that is this machine - a USB Duo, ``kind="std"``.
    On macOS it is never this machine: EURECA ships a Windows DLL and a Linux
    ``.so`` and nothing else, so a local open cannot succeed here, ever. The
    old default failed into a 3 s reconnect loop against a driver that does
    not exist on the platform, which reads as "the app is broken" rather than
    "you are on the wrong machine". So default to the cable, which is the
    bench's actual wiring: detector on the Pi, operator interface here.

    ``CLOUDS_SPECTRO_HOST`` moves it; ``--net HOST`` overrides it; ``--flight``
    opens no detector at all.
    """
    if sys.platform != "darwin":
        return None
    return os.environ.get("CLOUDS_SPECTRO_HOST") or BENCH_PI


def _parse(argv=None):
    ap = argparse.ArgumentParser(
        prog="clouds_ui", description="CLOUDS operator interface "
                                      "(bench instrument + flight downlink)")
    det = ap.add_argument_group("detector (bench)")
    det.add_argument("--net", metavar="HOST", default=_default_net(),
                     help="detector on another machine (the Pi's "
                          "--bench-stream, or spectro.net_server). Defaults "
                          "to the bench Pi on macOS, which has no native "
                          "detector driver, and to this machine elsewhere")
    fl = ap.add_argument_group("flight link")
    fl.add_argument("--flight", action="store_true",
                    help="downlink only: open no detector, start on the "
                         "downlink source with the flight sections expanded")
    fl.add_argument("--experiment", default="192.168.100.10",
                    help="experiment (Pi) address for the TCP command link")
    fl.add_argument("--cmd-port", type=int, default=4001)
    fl.add_argument("--listen", type=int, default=4000,
                    help="UDP telemetry port to bind")
    fl.add_argument("--no-link", action="store_true",
                    help="instrument only: no downlink receiver, no uplink")
    fl.add_argument("--listen-only", action="store_true",
                    help="receive telemetry but open no command link")
    fl.add_argument("--flight-mode", action="store_true",
                    help="disable the ground interlock (S.10) at startup")
    fl.add_argument("--log-dir", default="./gse_sessions",
                    help="session log directory (G-05)")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = _parse(argv)

    kind = None
    host = None
    if args.net:
        host, kind = args.net, "net"

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "CLOUDS.SpectralEngine")
        except Exception:
            pass

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
        sys.argv if argv is None else [sys.argv[0]])
    ico = os.path.join(HERE, "assets", "clouds.ico")
    if os.path.exists(ico):
        app.setWindowIcon(QtGui.QIcon(ico))

    receiver = commander = session = None
    if not args.no_link:
        # Imported here, not at module scope: --no-link must not need the gse
        # package on the path at all.
        from clouds_gse.commander import Commander
        from clouds_gse.receiver import Receiver
        from clouds_gse.session_log import SessionLog

        session = SessionLog(args.log_dir)
        receiver = Receiver(port=args.listen)
        # Session logging hangs off the receiver's own callbacks, so every
        # packet is recorded as it arrives rather than whenever the UI last
        # polled - a dropped frame stays a gap in the CSV.
        receiver._cb["hk"] = session.log_hk
        receiver._cb["ev"] = session.log_event
        receiver._cb["ql"] = session.log_quicklook
        receiver.start()
        if not args.listen_only:
            commander = Commander(args.experiment, args.cmd_port,
                                  flight_mode=args.flight_mode, log=print)
            commander.start_heartbeat()

    from .window import CloudsWindow

    win = CloudsWindow(kind=kind, host=host,
                       receiver=receiver, commander=commander,
                       session=session,
                       source="downlink" if args.flight else "detector")
    if args.flight_mode and commander is not None:
        win.flight.chk_flight_mode.setChecked(True)
    win.fold_for(flight=args.flight)
    win.show()

    if not args.flight:
        win._connect()
        if win.connected:
            win._start()
    print("[CLOUDS] ready - window open.")
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
