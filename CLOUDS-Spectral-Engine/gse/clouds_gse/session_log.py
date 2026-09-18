"""GSE session logging + CSV/JSON export (feature G-05, SED section 4.12.1).

Everything received is logged as it arrives: housekeeping to CSV, events to
CSV, quick-look spectra to JSON-lines (one spectrum per line), Pi status to
CSV, and the command uplink - every command and its verdict - to CSV.
``summary()`` gives the post-session JSON export.

The rule here is that nothing the operator can see is missing from the
session afterwards. Pi status and the uplink used to be the exceptions: both
were on screen (or, for Pi status, one `monitor` print away) and in no file,
so a post-flight reader could see the sensor rows but not the free disk that
explained a storage gap, nor which commands were sent, refused or never left
the ground. A ground-refused command (S.10 interlock) is the sharpest case -
it never reaches the Pi, so the Pi's own `comms_*.log` cannot hold it and
this file is its only record.

Writes come from three threads - the receiver's, the commander's caller
(the GUI thread) and the heartbeat - so every ingest path takes ``_lock``.
Each row is flushed as it is written: a session that ends in a power cut
keeps everything up to the cut.
"""
from __future__ import annotations

import csv
import json
import os
import threading
import time

from clouds_link import hk
from clouds_link.frames import event_name, severity_name


class SessionLog:
    def __init__(self, directory: str, stamp: str | None = None):
        os.makedirs(directory, exist_ok=True)
        stamp = stamp or time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        self.hk_path = os.path.join(directory, f"session_{stamp}_hk.csv")
        self.events_path = os.path.join(directory, f"session_{stamp}_events.csv")
        self.ql_path = os.path.join(directory, f"session_{stamp}_quicklook.jsonl")
        self.pistatus_path = os.path.join(directory,
                                          f"session_{stamp}_pistatus.csv")
        self.commands_path = os.path.join(directory,
                                          f"session_{stamp}_commands.csv")
        self._lock = threading.Lock()
        self._hk_file = None
        self._hk_writer = None
        self._ev_file = None
        self._ev_writer = None
        self._ql_file = None
        self._ps_file = None
        self._ps_writer = None
        self._cmd_file = None
        self._cmd_writer = None
        self.counts = {"hk": 0, "events": 0, "quicklook": 0, "pistatus": 0,
                       "commands": 0}
        self._t_first: float | None = None
        self._t_last: float | None = None

    # -- ingest --------------------------------------------------------------

    def log_hk(self, frame, housekeeping: hk.Housekeeping) -> None:
        row = {"recv_t": round(time.time(), 3),
               "frame_t": round(frame.timestamp, 3),
               "seq": frame.seq, **housekeeping.to_row()}
        with self._lock:
            if self._hk_writer is None:
                self._hk_file = open(self.hk_path, "w", newline="",
                                     encoding="utf-8")
                self._hk_writer = csv.DictWriter(self._hk_file,
                                                 fieldnames=list(row))
                self._hk_writer.writeheader()
            self._hk_writer.writerow(row)
            self._hk_file.flush()
            self.counts["hk"] += 1
            self._span(frame.timestamp)

    def log_event(self, frame, event: dict) -> None:
        row = {"recv_t": round(time.time(), 3),
               "frame_t": round(frame.timestamp, 3), "seq": frame.seq,
               "code": event["code"], "code_name": event_name(event["code"]),
               "severity": event["severity"],
               "severity_name": severity_name(event["severity"]),
               "text": event["text"]}
        with self._lock:
            if self._ev_writer is None:
                self._ev_file = open(self.events_path, "w", newline="",
                                     encoding="utf-8")
                self._ev_writer = csv.DictWriter(self._ev_file,
                                                 fieldnames=list(row))
                self._ev_writer.writeheader()
            self._ev_writer.writerow(row)
            self._ev_file.flush()
            self.counts["events"] += 1
            self._span(frame.timestamp)

    def log_quicklook(self, frame, ql: dict) -> None:
        rec = {"recv_t": round(time.time(), 3),
               "frame_t": round(frame.timestamp, 3), "seq": frame.seq, **ql}
        with self._lock:
            if self._ql_file is None:
                self._ql_file = open(self.ql_path, "w", encoding="utf-8")
            self._ql_file.write(json.dumps(rec) + "\n")
            self._ql_file.flush()
            self.counts["quicklook"] += 1
            self._span(frame.timestamp)

    def log_pistatus(self, frame, ps: dict) -> None:
        """Pi health (PacketType.PISTATUS): free disk, frames stored, UART
        and detector state, CPU temperature.

        These are the numbers that explain the *other* files - a storage gap
        against `disk_free_mb`, a quiet quick-look against `spectro_ok`, a
        silent MCU against `uart_ok` - so they belong in the session, not
        only in the receiver's last-value field.
        """
        row = {"recv_t": round(time.time(), 3),
               "frame_t": round(frame.timestamp, 3), "seq": frame.seq, **ps}
        with self._lock:
            if self._ps_writer is None:
                self._ps_file = open(self.pistatus_path, "w", newline="",
                                     encoding="utf-8")
                self._ps_writer = csv.DictWriter(self._ps_file,
                                                 fieldnames=list(row))
                self._ps_writer.writeheader()
            self._ps_writer.writerow(row)
            self._ps_file.flush()
            self.counts["pistatus"] += 1
            self._span(frame.timestamp)

    #: Columns of the uplink log. Fixed rather than taken from the first
    #: record, because the first command of a session may well be one that
    #: never reached the Pi (no link, or interlocked) and a header that then
    #: lacked `rtt_ms` would be wrong for every row after it.
    COMMAND_FIELDS = ("send_t", "origin", "cmd", "cmd_name", "key", "value",
                      "seq", "result", "result_name", "rtt_ms", "note")

    def log_command(self, record: dict) -> None:
        """One uplinked command and what came back (``Commander.on_result``).

        Includes commands that never left the ground: an S.10 interlock
        refusal is logged with ``result_name=INTERLOCK_GROUND`` and no
        ``seq``, and a link failure with ``result_name=NO_LINK``. Both are
        invisible to the Pi, so this is the only place they are recorded.
        """
        row = {k: record.get(k, "") for k in self.COMMAND_FIELDS}
        row["send_t"] = round(record.get("send_t") or time.time(), 3)
        with self._lock:
            if self._cmd_writer is None:
                self._cmd_file = open(self.commands_path, "w", newline="",
                                      encoding="utf-8")
                self._cmd_writer = csv.DictWriter(
                    self._cmd_file, fieldnames=list(self.COMMAND_FIELDS))
                self._cmd_writer.writeheader()
            self._cmd_writer.writerow(row)
            self._cmd_file.flush()
            self.counts["commands"] += 1

    def _span(self, t: float) -> None:
        if self._t_first is None:
            self._t_first = t
        self._t_last = t

    # -- export --------------------------------------------------------------

    def summary(self, gaps=None, stats=None) -> dict:
        s = {"packets": dict(self.counts),
             "first_frame_t": self._t_first, "last_frame_t": self._t_last,
             "files": {"hk": self.hk_path, "events": self.events_path,
                       "quicklook": self.ql_path,
                       "pistatus": self.pistatus_path,
                       "commands": self.commands_path}}
        if gaps is not None:
            # "unsequenced" = packets received but exempt from gap accounting
            # (dual-origin types, see clouds_link.frames.UNSEQUENCED_TYPES), so
            # "lost" is never inflated by them and is not a coverage claim.
            s["link"] = {"received": gaps.received, "lost": gaps.lost,
                         "unsequenced": getattr(gaps, "unsequenced", 0)}
        if stats:
            # Receiver counters, captured before it is stopped: packets that
            # arrived and could *not* be read are as much a link fact as the
            # ones that were lost, and `hk_reject_reason` is the one that
            # explains a session of empty sensor rows (see Receiver).
            s.setdefault("link", {}).update(stats)
        return s

    def export_summary(self, path: str, gaps=None, stats=None) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.summary(gaps, stats), f, indent=2)

    def close(self) -> None:
        with self._lock:
            for fh in (self._hk_file, self._ev_file, self._ql_file,
                       self._ps_file, self._cmd_file):
                if fh:
                    fh.close()
            self._hk_file = self._ev_file = self._ql_file = None
            self._ps_file = self._cmd_file = None
            self._hk_writer = self._ev_writer = None
            self._ps_writer = self._cmd_writer = None
