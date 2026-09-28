"""UDP downlink (O.4): HK/event relay + quick-look spectra + Pi status,
shaped to the E-Link limits.

MCU frames are relayed byte-identical (their CRC survives end-to-end, and
the GSE sees the MCU's own sequence numbers for gap tracking). Pi-origin
packets (QUICKLOOK, PISTATUS, EVENT) get **one counter per packet type** - the
convention the MCU firmware already uses (`hk_seq_no` / `ev_seq_no` in
flight/mcu/src/main.c) and the one the GSE's gap tracker assumes
(`clouds_link.frames.GapStats`, feature G-07).

One shared counter across types would make every interleaved packet of another
type look lost downstream: PISTATUS at seq 0, two QUICKLOOKs, and the next
PISTATUS lands at 4 - the GSE charges 3 phantom losses on a clean link.

**Shaping (2026-09-29).** The E-Link allows 100 kbit/s on average and
400 kbit/s at any time (`clouds_link.linkrate`, on the wire, IP/UDP headers
included). ``Downlink`` meters every packet against both and **drops** one
that would exceed either - no queue, because a queue that fills at 400 kbit/s
is a delay nobody asked for, and the storage copy already has everything.
Quick-look is the bulk class: it stops at 90 % of either limit so that HK,
events and Pi status, which together are ~1 % of the average allowance, are
never the packets that go. The flight mix is ~3.2 kbit/s, so in flight the
shaper is a guard, not a governor; ``FswConfig.downlink_*_kbit_s`` can be
lowered on the bench to see it act. Drops are counted per type, sent down in
PISTATUS and, at most once a minute, as a ``DOWNLINK_SHAPED`` event.
"""
from __future__ import annotations

import socket
import threading
import time
from collections import Counter

import numpy as np

from clouds_link import frames
from clouds_link.frames import EventCode, EventSeverity, PacketType
from clouds_link.linkrate import (AVG_WINDOW_S, DOWNLINK_AVG_BIT_S,
                                  DOWNLINK_PEAK_BIT_S, DROP_EVENT_INTERVAL_S,
                                  PEAK_WINDOW_S, QUICKLOOK_HEADROOM, LinkMeter,
                                  udp_wire_bytes)
from spectro.processing import average_frames, bin_mean

#: Packet types the shaper sacrifices first. Everything else is priority
#: traffic and is admitted up to the limit itself.
BULK_TYPES = frozenset({PacketType.QUICKLOOK})

_TYPE_OFFSET = 3        # packet type byte in the frame header (frames.HEADER)


class Downlink:
    """One UDP socket to ground, metered and shaped.

    ``relay`` / ``send`` return whether the packet went out. Both may be
    called from any thread: the UART reader relays HK and events, the main
    loop sends quick-look and status, and a ``STATUS?`` from ground sends a
    PISTATUS from the command server's handler thread.
    """

    def __init__(self, host: str, port: int,
                 avg_bit_s: float = DOWNLINK_AVG_BIT_S,
                 peak_bit_s: float = DOWNLINK_PEAK_BIT_S):
        self._addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._seq: dict[int, frames.SeqCounter] = {}   # one per packet type
        self._lock = threading.Lock()
        self.meter = LinkMeter(windows=(PEAK_WINDOW_S, AVG_WINDOW_S))
        self.limits = ((PEAK_WINDOW_S, float(peak_bit_s)),
                       (AVG_WINDOW_S, float(avg_bit_s)))
        self.sent = 0                       # packets
        self.sent_wire_bytes = 0
        self.dropped: Counter[int] = Counter()      # per packet type
        self.dropped_total = 0
        self.dropped_priority = 0           # drops that were not bulk

    # -- rates ---------------------------------------------------------------

    def avg_bit_s(self, now: float | None = None) -> float:
        return self.meter.bit_s(AVG_WINDOW_S, now)

    def peak_bit_s(self, now: float | None = None) -> float:
        return self.meter.bit_s(PEAK_WINDOW_S, now)

    # -- sending -------------------------------------------------------------

    def relay(self, raw: bytes, now: float | None = None) -> bool:
        """Forward an MCU frame unchanged (HK, EVENT). The MCU's own seq is
        kept, so a relayed frame the shaper drops shows on the ground as a
        gap - and ``dropped_priority`` says why."""
        return self._put(raw[_TYPE_OFFSET], lambda: raw,
                         udp_wire_bytes(len(raw)), now)

    def send(self, ptype: int, payload: bytes, now: float | None = None) -> bool:
        """Frame and send a Pi-origin packet. The sequence number is taken
        only once the packet is admitted, so a dropped packet leaves no gap:
        ``GapStats.lost`` on the ground keeps meaning "the link lost it"."""
        wire = udp_wire_bytes(frames.HEADER_LEN + len(payload) + frames.CRC_LEN)

        def build() -> bytes:
            f = frames.Frame(type=ptype, payload=payload,
                             seq=self._next_seq(ptype))
            return f.stamp().encode()

        return self._put(ptype, build, wire, now)

    def _put(self, ptype: int, build_raw, wire: int, now: float | None) -> bool:
        with self._lock:
            headroom = QUICKLOOK_HEADROOM if ptype in BULK_TYPES else 0.0
            if not self.meter.admit(wire, self.limits, now, headroom=headroom):
                self.dropped[ptype] += 1
                self.dropped_total += 1
                if ptype not in BULK_TYPES:
                    self.dropped_priority += 1
                return False
            raw = build_raw()
            self._sock.sendto(raw, self._addr)
            self.sent += 1
            self.sent_wire_bytes += wire
            return True

    def _next_seq(self, ptype: int) -> int:
        counter = self._seq.get(ptype)
        if counter is None:
            counter = self._seq[ptype] = frames.SeqCounter()
        return counter.next()

    def close(self) -> None:
        self._sock.close()


class DropReporter:
    """Turn the shaper's drop counters into at most one EVENT per interval.

    A link that is over its limit drops packets every second; an event per
    drop would be a flood of the very thing being shaped. One WARNING per
    ``interval_s`` names how many went and how many of them were quick-look,
    and nothing is sent while nothing is dropped.
    """

    def __init__(self, downlink: Downlink, send_event,
                 interval_s: float = DROP_EVENT_INTERVAL_S):
        self._down = downlink
        self._send_event = send_event
        self._interval = interval_s
        self._reported_total = 0
        self._reported_bulk = 0
        self._last_t: float | None = None

    def poll(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        total = self._down.dropped_total
        if total == self._reported_total:
            return False
        if self._last_t is not None and now - self._last_t < self._interval:
            return False
        bulk = sum(n for t, n in self._down.dropped.items() if t in BULK_TYPES)
        n, nb = total - self._reported_total, bulk - self._reported_bulk
        since = 0.0 if self._last_t is None else now - self._last_t
        self._reported_total, self._reported_bulk, self._last_t = total, bulk, now
        self._send_event(EventCode.DOWNLINK_SHAPED, EventSeverity.WARNING,
                         f"downlink shaped: {n} dropped ({nb} quick-look)"
                         + (f" in {since:.0f} s" if since else ""))
        return True


def bin_channel(frame_counts, lo: int, hi: int, factor: int) -> list[int]:
    """Mean-bin a channel's pixel window [lo, hi] by ``factor`` (feature P-04).

    A partial trailing bin is dropped so every value averages ``factor``
    real pixels. The arithmetic is `spectro.processing.bin_mean`, shared with
    the ground's binned dark so both sides agree on the edges."""
    binned = bin_mean(np.asarray(frame_counts[lo:hi + 1], dtype=np.float64), factor)
    return [int(v) for v in np.clip(binned, 0, 0xFFFF)]


class QuicklookSender:
    """Every ``interval_s``, downlink both channels of the latest frame,
    binned ``bin_factor`` x (29 + 31 bins, 164 B of frames, ~2 kbit/s on
    the wire at the 1 Hz flight cadence).

    The frame is **despiked before binning**, the same USB-glitch rejection
    the bench view applies (`spectro.processing.average_frames`, single
    frame -> spatial despike). The transfer pins a random ~9 % of pixels per
    frame to ~33514 ct and they move frame to frame, so a plain 8-px mean
    carries a +4 k ct hit in about half of its bins and the quick-look jumps
    every second while its baseline sits ~3 k high (`calibration.json`
    notes: "never plain-average"). Storage still gets the raw frame - this
    touches the downlink copy only. No dark subtraction here: that is the
    ground's call, and the stats card says the frame is raw from the Pi.

    ``maybe_send`` reports whether it *attempted* the send; whether the
    shaper let the packets through is in ``Downlink.dropped``.
    """

    def __init__(self, downlink: Downlink, calibration, bin_factor: int = 8,
                 interval_s: float = 1.0):
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
