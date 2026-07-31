# CLOUDS Software Specification

Consolidated software spec for the BEXUS 38 CLOUDS experiment.
Sources: BX38_CLOUDS_SED v1.1 (01 Mar 2026) — §2 requirements, §4.2.2/§4.6–4.8
electronics, §4.11 software, §4.12 GSE, Table 6-3 — plus the revised software
design in [SED_SOFTWARE_DESIGN_v1-2_draft.md](SED_SOFTWARE_DESIGN_v1-2_draft.md).
Companion feature list: [SOFTWARE_FEATURES.md](SOFTWARE_FEATURES.md).

## 1. Scope

Four software items:

| Item | Runs on | Language / stack |
|---|---|---|
| **FSW-MCU** — experiment sequencer firmware | RP2350 (main electronics board) | C/C++, Pico SDK, PlatformIO |
| **FSW-PI** — flight data & comms application | Raspberry Pi 5, Raspberry Pi OS Lite, systemd service | Python 3 (reuses `spectro/` modules from this repo) |
| **GSE** — ground station GUI | Team laptop, Ethernet to experiment | Python (candidate; LabVIEW alternative — decision post-PDR) |
| **PRE** — pre-flight analysis tools | Any | Python (solar-position/axicon tool, calibration scripts) |

Design authority split: **FSW-MCU owns the experiment sequence** and must
complete it with no input from FSW-PI, the E-Link, or ground. FSW-PI handles
spectra, storage of spectra, and all external communication.

## 2. Requirements

### 2.1 From the SED (verbatim intent, software-relevant)

| SED ID | Requirement | Falls on |
|---|---|---|
| F.1/F.2 | Measure solar intensity and spectral distribution, 350–850 nm | FSW-PI |
| F.3/F.4 | Uniform dispersion; controlled CaCO₃ release | FSW-MCU |
| F.5 | Temperature measurement during ascent | FSW-MCU |
| F.6 | Humidity during ascent **and** inside chamber (two locations) | FSW-MCU |
| P.3 | Spectrometer sampling rate ≥ 1 Hz | FSW-PI |
| P.6 | Uniform dispersion achieved within 5 min | FSW-MCU |
| P.7 | Distribution stays uniform ≥ 3 min | FSW-MCU |
| P.8–P.10 | Ext. temperature −60…+30 °C, ±5 °C, 1 Hz | FSW-MCU |
| P.11–P.13 | Humidity 0–100 % RH, 1 Hz (accuracy TBD) | FSW-MCU |
| O.2 | Release CaCO₃ **twice** in flight if ground link lost; otherwise execute full sequence **by default** | FSW-MCU |
| O.3 | Store all acquired data onboard | FSW-MCU + FSW-PI |
| O.4 | Downlink a predetermined amount of data | FSW-PI |
| D.7 | E-Link connector Amphenol RJF21B (Ethernet) | FSW-PI |
| D.14 | ≤ 150 Wh mission energy (budget 121 Wh) — software must not add consumers | all |

### 2.2 Derived software requirements (from design review)

| ID | Requirement | Rationale |
|---|---|---|
| S.1 | FSW-MCU shall execute the full sequence (seal → release ×2 → measure ×2 → terminate) autonomously, triggered by pressure-derived launch/float detection with timer fallback | O.2; T-07 |
| S.2 | Ground commands shall only accelerate, hold, or abort the default sequence; no state may block indefinitely on ground input | O.2 |
| S.3 | Fired-valve flags shall be persisted to non-volatile storage **before** actuation; on reset the sequence resumes, never re-fires | irreversible actuators + brownout risk |
| S.4 | Spectra and HK shall share one timebase (Pi RTC master, UART sync ≤ 10 s interval, target skew < 100 ms) | §7.1 paired analysis needs synchronized channels |
| S.5 | Every stored record and downlink packet shall carry a sequence number and CRC-16 | SED §4.11 safety concepts |
| S.6 | HK data shall be written redundantly to both RP2350 SD cards; files rotated every 10 min | O.3; corruption containment |
| S.7 | Loss of FSW-PI shall not delay or prevent any FSW-MCU state transition | compute-split design |
| S.8 | Actuator commands over TCP shall require an arm/execute two-step; open/close valve lines are additionally hardware-interlocked | command safety |
| S.9 | Both processors shall run hardware watchdogs (RP2350 2 s; Pi systemd `RuntimeWatchdogSec=15`) with automatic restart + state resume | SED watchdog concept |
| S.10 | GSE shall block particle-release commands while on ground (software interlock) | SED §4.12.2 |

## 3. Interfaces

| Interface | Spec |
|---|---|
| E-Link downlink | UDP over Ethernet; ~1.9 kbit/s average (limit 2 kbit/s continuous; bursts ≤ 400 kbit/s max, 100 kbit/s avg per Table 6-3); self-contained packets (seq + timestamp + CRC-16), loss-tolerant |
| E-Link uplink | TCP, ≤ 1 kbit/s; command set `PING, START, HOLD, RESUME, ABORT, RELEASE 1\|2, SET_PARAM, STATUS?`; mandatory ACK; arm/execute for actuators |
| IP addressing | 2 addresses: FSW-PI, GSE bench port |
| Pi ↔ RP2350 | UART, COBS-framed, CRC-16. Down: HK @ 1 Hz, state changes, actuator events. Up: forwarded commands, time sync every 10 s |
| Spectrometer ↔ Pi | USB (FTDI FT2232H, VID 0403/PID 6010) → `/dev/ttyUSB*`, vendor library `libe9u_LSMD.so` (built from `drivers/e9u_LSMD_LIB_Linux/`, same API as the Windows DLL) — driven by this repo's `spectro/eureca_driver.py`; needs the vendor udev rules |
| SD ↔ RP2350 | SPI, 2 cards, redundant HK + actuator log |
| Sensors ↔ RP2350 | BME280 I²C; STLM20 analog/ADC; Keller 23SY per datasheet; IMU I²C/SPI |
| Actuators ↔ RP2350 | 4× valve via GPIO→MOSFET (HW interlock on open/close pairs); membrane solenoid via PWM → inverter stage, 12 V |

## 4. Data & performance budget

Spectrometer: EURECA e9u-SPMD-350/850-10-Duo — one 2048 px × 16-bit detector
(~4.1 kB/frame) carrying both fibre channels (Ch1 measurement px 0–235,
Ch2 reference px 1516–1766; factory polynomials in `calibration.json`).
Capable of 450 fps; required rate 1 Hz → huge margin.

| Stream | Rate | 5 h volume | Destination |
|---|---|---|---|
| Full spectra + header | 1 Hz | ~75 MB | Pi SD |
| HK (2× temp, BME280, 2× pressure, IMU, actuator status) | 1 Hz, ≤ 256 B | ≤ 4.6 MB | 2× RP2350 SD (redundant) |
| Event/error log | sporadic | ≪ 1 MB | all 3 cards |

Downlink subset (O.4): HK packet 1 Hz + 8×-binned quick-look spectrum **1 Hz**
+ events. Full-resolution data recovered from SD after landing.

Sizes below are the **encoded frame sizes of the implementation** (14 B header
+ payload + 2 B CRC), measured on the wire, not estimates:

| Packet | Framed size | Cadence | Rate |
|---|---|---|---|
| HK (relayed, payload `hk.SIZE` = 44 B) | 60 B | 1 Hz | 0.480 kbit/s |
| Quick-look, both channels (29 + 31 bins) | 164 B | 1 Hz | 1.312 kbit/s |
| PISTATUS | 28 B | 10 s | 0.022 kbit/s |
| **Total** | | | **1.814 kbit/s** of 2 kbit/s |

~9 % margin, leaving ~24 B/s for sporadic events.

This supersedes the earlier "quick-look every 30 s (~1.1 kB burst ≈ 0.3 kbit/s
avg)". That 1.1 kB assumed ~256 bins per channel — i.e. the whole detector
binned 8× — but the two fibre channels occupy only px 0–235 and 1516–1766, so
8× binning yields **29 + 31 bins, 164 B for both channels**, roughly 7× smaller
than assumed. The 30 s cadence was therefore ~30× more conservative than the
link required; at the true size a quick-look accompanies every 1 Hz sample and
still fits.

**Constraint this introduces:** at 1 Hz quick-look the budget leaves ~83 B for
a framed HK packet, i.e. an **HK payload of ≤ 67 B** (implementation: 44 B). HK
was originally allowed ~180 B here; at that size 1 Hz quick-look would total
~2.9 kbit/s and bust the 2 kbit/s continuous limit. If HK grows past ~67 B,
either bin the quick-look harder or reduce its cadence.
`tests/test_fsw_telemetry.py::TestDownlinkBudget` enforces this from real
encoded frames, so exceeding it fails a test rather than the flight link.

Buffering: ring buffers (Pi 64 kB, MCU 8 kB), block writes; storage write
rate ≥ 100× data rate; on overflow drop the downlink copy, never the
storage copy.

## 5. Experiment sequence (FSW-MCU state machine)

`INIT → STANDBY → ASCENT → SEAL → RELEASE_1 → MEASURE_1 → RELEASE_2 →
MEASURE_2 → TERMINATION → SAFE`; any critical fault → SAFE (actuators
de-energized, data preserved, HK + downlink continue).

Autonomy triggers (pre-flight configurable): launch = sustained Δp over
60 s; float = p < 55 hPa ∧ |dp/dt| low for 5 min, or T_float = 120 min
after launch; link-loss latch after 10 min without TCP heartbeat;
t_measure ≥ 8 min per phase (covers P.6 5-min uniformity + P.7 3-min hold).

Full state/action table, pseudocode, and rationale:
[SED_SOFTWARE_DESIGN_v1-2_draft.md](SED_SOFTWARE_DESIGN_v1-2_draft.md).

## 6. Verification

| Test | Software scope |
|---|---|
| T-06 Electrical/Power | Rails up, boot both processors, no software consumer beyond budget |
| **T-07 Autonomy & Failsafe** | Pull E-Link mid-sequence → full autonomous double release; kill Pi → MCU completes sequence; watchdog resets → resume without re-fire |
| T-03 Sensor calibration | HK channel plausibility + calibration constants |
| T-01 Optical/Spectral calibration | FSW-PI acquisition + pixel→nm mapping |
| T-10 End-to-end | Full sequence, GSE monitoring, data recovery from all 3 SD cards |

Bench testing without hardware: FSW-PI runs against the mock driver
(`spectro/mock_driver.py` pattern); FSW-MCU on a bench Pico 2 with
simulated sensor inputs.

## 7. Open points (owner ≠ software, but software-visible)

- F.7 camera: undecided; CSI interface + downlink thumbnail budget reserved.
- Second humidity sensor (F.6): parts list has one BME280; HK format
  reserves two RH channels.
- GSE technology (Python vs LabVIEW): decision post-PDR.
- P.1/P.2 (intensity accuracy / spectral resolution): TBD in SED; spec
  inherits whatever CDR fixes.
