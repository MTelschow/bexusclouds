"""CLOUDS packet frame: header + payload + CRC-16 (spec section 3, S.5).

Layout (little-endian), identical on UDP downlink and UART (UART adds COBS):

    offset  size  field
    0       2     magic       0xC7 0x1D
    2       1     version     1
    3       1     type        PacketType
    4       2     seq         u16, per-sender, wraps
    6       4     t_s         u32 unix seconds (synced timebase, S.4)
    10      2     t_ms        u16 milliseconds 0..999
    12      2     plen        u16 payload length
    14      n     payload
    14+n    2     crc16       CCITT-FALSE over bytes [0, 14+n)

C mirror: flight/mcu/src/core/frame.c - keep byte-for-byte identical.
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field
from enum import IntEnum

from .crc16 import crc16

MAGIC = b"\xC7\x1D"
VERSION = 1
HEADER = struct.Struct("<2sBBHIHH")
HEADER_LEN = HEADER.size          # 14
CRC_LEN = 2
MAX_PAYLOAD = 4096


class FrameError(ValueError):
    pass


class PacketType(IntEnum):
    HK = 0x01          # MCU housekeeping (payload: hk.py)
    EVENT = 0x02       # code u8, severity u8, utf-8 text
    QUICKLOOK = 0x03   # channel u8, bin u8, exposure_ms u16, n u16, n x u16
    PISTATUS = 0x04    # Pi health (payload below)
    CMD = 0x10         # cmd u8, key u8, value i32
    ACK = 0x11         # cmd_seq u16, cmd u8, result u8
    TIMESYNC = 0x12    # t_s u32, t_ms u16


class AckResult(IntEnum):
    OK = 0
    REJECTED = 1
    INVALID = 2
    NOT_ARMED = 3      # arm/execute violated (S.8)
    INTERLOCK = 4      # ground interlock (S.10)


class EventSeverity(IntEnum):
    INFO = 0
    WARNING = 1
    ERROR = 2
    CRITICAL = 3


@dataclass
class Frame:
    type: int
    payload: bytes = b""
    seq: int = 0
    t_s: int = 0
    t_ms: int = 0
    version: int = VERSION

    def stamp(self, t: float | None = None) -> "Frame":
        t = time.time() if t is None else t
        self.t_s = int(t)
        self.t_ms = int((t - self.t_s) * 1000)
        return self

    @property
    def timestamp(self) -> float:
        return self.t_s + self.t_ms / 1000.0

    def encode(self) -> bytes:
        if len(self.payload) > MAX_PAYLOAD:
            raise FrameError(f"payload too large: {len(self.payload)}")
        head = HEADER.pack(MAGIC, self.version, self.type,
                           self.seq & 0xFFFF, self.t_s & 0xFFFFFFFF,
                           self.t_ms, len(self.payload))
        body = head + self.payload
        return body + struct.pack("<H", crc16(body))


def decode(data: bytes) -> Frame:
    if len(data) < HEADER_LEN + CRC_LEN:
        raise FrameError(f"frame too short: {len(data)} bytes")
    magic, version, ptype, seq, t_s, t_ms, plen = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise FrameError("bad magic")
    if version != VERSION:
        raise FrameError(f"unsupported protocol version {version}")
    end = HEADER_LEN + plen
    if len(data) < end + CRC_LEN:
        raise FrameError("frame truncated")
    (crc,) = struct.unpack_from("<H", data, end)
    if crc != crc16(data[:end]):
        raise FrameError("CRC mismatch")
    return Frame(type=ptype, payload=bytes(data[HEADER_LEN:end]),
                 seq=seq, t_s=t_s, t_ms=t_ms, version=version)


def try_parse_stream(buf: bytes) -> tuple["Frame | None", int]:
    """Parse one frame off the front of a TCP byte stream.

    Frames are self-delimiting (header carries the payload length). Returns
    ``(frame, bytes_consumed)``; ``(None, 0)`` = need more data, and
    ``(None, n>0)`` = n bytes of garbage dropped to resynchronise.
    """
    if len(buf) < HEADER_LEN:
        return None, 0
    if buf[:2] != MAGIC:
        nxt = buf.find(MAGIC, 1)
        return None, len(buf) if nxt < 0 else nxt
    plen = int.from_bytes(buf[12:14], "little")
    if plen > MAX_PAYLOAD:
        return None, 2   # bogus header: skip the magic, resync
    total = HEADER_LEN + plen + CRC_LEN
    if len(buf) < total:
        return None, 0
    try:
        return decode(buf[:total]), total
    except FrameError:
        return None, 2


class SeqCounter:
    """Per-sender sequence numbers (wraps at 2^16)."""

    def __init__(self, start: int = 0):
        self._n = start

    def next(self) -> int:
        n = self._n
        self._n = (self._n + 1) & 0xFFFF
        return n


#: Packet types with more than one independent sender, so no single sequence
#: space exists for them: EVENT is emitted both by the MCU (`ev_seq_no`) and by
#: the Pi itself, and the Pi relays the MCU's frames byte-identical - two
#: counters interleaved under one type. Counting gaps there would invent losses
#: on a clean link, so they are recorded but never charged. Detecting *event*
#: loss would need a distinct packet type per origin, not a smarter gap rule.
UNSEQUENCED_TYPES = frozenset({PacketType.EVENT})


@dataclass
class GapStats:
    """Downlink sequence-gap tracking (GSE feature G-07).

    One sequence space per packet type: both the MCU firmware and the Pi's
    ``Downlink`` number each type independently, so gaps are only meaningful
    within a type. See ``UNSEQUENCED_TYPES`` for the dual-origin exception.
    """
    received: int = 0
    lost: int = 0
    unsequenced: int = 0
    _last: dict = field(default_factory=dict)

    def update(self, ptype: int, seq: int) -> int:
        """Record one packet; returns packets charged as lost before it."""
        self.received += 1
        if ptype in UNSEQUENCED_TYPES:
            self.unsequenced += 1
            return 0
        last = self._last.get(ptype)
        self._last[ptype] = seq
        if last is None:
            return 0
        gap = (seq - last - 1) & 0xFFFF
        if gap > 0x7FFF:      # reordering/restart, not loss
            gap = 0
        self.lost += gap
        return gap


# -- payload helpers ---------------------------------------------------------

_QL_HEAD = struct.Struct("<BBHH")
_PISTATUS = struct.Struct("<IIBBh")
_CMD = struct.Struct("<BBi")
_ACK = struct.Struct("<HBB")
_TSYNC = struct.Struct("<IH")


def pack_quicklook(channel: int, bin_factor: int, exposure_ms: int,
                   counts) -> bytes:
    counts = list(counts)
    return _QL_HEAD.pack(channel, bin_factor, min(exposure_ms, 0xFFFF),
                         len(counts)) + struct.pack(
        f"<{len(counts)}H", *(min(int(c), 0xFFFF) for c in counts))


def unpack_quicklook(payload: bytes) -> dict:
    ch, binf, exp_ms, n = _QL_HEAD.unpack_from(payload)
    counts = struct.unpack_from(f"<{n}H", payload, _QL_HEAD.size)
    return {"channel": ch, "bin": binf, "exposure_ms": exp_ms,
            "counts": list(counts)}


def pack_pistatus(disk_free_mb: int, spectra_count: int, uart_ok: bool,
                  spectro_ok: bool, cpu_temp_cc: int) -> bytes:
    return _PISTATUS.pack(disk_free_mb, spectra_count, int(uart_ok),
                          int(spectro_ok), cpu_temp_cc)


def unpack_pistatus(payload: bytes) -> dict:
    d, s, u, sp, t = _PISTATUS.unpack_from(payload)
    return {"disk_free_mb": d, "spectra_count": s, "uart_ok": bool(u),
            "spectro_ok": bool(sp), "cpu_temp_cc": t}


def pack_cmd(cmd: int, key: int = 0, value: int = 0) -> bytes:
    return _CMD.pack(cmd, key, value)


def unpack_cmd(payload: bytes) -> tuple[int, int, int]:
    return _CMD.unpack_from(payload)


def pack_ack(cmd_seq: int, cmd: int, result: int) -> bytes:
    return _ACK.pack(cmd_seq, cmd, result)


def unpack_ack(payload: bytes) -> tuple[int, int, int]:
    return _ACK.unpack_from(payload)


def pack_timesync(t: float) -> bytes:
    t_s = int(t)
    return _TSYNC.pack(t_s & 0xFFFFFFFF, int((t - t_s) * 1000))


def unpack_timesync(payload: bytes) -> float:
    t_s, t_ms = _TSYNC.unpack_from(payload)
    return t_s + t_ms / 1000.0


def pack_event(code: int, severity: int, text: str = "") -> bytes:
    return bytes([code, severity]) + text.encode("utf-8")[:64]


def unpack_event(payload: bytes) -> dict:
    return {"code": payload[0], "severity": payload[1],
            "text": payload[2:].decode("utf-8", "replace")}
