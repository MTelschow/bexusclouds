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

50 tests: protocol vectors shared with the Python side, plus the T-07
rehearsals — full autonomous double release from a simulated pressure
profile, hold/resume/abort, ground overrides, float-timer fallback, seal
retry, link-loss latch, and reset-resume without re-firing (S.3). The
rehearsal runs twice: once with instant mock actuators, once with every
drive taking its real 5 s through `core/pulse` (one solenoid at a time,
nothing energized in SAFE).

`tests/test_fsw_mcu_actuators.py` guards the same invariant at source level
for `src/hw/`, which the native build cannot compile — and with it the
schema mirrors (ACK results, SET_PARAM keys, command codes, the arm window)
and the S.7 rule that `core/link.c` cannot reach the sequencer.

## Firmware build (official Pico SDK, per SED 4.11i)

```sh
export PICO_SDK_PATH=~/pico-sdk        # SDK >= 2.0
cmake -B build -DPICO_PLATFORM=rp2350 -DPICO_BOARD=pico2
cmake --build build                    # -> clouds_fsw_mcu.uf2
picotool load -f -x build/clouds_fsw_mcu.uf2   # -f forces BOOTSEL over USB
```

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

- **Every command is answered.** `handle_command()` gates it through
  `core/link.c` (arm/execute) and, if it passes, `seq_command()` — whose
  return value *is* the ACK result. Ground therefore hears the MCU's own
  verdict: `REJECTED` for a release in the wrong state or a valve already
  fired, `NOT_ARMED` for an unarmed release, `INVALID` for an unknown
  command or an out-of-range parameter.
- **The MCU keeps its own arm latch.** The Pi enforces S.8 first, but a
  corrupted `CMD_RELEASE` that survives CRC-16 must not be able to fire a
  valve on the strength of the wire alone. One `ARM` authorises exactly one
  execute, inside `LINK_ARM_WINDOW_MS` (mirrors `ARM_WINDOW_S` on the Pi).
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
  solenoid), there is no chamber pressure sensor and no second RH channel on
  i2c0, and the BNO055 at 0x28 answers with a valid chip id while its
  accel/mag/gyro IDs read 0x00. The SED baselines no IMU at all, so there is
  nothing to verify that integration against (DEVLOG 2026-08-31).
- **M-07 membrane**: the drive is done. GP26, measured, with
  `PARAM_MEMBRANE_HZ` reaching the driver through `seq_ops_t.ctx`, default
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
