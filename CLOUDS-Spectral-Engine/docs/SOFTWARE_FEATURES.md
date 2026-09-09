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
| M-05 | Ground override handling: HOLD / RESUME / ABORT / RELEASE n as accelerators only | P1 | S.2 | ✔ every command is answered with an `ACK` carrying the MCU's own verdict (`core/link.c` gate → `seq_command()` result), so a release refused for state, arm or parameter reaches ground as a refusal instead of an OK |
| M-06 | Valve control via interlocked GPIO/MOSFET pairs; actuation verify (current sense / pressure response) | P0 | F.4 | ◐ |
| M-07 | Membrane PWM control (freq/duty configurable), duty-cycled to hold dispersion ≥ 3 min | P0 | F.3, P.6, P.7 | ◐ drive done: GP26, **2 Hz** default, loop-toggled via `core/sqwave` because 2 Hz is below the ~9 Hz PWM floor; measured 300/200 ms on the board. Duty-cycling to hold ≥ 3 min (P.7) is still sequencer-side. A **CaCO3 dispersion motor** on GP17/GP18 (not in the SED) also runs on each release: one 5 s scheduled pulse, forward line only, reverse line as interlock. Both actuators **measured and seen running together** - membrane holds 1.99 Hz under the motor drive, 24 V rail flat. Motor current still unmeasured (DEVLOG 2026-08-31). Both are now **commandable from the GSE panel** (`MEMBRANE` duty/`SET_PARAM MEMBRANE_HZ`, `DISPERSE`), refused in TERMINATION/SAFE, and the drive state reaches ground: `membrane_duty` and `valve_status` are filled from the sequencer and `core/pulse` instead of staying 0 |
| M-08 | Fired-valve flags persisted **before** actuation; brownout-safe resume of sequence + mission clock | P0 | S.3 | ◐ |
| M-09 | 1 Hz sensor acquisition: 2× STLM20, BME280, IMU, 3× INA226 | P0 | F.5, F.6, P.8–P.13 | ◐ BME280 live; STLM20 pair not populated, IMU faulted - both flagged via `error_flags` (DEVLOG 2026-08-31). **Keller 23SY ×2 removed from the design**, and `p_ch_pa`/`rh2_cpct` with them: a field no part can fill reads as data on a display. **INA226 ×3 give voltage and current**: `rail_mv[]` (bus voltage, mV - 24.06 / 5.09 / 3.30 V measured) plus `shunt_raw[]` (shunt register, i16, 2.5 µV/LSB). Four rails ride the packet - **V_in** (0x40, the incoming bus; it was mislabelled 24 V), the **24 V rail with no monitor fitted yet** (reserved slot, `RAIL_MV_INVALID`, shown as `not fitted` and excluded from `HKE_RAIL_FAIL`), 5 V (0x44) and 3.3 V (0x45) - which put `hk.SIZE` at 54 B. Amps are computed on the ground (`hk.rail_a()`, shunts 10 / 15 / 10 / 50 mΩ) rather than by the part's calibration register, so a wrong shunt is correctable after the fact. Parts identified by mfg/die register, not by address |
| M-10 | Sanity/range flags on every reading (store raw, flag implausible, never discard) | P1 | S. spec §2.2 | ☐ |
| M-11 | Redundant HK + actuator-event logging to 2× SD over SPI, 10-min file rotation, CRC-16 per record | P0 | O.3, S.5, S.6 | ☐ blocked: SPI0 pin map unverified, no card responds (DEVLOG 2026-08-31) |
| M-12 | UART link to Pi: COBS framing, CRC-16, HK @ 1 Hz up, commands + time sync down | P0 | S.4 | ✔ |
| M-13 | Hardware watchdog (2 s) + Pi-liveness monitor (continue alone if Pi silent > 60 s) | P0 | S.7, S.9 | ✔ `core/link.c`: any valid frame refreshes the link, `PARAM_PI_SILENT_S` (default 60 s, the Pi beats every 10 s with TIMESYNC) clears `MCUF_PI_OK` and raises one event. Reporting only — a source-level test asserts `core/link.c` cannot reach the sequencer (S.7). **confirmed on the bench** over the real GP0/GP1 wire: `MCUF_PI_OK` set by the 10 s TIMESYNC, cleared after 60 s of FSW silence, set again on restart (DEVLOG 2026-09-09) |
| M-14 | SAFE state: actuators de-energized, valves closed once, buffers flushed, logging continues | P0 | fail-safe concept | ✔ |
| M-15 | Chamber-seal verification (retry ×3, proceed flagged) | P1 | seal step | ☐ **needs a sensor**: the chamber-vs-ambient pressure divergence this was specified as died with the Keller pair, so `ops_seal_ok()` is `return true` until a replacement chamber sensor or valve position sense exists. The retry/flag logic around it is written and tested |
| M-16 | Config block on SD (thresholds, timers, PWM params) loaded at boot, settable via SET_PARAM | P1 | pre-flight tuning | ◐ |
| M-17 | Self-tests at INIT: sensor plausibility, SD write test, actuator continuity, UART echo | P1 | process flow | ◐ the UART half stays open by design: INIT must not wait for the Pi (S.7), so the link is proven by `MCUF_PI_OK` in flight rather than by an echo at boot |

## FSW-PI — Raspberry Pi 5 flight application (Python 3, systemd)

| ID | Feature | Prio | Trace | Status |
|---|---|---|---|---|
| P-01 | Spectrometer USB acquisition @ 1 Hz, both channels, exposure control — `spectro/eureca_driver.py` is cross-platform (Linux `.so` from `drivers/e9u_LSMD_LIB_Linux/`); ◐ until it is run against the camera on real Pi hardware | P0 | F.1, F.2, P.3 | ◐ |
| P-02 | Pixel→wavelength calibration + dark handling (reuse `spectro/calibration.py`, `processing.py`) | P0 | F.2 | ✔ |
| P-03 | Frame storage: ring buffer → block writes, timestamped files, 10-min rotation, CRC-16 | P0 | O.3, S.5 | ✔ |
| P-04 | UDP telemetry: HK relay @ 1 Hz + 8×-binned quick-look spectrum @ 1 Hz + events, 1.894 of 2 kbit/s avg (needs HK payload ≤ 67 B — see SOFTWARE_SPEC.md) | P0 | O.4 | ✔ |
| P-05 | TCP command server: ACK, arm/execute for actuator commands, forward to MCU over UART | P0 | S.8 | ✔ the ACK to ground carries the **MCU's** result for everything in `MCU_CONFIRMED` (a missing ACK inside `mcu_ack_timeout_s` is a rejection); `ARM` is forwarded too, so the MCU's own arm latch stays in step; `PING` is answered by the Pi, since the heartbeat is addressed to it. **Proven on hardware** end to end from the GSE panel: actuator drives ACK'd by the MCU, and a pad `RELEASE` refused `INTERLOCK` by the Pi with the GSE's own gate disabled (DEVLOG 2026-09-09) |
| P-06 | UART master: command forwarding, HK ingest, time sync every 10 s (RTC/NTP master) | P0 | S.4 | ✔ `clouds_fsw/mcu_link.py`: ACK correlation by sequence number, HK decoded on the way past for the interlock, TIMESYNC doubling as the beat the MCU's M-13 monitor watches. **Running on the bench UART** (`/dev/ttyAMA0`, PL011 on GPIO14/15 — see CLAUDE.md for what enabling it took) |
| P-07 | Communications log (all up/downlink traffic) to Pi SD | P1 | SED storage split | ✔ |
| P-08 | systemd unit: auto-start, restart-on-crash, RuntimeWatchdogSec=15, MCU-liveness alarm | P0 | S.9 | ✔ |
| P-09 | Auto-exposure guard: clip/saturation flagging (reuse ground-software logic); fixed exposure default for flight | P1 | F.1 | ✔ |
| P-10 | Graceful degradation: spectrometer USB loss → keep comms + HK relay running, periodic reconnect | P1 | S.7 mirror | ✔ |
| P-11 | Camera capture + thumbnail downlink (only if F.7 camera confirmed) | P2 | F.7 | ☐ |

## GSE — ground station (Python candidate; §4.12)

| ID | Feature | Prio | Trace | Status |
|---|---|---|---|---|
| G-01 | Live HK display: temperatures, humidity, pressures, IMU, rails, state, actuator status | P0 | §4.12.1 | ✔ the flight half of the one operator interface (`clouds_ui`). Actuator status is the `Membrane` and `Driving` rows (`ValveStatus` bits); a commanded drive is a 5 s pulse, so this is the only place ground sees it happen. A `Sensors` section shows every reading in the packet against the part that produces it, and a field whose `HKE_*` bit says it has no source reads `not populated` instead of a number. **Rails show volts and amps**, one row per INA226, right-aligned in the monospaced face so three rails read as a column; `no monitor` where the part did not answer, because 0.00 V / 0.000 A is what a genuinely dead rail reads. The shunt resistances the current is derived from are printed under the section - if one is wrong every amp on the panel is wrong with it, and the operator has to be able to see which assumption to doubt |
| G-02 | Live quick-look spectrum display (reuse this repo's dual-trace view / `spectro/` processing) | P0 | §4.12.1 | ✔ and it is literally the same view now: `clouds_ui` renders detector frames and downlink quick-looks on one axis, with an explicit source selector and a banner naming the source, its rate and its binning — the two were separate applications precisely because they are easy to mistake for each other |
| G-03 | Command console with arm/execute UI + full command set | P0 | §4.12.1 | ✔ plus an **Actuators** panel for the dispersion hardware - membrane duty + frequency with Drive/Stop, one motor pulse - and `membrane <duty>` / `disperse` in the console monitor |
| G-04 | Ground interlock: particle-release commands blocked while on ground | P0 | S.10 | ✔ and re-checked on the Pi (`FLIGHT_ONLY`): the GSE's own check runs on a laptop and anything can open TCP 4001, so `RELEASE` needs fresh HK showing ASCENT..MEASURE_2 or it is refused `INTERLOCK` — `allow_ground_release` overrides it for bench rehearsals, loudly |
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
