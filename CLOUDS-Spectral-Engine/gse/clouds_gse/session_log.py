"""GSE session logging + CSV/JSON export (feature G-05, SED section 4.12.1).

Everything received is logged as it arrives: housekeeping to CSV, events to
CSV, quick-look spectra to JSON-lines (one spectrum per line). ``summary()``
gives the post-session JSON export.
"""
from __future__ import annotations

import csv
import json
import os
import time

from clouds_link import hk


class SessionLog:
    def __init__(self, directory: str, stamp: str | None = None):
        os.makedirs(directory, exist_ok=True)
        stamp = stamp or time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        self.hk_path = os.path.join(directory, f"session_{stamp}_hk.csv")
        self.events_path = os.path.join(directory, f"session_{stamp}_events.csv")
        self.ql_path = os.path.join(directory, f"session_{stamp}_quicklook.jsonl")
        self._hk_file = None
        self._hk_writer = None
        self._ev_file = None
        self._ev_writer = None
        self._ql_file = None
        self.counts = {"hk": 0, "events": 0, "quicklook": 0}
        self._t_first: float | None = None
        self._t_last: float | None = None

    # -- ingest --------------------------------------------------------------

    def log_hk(self, frame, housekeeping: hk.Housekeeping) -> None:
        row = {"recv_t": round(time.time(), 3),
               "frame_t": round(frame.timestamp, 3),
               "seq": frame.seq, **housekeeping.to_row()}
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
               "code": event["code"], "severity": event["severity"],
               "text": event["text"]}
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
        if self._ql_file is None:
            self._ql_file = open(self.ql_path, "w", encoding="utf-8")
        rec = {"recv_t": round(time.time(), 3),
               "frame_t": round(frame.timestamp, 3), "seq": frame.seq, **ql}
        self._ql_file.write(json.dumps(rec) + "\n")
        self._ql_file.flush()
        self.counts["quicklook"] += 1
        self._span(frame.timestamp)

    def _span(self, t: float) -> None:
        if self._t_first is None:
            self._t_first = t
        self._t_last = t

    # -- export --------------------------------------------------------------

    def summary(self, gaps=None) -> dict:
        s = {"packets": dict(self.counts),
             "first_frame_t": self._t_first, "last_frame_t": self._t_last,
             "files": {"hk": self.hk_path, "events": self.events_path,
                       "quicklook": self.ql_path}}
        if gaps is not None:
            s["link"] = {"received": gaps.received, "lost": gaps.lost}
        return s

    def export_summary(self, path: str, gaps=None) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.summary(gaps), f, indent=2)

    def close(self) -> None:
        for fh in (self._hk_file, self._ev_file, self._ql_file):
            if fh:
                fh.close()
        self._hk_file = self._ev_file = self._ql_file = None
        self._hk_writer = self._ev_writer = None
