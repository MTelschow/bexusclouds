# CLOUDS Spectral Engine — working notes

BEXUS 38 dual-spectrometer software: a Qt **bench panel**, the **Raspberry Pi
flight app** (FSW-PI), the **RP2350 sequencer firmware**, and the **ground
station** (GSE), all sharing one protocol (`clouds_link/`) and one instrument
layer (`spectro/`).

`docs/` is the source of truth. Don't duplicate it here; update it when
behaviour changes.

| doc | what is in it |
|---|---|
| `docs/COMMANDS.md` | **`PYTHONPATH`, launchers, app flags, the four pre-commit checks, firmware build** |
| `docs/ARCHITECTURE.md` | driver/UI split, `--mock` stack, `clouds_link/`, command-ACK rule, env vars |
| `docs/GUI_SOURCES.md` | detector vs downlink source, quick-look cadence, **downlink budget + HK ceiling** |
| `docs/HARDWARE.md` | detector, **RP2350 carrier pinout (measured)**, HK wire format, open flight gaps |
| `docs/TRAPS.md` | failures that already cost time here — read before debugging hardware or UI |
| `docs/PI_SETUP.md` | bench network PC↔Pi, UART enable, `/opt/clouds` deployment |
| `docs/DRIVER.md` | vendor libraries, USB glitch |
| `docs/CALIBRATION.md` | pixel→nm, **data scaling** |
| `docs/SOFTWARE_SPEC.md`, `docs/SOFTWARE_FEATURES.md` | spec + feature status |
| `docs/DEVLOG.md` | why things are as they are |
| `docs/UI_STYLE.md`, `docs/BENCH.md` | UI conventions, **bench = flight settings**, lamp/QC bench tools |

## Critical rules

- **A failed sensor read must never report a low pressure** — it mimics launch
  detection and fires valves. Hold last good, flag `HKE_P_AMB_STALE`.
- **Every command is confirmed end to end.** A UART write is not evidence of
  execution; a missing ACK is a rejection.
- **The Pi never sequences the experiment** (S.7). The MCU is autonomous; the
  Pi forwards and confirms.
- **Two actuators exist: the dispersion motor and the membrane solenoid.**
  The pinch and equalisation valves were removed from the experiment
  (2026-09-18) along with their pins, drives, HK bits and `RELEASE`, which is
  now answered `ACK_INVALID`. `docs/SOFTWARE_SPEC.md` §5.
- **While ground is connected, nothing is refused** (operator decision,
  2026-09-18): no ground interlock, no arm/execute, no state check. `ACK_OK`
  for anything the chain can parse; `ACK_INVALID` only for input it cannot act
  on. Do not re-add a gate without being asked.
- **`board.h` is preliminary — measure before trusting it.** The pins that
  were wrong were the valves', and they are gone with the valves. `ACT_R_2..4`
  and `ACT_EC` are unmapped on purpose: the schematic names channels, not
  loads. `docs/HARDWARE.md`.
- **Never `printf` on the MCU's `uart0`** — `pico_enable_stdio_uart` stays 0,
  it is the HK downlink.
- **HK payload ceiling is 67 B**; `hk.SIZE` is **80 B — 13 B over**: the
  chamber BNO055's 12 B, the BMV080's 2 B, then the motor encoder's 2 B
  (all 2026-09-28, operator deferred the budget). `tests/test_fsw_telemetry.py::TestDownlinkBudget`
  fails until that is settled — expected, don't "fix" it by editing the test.
  `error_flags` has **no free bit left** (bit 7 = `IMU_CHM_FAIL`), which is
  why the retired `fired` byte at offset 2 is now `pm_status`; the byte never
  moved, but a session logged before 2026-09-18 decodes valve bits there.
  `valve_status` bit 7 is `HKV_DISPERSE_STALLED` (sensed, from the encoder).
- **The motor encoder is digital, not analog** — Faulhaber IE3-1024L,
  differential TIA-422 A/B/I, 5 V, **no receiver on the carrier**. Measured
  2026-09-28: **GP19 = one channel (with 80 ns glitches on 37 % of periods),
  GP21 = the resistor midpoint of both channels (a direction sample at GP19's
  fall, not a channel)**. `hw/quadrature_encoder.pio` is therefore a
  deglitched x1 edge counter with `JMP PIN` direction, **1024 counts/rev**,
  not the pico-examples x4 decoder. Verified ~2190 rpm at 50 % duty. Never
  drive GP19..GP22. `docs/HARDWARE.md`.
- **Three parts on SPI_1, two frame widths.** Chamber BME280 (CS1/GP9, 8-bit)
  and BMV080 (CS2/GP12, 16-bit words) share one bus, so **neither `hw_init()`
  nor `spi_init()` sets a frame format** — each driver sets its own inside its
  `cs_select()`, while CS is still high. Don't hoist it back to bus init.
  **All four SPI_1 selects (GP9/12/13/47) are parked high in `hw_init()`
  before `spi_init(spi1)`** - an unconfigured RP2350 pad is a pulled-down
  input, so an undriven active-low CS is asserted. Don't drop CS3/CS4 as
  "unused". Both BME280s and the INA226s re-init from the sweep every
  `SENSOR_RETRY_MS` while failing; the BMV080 cannot (it sleeps).
- **SPI_1 is dead on the bench (2026-09-28) — the bus, not the drivers.**
  Nothing answers on any of the four chip selects: not the BMV080, not the
  chamber BME280. MISO idles high correctly and **no select changes it**, so
  the pins look floating (harness, fit, or supply rails). Don't debug the
  drivers against this, and don't trust a pin-level result without reading
  `docs/TRAPS.md` first: a floating RP2350 pad latches and couples to its
  neighbours, which reads exactly like a short, and every pin not under test
  must be parked hi-Z or you measure the SPI peripheral instead of the board.
  Both of those cost a wrong conclusion here already.
- **The BMV080 has no register map.** It only works through Bosch's prebuilt
  archives in the sibling `sensor-driver/` tree — plain `arm_cortex_m33`
  (soft-float ABI), never `m33f`, and both archives inside one `--start-group`.
  They are Bosch-confidential with no redistribution grant, and the flight
  image now needs them to link. The library also wants a 10 kB stack, so the
  core-0 stack is moved out of SCRATCH_Y by three linker `--defsym`s
  (`flight/mcu/CMakeLists.txt` explains the arithmetic).
- **`bmv080_port.c` is the one file in `src/hw/` allowed to sleep**, because
  the vendor library calls its delay callback synchronously. It slices the
  wait, kicks the watchdog and refuses anything over `BMV080_DELAY_MAX_MS`.
  The exemption is named in `tests/test_fsw_mcu_actuators.py`; nothing else
  in `hw/` may block.
- **Two BNO055s on i2c0, fixed addresses**: ambient `0x29` (`accel_mg`,
  `IMU_FAIL`), chamber `0x28` (`chm_accel_mg`, `IMU_CHM_FAIL`). One
  `bno055_t` each; never re-add address discovery — it would claim the wrong
  part.
- **Two spectrum sources, operator's explicit choice.** Detector (live, every
  pixel, bench only) vs downlink quick-look (1 Hz, mean-binned). Nothing in the
  app may switch `self.source` on its own. `docs/GUI_SOURCES.md`.
- **The vendor library owns the USB device exclusively** — use
  `clouds_fsw.main --bench-stream`, never a second `spectro.net_server`.

## Conventions

- The bench runs the same settings as flight — `docs/BENCH.md`.
- Calibration lives in `calibration.json`, never hardcoded in the UI.
- Storage first, then downlink (O.3) — see `FlightApp._on_spectrum`.
- Don't commit unless asked; the default branch is `main`.
- New hardware findings belong in `docs/HARDWARE.md`, with the measurement that
  showed it; new failure modes in `docs/TRAPS.md`.
