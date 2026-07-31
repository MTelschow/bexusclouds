"""UART link to the RP2350: COBS-framed CLOUDS frames over a byte transport.

Transports are pluggable so the whole link is testable without hardware:
``SerialTransport`` (pyserial, on the Pi) or ``PipeTransport`` (in-memory
pair used by the tests and by the fake-MCU end-to-end harness).
"""
from __future__ import annotations

import queue
import threading
import time

from clouds_link import cobs, frames

DELIMITER = b"\x00"
MAX_FRAME = 4200


class Transport:
    def read(self, timeout: float) -> bytes:  # pragma: no cover - interface
        raise NotImplementedError

    def write(self, data: bytes) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        pass


class SerialTransport(Transport):
    """pyserial-backed transport (lazy import: not needed for tests)."""

    def __init__(self, port: str, baud: int):
        import serial  # noqa: PLC0415
        self._ser = serial.Serial(port, baud, timeout=0.1)

    def read(self, timeout: float) -> bytes:
        self._ser.timeout = timeout
        n = max(1, self._ser.in_waiting)
        return self._ser.read(n)

    def write(self, data: bytes) -> None:
        self._ser.write(data)

    def close(self) -> None:
        self._ser.close()


class PipeTransport(Transport):
    """One end of an in-memory byte pipe. Create pairs with ``pair()``."""

    def __init__(self, rx: "queue.Queue[bytes]", tx: "queue.Queue[bytes]"):
        self._rx, self._tx = rx, tx

    @classmethod
    def pair(cls) -> tuple["PipeTransport", "PipeTransport"]:
        a: queue.Queue = queue.Queue()
        b: queue.Queue = queue.Queue()
        return cls(a, b), cls(b, a)

    def read(self, timeout: float) -> bytes:
        try:
            return self._rx.get(timeout=timeout)
        except queue.Empty:
            return b""

    def write(self, data: bytes) -> None:
        self._tx.put(bytes(data))


class UartLink:
    """Framing + background reader. ``on_frame(Frame)`` runs on the reader
    thread; keep handlers quick and exception-safe."""

    def __init__(self, transport: Transport, on_frame=None):
        self._t = transport
        self._on_frame = on_frame
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.rx_frames = 0
        self.rx_errors = 0
        self.last_rx: float = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._reader, daemon=True,
                                        name="uart-reader")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._t.close()

    def alive(self, within_s: float) -> bool:
        """MCU liveness: any valid frame within the window (S.9 mirror)."""
        return self.last_rx > 0 and (time.time() - self.last_rx) <= within_s

    def send(self, frame: frames.Frame) -> None:
        wire = cobs.encode(frame.encode()) + DELIMITER
        with self._lock:
            self._t.write(wire)

    def _reader(self) -> None:
        while not self._stop.is_set():
            chunk = self._t.read(timeout=0.2)
            if not chunk:
                continue
            self._buf.extend(chunk)
            while DELIMITER in self._buf:
                raw, _, rest = self._buf.partition(DELIMITER)
                self._buf = bytearray(rest)
                if not raw:
                    continue
                self._handle(bytes(raw))
            if len(self._buf) > MAX_FRAME:   # noise without delimiter
                self._buf.clear()
                self.rx_errors += 1

    def _handle(self, raw: bytes) -> None:
        try:
            frame = frames.decode(cobs.decode(raw))
        except (cobs.CobsError, frames.FrameError):
            self.rx_errors += 1
            return
        self.rx_frames += 1
        self.last_rx = time.time()
        if self._on_frame is not None:
            try:
                self._on_frame(frame)
            except Exception:   # noqa: BLE001 - reader thread must survive
                self.rx_errors += 1
