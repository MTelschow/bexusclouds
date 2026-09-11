"""A dark frame that survives a restart.

A dark frame is the detector's own output with no light on it - pedestal,
per-pixel offset and dark current - and subtracting it is what makes counts
mean anything. Capturing one takes a darkened bench, so re-taking it on every
start of the operator interface is work the operator should not have to repeat:
this module stores the captured frame next to the calibration and loads it
back.

Two rules keep a stored dark from becoming a lie:

* **It is only valid at the exposure it was taken at.** Dark current scales
  with integration time, so a 10 ms dark subtracted from a 200 ms frame
  removes the wrong pedestal - and the result still looks like a spectrum.
  ``exposure_us`` therefore travels with the counts and the UI withholds the
  subtraction when the two disagree, rather than quietly using it.
* **It belongs to one detector.** ``pixels``, ``model`` and ``serial`` travel
  with it, and a frame whose length does not match the detector in front of
  you is refused (``DarkError``) instead of being broadcast onto the wrong
  geometry.

The file is `.npz` (numpy, self-describing, no pickle) at
``CLOUDS_DARK`` or ``<repo>/dark_frame.npz``. It is instrument state, not
configuration: regenerable in one button press, so it is not committed.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import numpy as np


class DarkError(RuntimeError):
    """A stored dark frame exists but cannot be used as it is."""


DEFAULT_NAME = "dark_frame.npz"
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_path() -> str:
    """``CLOUDS_DARK`` if set, else ``dark_frame.npz`` beside the calibration."""
    return os.environ.get("CLOUDS_DARK") or os.path.join(_REPO, DEFAULT_NAME)


@dataclass
class DarkFrame:
    """One captured dark, with the conditions that make it meaningful."""

    counts: np.ndarray
    exposure_us: int
    navg: int = 1
    clean: bool = True              # glitch filter on during capture
    captured_t: float = field(default_factory=time.time)
    model: str = ""
    serial: str = ""
    source: str = ""                # "std", "net 192.168.100.10", ...

    @property
    def pixels(self) -> int:
        return int(np.asarray(self.counts).size)

    @property
    def exposure_ms(self) -> float:
        return self.exposure_us / 1000.0

    @property
    def mean(self) -> float:
        return float(np.asarray(self.counts, dtype=float).mean())

    def matches_exposure(self, exposure_us: int, tol_us: int = 1) -> bool:
        return abs(int(exposure_us) - int(self.exposure_us)) <= tol_us

    def summary(self) -> str:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.captured_t))
        return (f"{self.exposure_ms:g} ms  x{self.navg}  "
                f"mean {self.mean:.0f} ct  {when}")


def save(dark: DarkFrame, path: str | None = None) -> str:
    """Write ``dark`` and return the path it went to."""
    path = path or default_path()
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    np.savez(path,
             counts=np.asarray(dark.counts, dtype=np.float32),
             exposure_us=np.int64(dark.exposure_us),
             navg=np.int64(dark.navg),
             clean=np.bool_(dark.clean),
             captured_t=np.float64(dark.captured_t),
             model=np.str_(dark.model),
             serial=np.str_(dark.serial),
             source=np.str_(dark.source))
    return path


def load(path: str | None = None, pixels: int | None = None) -> DarkFrame | None:
    """Read the stored dark, or ``None`` if there is none.

    ``pixels`` is the detector in front of you: a stored frame of a different
    length is a different instrument (or a different channel layout) and
    raises ``DarkError`` rather than being resized onto this one.
    """
    path = path or default_path()
    if not os.path.isfile(path):
        return None
    try:
        with np.load(path, allow_pickle=False) as z:
            dark = DarkFrame(
                counts=np.asarray(z["counts"], dtype=float),
                exposure_us=int(z["exposure_us"]),
                navg=int(z["navg"]),
                clean=bool(z["clean"]),
                captured_t=float(z["captured_t"]),
                model=str(z["model"]),
                serial=str(z["serial"]),
                source=str(z["source"]))
    except (OSError, ValueError, KeyError) as e:
        raise DarkError(f"stored dark frame {path} is unreadable: {e}") from e
    if dark.counts.ndim != 1 or dark.pixels == 0:
        raise DarkError(f"stored dark frame {path} is not a single frame")
    if pixels is not None and dark.pixels != int(pixels):
        raise DarkError(
            f"stored dark frame {path} is {dark.pixels} px, this detector is "
            f"{int(pixels)} px - capture a new dark")
    return dark


def clear(path: str | None = None) -> bool:
    """Delete the stored dark. ``True`` if there was one."""
    path = path or default_path()
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False
