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
  geometry. Length only proves geometry, so the serial is checked too, once
  the detector has answered: ``serial_conflict()`` names the disagreement and
  the UI drops the frame on connect rather than subtracting one instrument's
  pedestal off another's light (a mock reports ``MOCK-0001`` and is dropped by
  the same rule).

The file is `.npz` (numpy, self-describing, no pickle) at
``CLOUDS_DARK`` or ``<repo>/dark_frame.npz``.

``dark_frame.npz`` is **committed** (2026-09-17). It was ignored as instrument
state - regenerable in one button press - which is true on the bench and false
everywhere else: a checkout on a second machine had no dark at all, and the
button needs the Duo and a darkened bench to press. The tracked file is the
bench dark of S/N 20260312-004; it is a starting point, not a measurement
anybody has to keep, and every guard above still applies to it. Capture
overwrites it, `Clear` deletes it (``git checkout dark_frame.npz`` brings the
baseline back). Sessions that must not touch the default - ``--mock``,
``verify_qt.py``, ``qc_live.py`` - point ``CLOUDS_DARK`` at ``output/`` or run
with ``persist_dark=False``, unchanged by this.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import numpy as np


class DarkError(RuntimeError):
    """A stored dark frame exists but cannot be used as it is."""


DEFAULT_NAME = "dark_frame.npz"
# How far a channel window may sit over the covered gap before the dark is
# called lit. The gap's own 99th percentile runs ~2.5 k over its median on
# this detector (hot pixels at the window edges), so a smaller margin would
# call every good dark a leak.
LEAK_MARGIN_CT = 2000.0
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

    def serial_conflict(self, serial: str) -> str:
        """Why this dark does not belong to ``serial``, or ``""``.

        Unknown on either side is not a conflict: darks captured before the
        serial travelled with them, and drivers that do not report one, must
        not start refusing themselves. Two serials that are both known and
        different are a different instrument, and that is a conflict whatever
        the pixel count says - two 2048 px Duos would pass the length check.
        """
        mine, theirs = self.serial.strip(), (serial or "").strip()
        if not mine or not theirs or mine == theirs:
            return ""
        return (f"stored dark is from SN {mine}, this detector is SN {theirs} "
                f"- capture a new dark")

    def light_leak(self, windows, margin_ct: float = LEAK_MARGIN_CT) -> dict:
        """Channels that were lit while this dark was taken.

        The inter-channel gap cannot see light by construction, so it is the
        reference for what "no light" costs on this detector. A fibre that was
        not blocked puts *lines* into its window - the mean barely moves while
        a peak lands 10 k over the gap - so the comparison is on the 99th
        percentile of each, not the mean.

        A dark taken with light on the bench is worse than no dark: it absorbs
        real signal into the baseline and nothing downstream can tell. This
        does not refuse the frame (a leak is a bench mistake, not a corrupt
        file, and the pedestal is still right where nothing leaked) - it names
        it, so the operator can retake it blocked.

        ``windows`` is ``[(name, lo, hi), ...]``, inclusive, as in the
        calibration. Returns ``{name: excess_ct}`` for the lit ones only.
        """
        counts = np.asarray(self.counts, dtype=float)
        gap = np.ones(counts.size, dtype=bool)
        spans = []
        for name, lo, hi in windows:
            lo, hi = max(0, int(lo)), min(counts.size - 1, int(hi))
            if hi < lo:
                continue
            gap[lo:hi + 1] = False
            spans.append((name, lo, hi))
        if not spans or gap.sum() < 32:
            return {}                       # no covered reference to compare to
        ref = float(np.percentile(counts[gap], 99))
        lit = {}
        for name, lo, hi in spans:
            excess = float(np.percentile(counts[lo:hi + 1], 99)) - ref
            if excess > margin_ct:
                lit[name] = excess
        return lit

    def leak_note(self, windows, margin_ct: float = LEAK_MARGIN_CT) -> str:
        """``light_leak`` as one line for the operator, or ``""``."""
        lit = self.light_leak(windows, margin_ct)
        if not lit:
            return ""
        which = ", ".join(f"{n} +{v / 1000:.1f} k"
                          for n, v in sorted(lit.items()))
        return (f"this dark was taken with light on {which} over the covered "
                f"gap - retake it with the fibres blocked")

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
