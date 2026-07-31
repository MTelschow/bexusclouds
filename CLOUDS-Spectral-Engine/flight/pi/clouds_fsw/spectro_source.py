"""Spectrometer acquisition thread: 1 Hz frames (P.3), saturation flagging,
reconnect-on-failure (P-10), optional auto-exposure guard (P-09).

Reuses the repo's ``spectro`` package: driver interface + factory
(``open_driver``), calibration channel windows, and the glitch-robust peak
detector from processing.py for the exposure guard.
"""
from __future__ import annotations

import threading
import time

from spectro.driver import DriverError
from spectro.processing import robust_peak, saturated_fraction

from .storage import FLAG_MOCK, FLAG_SATURATED

_EXP_MIN_US = 1_000
_EXP_MAX_US = 1_000_000


class SpectroSource:
    """``on_frame(t, counts_u16, exposure_us, flags)`` fires once per sample
    on the acquisition thread."""

    def __init__(self, driver_factory, calibration, on_frame,
                 interval_s: float = 1.0, exposure_us: int = 100_000,
                 auto_exposure: bool = False, reconnect_s: float = 5.0,
                 on_status=None):
        self._factory = driver_factory
        self._cal = calibration
        self._on_frame = on_frame
        self._on_status = on_status or (lambda ok: None)
        self._interval = interval_s
        self._exposure_us = exposure_us
        self._auto = auto_exposure
        self._reconnect_s = reconnect_s
        self._driver = None
        self._info = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected = False
        self.frames = 0
        self.errors = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="spectro")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._close()

    def _close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.close()
            except Exception:  # noqa: BLE001
                pass
            self._driver = None
        if self.connected:
            self.connected = False
            self._on_status(False)

    def _connect(self) -> bool:
        try:
            self._driver = self._factory()
            self._info = self._driver.connect()
            self._driver.set_times_us(self._exposure_us)
            self.connected = True
            self._on_status(True)
            return True
        except (DriverError, Exception):  # noqa: BLE001
            self._close()
            return False

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._driver is None:
                if not self._connect():
                    self._stop.wait(self._reconnect_s)   # P-10 retry loop
                    continue
            t0 = time.time()
            try:
                counts = self._driver.grab()
            except (DriverError, Exception):  # noqa: BLE001
                self.errors += 1
                self._close()                            # P-10: degrade, retry
                continue
            flags = self._flags(counts)
            self.frames += 1
            try:
                self._on_frame(t0, counts, self._exposure_us, flags)
            except Exception:  # noqa: BLE001 - acquisition must survive
                self.errors += 1
            if self._auto:
                self._exposure_guard(counts)
            # hold the 1 Hz cadence regardless of grab duration
            remaining = self._interval - (time.time() - t0)
            if remaining > 0:
                self._stop.wait(remaining)

    def _flags(self, counts) -> int:
        sat = self._cal.saturation_count
        flags = 0
        for ch in self._cal.channels:
            if saturated_fraction(ch.slice(counts), sat) > 0:
                flags |= FLAG_SATURATED
        if getattr(self._info, "mock", False):
            flags |= FLAG_MOCK
        return flags

    def _exposure_guard(self, counts) -> None:
        """P-09 optional servo: keep the brightest channel peak in a safe
        band. Glitch-robust peak, so a USB spike cannot slam the exposure."""
        sat = self._cal.saturation_count
        peak = max(robust_peak(ch.slice(counts)) for ch in self._cal.channels)
        new = self._exposure_us
        if peak >= 0.90 * sat:
            new = int(self._exposure_us * 0.5)
        elif peak < 0.20 * sat:
            new = int(self._exposure_us * 1.5)
        new = min(max(new, _EXP_MIN_US), _EXP_MAX_US)
        if new != self._exposure_us and self._driver is not None:
            try:
                self._driver.set_times_us(new)
                self._exposure_us = new
            except Exception:  # noqa: BLE001
                self.errors += 1
