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
| F.3/F.4 | Uniform dispersion; ~~controlled CaCO₃ release~~ — **the pinch and equalisation valves were removed from the experiment 2026-09-18**; the dispersion motor and the membrane solenoid are the only actuators left, so nothing in software releases anything | FSW-MCU |
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
| S.1 | ~~FSW-MCU shall execute the full sequence (seal → release ×2 → measure ×2 → terminate) autonomously, triggered by pressure-derived launch/float detection~~ — **replaced 2026-09-18** (see §5): the operator's `START` begins the experiment and ground silence hands it to the automatic cycle. Launch and float are still detected and reported, and drive nothing | O.2; T-07 |
| S.2 | Ground commands shall only start or stop the experiment; no state may block indefinitely on ground input. **Reworded 2026-09-28**: with S.1's pressure-driven sequence gone there is no "default sequence" left to accelerate or pause, so `HOLD`/`RESUME` were retired and the mission is carried by `PING`, `START` and `STOP` | O.2 |
| S.3 | ~~Fired-valve flags shall be persisted **before** actuation; on reset the sequence resumes, never re-fires~~ — **moot since 2026-09-18**: with the valves gone there is no irreversible actuator to guard. The state and the mission clock are still persisted on every transition, so a reset resumes where it was | irreversible actuators + brownout risk |
| S.4 | Spectra and HK shall share one timebase (Pi RTC master, UART sync ≤ 10 s interval, target skew < 100 ms) | §7.1 paired analysis needs synchronized channels |
| S.5 | Every stored record and downlink packet shall carry a sequence number and CRC-16 | SED §4.11 safety concepts |
| S.6 | HK data shall be written redundantly to both RP2350 SD cards; files rotated every 10 min | O.3; corruption containment |
| S.7 | Loss of FSW-PI shall not delay or prevent any FSW-MCU state transition | compute-split design |
| S.8 | ~~Actuator commands over TCP shall require an arm/execute two-step~~ — **dropped 2026-09-18** by operator decision: while ground is connected every command executes, and the GSE's confirm dialog is the only step in front of a release. Open/close valve lines remain hardware-interlocked on the board | command safety |
| S.9 | Both processors shall run hardware watchdogs (RP2350 2 s; Pi systemd `RuntimeWatchdogSec=15`) with automatic restart + state resume | SED watchdog concept |
| S.10 | ~~GSE shall block particle-release commands while on ground (software interlock)~~ — **dropped 2026-09-18** by operator decision, together with the flight-mode switch that lifted it. `START` is now the single operator action that begins the experiment | SED §4.12.2 |

## 3. Interfaces

| Interface | Spec |
|---|---|
| E-Link downlink | UDP over Ethernet; ~1.9 kbit/s average (limit 2 kbit/s continuous; bursts ≤ 400 kbit/s max, 100 kbit/s avg per Table 6-3); self-contained packets (seq + timestamp + CRC-16), loss-tolerant |
| E-Link uplink | TCP, ≤ 1 kbit/s; command set `PING, START, STOP, SET_PARAM, STATUS?, MEMBRANE, DISPERSE` (+ `ARM`, `RELEASE 1\|2` and the retired `HOLD`/`RESUME` opcodes `0x02`/`0x03` — `ARM` is answered OK and does nothing, the rest are answered `INVALID`; `STOP` is `ABORT`'s old opcode `0x04`); mandatory ACK. **Nothing is gated (2026-09-18)**: no arm/execute, no ground interlock, no state refusal - a command the chain can parse is executed and answered `OK`, and `INVALID` is left for input it cannot act on at all (unknown command, duty > 100, parameter out of envelope). `MEMBRANE` (duty %, 0 = off) and `DISPERSE` (pulse / run / stop, speed from `SET_PARAM DISPERSE_DUTY`) are the operator's drives of the dispersion hardware |
| IP addressing | 2 addresses: FSW-PI, GSE bench port |
| Pi ↔ RP2350 | UART, COBS-framed, CRC-16. Down: HK @ 1 Hz, state changes, actuator events. Up: forwarded commands, time sync every 10 s |
| Spectrometer ↔ Pi | USB (FTDI FT2232H, VID 0403/PID 6010) → `/dev/ttyUSB*`, vendor library `libe9u_LSMD.so` (built from `drivers/e9u_LSMD_LIB_Linux/`, same API as the Windows DLL) — driven by this repo's `spectro/eureca_driver.py`; needs the vendor udev rules |
| SD ↔ RP2350 | SPI, 2 cards, redundant HK + actuator log |
| Sensors ↔ RP2350 | BME280 ×2 - **ambient** on I²C (`0x76`) and **chamber** on SPI_1 (chip select GP9); STLM20 analog/ADC; IMU I²C/SPI; INA226 ×3 I²C (rail voltage + shunt voltage) |
| Actuators ↔ RP2350 | CaCO₃ dispersion motor on the `ACT_HB` H-bridge (GP17 fwd / GP18 rev, current sense GP46); membrane solenoid via PWM → inverter stage, 12 V. The four valves (2 pinch + 2 equalisation) were removed from the experiment 2026-09-18, with their pins, drives and HK bits |

## 4. Data & performance budget

Spectrometer: EURECA e9u-SPMD-350/850-10-Duo — one 2048 px × 16-bit detector
(~4.1 kB/frame) carrying both fibre channels (Ch1 measurement px 0–235,
Ch2 reference px 1516–1766; factory polynomials in `calibration.json`).
Capable of 450 fps; required rate 1 Hz → huge margin.

| Stream | Rate | 5 h volume | Destination |
|---|---|---|---|
| Full spectra + header | 1 Hz | ~75 MB | Pi SD |
| HK (2× temp, BME280, ambient pressure, IMU, 3× rail V + I, actuator status) | 1 Hz, ≤ 256 B | ≤ 4.6 MB | 2× RP2350 SD (redundant) |
| Event/error log | sporadic | ≪ 1 MB | all 3 cards |

Downlink subset (O.4): HK packet 1 Hz + 8×-binned quick-look spectrum **1 Hz**
+ events. Full-resolution data recovered from SD after landing.

Sizes below are the **encoded frame sizes of the implementation** (14 B header
+ payload + 2 B CRC), measured on the wire, not estimates:

| Packet | Framed size | Cadence | Rate |
|---|---|---|---|
| HK (relayed, payload `hk.SIZE` = 64 B) | 80 B | 1 Hz | 0.640 kbit/s |
| Quick-look, both channels (29 + 31 bins) | 164 B | 1 Hz | 1.312 kbit/s |
| PISTATUS | 28 B | 10 s | 0.022 kbit/s |
| **Total** | | | **1.974 kbit/s** of 2 kbit/s |

~5 % margin, leaving ~13 B/s for sporadic events. The INA226 rail voltages
cost the 6 B that took HK from 44 to 50 B, and their shunt voltages 6 B
after that. The 4 B beyond those are the fourth rail slot, 24 V, whose
monitor is not fitted yet: reserving it keeps fitting the part out of the
wire format (DEVLOG 2026-09-09). The last 8 B are the chamber BME280's
temperature, humidity and pressure (DEVLOG 2026-09-17).

This supersedes the earlier "quick-look every 30 s (~1.1 kB burst ≈ 0.3 kbit/s
avg)". That 1.1 kB assumed ~256 bins per channel — i.e. the whole detector
binned 8× — but the two fibre channels occupy only px 0–235 and 1516–1766, so
8× binning yields **29 + 31 bins, 164 B for both channels**, roughly 7× smaller
than assumed. The 30 s cadence was therefore ~30× more conservative than the
link required; at the true size a quick-look accompanies every 1 Hz sample and
still fits.

**Constraint this introduces:** at 1 Hz quick-look the budget leaves ~83 B for
a framed HK packet, i.e. an **HK payload of ≤ 67 B** (implementation: 54 B). HK
was originally allowed ~180 B here; at that size 1 Hz quick-look would total
~2.9 kbit/s and bust the 2 kbit/s continuous limit. If HK grows past ~67 B,
either bin the quick-look harder or reduce its cadence.
`tests/test_fsw_telemetry.py::TestDownlinkBudget` enforces this from real
encoded frames, so exceeding it fails a test rather than the flight link.

Buffering: ring buffers (Pi 64 kB, MCU 8 kB), block writes; storage write
rate ≥ 100× data rate; on overflow drop the downlink copy, never the
storage copy.

## 5. Experiment sequence (FSW-MCU state machine)

**Changed 2026-09-18.** The sequence is no longer driven by the flight
profile. It is started by the operator and, when the operator goes away,
runs a fixed cycle until they come back.

`INIT → STANDBY → RUNNING → {AUTO_DISPERSE → AUTO_MEMBRANE → AUTO_WAIT}* →
RUNNING`; `STOP` or any critical fault → `TERMINATION → SAFE` (actuators
de-energized, data preserved, HK + downlink continue).

- **STANDBY** — on the pad. Nothing happens on its own; `START` from the
  ground station is the only way out, and a link that was never up is not a
  link that was lost, so automatic mode cannot start here.
- **RUNNING** — started. Sensors are swept, HK is logged to both SD cards
  and the Pi stores every spectrum, as in every state. Ground owns the
  actuators.
- **automatic mode** — entered from RUNNING after `LINKLOSS_S` (10 min) with
  no ground command of any kind, the GSE's 5 s PING included. It cycles
  **2 min dispersion motor only → 3 min push-pull solenoid only → 5 min
  neither**, at the configured motor and solenoid defaults, and repeats for
  as long as the link stays down. Measurement and storage never stop.
  The **first ground command of any kind ends it in the same call**: both
  actuators de-energize and the state returns to RUNNING. The next entry
  always restarts at the motor phase - the cycle carries nothing across a
  link-up period or a reset.
- **there is nothing irreversible left to drive.** The pinch and
  equalisation valves came off the experiment on 2026-09-18; `RELEASE` is
  answered `INVALID` and the persist-before-fire rule (S.3) has nothing to
  guard. Both remaining actuators stop when they are told to.
- **Three commands carry the mission (2026-09-28).** `PING` asks whether the
  chain answers, `START` arms autonomy (`RUNNING`, inhibit lifted), and
  `STOP` means *manual, and stay manual*: actuators de-energized,
  `TERMINATION → SAFE`, and automatic mode inhibited until the next `START`,
  link loss included (`MCUF_STOPPED`, docs/TRAPS.md). `STOP` keeps `ABORT`'s
  opcode `0x04` because it keeps its effect and adds the inhibit that the old
  `ABORT` *cleared* - abort, then lose the link, and the cycle used to
  restart the motor the operator had just shut down. `HOLD` (`0x02`) and
  `RESUME` (`0x03`) are retired, answered `INVALID`, numbers not reused: an
  old `HOLD` asked for the actuators to keep running, which `STOP` does not
  do, so mapping one onto the other would execute something other than what
  was sent.
- **Nothing is refused while ground is connected (2026-09-18).** `START` is
  accepted in any state, including back out of `SAFE` after a `STOP`; a drive
  commanded after a `STOP` re-energizes and takes the state to `RUNNING` with
  it, so housekeeping never reports `SAFE` over a turning motor - but it does
  **not** lift the inhibit, which only `START` does. `INVALID`
  is left for input the firmware cannot act on at all: an unknown command, a
  duty above 100, a parameter outside its envelope, or a `RELEASE` for
  hardware that is not on the experiment any more.

Autonomy triggers (pre-flight configurable): link-loss latch after 10 min
without a ground command (`LINKLOSS_S`); phase lengths `AUTO_DISPERSE_S` /
`AUTO_MEMBRANE_S` / `AUTO_WAIT_S`. Launch (sustained Δp over 60 s) and float
(p < 55 hPa ∧ |dp/dt| low for 5 min, or T_float = 120 min after launch) are
still detected and still reported as events, but **no state depends on
them** any more. `T_MEASURE_S` and `SEAL_RETRY` are retired with the
measurement phases and the SEAL state; their parameter keys (8, 11) are
refused rather than reused.

Full state/action table, pseudocode, and rationale:
[SED_SOFTWARE_DESIGN_v1-2_draft.md](SED_SOFTWARE_DESIGN_v1-2_draft.md).

## 6. Verification

| Test | Software scope |
|---|---|
| T-06 Electrical/Power | Rails up, boot both processors, no software consumer beyond budget |
| **T-07 Autonomy & Failsafe** | Pull E-Link after START → the 2/3/5 cycle runs unattended and stops on the first command back; kill Pi → MCU keeps cycling and logging; watchdog resets → resume without re-fire |
| T-03 Sensor calibration | HK channel plausibility + calibration constants |
| T-01 Optical/Spectral calibration | FSW-PI acquisition + pixel→nm mapping |
| T-10 End-to-end | START, both releases, a link drop through at least one full cycle, GSE monitoring, data recovery from all 3 SD cards |

Bench testing without hardware: FSW-PI runs against the mock driver
(`spectro/mock_driver.py` pattern); FSW-MCU on a bench Pico 2 with
simulated sensor inputs.

## 7. Open points (owner ≠ software, but software-visible)

- F.7 camera: undecided; CSI interface + downlink thumbnail budget reserved.
- Second humidity sensor (F.6): **sourced, from a second BME280**. The
  chamber part on SPI_1 (chip select GP9) gives chamber humidity *and*
  chamber pressure, in `chm_rh_cpct` / `chm_p_pa` behind their own
  `HKE_BME280_CHM_FAIL`. It is instrumentation only: launch and float
  detection still read `p_amb_pa` from the ambient part on I²C, so a chamber
  fault cannot reach the sequencer. **Not yet run against the fitted part**
  (DEVLOG 2026-09-17). F.6's two-location requirement and the M-15 seal check both need a part
  chosen before either has software to write.
- GSE technology (Python vs LabVIEW): decision post-PDR.
- P.1/P.2 (intensity accuracy / spectral resolution): TBD in SED; spec
  inherits whatever CDR fixes.
