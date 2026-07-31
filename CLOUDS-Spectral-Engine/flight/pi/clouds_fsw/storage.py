"""Onboard storage (O.3, S.5): CRC'd binary spectra records + comms log.

Record format (little-endian), file magic ``CSF1`` once at file start:

    t_s u32, t_ms u16, exposure_us u32, flags u8, n u16, counts n x u16,
    crc16 u16 over the record bytes before the CRC

Files rotate every ``rotate_s`` (default 10 min) so one corruption event
costs at most one rotation period of one stream (S.6 rationale).
"""
from __future__ import annotations

import os
import struct
import threading
import time

from clouds_link.crc16 import crc16

FILE_MAGIC = b"CSF1"
_REC_HEAD = struct.Struct("<IHIBH")

FLAG_SATURATED = 1 << 0
FLAG_MOCK = 1 << 1


class _RotatingFile:
    """Thread-safe: the writer thread and a shutdown from another thread
    may race on rotation/close - every file operation holds the lock."""

    def __init__(self, directory: str, prefix: str, suffix: str,
                 rotate_s: float, binary: bool, header: bytes = b""):
        self._dir = directory
        self._prefix, self._suffix = prefix, suffix
        self._rotate_s = rotate_s
        self._binary = binary
        self._header = header
        self._fh = None
        self._opened_at = 0.0
        self._lock = threading.Lock()
        os.makedirs(directory, exist_ok=True)

    def _open_new(self, now: float) -> None:
        self._close_locked()
        stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime(now))
        path = os.path.join(self._dir, f"{self._prefix}{stamp}{self._suffix}")
        i = 0
        while os.path.exists(path):   # same-second rotation (tests)
            i += 1
            path = os.path.join(
                self._dir, f"{self._prefix}{stamp}_{i}{self._suffix}")
        self._fh = open(path, "wb" if self._binary else "w",
                        encoding=None if self._binary else "utf-8")
        if self._binary and self._header:
            self._fh.write(self._header)
        self._opened_at = now

    def write(self, data, now: float) -> None:
        with self._lock:
            if self._fh is None or (now - self._opened_at) >= self._rotate_s:
                self._open_new(now)
            self._fh.write(data)

    def flush(self) -> None:
        with self._lock:
            if self._fh:
                self._fh.flush()
                os.fsync(self._fh.fileno())

    def _close_locked(self) -> None:
        if self._fh:
            self._fh.flush()
            self._fh.close()
            self._fh = None

    def close(self) -> None:
        with self._lock:
            self._close_locked()


class FrameStore:
    """Buffered block writes; flush every ``flush_every`` records (write
    strategy from SED section 4.11e: storage copy is never dropped)."""

    def __init__(self, directory: str, rotate_s: float = 600.0,
                 flush_every: int = 10):
        self._file = _RotatingFile(directory, "spectra_", ".csb",
                                   rotate_s, binary=True, header=FILE_MAGIC)
        self._flush_every = max(1, flush_every)
        self.count = 0

    def write(self, t: float, counts, exposure_us: int, flags: int = 0,
              now: float | None = None) -> None:
        t_s = int(t)
        t_ms = int((t - t_s) * 1000)
        body = _REC_HEAD.pack(t_s & 0xFFFFFFFF, t_ms, exposure_us,
                              flags & 0xFF, len(counts))
        body += struct.pack(f"<{len(counts)}H",
                            *(int(c) & 0xFFFF for c in counts))
        rec = body + struct.pack("<H", crc16(body))
        self._file.write(rec, time.time() if now is None else now)
        self.count += 1
        if self.count % self._flush_every == 0:
            self._file.flush()

    def close(self) -> None:
        self._file.close()


class StorageError(ValueError):
    pass


def read_spectra(path: str, strict: bool = True):
    """Yield ``(t, exposure_us, flags, counts)`` records, verifying CRCs.

    strict=False skips corrupt records instead of raising (recovery mode,
    pre-flight tool R-03)."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != FILE_MAGIC:
        raise StorageError(f"not a CLOUDS spectra file: {path}")
    idx = 4
    while idx < len(data):
        if idx + _REC_HEAD.size > len(data):
            if strict:
                raise StorageError("truncated record header")
            return
        t_s, t_ms, exp_us, flags, n = _REC_HEAD.unpack_from(data, idx)
        end = idx + _REC_HEAD.size + 2 * n
        if end + 2 > len(data):
            if strict:
                raise StorageError("truncated record body")
            return
        body = data[idx:end]
        (crc,) = struct.unpack_from("<H", data, end)
        if crc != crc16(body):
            if strict:
                raise StorageError(f"CRC mismatch at offset {idx}")
            idx = end + 2
            continue
        counts = struct.unpack_from(f"<{n}H", data, idx + _REC_HEAD.size)
        yield (t_s + t_ms / 1000.0, exp_us, flags, list(counts))
        idx = end + 2


class CommLog:
    """Timestamped text log of all up/downlink + UART traffic (P-07)."""

    def __init__(self, directory: str, rotate_s: float = 600.0):
        self._file = _RotatingFile(directory, "comms_", ".log",
                                   rotate_s, binary=False)

    def log(self, direction: str, what: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now))
        self._file.write(
            f"{stamp}.{int((now % 1) * 1000):03d} {direction:4s} {what}\n", now)
        self._file.flush()

    def close(self) -> None:
        self._file.close()
