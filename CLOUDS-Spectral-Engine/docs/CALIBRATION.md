# Calibration - pixel -> wavelength

The CLOUDS Duo is a single Toshiba **TCD1304DG** (2048-px) CCD that images
**two fibre channels** at once: Ch1 on the low pixels, Ch2 on the high pixels.
The pixels between the two windows are dark.

Pixel->wavelength is a 2nd-order fit per channel:

```
nm = a*x^2 + b*x + c        (x = pixel index, 0..2047)
```

| Channel | role (default) | pixel window | range | a | b | c |
|---|---|---|---|---|---|---|
| Ch1 | measurement | 0-235 | 383.6-850.3 nm | -3.2e-5 | 2.0017 | 383.6101 |
| Ch2 | reference | 1516-1766 | 350.0-850.0 nm | -2.2e-5 | 2.0693 | -2737.1739 |

Source: INSION spectrometer data sheet `P.167.PR.0001` (2026-05-12), a
2nd-order wavelength-to-pixel fit on interference filters
IF450/IF550/IF650/IF750/IF850. Values are shipped in
[`calibration.json`](../calibration.json) and loaded by
`spectro/calibration.py` - never hardcoded in the UI.

## Data scaling

The ADC is 12-bit but the Windows DLL returns each pixel **left-shifted into
16-bit** (value ~= adc x 16), so counts run 0..65535 and saturation sits at
~ **65520**. `saturation_count` in `calibration.json` drives the live clipping
flag.

**The Linux `.so` does not apply that shift.** Measured on the flight Pi with
vendor library 2.4.02 (`e9u_LSMD-TCD1304-PRO`, identity reports `ADC: 12 Bits`):
raw frames peaked at 2336 with an on-chip dark value of 76, and the values were
not multiples of 16 — i.e. plain 12-bit samples. Left uncorrected this breaks
every threshold derived from `saturation_count`: `saturated_fraction` can never
exceed 0, so clipping is undetectable, and the P-09 exposure servo in
`flight/pi/clouds_fsw/spectro_source.py` sees `peak < 0.20 * 65520` forever —
multiplying the exposure by 1.5 each cycle until it pins at `_EXP_MAX_US`, with
its reduce branch (`peak >= 0.90 * sat`) unreachable.

`spectro/eureca_driver.py` therefore normalises the Linux path up to the
documented scale: `grab()` clamps to 12 bits (so the shift cannot wrap
`uint16`) then shifts, and `dark_value()` applies the same factor because it is
subtracted straight from frame counts. One calibration stays valid on both
platforms. `CLOUDS_E9U_COUNT_SHIFT` overrides the factor — set it to `0` if a
future vendor release starts shifting on Linux too, which would otherwise
double-scale.

## The stored dark frame

A dark frame is the detector with no light on it - pedestal, per-pixel offset,
dark current - and on this unit that pedestal is large: the **covered**
inter-channel gap (px 236-1515, which cannot see light by construction) reads
~24 000 ct at 10 ms, ~37 % of the 65520 full scale. Subtracting it is not a
refinement, it is what makes a count mean anything.

Capturing one needs a darkened bench, so the operator interface keeps the last
capture: `Capture dark` writes `dark_frame.npz` (numpy, no pickle, beside
`calibration.json`; `CLOUDS_DARK` moves it) and the next start loads it back.
`Clear` drops it and deletes the file, so what is on screen is what comes back.

**`dark_frame.npz` is committed** (2026-09-17). It was `.gitignore`d as
instrument state, on the argument that it is regenerable in one button press -
true on the bench, false anywhere else, because that button needs the Duo and a
darkened room. A second machine cloned the repo and had no dark at all. The
tracked file is the bench dark of S/N 20260312-004 at 10 ms, x16: a baseline to
start from, not a measurement anybody is obliged to keep - a capture overwrites
it, `Clear` deletes it, `git checkout dark_frame.npz` brings it back. Every
guard below applies to it exactly as to a fresh one, so the committed frame
cannot be used at the wrong exposure or on the wrong instrument. Scratch darks
(`verify_qt.py`, `qc_live.py`) still go to `output/` via `CLOUDS_DARK`, and
`--mock` keeps `persist_dark=False`.

Three guards, in `spectro/dark.py`:

* **The exposure travels with the counts.** Dark current scales with
  integration time, so a 10 ms dark subtracted off a 200 ms frame removes the
  wrong pedestal and still looks like a spectrum. A restored dark therefore
  brings its exposure back with it and switches the auto-integration servo
  off - a servo that moves the exposure would invalidate the dark within a
  frame or two. Change the exposure and the subtraction is **withheld**, with
  the Dark frame section saying so, rather than applied to a frame it does not
  describe.
* **So do `pixels`, `model` and `serial`.** A stored frame whose length does
  not match the detector in front of you raises `DarkError` instead of being
  broadcast onto the wrong geometry. Length only proves geometry - two 2048 px
  Duos pass it - so `serial_conflict()` is checked as well, at Connect, where
  the detector has finally said who it is: a mismatch drops the dark and says
  which serial it came from. The mock (`MOCK-0001`) is dropped by the same
  rule, which is what keeps the committed bench dark out of a mock session.
* **A lit dark is named.** `light_leak()` compares each channel window's 99th
  percentile against the covered gap's; more than `LEAK_MARGIN_CT` = 2000 ct
  over it means a fibre was not blocked. It is on the 99th percentile because
  a leak is *lines*: 40 lit pixels of 251 move the window mean ~1.9 k while a
  peak lands 12 k over the gap.

**A dark captured with light on the bench is worse than no dark**: it absorbs
real signal into the baseline, and nothing downstream can tell. That is why
the check above exists - but it only names the frame, it does not refuse it:
the pedestal is still right everywhere nothing leaked, and a bench mistake is
not a corrupt file. On 2026-09-11 the stored dark had the reference channel
~6.9 k **above** the gap in the mean (Ch2 +13.7 k, Ch1 +3.1 k on the 99th
percentile), i.e. light was still reaching both fibres; it is a usable
pedestal for Ch1 and an over-subtraction for Ch2 until it is retaken blocked.
**That frame is the one committed as the baseline**, and the operator
interface says so on every restore, in the hint and in the Dark frame
section, until somebody retakes it with the fibres blocked.

## Validation

A covers-on dark frame showed stray room light leaking through both SMA fibres;
the leak peaks landed inside the predicted Ch1 (~pixel 122 ~ 633 nm) and Ch2
(~pixel 1718 ~ 747 nm) windows - confirming the polynomials map directly onto
the EURECA 2048-px readout with no pixel remapping.

## Role assignment

`role_default` (Ch1 = measurement, Ch2 = reference) is the app default. Which
physical SMA fibre carries the chamber signal vs the reference path is a wiring
choice, so the assignment is user-settable in the UI.

## Planned: empirical recalibration

A later pass adds a recal tool: measure known emission lines (e.g. a Hg/Ar pen
lamp or known laser lines), refit a,b,c per channel, and write a new versioned
`calibration.json`. The factory fit is the shipped default.
