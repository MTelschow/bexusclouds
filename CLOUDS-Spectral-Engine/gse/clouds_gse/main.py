"""GSE entry point.

Console:  python -m clouds_gse.main --experiment 192.168.100.10
GUI:      python -m clouds_gse.main --experiment 192.168.100.10 --gui
Listen-only (no command link): python -m clouds_gse.main --listen-only

The ground interlock (S.10) starts ENGAGED: RELEASE/START are refused
locally until --flight-mode is given or the operator toggles it in the UI.
"""
from __future__ import annotations

import argparse

from .commander import Commander
from .monitor import ConsoleMonitor
from .receiver import Receiver
from .session_log import SessionLog


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CLOUDS ground station")
    ap.add_argument("--experiment", default="192.168.100.10",
                    help="experiment (Pi) address for the TCP command link")
    ap.add_argument("--cmd-port", type=int, default=4001)
    ap.add_argument("--listen", type=int, default=4000,
                    help="UDP telemetry port to bind")
    ap.add_argument("--listen-only", action="store_true",
                    help="no command link (monitoring / replay)")
    ap.add_argument("--flight-mode", action="store_true",
                    help="disable the ground interlock (S.10) at startup")
    ap.add_argument("--log-dir", default="./gse_sessions")
    ap.add_argument("--gui", action="store_true", help="PyQt5 dashboard")
    args = ap.parse_args(argv)

    session = SessionLog(args.log_dir)
    receiver = Receiver(port=args.listen)
    receiver.start()

    commander = None
    if not args.listen_only:
        commander = Commander(args.experiment, args.cmd_port,
                              flight_mode=args.flight_mode, log=print)
        commander.start_heartbeat()

    try:
        if args.gui:
            from .app import run_gui  # noqa: PLC0415 - Qt only when asked
            return run_gui(receiver, commander, session)
        monitor = ConsoleMonitor(receiver, commander, session)
        monitor.repl()
        return 0
    finally:
        if commander:
            commander.close()
        receiver.stop()
        session.export_summary(
            session.hk_path.replace("_hk.csv", "_summary.json"),
            receiver.gaps)
        session.close()
        print(f"session logs in {args.log_dir}")


if __name__ == "__main__":
    raise SystemExit(main())
