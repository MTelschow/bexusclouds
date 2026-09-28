"""E-Link data-rate limits and the one meter that measures against them.

The E-Link (BEXUS user manual, Table 6-3) allows the experiment:

* **downlink** (Pi -> ground, UDP): **100 kbit/s on average** and
  **400 kbit/s at any time**;
* **uplink** (ground -> Pi, TCP): **1 kbit/s**.

Operator decision 2026-09-29: these replace the self-imposed "2 kbit/s
continuous" budget the software carried before, and they are *enforced* -
the Pi's ``Downlink`` drops packets that would exceed either downlink limit
(quick-look first), and the ground's ``Commander`` refuses a command that
would exceed the uplink limit (never the heartbeat). The windows that give
"average" and "at any time" a meaning are fixed here: a 60 s sliding window
for the averages and a 1 s sliding window for the peak. The uplink cannot be
held to a 1 s window at all - one command transaction is already ~1040 bit
of wire - so it is the 60 s average too.

Everything is counted **on the wire**, not as frame bytes: each UDP datagram
costs its 14 B Ethernet + 20 B IPv4 + 8 B UDP headers on top of the frame,
each TCP segment 14 + 20 + 20. A command transaction on the uplink is the
CMD segment plus the ground's bare TCP acknowledgement of the Pi's reply;
the reply itself travels Pi -> ground and is downlink traffic.

This module is shared by the flight app, the ground station and the panel
so that the limits exist in exactly one place and every rate on screen is
the rate the Pi enforces. It imports nothing from the rest of the protocol
and nothing from Qt.

``LinkMeter.bit_s`` always divides by the **full** window: a sliding-window
average is "bytes in the last W seconds over W". Dividing by the elapsed
time instead would turn the first 96 B housekeeping frame after start into
768 kbit/s and trip the shaper on packet one. The price is that a display
ramps up over the first window after a start or a rebind, which is true and
is said in the tooltips.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Iterable

# -- limits (bit/s) and their windows (s) ------------------------------------

UPLINK_MAX_BIT_S = 1_000
UPLINK_WINDOW_S = 60.0

DOWNLINK_AVG_BIT_S = 100_000
AVG_WINDOW_S = 60.0

DOWNLINK_PEAK_BIT_S = 400_000
PEAK_WINDOW_S = 1.0

#: ``(window_s, bit_s)`` pairs, every one of which must hold.
DOWNLINK_LIMITS = ((PEAK_WINDOW_S, DOWNLINK_PEAK_BIT_S),
                   (AVG_WINDOW_S, DOWNLINK_AVG_BIT_S))
UPLINK_LIMITS = ((UPLINK_WINDOW_S, UPLINK_MAX_BIT_S),)

#: The bulk class (quick-look) stops at this fraction below either downlink
#: limit, so housekeeping, events and Pi status always have room.
QUICKLOOK_HEADROOM = 0.10

#: At most one "downlink shaped" event per this interval, however many
#: packets were dropped in it.
DROP_EVENT_INTERVAL_S = 60.0

# -- wire overhead (bytes) ----------------------------------------------------

ETH_HEADER = 14
IPV4_HEADER = 20
UDP_HEADER = 8
TCP_HEADER = 20
UDP_WIRE_OVERHEAD = ETH_HEADER + IPV4_HEADER + UDP_HEADER      # 42
TCP_WIRE_OVERHEAD = ETH_HEADER + IPV4_HEADER + TCP_HEADER      # 54


def udp_wire_bytes(frame_len: int) -> int:
    """Bytes one frame costs on the wire as a UDP datagram."""
    return frame_len + UDP_WIRE_OVERHEAD


def tcp_wire_bytes(frame_len: int) -> int:
    """Bytes one frame costs on the wire as a TCP segment (one frame per
    segment, which is how both ends send them)."""
    return frame_len + TCP_WIRE_OVERHEAD


def uplink_transaction_bytes(cmd_frame_len: int) -> int:
    """Ground -> Pi bytes of one command: the CMD segment plus the bare TCP
    acknowledgement the ground sends for the Pi's ACK frame. That second
    segment cannot be observed from the application, so this is the
    conservative reading of "everything the uplink carries"."""
    return tcp_wire_bytes(cmd_frame_len) + TCP_WIRE_OVERHEAD


# -- the meter -----------------------------------------------------------------

Limits = Iterable[tuple[float, float]]


class LinkMeter:
    """Sliding-window byte meter answering "how many bytes in the last W
    seconds" for one or more windows, and "may N more bytes go now".

    Thread-safe: the Pi's downlink is fed from the UART thread and the main
    loop, the uplink from one handler thread per ground connection.
    """

    def __init__(self, windows: Iterable[float] = (PEAK_WINDOW_S, AVG_WINDOW_S)):
        self.windows = tuple(float(w) for w in windows)
        if not self.windows or min(self.windows) <= 0:
            raise ValueError("LinkMeter needs at least one positive window")
        self._span = max(self.windows)
        self._events: deque[tuple[float, int]] = deque()
        self._total = 0                     # bytes inside the longest window
        self._lock = threading.Lock()

    # -- feeding -------------------------------------------------------------

    def add(self, nbytes: int, now: float | None = None) -> None:
        with self._lock:
            self._add(int(nbytes), self._now(now))

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._total = 0

    # -- reading -------------------------------------------------------------

    def bytes_in(self, window_s: float, now: float | None = None) -> int:
        """Bytes recorded in the last ``window_s`` seconds. ``window_s`` may be
        any value up to the longest window this meter keeps."""
        with self._lock:
            return self._bytes_in(float(window_s), self._now(now))

    def bit_s(self, window_s: float, now: float | None = None) -> float:
        """Average rate over the last ``window_s`` seconds - bytes in the
        window over the *whole* window (see the module docstring)."""
        return self.bytes_in(window_s, now) * 8.0 / float(window_s)

    def would_exceed(self, nbytes: int, limits: Limits,
                     now: float | None = None, headroom: float = 0.0,
                     reserve_bytes: int = 0) -> bool:
        """True if adding ``nbytes`` now would break any ``(window, bit_s)``
        in ``limits``. ``headroom`` lowers every limit by that fraction;
        ``reserve_bytes`` is capacity that must stay unspent in every window
        (the commander's heartbeat allowance)."""
        with self._lock:
            return self._would_exceed(int(nbytes), limits, self._now(now),
                                      headroom, int(reserve_bytes))

    def admit(self, nbytes: int, limits: Limits, now: float | None = None,
              headroom: float = 0.0, reserve_bytes: int = 0) -> bool:
        """Atomically check ``would_exceed`` and, if the bytes fit, record
        them. Returns whether they were recorded."""
        with self._lock:
            t = self._now(now)
            if self._would_exceed(int(nbytes), limits, t, headroom,
                                  int(reserve_bytes)):
                return False
            self._add(int(nbytes), t)
            return True

    def time_until_admit(self, nbytes: int, limits: Limits,
                         now: float | None = None, headroom: float = 0.0,
                         reserve_bytes: int = 0) -> float:
        """Seconds until ``nbytes`` would be admitted if nothing else is
        sent - 0 when they fit now. Walks the oldest entries of each broken
        window forward until enough of them have aged out."""
        with self._lock:
            t = self._now(now)
            self._prune(t)
            worst = 0.0
            for window_s, bit_s in limits:
                window_s = float(window_s)
                cap = self._capacity(window_s, bit_s, headroom) - int(reserve_bytes)
                used = self._bytes_in(window_s, t)
                deficit = used + int(nbytes) - cap
                if deficit <= 0:
                    continue
                if int(nbytes) > cap:
                    return float("inf")     # never fits, whatever ages out
                freed = 0
                for et, en in self._events:     # oldest first
                    if et <= t - window_s:
                        continue                # already outside this window
                    freed += en
                    if freed >= deficit:
                        worst = max(worst, et + window_s - t)
                        break
            return worst

    # -- internals (lock held) --------------------------------------------------

    @staticmethod
    def _now(now: float | None) -> float:
        return time.time() if now is None else float(now)

    def _add(self, nbytes: int, t: float) -> None:
        self._prune(t)
        self._events.append((t, nbytes))
        self._total += nbytes

    def _prune(self, t: float) -> None:
        cutoff = t - self._span
        ev = self._events
        while ev and ev[0][0] <= cutoff:
            self._total -= ev.popleft()[1]

    def _bytes_in(self, window_s: float, t: float) -> int:
        self._prune(t)
        if window_s >= self._span:
            return self._total
        cutoff = t - window_s
        n = 0
        for et, en in reversed(self._events):   # newest first; short window
            if et <= cutoff:
                break
            n += en
        return n

    @staticmethod
    def _capacity(window_s: float, bit_s: float, headroom: float) -> float:
        return bit_s * window_s / 8.0 * (1.0 - headroom)

    def _would_exceed(self, nbytes: int, limits: Limits, t: float,
                      headroom: float, reserve_bytes: int) -> bool:
        for window_s, bit_s in limits:
            window_s = float(window_s)
            cap = self._capacity(window_s, bit_s, headroom)
            if self._bytes_in(window_s, t) + nbytes + reserve_bytes > cap:
                return True
        return False
