"""Frame processing: averaging, saturation, and dual-beam ratio views.

Pure numpy, hardware-free. The UI dark-subtracts before calling the ratio
helpers, so ``transmission`` == measurement / reference of the corrected
signals. The two fibre channels sit on different pixel grids, so ratio views
resample both onto a common wavelength grid first.
"""
from __future__ import annotations

import numpy as np


# The USB transfer pins a random ~9% of pixels per frame to a glitch code (commonly
# ~33514, but the value varies with signal). It is a data-path artifact, not photons.
# We detect it as an ISOLATED 1-pixel spike that towers over its HIGHER neighbour:
# value-agnostic (catches any glitch value) and safe, because real spectral lines are
# >=3-4 px wide (instrument FWHM ~7 nm) and always have a high neighbour toward their
# peak, so they are never flagged.
GLITCH_TYPICAL = 33514     # the commonly-seen code, for reference only
# 3.0x gives a wide safety margin: the narrowest real line the instrument can form is
# ~3.7 px (7.4 nm FWHM), fully preserved; only sub-1.5 px spikes (unphysical -> glitches)
# are touched. Baseline glitches tower ~20x over neighbours, so none are missed.
SPIKE_RATIO = 3.0          # a glitch pixel is >= this x its higher neighbour ...
SPIKE_ABS = 4000           # ... and at least this many counts above it
# Longest run of adjacent glitch pixels treated as one spike. At the ~9 % hit
# rate a frame carries ~1.2 runs of three (2048 x 0.09^3 x 0.91^2), and a
# three-run has no towering neighbour inside it, so the 1- and 2-px tests
# left it standing - and an 8-px quick-look bin then read +12 k. Three is the
# limit that is still safe against a real line: at the instrument's own
# resolution (3.7 px FWHM) the run's edge pixels are at most 2.3x their outer
# neighbours (both channels, any pedestal, 2026-09-29), under SPIKE_RATIO.
# Four would be a 4.7 px feature, wider than the narrowest real line.
SPIKE_MAX_PX = 3


def _glitch_mask(row: np.ndarray) -> np.ndarray:
    """Boolean mask of isolated 1..SPIKE_MAX_PX-pixel spikes (USB glitches);
    value-agnostic. Real lines are >=3.7 px (7 nm FWHM), so a spike this
    narrow is always a glitch: every pixel of the run must tower over the
    higher of the two pixels just outside it."""
    f = np.asarray(row, dtype=np.float64)
    n = f.size
    bad = np.zeros(n, dtype=bool)
    for k in range(1, SPIKE_MAX_PX + 1):                # k-pixel-wide runs f[i..i+k-1]
        if n < k + 2:
            break
        outer = np.maximum(f[:-(k + 1)], f[k + 1:])     # max(f[i-1], f[i+k])
        run = f[1:n - k]                                # f[i] for i in 1..n-k-1
        for j in range(1, k):
            run = np.minimum(run, f[1 + j:n - k + j])   # min over the run
        hit = (run > SPIKE_RATIO * outer) & (run - outer > SPIKE_ABS)
        for j in range(k):
            bad[1 + j:n - k + j] |= hit
    if n >= 2:                                          # edge pixels: single neighbour
        if (f[0] > SPIKE_RATIO * f[1]) and (f[0] - f[1] > SPIKE_ABS):
            bad[0] = True
        if (f[-1] > SPIKE_RATIO * f[-2]) and (f[-1] - f[-2] > SPIKE_ABS):
            bad[-1] = True
    return bad


def _despike(row: np.ndarray) -> np.ndarray:
    """Replace glitch pixels (value-band or isolated spike) by interpolation."""
    f = np.asarray(row, dtype=np.float64).copy()
    bad = _glitch_mask(f)
    if bad.any():
        idx = np.arange(f.size)
        good = ~bad
        if good.sum() >= 2:
            f[bad] = np.interp(idx[bad], idx[good], f[good])
    return f


def glitch_fraction(frames) -> float:
    """Fraction of samples flagged as a USB glitch (a live cable-health gauge)."""
    a = np.asarray(frames, dtype=np.float64)
    if a.size == 0:
        return 0.0
    if a.ndim == 1:
        return float(_glitch_mask(a).mean())
    return float(np.mean([_glitch_mask(row).mean() for row in a]))


def average_frames(frames, method: str = "median", clean: bool = True) -> np.ndarray:
    """Combine a frame stack, rejecting USB glitches first.

    method="median" (default) is the robust choice on a long cable; "mean" is the
    plain average. clean=False returns the raw average (legacy behaviour). A single
    frame (navg=1) is spatially despiked; a stack is median-combined then despiked.
    """
    a = np.asarray(frames, dtype=np.float64)
    if a.ndim == 1:
        return _despike(a) if clean else a
    if not clean:
        return a.mean(axis=0)
    # Despike EACH frame BEFORE combining: on a glitchy cable a pixel hit in a minority
    # of frames would otherwise survive an even-count median as a mid-level artifact
    # (e.g. median([1572,33514,1572,33514]) = 17543). Per-frame despike removes the
    # isolated hit in each frame, so the combine sees clean data regardless of navg.
    cleaned = np.array([_despike(row) for row in a])
    out = np.median(cleaned, axis=0) if method == "median" else cleaned.mean(axis=0)
    return _despike(out)                          # final pass for any residual cluster


def saturated_fraction(counts, sat) -> float:
    c = np.asarray(counts)
    return float(np.count_nonzero(c >= sat) / c.size) if c.size else 0.0


def _robust_trace(row, smooth_px: int = 5) -> np.ndarray:
    """Despike + a short boxcar - the basis for glitch-robust peak detection on a long
    USB cable. The glitch density is high enough that an even-count median averages
    2-of-N glitches into mid-level artifacts that survive despike; a real spectral line
    is >=3.7 px FWHM and survives the boxcar while a 1-3 px glitch artifact is diluted
    below it. See docs/DEVLOG.md."""
    d = _despike(np.asarray(row, dtype=np.float64))
    w = int(smooth_px)
    if w > 1 and d.size >= w:
        d = np.convolve(d, np.ones(w) / w, mode="same")
    return d


def robust_peak(row, smooth_px: int = 5) -> float:
    """Glitch-robust peak VALUE of a channel slice (exposure control: auto + tracking)."""
    d = _robust_trace(row, smooth_px)
    return float(d.max()) if d.size else 0.0


def robust_peak_index(row, smooth_px: int = 5) -> int:
    """Glitch-robust peak INDEX (the displayed peak marker + reported peak wavelength),
    so a surviving glitch artifact cannot steal the marker from the real line."""
    d = _robust_trace(row, smooth_px)
    return int(np.argmax(d)) if d.size else 0


def bin_mean(window, factor: int) -> np.ndarray:
    """Mean-bin a 1-D window by ``factor`` px, dropping a partial trailing bin.

    The quick-look's binning (feature P-04): the Pi bins each channel's pixel
    window this way, and the ground bins the stored dark the same way to
    subtract it from the quick-look - one function so the edges cannot drift
    apart. ``factor < 1`` returns the window unchanged.
    """
    w = np.asarray(window, dtype=np.float64)
    f = int(factor)
    if f <= 1:
        return w
    n = (w.size // f) * f
    if n == 0:
        return w[:0]
    return w[:n].reshape(-1, f).mean(axis=1)


def smooth(y, window: int = 0, mode: str = "savgol") -> np.ndarray:
    """Smooth a 1-D spectrum. window<3 -> no-op. mode 'boxcar' | 'savgol'.

    Savitzky-Golay (order 2) preserves peak position/height/FWHM far better than a
    boxcar; window is forced odd and clamped to the data length.
    """
    y = np.asarray(y, dtype=np.float64)
    w = int(window)
    if w < 3 or y.size < 3:
        return y
    w = min(w, y.size if y.size % 2 else y.size - 1)
    if w % 2 == 0:
        w += 1
    if w < 3:
        return y
    if mode == "boxcar":
        return np.convolve(y, np.ones(w) / w, mode="same")
    from scipy.signal import savgol_filter
    return savgol_filter(y, w, min(2, w - 1))


def reference_ratio(signal, reference, eps: float = 1.0) -> np.ndarray:
    """signal / reference, clipped -- the flat-field / 100%-line normalisation.

    Captured with no sample, the no-sample baseline reads ~1.0; a sample in the
    measurement beam then shows up as the deviation from 1.
    """
    s = np.asarray(signal, dtype=np.float64)
    r = np.asarray(reference, dtype=np.float64)
    return s / np.clip(r, eps, None)


def resample(nm_src, y_src, nm_grid) -> np.ndarray:
    """Linear-interpolate (nm_src, y_src) onto nm_grid (all nm ascending)."""
    return np.interp(np.asarray(nm_grid, float),
                     np.asarray(nm_src, float), np.asarray(y_src, float))


def common_grid(nm_a, nm_b, n: int = 256) -> np.ndarray:
    """The overlapping wavelength range of two channels, n points ascending."""
    lo = max(float(np.min(nm_a)), float(np.min(nm_b)))
    hi = min(float(np.max(nm_a)), float(np.max(nm_b)))
    if lo >= hi:
        raise ValueError(f"channels do not overlap in wavelength (lo={lo:.1f} >= hi={hi:.1f})")
    return np.linspace(lo, hi, n)


def transmission(meas, ref, eps: float = 1.0) -> np.ndarray:
    m = np.asarray(meas, float)
    r = np.asarray(ref, float)
    return m / np.clip(r, eps, None)


def absorbance(meas, ref, eps: float = 1.0) -> np.ndarray:
    return -np.log10(np.clip(transmission(meas, ref, eps), 1e-9, None))
