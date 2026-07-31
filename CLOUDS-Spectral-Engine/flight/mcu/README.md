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

27 tests: protocol vectors shared with the Python side, plus the T-07
rehearsals — full autonomous double release from a simulated pressure
profile, hold/resume/abort, ground overrides, float-timer fallback, seal
retry, link-loss latch, and reset-resume without re-firing (S.3). The
rehearsal runs twice: once with instant mock actuators, once with every
drive taking its real 5 s through `core/pulse` (one solenoid at a time,
nothing energized in SAFE).

`tests/test_fsw_mcu_actuators.py` guards the same invariant at source level
for `src/hw/`, which the native build cannot compile.

## Firmware build (official Pico SDK, per SED 4.11i)

```sh
export PICO_SDK_PATH=~/pico-sdk        # SDK >= 2.0
cmake -B build -DPICO_PLATFORM=rp2350 -DPICO_BOARD=pico2
cmake --build build                    # -> clouds_fsw_mcu.uf2
```

## Open hardware integration points (marked `TODO` in `src/hw/`)

- **M-11 SD stack**: FatFs over SPI0, both cards; persistence is a RAM
  stub until then — flight code MUST replace it (S.3 depends on it).
- **M-09 sensors**: BME280 / Keller 23SY / IMU drivers (STLM20 ADC done).
- **M-15 seal check**: chamber-vs-ambient divergence once plumbing exists.
- **M-17 self-tests**: sensor plausibility, SD write test, continuity.
- **M-06 actuation verify**: current sense / pressure response after a
  drive. The drive itself is done — timed, interlocked, non-blocking.

Pin map: `src/hw/board.h` (preliminary — track the PCB).
