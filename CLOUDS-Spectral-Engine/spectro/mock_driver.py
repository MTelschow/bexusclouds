"""Synthetic EURECA Duo - lets the UI and verify scripts run with no hardware.

Reproduces the character of the real readout we measured: a ~1500-count
baseline, a regular fixed-pattern comb near half-scale, and two spectral bumps
inside the Ch1 (px 0-235) and Ch2 (px 1516-1766) windows that grow with
exposure and clip at saturation (~65520). Pixels between the windows are dark.
"""
from __future__ import annotations

import numpy as np

from .driver import DeviceInfo, SpectrometerDriver

_BASELINE = 1500.0
_COMB_PERIOD = 37
_COMB_LEVEL = 32000.0
_SAT = 65520
_READ_NOISE = 12.0


class MockDriver(SpectrometerDriver):
    PIXELS = 2048

    def __init__(self, seed: int = 0, **_kw):
        self._rng = np.random.default_rng(seed)
        self._exp_us = 100_000
        self._fc = 0
        self._comb = np.zeros(self.PIXELS, dtype=np.float64)
        self._comb[::_COMB_PERIOD] = _COMB_LEVEL
        self._shape = self._build_shape()

    def _build_shape(self) -> np.ndarray:
        x = np.arange(self.PIXELS)
        ch1 = np.exp(-0.5 * ((x - 120) / 45.0) ** 2) * ((x >= 0) & (x <= 235))
        ch2 = 0.8 * np.exp(-0.5 * ((x - 1660) / 55.0) ** 2) * ((x >= 1516) & (x <= 1766))
        return ch1 + ch2

    def connect(self) -> DeviceInfo:
        return DeviceInfo(
            model="e9u_LSMD-TCD1304-PRO", serial="MOCK-0001",
            com_port="\\\\.\\MOCK", pixels=self.PIXELS, firmware="mock",
            raw="synthetic Duo", mock=True,
        )

    def set_times_us(self, exposure_us: int, frame_us: int | None = None) -> None:
        self._exp_us = int(exposure_us)

    def grab(self, discard: int = 0) -> np.ndarray:
        self._fc += 1 + max(0, discard)
        ms = self._exp_us / 1000.0
        frame = _BASELINE + self._comb + self._shape * (ms * 900.0)
        frame += self._rng.normal(0.0, _READ_NOISE, self.PIXELS)
        return np.clip(frame, 0, _SAT).astype(np.uint16)

    def dark_value(self):
        return _BASELINE

    def frame_counter(self):
        return self._fc

    def close(self) -> None:
        pass
