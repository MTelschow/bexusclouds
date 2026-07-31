"""Headless console monitor: live HK lines + command REPL (late-access /
integration use, and the fallback when no display is available).

Commands:  ping start hold resume abort  release 1|2  set <key> <value>
           status flight-mode quit
"""
from __future__ import annotations

import threading

from clouds_link.commands import Command, Param
from clouds_link.frames import AckResult

from .commander import Commander, CommandError, InterlockError
from .receiver import Receiver
from .session_log import SessionLog


def _fmt_hk(h) -> str:
    return (f"[{h.state_name:11s}] fired={h.fired:02b} "
            f"p_amb={h.p_amb_pa / 100:8.1f} hPa p_ch={h.p_ch_pa / 100:8.1f} hPa "
            f"T1={h.temp1_cc / 100:6.1f} C RH1={h.rh1_cpct / 100:5.1f}% "
            f"duty={h.membrane_duty:3d}% t+{h.mission_t_s}s")


class ConsoleMonitor:
    def __init__(self, receiver: Receiver, commander: Commander | None,
                 session: SessionLog, print_fn=print):
        self._rx = receiver
        self._cmd = commander
        self._session = session
        self._print = print_fn
        self._last_state = None
        receiver._cb["hk"] = self._on_hk
        receiver._cb["ev"] = self._on_event
        receiver._cb["ql"] = self._session.log_quicklook

    def _on_hk(self, frame, h) -> None:
        self._session.log_hk(frame, h)
        if h.state != self._last_state:   # always show state changes
            self._last_state = h.state
            self._print(_fmt_hk(h))
        elif frame.seq % 10 == 0:         # 1-in-10 heartbeat line otherwise
            self._print(_fmt_hk(h))

    def _on_event(self, frame, ev) -> None:
        self._session.log_event(frame, ev)
        sev = ("INFO", "WARN", "ERROR", "CRIT")[min(ev["severity"], 3)]
        self._print(f"EVENT {sev} code={ev['code']}: {ev['text']}")

    def repl(self, input_fn=input) -> None:
        self._print("GSE console - commands: ping start hold resume abort "
                    "release 1|2, set <param> <value>, status, flight-mode, quit")
        while True:
            try:
                line = input_fn("gse> ").strip()
            except (EOFError, KeyboardInterrupt):
                return
            if not line:
                continue
            if line in ("quit", "exit"):
                return
            self._dispatch(line)

    def _dispatch(self, line: str) -> None:
        if self._cmd is None:
            self._print("no command link (started with --listen-only)")
            return
        parts = line.split()
        try:
            if parts[0] == "release" and len(parts) == 2:
                r = self._cmd.release(int(parts[1]))
            elif parts[0] == "set" and len(parts) == 3:
                key = Param[parts[1].upper()] if not parts[1].isdigit() \
                    else int(parts[1])
                r = self._cmd.set_param(int(key), int(parts[2]))
            elif parts[0] == "flight-mode":
                self._cmd.flight_mode = not self._cmd.flight_mode
                self._print(f"flight mode: {'ON' if self._cmd.flight_mode else 'off'}")
                return
            elif parts[0] == "status":
                age = self._rx.hk_age_s()
                self._print(f"hk age: {age if age is None else f'{age:.1f} s'}  "
                            f"rx: {self._rx.gaps.received} lost: {self._rx.gaps.lost}  "
                            f"pi: {self._rx.last_pistatus}")
                return
            else:
                r = self._cmd.send(Command[parts[0].upper()])
            self._print(f"-> {AckResult(r).name}")
        except InterlockError as e:
            self._print(f"INTERLOCK: {e}")
        except (CommandError, KeyError, ValueError) as e:
            self._print(f"error: {e}")
