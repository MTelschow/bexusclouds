"""UDP downlink (O.4): HK/event relay + quick-look spectra + Pi status.

MCU frames are relayed byte-identical (their CRC survives end-to-end, and
the GSE sees the MCU's own sequence numbers for gap tracking). Pi-origin
packets (QUICKLOOK, PISTATUS, EVENT) get **one counter per packet type** - the
convention the MCU firmware already uses (`hk_seq_no` / `ev_seq_no` in
flight/mcu/src/main.c) and the one the GSE's gap tracker assumes
(`clouds_link.frames.GapStats`, feature G-07).

One shared counter across types would make every interleaved packet of another
type look lost downstream: PISTATUS at seq 0, two QUICKLOOKs, and the next
PISTATUS lands at 4 - the GSE charges 3 phantom losses on a clean link.
Budget per spec section 4: ~1.9 kbit/s average against the 2 kbit/s continuous
figure.
"""
from __future__ import annotations

import socket
import time
from collections import deque

import numpy as np

from clouds_link import frames
from spectro.processing import average_frames, bin_mean


class BudgetMeter:
    """Sliding-window byte meter for the continuous downlink stream."""

    def __init__(self, window_s: float = 10.0):
        self._window = window_s
        self._events: deque[tuple[float, int]] = deque()

    def add(self, nbytes: int, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._events.append((now, nbytes))

    def kbit_s(self, now: float | None = None) -> float:
        now = time.time() if now is None else now
        while self._events and self._events[0][0] < now - self._window:
            self._events.popleft()
        return sum(n for _, n in self._events) * 8 / 1000.0 / self._window


class Downlink:
    def __init__(self, host: str, port: int, budget_kbit_s: float = 2.0):
        self._addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._seq: dict[int, frames.SeqCounter] = {}   # one per packet type
        self.meter = BudgetMeter()
        self.budget_kbit_s = budget_kbit_s
        self.sent = 0
        self.over_budget = False

    def relay(self, raw: bytes) -> None:
        """Forward an MCU frame unchanged (HK, EVENT)."""
        self._sock.sendto(raw, self._addr)
        self.meter.add(len(raw))
        self.sent += 1
        self.over_budget = self.meter.kbit_s() > self.budget_kbit_s

    def _next_seq(self, ptype: int) -> int:
        counter = self._seq.get(ptype)
        if counter is None:
            counter = self._seq[ptype] = frames.SeqCounter()
        return counter.next()

    def send(self, ptype: int, payload: bytes) -> None:
        f = frames.Frame(type=ptype, payload=payload,
                         seq=self._next_seq(ptype))
        f.stamp()
        raw = f.encode()
        self._sock.sendto(raw, self._addr)
        # quick-look bursts ride the 400 kbit/s max allowance, but count them
        # anyway so over_budget reflects the true continuous rate
        self.meter.add(len(raw))
        self.sent += 1

    def close(self) -> None:
        self._sock.close()


def bin_channel(frame_counts, lo: int, hi: int, factor: int) -> list[int]:
    """Mean-bin a channel's pixel window [lo, hi] by ``factor`` (feature P-04).

    A partial trailing bin is dropped so every value averages ``factor``
    real pixels. The arithmetic is `spectro.processing.bin_mean`, shared with
    the ground's binned dark so both sides agree on the edges."""
    binned = bin_mean(np.asarray(frame_counts[lo:hi + 1], dtype=np.float64), factor)
    return [int(v) for v in np.clip(binned, 0, 0xFFFF)]


class QuicklookSender:
    """Every ``interval_s``, downlink both channels of the latest frame,
    binned ``bin_factor`` x (spec section 4: ~1.1 kB burst per 30 s).

    The frame is **despiked before binning**, the same USB-glitch rejection
    the bench view applies (`spectro.processing.average_frames`, single
    frame -> spatial despike). The transfer pins a random ~9 % of pixels per
    frame to ~33514 ct and they move frame to frame, so a plain 8-px mean
    carries a +4 k ct hit in about half of its bins and the quick-look jumps
    every second while its baseline sits ~3 k high (`calibration.json`
    notes: "never plain-average"). Storage still gets the raw frame - this
    touches the downlink copy only. No dark subtraction here: that is the
    ground's call, and the stats card says the frame is raw from the Pi.
    """

    def __init__(self, downlink: Downlink, calibration, bin_factor: int = 8,
                 interval_s: float = 30.0):
        self._down = downlink
        self._cal = calibration
        self._bin = bin_factor
        self._interval = interval_s
        self._last_sent = 0.0

    def maybe_send(self, latest, now: float | None = None) -> bool:
        """latest = (t, counts, exposure_us) or None. Returns True if sent."""
        now = time.time() if now is None else now
        if latest is None or (now - self._last_sent) < self._interval:
            return False
        _, counts, exposure_us = latest
        counts = average_frames(counts, clean=True)     # despike once, both channels
        for idx, role in enumerate(("measurement", "reference")):
            ch = self._cal.by_role_optional(role)
            if ch is None:
                continue
            lo, hi = ch.pixel_window
            binned = bin_channel(counts, lo, hi, self._bin)
            payload = frames.pack_quicklook(idx, self._bin,
                                            exposure_us // 1000, binned)
            self._down.send(frames.PacketType.QUICKLOOK, payload)
        self._last_sent = now
        return True
