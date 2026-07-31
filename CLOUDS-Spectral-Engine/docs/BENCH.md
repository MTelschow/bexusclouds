# Bench QC: Home Assistant light control + spectrometer response

Ground-test utilities to drive a controllable light source (via Home Assistant /
Philips Hue) and measure how the EURECA Duo responds -- a changing-light vector
for QC-ing and developing the software without a calibrated source.

## Tools

| script | what it does |
|---|---|
| `ha_lamp.py` | Scoped HA light control. Hard-locked to the **Living Room Hue lights only** (in-code allow-list); only on/off/brightness/colour services + a fixed parameter allow-list. Token read from `%USERPROFILE%\.clouds_ha_token` (out of repo), never printed. Default target = the whole room. |
| `lamp_response.py` | Floor lamp 1 response vs exposure, dark-subtracted. |
| `color_qc.py` | Spot colour sweep (R/G/B/W), paired dark-subtraction. |
| `dark_stage_qc.py` | Snapshots + darkens the whole room, runs the spot sweep, then restores from the snapshot. |
| `room_qc.py` | Whole-room warm brightness + colour-temperature sweep. |
| `power_estimate.py` | Drives floor lamp 1 up/down, saves frame stacks for a photon-transfer + dark-noise + responsivity campaign. |
| `analyze_power.py` | Corruption-robust radiometry: counts -> e- -> photons -> watts (gain, noise floor, detection limit). |
| `compute_power_summary.py` | Final power figures across the QE/throughput/integration band + spectrum & linearity plot. |
| `diag_frames.py` | Diagnoses the raw-stream variance artifacts. |
| `qc_show.py` | Live QC: capture one clean lit spectrum through the full UI (real camera + floor lamp + median cleaner). |
| `qc_live.py` | **Full feature QC sweep** on the real Duo, driven by lamp + shutter: ~30 checks across the whole pipeline (acquisition, dark/offset, glitch filter, averaging/SNR, views, smoothing, zoom, peak marker, flat-field, export, saturation, fps/drop, auto-exposure, continuous tracking, colour response, session logging). Quantitative pass criteria; restores the shutter as-found + lamp off. Latest: **28 PASS / 0 FAIL / 3 NOTE** (NOTEs = manual sample + absent DLL symbol). See `docs/DEVLOG.md` for the matrix + the bugs it caught. |
| `ha_cover.py` | Scoped HA control of the roller shutter (cover.rolladen) only -- open/close/stop/position. |
| `shutter_char.py` / `analyze_shutter.py` | Daylight characterization via the shutter (learning run) + glitch-cleaned analysis. |

The token is a Home Assistant long-lived access token stored at
`%USERPROFILE%\.clouds_ha_token` (outside the repo). Revoke it in
HA -> Profile -> Security when done; delete the file to remove it locally.

## Findings (2026-06)

The EURECA Duo's fibres have **bright-red dust covers** fitted (kept on for dust
protection). They act as a **red filter**:

- **Warm / red / white light comes through**, peaking ~650-700 nm.
- **Pure blue and green are blocked** -- their dark-subtracted signal is just noise.

Measured (measurement channel, dark-subtracted):

- **Floor lamp 1** (warm, well-coupled): strong and **dead-linear with exposure**
  (0.28 M -> 0.90 M -> 3.2 M counts at 10 / 50 / 200 ms). The cleanest vector.
- **Whole room, warm**, 40 ms: red-band signal scales with brightness
  (60 % -> 170 k, 100 % -> 682 k); **cool** white gives less (382 k) because the
  covers favour red. A usable strong vector.
- **Individual colour spots** (indirect): weak; only their red content survives
  the covers, and pure blue/green are invisible.

**Changing-light QC vector available now:** warm light (floor lamp or whole room)
+ brightness / colour-temperature -> a strong, repeatable, controllable signal.
**Full-spectrum colour response is gated on removing the dust covers** (a hands-on
step). With the covers off, blue/green get through and the RGB spots become a
proper colour vector.

## Power sensitivity -- how much light the spectrometer needs (2026-06)

Detector is the **Toshiba TCD1304DG** (firmware `CG1.36` -> **gain 1.36 e-/count**,
full well ~89 ke-; read+dark noise ~28 e- measured / 46 e- firmware). Driving floor
lamp 1 and converting counts -> e- -> photons -> watts:

- **Minimum detectable input** (per-pixel SNR 10, 100 ms, red ~660 nm, QE~0.3,
  fibre->detector throughput~0.1): **~3.6 fW per pixel at the detector**,
  ~**0.04 pW/pixel** -> **~0.01 nW full-spectrum at the fibre input** (one channel).
  Order-of-magnitude only; over throughput 5-25 % and 0.1-1 s it spans ~0.5-17 pW.
- **Saturation:** ~0.9 nW/pixel at 1 ms (~210 nW across the band); ~0.01 nW/pixel at 100 ms.
- **vs the LCU's ~2.5 mW peak:** ~3e8x above the noise floor and ~1e4x past
  saturation even at the shortest integration -> **light is a non-issue; the design
  driver is attenuation / short exposure, not collection.**

Two raw-stream artifacts found and handled in the analysis (and worth fixing in the
acquisition path): a **transfer glitch** corrupting a *random* ~9 %/frame of pixels
to a fixed ~33514 code (a data-path artifact aggravated by the ~5 m USB cable kept for
remote access; a short shielded cable removes it at the source) -- reject by clipping
that band or **median-combining** frames,
never plain-average (a plain mean lifts the true ~1500-count baseline to ~4500); and
~5 % common-mode **source flicker** (defeats photon-transfer gain on a Hue bulb, so the
firmware gain is used instead).

## Daylight via the roller shutter (2026-06 learning experiment)

Using `cover.rolladen` as a controllable daylight source (red caps still on), software
left untouched:

- **Red caps are a ~600 nm long-pass:** daylight gives ZERO signal below ~600 nm, then a
  broad solar continuum in the red/NIR (peaks ~700-740 nm, extends past 850 nm).
- **The shutter dims daylight monotonically** but the fibre is essentially shadowed below
  ~40 % open (threshold / nonlinear); strong signal at 75-100 %.
- **The raw spectrum is instrument-convolved, NOT yet true source spectra.** The red/NIR
  roll-off (and an apparent ~760-790 nm "dip") is dominated by cap transmission x detector
  QE: the Hue lamp, with NO atmospheric path, shows the same NIR falloff through the same
  cap. So it is NOT a confirmed atmospheric feature -- resolving real absorption (e.g. the
  O2 A-band) needs flat-fielding against a reference spectrum + likely the covers off.
  (Signal QUALITY is excellent though: ~140/pixel continuum SNR at 10 ms.) The glitch
  filter does leave real downward features intact (dips are never flagged).
- **Daylight here is NOT steady (~4-7 % over ~1.6 s)** -- clouds / foliage / low evening
  sun -- so it can't rescue the photon-transfer gain either; firmware CG 1.36 stands. The
  same ~5 % frame-to-frame wobble also appears with the Hue, so it may be camera/exposure
  jitter rather than the source (worth a dedicated dark-stack test). Either way it
  validates the **dual-channel reference design**: the flight sun WILL fluctuate (clouds +
  balloon motion), so the meas/ref ratio is essential.

## Scope / safety

`ha_lamp.py` can only ever address the Living Room Hue lights in its allow-list;
any other entity / service / parameter is refused in code, and the harness gates
any other use of the token. The experiment scripts always switch the room **off**
at the end (try/finally).
