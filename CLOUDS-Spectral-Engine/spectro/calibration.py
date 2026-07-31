"""Pixel <-> wavelength calibration for the CLOUDS dual-spectrometer.

Loads the factory INSION polynomials from ``calibration.json`` and provides
pixel->nm mapping and channel slicing for the EURECA Duo (two fibre channels on
one 2048-px detector). Hardware-free: pure data + numpy.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_JSON = os.path.normpath(os.path.join(_HERE, os.pardir, "calibration.json"))


@dataclass(frozen=True)
class Channel:
    """One fibre channel: a contiguous pixel window with its own pixel->nm fit."""

    name: str
    role: str                       # "measurement" | "reference"
    pixel_window: tuple[int, int]   # inclusive [lo, hi]
    a: float
    b: float
    c: float
    range_nm: tuple[float, float]
    fwhm_nm: float
    intensity_correction: float

    @property
    def pixels(self) -> np.ndarray:
        lo, hi = self.pixel_window
        return np.arange(lo, hi + 1, dtype=np.int32)

    def pixel_to_nm(self, x) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        return self.a * x * x + self.b * x + self.c

    @property
    def wavelengths(self) -> np.ndarray:
        """nm for every pixel in this channel's window (monotonic increasing)."""
        return self.pixel_to_nm(self.pixels)

    def slice(self, frame) -> np.ndarray:
        """Counts for this channel's pixel window out of a full detector frame."""
        lo, hi = self.pixel_window
        return np.asarray(frame)[lo:hi + 1]


@dataclass
class Calibration:
    instrument: dict
    channels: tuple[Channel, ...]
    source: str

    @property
    def n_pixels(self) -> int:
        return int(self.instrument.get("pixels", 2048))

    @property
    def saturation_count(self) -> int:
        return int(self.instrument.get("saturation_count", 65520))

    def channel(self, name: str) -> Channel:
        for ch in self.channels:
            if ch.name == name:
                return ch
        raise KeyError(name)

    def by_role(self, role: str) -> Channel:
        for ch in self.channels:
            if ch.role == role:
                return ch
        raise KeyError(role)

    def by_role_optional(self, role: str):
        """Like by_role but returns None instead of raising - for single-channel
        instruments that have no reference channel (see calibration_single.json)."""
        for ch in self.channels:
            if ch.role == role:
                return ch
        return None

    def set_poly(self, role: str, a: float, b: float, c: float) -> None:
        """Replace one channel's pixel->nm polynomial (e.g. from a recalibration)."""
        out = []
        for ch in self.channels:
            if ch.role == role:
                lo, hi = ch.pixel_window
                w0, w1 = a * lo * lo + b * lo + c, a * hi * hi + b * hi + c
                ch = replace(ch, a=a, b=b, c=c, range_nm=(min(w0, w1), max(w0, w1)))
            out.append(ch)
        self.channels = tuple(out)

    def to_dict(self) -> dict:
        return {
            "schema": "clouds-spectral-calibration/1",
            "instrument": self.instrument,
            "source": self.source,
            "wavelength_model": "poly2",
            "wavelength_formula": "nm = a*x^2 + b*x + c   (x = pixel index)",
            "channels": [{
                "name": ch.name, "role_default": ch.role,
                "pixel_window": [ch.pixel_window[0], ch.pixel_window[1]],
                "poly": {"a": ch.a, "b": ch.b, "c": ch.c},
                "range_nm": [ch.range_nm[0], ch.range_nm[1]],
                "fwhm_nm": ch.fwhm_nm, "intensity_correction": ch.intensity_correction,
            } for ch in self.channels],
            "notes": ["Written by the CLOUDS Spectral Engine interactive calibration."],
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str | None = None) -> "Calibration":
        path = path or os.environ.get("CLOUDS_CALIBRATION") or _DEFAULT_JSON
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        sat = int(d.get("instrument", {}).get("saturation_count", 65520))
        if sat <= 0:
            raise ValueError(f"calibration saturation_count must be > 0, got {sat} ({path})")
        channels = []
        for c in d["channels"]:
            p = c["poly"]
            channels.append(
                Channel(
                    name=c["name"],
                    role=c.get("role", c.get("role_default", "measurement")),
                    pixel_window=(int(c["pixel_window"][0]), int(c["pixel_window"][1])),
                    a=float(p["a"]), b=float(p["b"]), c=float(p["c"]),
                    range_nm=(float(c["range_nm"][0]), float(c["range_nm"][1])),
                    fwhm_nm=float(c.get("fwhm_nm", 0.0)),
                    intensity_correction=float(c.get("intensity_correction", 1.0)),
                )
            )
        return cls(
            instrument=d.get("instrument", {}),
            channels=tuple(channels),
            source=d.get("source", ""),
        )


def subtract_dark(frame, dark) -> np.ndarray:
    """``frame - dark`` clipped at 0. ``dark=None`` returns the frame unchanged."""
    f = np.asarray(frame, dtype=np.float64)
    if dark is None:
        return f
    return np.clip(f - np.asarray(dark, dtype=np.float64), 0.0, None)
