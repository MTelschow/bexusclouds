"""GSE entry point.

Console:  python -m clouds_gse.main --experiment 192.168.100.10
Listen-only (no command link): python -m clouds_gse.main --listen-only

There is no --gui here any more. The dashboard and the bench panel are one
application now - `python -m clouds_ui --flight` - so that a spectrum on
screen always says which source it came from. This module is the headless
path (and the fallback when no display is available).

There is no ground interlock and no flight-mode switch any more
(2026-09-18): `start` is what begins the experiment, and every command is
sent as typed.
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
    ap.add_argument("--log-dir", default="./gse_sessions")
    args = ap.parse_args(argv)

    session = SessionLog(args.log_dir)
    receiver = Receiver(port=args.listen)
    receiver.start()

    commander = None
    if not args.listen_only:
        commander = Commander(args.experiment, args.cmd_port, log=print,
                              on_result=session.log_command)
        commander.start_heartbeat()

    try:
        monitor = ConsoleMonitor(receiver, commander, session)
        monitor.repl()
        return 0
    finally:
        if commander:
            commander.close()
        receiver.stop()
        session.export_summary(
            session.hk_path.replace("_hk.csv", "_summary.json"),
            receiver.gaps,
            {"rx_packets": receiver.rx_packets, "rx_bytes": receiver.rx_bytes,
             "decode_errors": receiver.decode_errors,
             "hk_rejected": receiver.hk_rejected,
             "hk_reject_reason": receiver.hk_reject_reason})
        session.close()
        print(f"session logs in {args.log_dir}")


if __name__ == "__main__":
    raise SystemExit(main())
