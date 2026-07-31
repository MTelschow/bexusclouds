"""GSE telemetry receiver (G-01, G-02, G-07): UDP frames -> live state.

Keeps the latest housekeeping, the latest quick-look spectrum per channel,
a bounded event history, and per-type sequence-gap statistics. Callbacks
(``on_hk``, ``on_quicklook``, ``on_event``, ``on_pistatus``) run on the
receiver thread - GUI consumers must marshal to their own thread.
"""
from __future__ import annotations

import socket
import threading
import time
from collections import deque

from clouds_link import frames, hk
from clouds_link.frames import GapStats, PacketType


class Receiver:
    def __init__(self, bind: str = "0.0.0.0", port: int = 4000,
                 on_hk=None, on_quicklook=None, on_event=None,
                 on_pistatus=None):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((bind, port))
        self._sock.settimeout(0.2)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cb = {"hk": on_hk, "ql": on_quicklook, "ev": on_event,
                    "pi": on_pistatus}

        self.gaps = GapStats()
        self.decode_errors = 0
        self.last_hk: hk.Housekeeping | None = None
        self.last_hk_time: float = 0.0
        self.last_pistatus: dict | None = None
        self.quicklook: dict[int, dict] = {}          # channel -> payload
        self.events: deque = deque(maxlen=500)

    @property
    def port(self) -> int:
        return self._sock.getsockname()[1]

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="gse-receiver")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._sock.close()

    def hk_age_s(self) -> float | None:
        """Seconds since the last HK packet - the operator's link gauge."""
        if self.last_hk_time == 0.0:
            return None
        return time.time() - self.last_hk_time

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                raw, _ = self._sock.recvfrom(65536)
            except TimeoutError:
                continue
            except OSError:
                return
            self._handle(raw)

    def _handle(self, raw: bytes) -> None:
        try:
            frame = frames.decode(raw)
        except frames.FrameError:
            self.decode_errors += 1
            return
        self.gaps.update(frame.type, frame.seq)
        try:
            self._dispatch(frame)
        except Exception:  # noqa: BLE001 - receiver must survive callbacks
            self.decode_errors += 1

    def _dispatch(self, frame: frames.Frame) -> None:
        if frame.type == PacketType.HK:
            self.last_hk = hk.Housekeeping.unpack(frame.payload)
            self.last_hk_time = time.time()
            if self._cb["hk"]:
                self._cb["hk"](frame, self.last_hk)
        elif frame.type == PacketType.QUICKLOOK:
            d = frames.unpack_quicklook(frame.payload)
            d["t"] = frame.timestamp
            self.quicklook[d["channel"]] = d
            if self._cb["ql"]:
                self._cb["ql"](frame, d)
        elif frame.type == PacketType.EVENT:
            ev = frames.unpack_event(frame.payload)
            ev["t"] = frame.timestamp
            self.events.append(ev)
            if self._cb["ev"]:
                self._cb["ev"](frame, ev)
        elif frame.type == PacketType.PISTATUS:
            self.last_pistatus = frames.unpack_pistatus(frame.payload)
            if self._cb["pi"]:
                self._cb["pi"](frame, self.last_pistatus)
