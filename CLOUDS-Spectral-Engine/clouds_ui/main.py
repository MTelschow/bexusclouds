"""Entry point for the one CLOUDS operator interface.

    python -m clouds_ui                       # bench: the Duo on this machine
                                              # (macOS: the Duo on the Pi, see
                                              # below)
    python -m clouds_ui --net 192.168.100.10  # detector on the Pi (bench-stream)
    python -m clouds_ui --flight              # downlink only: HK, quick-look,
                                              # commanding. No detector.
    python -m clouds_ui --mock                # nothing real: synthetic
                                              # detector + simulated flight
                                              # chain, for demo and training

Apart from ``--mock``, which announces itself everywhere it can, a spectrum
on this screen is always a real measurement of real light: the interface
either talks to the Duo (locally, or over the cable via ``--net``) or it
opens no detector at all (``--flight``).

``--mock`` exists because the window has to be learnable, and reviewable,
away from the bench - there is one Duo and one Pi, and neither travels. It
fakes exactly two things, the light on the detector and the silicon on the
UART; everything between them is the real flight app, the real protocol and
the real ground station (``clouds_ui/mock_stack.py``). Because a simulated
spectrum that looked real would be the worst failure this app has, the mock
says so in the window title, in the plot's source banner, and in the device
line - and it never writes a dark frame or a flight-shaped session log that
a later real session could pick up.

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
import time

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
    det.add_argument("--net", metavar="HOST", default=None,
                     help="detector on another machine (the Pi's "
                          "--bench-stream, or spectro.net_server). Defaults "
                          "to the bench Pi on macOS, which has no native "
                          "detector driver, and to this machine elsewhere")
    det.add_argument("--mock", action="store_true",
                     help="no hardware at all: synthetic detector plus a "
                          "simulated flight chain (FSW + RP2350) on "
                          "loopback. For demo and training, and labelled as "
                          "such throughout the window")
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
    args = ap.parse_args(argv)
    if args.mock:
        # --net names a real detector on a real machine, which is the one
        # thing --mock promises there is none of. Refuse rather than pick a
        # winner: whichever we dropped, the operator would be looking at the
        # other one.
        if args.net:
            ap.error("--mock and --net are contradictory: --mock opens no "
                     "detector anywhere, --net names a real one")
    elif args.net is None:
        args.net = _default_net()
    return args


class Links:
    """The flight half's live objects, as one unit.

    They are built together (the mock stack needs the receiver's port, the
    commander needs the mock stack's) and torn down together, and the
    window's Restart button does both again without closing the window - so
    the construction lives in `open_links`, not inline in `main`, and the
    window gets a factory rather than the objects alone.
    """

    def __init__(self, receiver=None, commander=None, session=None,
                 mock_stack=None):
        self.receiver = receiver
        self.commander = commander
        self.session = session
        self.mock_stack = mock_stack


def open_links(args) -> Links:
    """Open the downlink receiver, the command link, the session log and,
    under ``--mock``, the simulated flight chain - or none of them under
    ``--no-link``. Every call is a fresh session: new sockets, a new log
    file with its own stamp, a new mock data directory."""
    links = Links()
    if args.no_link:
        return links
    # Imported here, not at module scope: --no-link must not need the gse
    # package on the path at all.
    from clouds_gse.commander import Commander
    from clouds_gse.receiver import Receiver
    from clouds_gse.session_log import SessionLog

    # A mock session is logged like any other - it is what an operator
    # practises reading - but its files say so in the name, so nobody
    # later mistakes a simulated flight for a flown one.
    stamp = ("mock_" + time.strftime("%Y%m%d_%H%M%S", time.gmtime())
             if args.mock else None)
    session = SessionLog(args.log_dir, stamp=stamp)
    # Loopback and an ephemeral port under --mock: the simulated downlink
    # must not collide with a real GSE already on UDP 4000, and must not
    # be reachable from off this machine.
    try:
        receiver = Receiver(bind="127.0.0.1" if args.mock else "0.0.0.0",
                            port=0 if args.mock else args.listen)
    except OSError:
        session.close()
        raise
    # Session logging hangs off the receiver's own callbacks, so every
    # packet is recorded as it arrives rather than whenever the UI last
    # polled - a dropped frame stays a gap in the CSV.
    receiver._cb["hk"] = session.log_hk
    receiver._cb["ev"] = session.log_event
    receiver._cb["ql"] = session.log_quicklook
    receiver.start()
    links.receiver, links.session = receiver, session

    cmd_host, cmd_port = args.experiment, args.cmd_port
    if args.mock:
        from .mock_stack import MockStack

        mock_stack = MockStack(receiver.port)
        mock_stack.start()
        cmd_host, cmd_port = "127.0.0.1", mock_stack.cmd_port
        links.mock_stack = mock_stack

    if not args.listen_only:
        commander = Commander(cmd_host, cmd_port,
                              flight_mode=args.flight_mode, log=print)
        commander.start_heartbeat()
        links.commander = commander
    return links


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

    links = open_links(args)

    from .window import CloudsWindow

    win = CloudsWindow(mock=args.mock, persist_dark=not args.mock,
                       kind=kind, host=host,
                       receiver=links.receiver, commander=links.commander,
                       session=links.session, mock_stack=links.mock_stack,
                       # Restart rebuilds the flight half from the same flags
                       # the session started with - same ports, same log
                       # directory, same mock-or-not.
                       link_factory=lambda: open_links(args),
                       source="downlink" if args.flight else "detector")
    if args.flight_mode and links.commander is not None:
        win.flight.chk_flight_mode.setChecked(True)
    win.fold_for(flight=args.flight)
    win.show()

    # The window closes its links in closeEvent; this is the backstop for a
    # quit that bypasses it. Under --mock the simulated Pi and MCU are
    # threads in this process and must not outlive the window, or a closed
    # window leaves an FSW writing frames and a temporary data directory
    # behind it. Idempotent, so running after closeEvent is a no-op.
    app.aboutToQuit.connect(win.close_links)

    if not args.flight:
        # Connect and go live - and if the detector is not up yet, keep
        # trying instead of leaving the instrument half dead for the session.
        # The flight half is on its own sockets and comes up regardless, which
        # is why a startup-only detector failure read as "the spectrum just
        # doesn't show" and got fixed by restarting the app.
        win.start_detector()
    print("[CLOUDS] ready - window open.")
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
