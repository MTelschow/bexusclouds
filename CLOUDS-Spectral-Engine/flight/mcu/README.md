# CLOUDS FSW-MCU — RP2350 sequencer firmware

The **authoritative experiment sequencer** (spec: [docs/SOFTWARE_SPEC.md](../../docs/SOFTWARE_SPEC.md),
design: [docs/SED_SOFTWARE_DESIGN_v1-2_draft.md](../../docs/SED_SOFTWARE_DESIGN_v1-2_draft.md)).
Runs the full experiment — launch/float detection, chamber seal, **two**
CaCO₃ releases, membrane dispersion, termination — with no dependency on
the Raspberry Pi, the E-Link, or ground (requirements O.2, S.1–S.3, S.7).

## Layout

| Path | Role |
|---|---|
| `src/core/` | **Portable, unit-tested logic** — no hardware includes |
| `src/core/sequencer.c` | State machine (M-01..M-08): INIT→…→SAFE, persist-before-fire, brownout resume |
| `src/core/autonomy.c` | Launch/float detection + link-loss latch (M-02..M-04) |
| `src/core/link.c` | Pi liveness + the MCU's own arm/execute gate (M-13, S.8) |
| `src/core/frame.c` | Packet frames + HK payload — byte mirror of `clouds_link/` (X-01) |
| `src/core/pulse.c` | Timed actuator drives, released by the loop — the 5 s valve pulse must never be slept through under the 2 s watchdog (S.8, S.9) |
| `src/core/cobs.c`, `crc16.c` | UART framing + CRC-16/CCITT-FALSE (S.5) |
| `src/core/config.c` | SET_PARAM table with range limits (M-16) |
| `src/hw/` | Pico SDK layer: pins, actuators, sensors, UART, watchdog |
| `src/main.c` | 1 Hz loop: sensors → log → HK → step; poll commands; kick watchdog |
| `test/test_core/` | Native test suite incl. the **simulated-flight harness (X-03)** |

## Tests (no hardware needed)

```sh
pio test -e native          # PlatformIO (bundles Unity)
./test/run_native.sh        # or: plain cc + vendored unity_min shim
```

54 tests: protocol vectors shared with the Python side, plus the T-07
rehearsals — the automatic-mode cycle walked phase by phase, the immediate
stop on the first command back, STANDBY never cycling, hold/abort, launch and
float reported without moving anything, and reset-resume. The cycle runs
twice: once with instant mock actuators, once with every
drive taking its real 5 s through `core/pulse` (one solenoid at a time,
nothing energized in SAFE).

`tests/test_fsw_mcu_actuators.py` guards the same invariant at source level
for `src/hw/`, which the native build cannot compile — and with it the
schema mirrors (ACK results, SET_PARAM keys, command codes, the arm window)
and the S.7 rule that `core/link.c` cannot reach the sequencer.

## Firmware build (official Pico SDK, per SED 4.11i)

```sh
export PICO_SDK_PATH=~/pico-sdk        # SDK >= 2.0
cmake -B build -DPICO_PLATFORM=rp2350  # PICO_BOARD defaults to clouds_carrier
cmake --build build                    # -> clouds_fsw_mcu.uf2
picotool load -f -x build/clouds_fsw_mcu.uf2   # -f forces BOOTSEL over USB
```

**The build needs the Bosch BMV080 SDK.** The particulate sensor has no
public register map, so its measurement algorithm is two prebuilt archives and
the flight image does not link without them. They are expected in the sibling
`sensor-driver/` tree (same git repo, one level above
`CLOUDS-Spectral-Engine`); point elsewhere with
`-DCLOUDS_BMV080_SDK_DIR=/path/to/sdk`, and CMake fails with that message if
the archive is missing rather than erroring somewhere in the link. The
`arm_cortex_m33` archive is the right one - **not `m33f`**, which is hard-float
and the SDK builds RP2350 `softfp`. The archives and the vendor headers are
Bosch-confidential with no redistribution grant
(`sensor-driver/LICENSE.md`): anyone handed this repo needs their own copy from
Bosch.

**The core-0 stack is moved out of the scratch banks** for the same sensor -
its library wants 10 kB where SCRATCH_Y holds 4 - by four linker `--defsym`s
in `CMakeLists.txt`, which explains the arithmetic. Two consequences worth
knowing before touching memory here: RAM is 504 kB rather than 512, and
SCRATCH_X is zero-length, so a `__scratch_x` placement now fails the link.

**The board is the carrier, not a Pico 2.** The CLOUDS carrier is an RP2350B
(QFN80, GP0..GP47); `boards/clouds_carrier.h` tells the SDK so
(`PICO_RP2350A 0`), and `CMakeLists.txt` selects it by default. The old
`-DPICO_BOARD=pico2` (RP2350A, GP0..GP29) still builds - for the bare Pico 2
on the bench - but everything above GP29 is compiled out on it, starting with
the membrane position switch on GP30, which then downlinks
`HKE_NO_MEMBRANE_SENSE` instead of a position. `PICO_BOARD` is cached by
CMake: an existing `build/` configured for pico2 must be deleted and
reconfigured, not just rebuilt.

**macOS: do not use Homebrew's `arm-none-eabi-gcc`.** It ships without newlib,
so every link dies on `cannot find -lg` / `cannot find -lc` - the first failure
is the SDK's own `bs2_default.elf`, which makes it look like an SDK problem.
Use the Arm GNU toolchain instead and point the SDK at it:

```sh
brew install picotool                  # plus libusb, for flashing
# Arm GNU Toolchain (bundles newlib). The cask installs a .pkg needing sudo;
# `pkgutil --expand-full <pkg> <dir>` extracts the same payload without root.
export PICO_TOOLCHAIN_PATH=~/arm-gnu-toolchain
```

**stdio is on USB, never on UART.** HK comes out of UART0 (GP0 TX / GP1 RX,
115200 8N1), which is exactly where the SDK would put stdio if it were
enabled — a `printf` there would land between framed HK packets. So
`pico_enable_stdio_uart` is 0 and `pico_enable_stdio_usb` is 1, which also
brings the picotool reset interface: `picotool load -f` reflashes a running
board with no BOOTSEL button. The USB half only works because `main()` calls
`stdio_init_all()`; without it the driver is compiled and then discarded.
Both invariants are guarded by `tests/test_fsw_mcu_stdio.py`.

## The link to the Pi (M-12, M-13, S.4, S.7, S.8)

The Pi is a **peer, not a dependency**: this loop is complete with the UART
unplugged, and nothing on the link may delay a state transition (S.7).

| Direction | Frames | Rate |
|---|---|---|
| MCU → Pi | `HK` (44 B payload), `EVENT`, `ACK` | 1 Hz + on demand |
| Pi → MCU | `CMD`, `TIMESYNC` | on demand + 10 s |

- **Every command is answered, and none is refused for state**
  (2026-09-18). `handle_command()` hands the frame straight to
  `seq_command()`, whose return value *is* the ACK result. `OK` for anything
  the firmware can act on, in any state; `INVALID` for what it cannot — an
  unknown command, a duty above 100, a parameter outside its envelope.
  `REJECTED` and `NOT_ARMED` are no longer produced: the arm/execute gate
  that lived in `core/link.c` is gone, and so is the ground interlock on the
  Pi in front of it.
- **Pi liveness is reported, never acted on.** Any valid frame refreshes it;
  after `PARAM_PI_SILENT_S` (default 60 s, against the Pi's 10 s TIMESYNC
  beat) `MCUF_PI_OK` clears and one `EV_PI_LINK_LOST` event goes out.
- **The uplink drain is bounded** (`MAX_FRAMES_PER_PASS`): each command
  costs a blocking ACK write, so an unbounded drain would let a flood of
  frames hold the loop past the 2 s watchdog.

## Open hardware integration points (marked `TODO` in `src/hw/`)

- **M-11 SD stack**: FatFs over SPI0, both cards; persistence is a RAM
  stub until then — flight code MUST replace it (S.3 depends on it).
  **Blocked**: `board.h`'s SPI0 pins are unverified and measure as
  unconnected, and an SD probe on them gets no response on either chip
  select. Needs the carrier schematic before any code (DEVLOG 2026-08-31).
- **M-09 sensors**: the **BME280 is done** (`src/hw/bme280.c`, ambient
  T/RH/pressure, verified on the board). Everything else on this carrier has
  no source and is flagged through `error_flags`: the **STLM20 pair is not
  populated** (and GP26, the pin the old map gave `ADC_TEMP1`, is the membrane
  solenoid), and **neither BNO055 answers on i2c0** (0/50 ACK at 0x28 and
  0x29 on 2026-09-11 and again 2026-09-28 while the other four parts on the
  bus answer - `docs/HARDWARE.md`; the 2026-08-31 part that answered
  `CHIP_ID 0xA0` is gone). The SED baselines no IMU at all, so there is
  nothing to verify that integration against (DEVLOG 2026-08-31). Chamber
  pressure and the second RH channel come from a **second BME280 on SPI_1**
  (chip select GP9), downlinked as `chm_*` behind `HKE_BME280_CHM_FAIL` -
  added 2026-09-17 and **not yet run against the fitted part**. Particulate
  mass comes from a **BMV080, the second part on SPI_1** (chip select GP12),
  downlinked as `pm2_5_ugm3` behind the `pm_status` byte - added 2026-09-28
  and **never answered on any board yet** (chip-id mismatch 107 on the
  2026-09-11 bench run, MISO undriven). Its driver is `src/hw/bmv080_dev.c`
  over `src/hw/bmv080_port.c` and the vendor archives; it is the one file in
  `src/hw/` allowed to block, because the library's delay callback is
  synchronous. Bring it up with `src/tools/bmv080_probe.c` before trusting the
  flight image, and check PS-low-at-power-up and all four supply rails first -
  neither is fixable in firmware.
- **SPI_1 itself is the open item, not either part.** Measured 2026-09-28:
  nothing answers on any of the four chip selects, and `src/tools/bme280_probe`
  now runs three bus-integrity tests ahead of its chip-id table to say why.
  The result that holds is test (a) - MISO idles high correctly and **no chip
  select changes it**, so nothing is responding. The drive and cross-short
  results (b)/(c) are **not** trustworthy while the pins may be floating: an
  unconnected RP2350 pad latches and couples to its neighbours, which reads
  exactly like a short, and this project has measured that behaviour before
  (DEVLOG 2026-09-11). Two rules came out of it, worth keeping for any future
  pin test here: **park every pin not under test as a high-impedance input**
  or you measure the SPI peripheral instead of the board, and **settle "is it
  floating" physically** - unplug the harness and re-run, or fit an external
  10k pull-up - before reading anything into a level. `docs/TRAPS.md` has both
  as traps; `docs/DEVLOG.md` has the captures.
- **M-09 rails**: the three fitted INA226 monitors are done
  (`src/hw/ina226.c`) - bus voltage in `rail_mv[]` and the raw shunt-voltage
  register in `shunt_raw[]`, both absolute registers. The calibration register
  is left unprogrammed on purpose: amps are Ohm's law on the ground
  (`clouds_link/hk.py` `RAIL_SHUNT_MOHM`, 10 / 15 / 50 / 50 mΩ), so a shunt
  value that turns out wrong can be re-applied to a logged session. Four rails
  ride the packet: `V_in` (0x40, the incoming gondola bus - it was labelled
  24 V until the two were found to be different nets), a **24 V rail with no
  monitor fitted yet**, 5 V (0x44) and 3.3 V (0x45). The unfitted slot reads
  `RAIL_MV_INVALID` and is excluded from `HKE_RAIL_FAIL` by `ina226_fitted()`:
  a flag that is set on every packet stops being read.
- **M-07 dispersion motor current sense**: `ACT_HB_SENS` on GP46 (ADC6 on the
  RP2350B) is sampled once per HK sweep - eight conversions averaged - and
  downlinked raw in `hb_sense_raw` (u16, 0..4095; `HB_SENSE_INVALID` 0xFFFF
  from a pico2 build, which has no GP46). It belongs to the **CaCO3 motor**,
  not the membrane solenoid: `ACT_HB` is one driver channel carrying GP17/GP18
  and this pin. The driver is a **DRV8251A**, whose IPROPI output mirrors the
  low-side current at 1500 uA/A into a 1.5 kOhm resistor, so ground scales the
  counts by `clouds_link/hk.py HB_SENSE_A_PER_V` = 0.444 A/V (3.3 V full scale
  = 1.47 A). No conversion in firmware, for the same reason as the shunts.
  **IPROPI reads 0 in coast** - it only sees low-side current - and the motor
  runs in 5 s pulses, so zeros between releases are expected. Guarded by
  `HAVE_HB_SENSE`, like the GP30 switch.
- **M-07 membrane**: the drive is done. GP26, measured, with
  `PARAM_MEMBRANE_MHZ` (millihertz, 0.1..400 Hz) reaching the driver through `seq_ops_t.ctx`, default
  **2 Hz**. Because 2 Hz is below the ~9 Hz PWM floor, edges are toggled from
  `hw_actuators_service()` via `core/sqwave` - loop-released for the same
  reason the valve pulses are, so a hung loop cannot leave the solenoid
  energized. At or above the floor it still uses a PWM slice. Verified on the
  board at 300 ms high / 200 ms low. The duty-cycling that holds dispersion
  for >= 3 min (P.7) is still the sequencer's side. The three
  INA226 rail monitors on the bus have no field in the 44-byte HK payload.
- **M-15 seal check**: chamber-vs-ambient divergence once plumbing exists.
- **M-17 self-tests**: sensor plausibility, SD write test, continuity.
- **M-06 actuation verify**: current sense / pressure response after a
  drive. The drive itself is done — timed, interlocked, non-blocking.

Pin map: `src/hw/board.h` (preliminary — track the PCB).
