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

# Windows: SIO_UDP_CONNRESET. Off by default, a UDP socket is told about ICMP
# port-unreachable replies by failing its next recvfrom with WSAECONNRESET -
# an error about a datagram that already left, reported against a socket that
# is fine. The receiver thread catches it too (belt and braces), but turning
# the behaviour off is the documented fix. No-op everywhere else.
_SIO_UDP_CONNRESET = 0x9800000C


def _suppress_udp_conn_reset(sock: socket.socket) -> None:
    if not hasattr(sock, "ioctl"):      # not Windows
        return
    try:
        sock.ioctl(_SIO_UDP_CONNRESET, False)
    except (OSError, AttributeError, ValueError):
        pass                            # best-effort; the except clause covers us


class Receiver:
    def __init__(self, bind: str = "0.0.0.0", port: int = 4000,
                 on_hk=None, on_quicklook=None, on_event=None,
                 on_pistatus=None):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._sock.bind((bind, port))
        except OSError as exc:
            self._sock.close()
            raise OSError(
                f"cannot bind UDP {bind}:{port} for the downlink ({exc}). "
                f"Another GSE or GUI is probably already listening - close it, "
                f"or start this one with --listen <other port>."
            ) from exc
        self._sock.settimeout(0.2)
        _suppress_udp_conn_reset(self._sock)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cb = {"hk": on_hk, "ql": on_quicklook, "ev": on_event,
                    "pi": on_pistatus}

        self.gaps = GapStats()
        self.decode_errors = 0
        # Wire counters for the traffic indicator (clouds_ui/traffic.py).
        # Counted where the datagram arrives, not after decode: a frame that
        # fails CRC still spent link budget, and a link that is delivering
        # nothing but garbage must not look idle. UDP payload bytes only -
        # the IP/UDP headers are the network's, not the downlink's.
        self.rx_bytes = 0
        self.rx_packets = 0
        self.last_rx_time: float = 0.0
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
            except ConnectionResetError:
                # Windows only: an ICMP port-unreachable for an earlier
                # datagram surfaces as WSAECONNRESET on the *next* recvfrom of
                # a connectionless socket. It says nothing about this socket's
                # health, and treating it as fatal silently ends the downlink
                # for the rest of the session. See _suppress_udp_conn_reset.
                continue
            except OSError:
                return
            self._handle(raw)

    def _handle(self, raw: bytes) -> None:
        self.rx_bytes += len(raw)
        self.rx_packets += 1
        self.last_rx_time = time.time()
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
