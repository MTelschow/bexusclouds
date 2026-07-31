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
