# CLOUDS Software Feature List

Implementation checklist derived from [SOFTWARE_SPEC.md](SOFTWARE_SPEC.md).
Priorities: **P0** = mission fails without it, **P1** = science/ops degraded,
**P2** = nice to have. Trace = SED requirement or derived spec ID.
Status: ✔ implemented & tested · ◐ logic done, hardware integration TODO · ☐ open.
Code: `flight/mcu/` (M-xx), `flight/pi/` (P-xx), `gse/` (G-xx), `clouds_link/` + `tests/` (X-xx).

## FSW-MCU — RP2350 sequencer firmware (C/C++, Pico SDK)

| ID | Feature | Prio | Trace | Status |
|---|---|---|---|---|
| M-01 | State machine INIT→STANDBY→ASCENT→SEAL→RELEASE_1→MEASURE_1→RELEASE_2→MEASURE_2→TERMINATION→SAFE | P0 | O.2, S.1 | ✔ |
| M-02 | Launch detection: sustained ambient Δp, 60 s debounce | P0 | S.1 | ✔ |
| M-03 | Float detection: p < 55 hPa ∧ low |dp/dt| 5 min, + T_float timer fallback | P0 | S.1 | ✔ |
| M-04 | Link-loss latch (10 min without heartbeat → autonomous, no further input required) | P0 | O.2, S.2 | ✔ |
| M-05 | Ground override handling: HOLD / RESUME / ABORT / RELEASE n as accelerators only | P1 | S.2 | ✔ |
| M-06 | Valve control via interlocked GPIO/MOSFET pairs; actuation verify (current sense / pressure response) | P0 | F.4 | ◐ |
| M-07 | Membrane PWM control (freq/duty configurable), duty-cycled to hold dispersion ≥ 3 min | P0 | F.3, P.6, P.7 | ◐ drive done: GP26, **2 Hz** default, loop-toggled via `core/sqwave` because 2 Hz is below the ~9 Hz PWM floor; measured 300/200 ms on the board. Duty-cycling to hold ≥ 3 min (P.7) is still sequencer-side (DEVLOG 2026-08-31) |
| M-08 | Fired-valve flags persisted **before** actuation; brownout-safe resume of sequence + mission clock | P0 | S.3 | ◐ |
| M-09 | 1 Hz sensor acquisition: 2× STLM20, BME280, 2× Keller 23SY, IMU | P0 | F.5, F.6, P.8–P.13 | ◐ BME280 live; STLM20 pair not populated, no Keller/RH2 on the bus, IMU faulted — all flagged via `error_flags` (DEVLOG 2026-08-31) |
| M-10 | Sanity/range flags on every reading (store raw, flag implausible, never discard) | P1 | S. spec §2.2 | ☐ |
| M-11 | Redundant HK + actuator-event logging to 2× SD over SPI, 10-min file rotation, CRC-16 per record | P0 | O.3, S.5, S.6 | ☐ blocked: SPI0 pin map unverified, no card responds (DEVLOG 2026-08-31) |
| M-12 | UART link to Pi: COBS framing, CRC-16, HK @ 1 Hz up, commands + time sync down | P0 | S.4 | ✔ |
| M-13 | Hardware watchdog (2 s) + Pi-liveness monitor (continue alone if Pi silent > 60 s) | P0 | S.7, S.9 | ◐ |
| M-14 | SAFE state: actuators de-energized, valves closed once, buffers flushed, logging continues | P0 | fail-safe concept | ✔ |
| M-15 | Chamber-seal verification (chamber vs ambient pressure divergence, retry ×3, proceed flagged) | P1 | seal step | ◐ |
| M-16 | Config block on SD (thresholds, timers, PWM params) loaded at boot, settable via SET_PARAM | P1 | pre-flight tuning | ◐ |
| M-17 | Self-tests at INIT: sensor plausibility, SD write test, actuator continuity, UART echo | P1 | process flow | ◐ |

## FSW-PI — Raspberry Pi 5 flight application (Python 3, systemd)

| ID | Feature | Prio | Trace | Status |
|---|---|---|---|---|
| P-01 | Spectrometer USB acquisition @ 1 Hz, both channels, exposure control — `spectro/eureca_driver.py` is cross-platform (Linux `.so` from `drivers/e9u_LSMD_LIB_Linux/`); ◐ until it is run against the camera on real Pi hardware | P0 | F.1, F.2, P.3 | ◐ |
| P-02 | Pixel→wavelength calibration + dark handling (reuse `spectro/calibration.py`, `processing.py`) | P0 | F.2 | ✔ |
| P-03 | Frame storage: ring buffer → block writes, timestamped files, 10-min rotation, CRC-16 | P0 | O.3, S.5 | ✔ |
| P-04 | UDP telemetry: HK relay @ 1 Hz + 8×-binned quick-look spectrum @ 1 Hz + events, 1.814 of 2 kbit/s avg (needs HK payload ≤ 67 B — see SOFTWARE_SPEC.md) | P0 | O.4 | ✔ |
| P-05 | TCP command server: ACK, arm/execute for actuator commands, forward to MCU over UART | P0 | S.8 | ✔ |
| P-06 | UART master: command forwarding, HK ingest, time sync every 10 s (RTC/NTP master) | P0 | S.4 | ✔ |
| P-07 | Communications log (all up/downlink traffic) to Pi SD | P1 | SED storage split | ✔ |
| P-08 | systemd unit: auto-start, restart-on-crash, RuntimeWatchdogSec=15, MCU-liveness alarm | P0 | S.9 | ✔ |
| P-09 | Auto-exposure guard: clip/saturation flagging (reuse ground-software logic); fixed exposure default for flight | P1 | F.1 | ✔ |
| P-10 | Graceful degradation: spectrometer USB loss → keep comms + HK relay running, periodic reconnect | P1 | S.7 mirror | ✔ |
| P-11 | Camera capture + thumbnail downlink (only if F.7 camera confirmed) | P2 | F.7 | ☐ |

## GSE — ground station (Python candidate; §4.12)

| ID | Feature | Prio | Trace | Status |
|---|---|---|---|---|
| G-01 | Live HK display: temperatures, humidity, pressures, IMU, state, actuator status | P0 | §4.12.1 | ✔ |
| G-02 | Live quick-look spectrum display (reuse this repo's dual-trace view / `spectro/` processing) | P0 | §4.12.1 | ✔ |
| G-03 | Command console with arm/execute UI + full command set | P0 | §4.12.1 | ✔ |
| G-04 | Ground interlock: particle-release commands blocked while on ground | P0 | S.10 | ✔ |
| G-05 | Session logging + CSV/JSON export | P1 | §4.12.1 | ✔ |
| G-06 | Calibration interface (offsets, reference comparisons) for T-01/T-03 | P1 | §4.12.1 | ☐ |
| G-07 | Link-quality panel (packet seq gaps, heartbeat RTT) | P2 | ops insight | ✔ |
| G-08 | Post-recovery data download / diagnostics mode over bench Ethernet | P1 | §4.12.2 | ◐ |

## PRE — pre-flight tools

| ID | Feature | Prio | Trace | Status |
|---|---|---|---|---|
| R-01 | Solar-position script: elevation over Esrange launch window → axicon cone-angle input + integration alignment check | P1 | §4.4 | ☐ |
| R-02 | Threshold derivation notebook: launch/float detection params from BEXUS flight profiles | P1 | M-02/M-03 | ☐ |
| R-03 | SD-card data recovery/merge tool (3 cards → one synchronized dataset for §7.1 analysis) | P1 | O.3, §7.1 | ☐ |
| R-04 | Telemetry replay tool (feed recorded downlink into GSE for training/rehearsal) | P2 | ops | ☐ |

## Cross-cutting / verification

| ID | Feature | Prio | Trace | Status |
|---|---|---|---|---|
| X-01 | Shared packet format definition (header, seq, timestamp, CRC-16) as a single documented schema used by MCU, Pi, GSE | P0 | S.5 | ✔ |
| X-02 | Mock spectrometer driver for hardware-free FSW-PI testing (adapt `spectro/mock_driver.py`) | P0 | bench testing | ✔ |
| X-03 | MCU bench harness: simulated pressure profile injection → full autonomous sequence on desk (T-07 rehearsal) | P0 | T-07 | ✔ |
| X-04 | End-to-end test script: boot → simulated flight → verify data on all 3 SDs + downlink completeness (T-10) | P0 | T-10 | ✔ |

## Suggested build order

1. **X-01** packet schema → **M-12/P-06** UART link (everything depends on framing).
2. **M-01…M-08** sequencer + autonomy on bench Pico with **X-03** harness (longest lead, highest risk, T-07 gate).
3. **P-01…P-03** spectrometer path on the Pi. The driver port is done (one
   cross-platform ctypes wrapper, Linux library vendored); what remains is a
   bench run on the Pi with the camera attached — udev + tty permissions and
   USB-cable/glitch behaviour are the things a desk test cannot settle.
4. **P-04/P-05** comms, then **G-01…G-04** minimal GSE (needed for every integrated test).
5. Everything P1/P2 after the first full **X-04** end-to-end pass.
