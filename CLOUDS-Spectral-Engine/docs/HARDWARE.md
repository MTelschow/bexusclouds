# Hardware — measured truth

Moved out of `CLAUDE.md` 2026-09-18. Detector, RP2350 carrier pinout, HK wire
format, and the open flight gaps that hang off them. New findings go here with
the measurement that showed them.

## Detector

EURECA **e9u-SPMD-350850-10-Duo**, board `e9u_LSMD-TCD1304-PRO`, **S/N
20260312-004**, INSION bench, **Toshiba TCD1304DG** 2048-px line CCD.
USB → FTDI **FT2232H** (`0403:6010`, iSerial `EU02290003`) → VCP serial. The
vendor library auto-detects the camera; no COM port or tty is hardcoded.

- **One detector carries both fibre channels.** `calibration.json`: Ch1 window
  `[0, 235]` (measurement), Ch2 `[1516, 1766]` (reference); the gap is dark.
  One shared exposure for both.
- **ADC is 12-bit**, transfer 16 bits/pixel. Identity reports
  `Dark_Pixel: 0 x 16` *before* `Pixel: 1 x 2048` — parse with care.
- `saturation_count` is **65520**, i.e. the 16-bit scale (12-bit × 16), not 4095.

## RP2350 carrier - measured, not from the drawings

`board.h` calls itself preliminary and it means it: five of its pin
assignments were wrong on the real board, and the wrong ones included two that
drive an actuator. Everything below was measured, with
the method in `docs/DEVLOG.md` (2026-08-31). **Measure before trusting that
header.** Two boards are in play; keep them apart by USB serial - bare Pico 2
`182A9FD0C5146E6F`, CLOUDS carrier `21DD2AE08840C863`.

**The carrier schematic (`pin_layout.jpeg`, 2026-09-11) confirms every measured
pin and contradicts two that were never measured.** The full net table is in
`board.h`. `PIN_PINCH_1`/`PIN_PINCH_2` (GP2/GP3) are the Pi's **`PI_RTS`/
`PI_CTS`**, and `PIN_EQ1/2_OPEN/CLOSE` (GP4..GP7) are **`SPI_0` + `SD_1_SENS`**
- so firing a pinch valve today toggles a UART flow-control line. Those defines
are **deliberately left wrong** with the contradiction written beside them: the
board's actuator channels are `ACT_R_1..4` (GP26/25/24/23), `ACT_EC`
(GP19..GP22) and `ACT_HB` (GP17/GP18/GP46), but the page names *channels, not
loads*, and guessing which relay holds pinch 1 is how an actuator gets driven
from the wrong pin. Needs the load side of the schematic or a measurement.
Also: the carrier is an **RP2350B** (GP0..GP47). The build was
`-DPICO_BOARD=pico2` (RP2350A, 30 GPIOs) until 2026-09-17, which left the
INA226 alert pins, the 24 V regulator enable, five ADC channels and
`ACT_HB_SENS` unreachable; it now defaults to `flight/mcu/boards/clouds_carrier.h`
(`PICO_RP2350A 0`), the first user being the membrane switch on **GP30**.
`-DPICO_BOARD=pico2` still builds for the bare Pico 2, with GP30 compiled out
and `HKE_NO_MEMBRANE_SENSE` set. **Reconfigure `flight/mcu/build` from
scratch** after pulling this: `PICO_BOARD` is cached.

| What | Where | State |
|---|---|---|
| i2c0 | **SDA GP28, SCL GP29** (not GP12/13, which are SPI_1 chip selects) | BME280 `0x76`, the **ambient** part - the only usable sensor on this bus |
| spi1 | **MISO GP8, SCK GP10, MOSI GP11**, CS **GP9** (`SPI_1_CS1`) | **Chamber BME280** (2026-09-17). Second identical part, own bus, own error bit `HKE_BME280_CHM_FAIL`; downlinked as `chm_temp_cc` / `chm_rh_cpct` / `chm_p_pa`. **Instrumentation only** - `autonomy_step()` still reads `p_amb_pa` from the i2c0 part, so a chamber fault cannot fire a valve. Safe to `spi_init()` where SPI_0 is not, because nothing else in `board.h` claims GP8/GP10/GP11. Mode 0, 1 MHz, CS driven as plain GPIO (hardware CSn deasserts between bytes and breaks the address-then-burst read). **Never run against a fitted part** - the CS is as specified, not measured; a wrong CS fails the `0x60` chip-id check and downlinks the flag, so try GP12/GP13/GP47 before suspecting the sensor |
| INA226 ×3 | `0x40` **V_in**, `0x44` 5 V, `0x45` 3.3 V | live and **downlinked**: bus voltage in `hk.rail_mv[]` (mV, measured 24.06 / 5.09 / 3.30 V) and the raw shunt-voltage register in `hk.shunt_raw[]` (i16, 2.5 µV/LSB). **Amps are computed on the ground**, `hk.rail_a()` over `RAIL_SHUNT_MOHM = 10, 15, 50, 50 mΩ` - the part's calibration register is left alone, so a wrong shunt value can be corrected against a logged session instead of being baked into it |
| INA226 24 V | **not fitted** | the rail holds slot 1 of `rail_mv[]` / `shunt_raw[]` and downlinks `RAIL_MV_INVALID`; the panel says `not fitted`, and `HKE_RAIL_FAIL` is **not** raised for it - an absent part is not a fault to chase (`ina226_fitted()`) |
| BNO055 IMU | `0x29` **or** `0x28` - the strap, not the part: 0x29 is the datasheet default and COM3 has an internal pull-up, so `hw/bno055.c` tries both and latches whichever returns a whole ID block | **does not answer (2026-09-11)**: 0/50 ACK at 0x28 *and* 0x29, read- and write-probe, in the same sweep where 0x40/0x44/0x45/0x76 all answer - electrically absent from i2c0, which is *not* the "sub-sensor dies dead" on record from 2026-08-31, when it answered `CHIP_ID 0xA0`. The board changed between those dates. Driven by `hw/bno055.c`: **400 ms start-up wait (TSup) before the bus is touched at all**, then reset, 650 ms boot (TPOR), ID check, 19 ms CONFIGMODE wait, 7 ms mode switch, `OPR_MODE` read-back, 30 s retry - five 1 Hz sweeps to a first sample, never sleeping. With no part it reports `HKE_IMU_FAIL` and zeroed vectors, verified on hardware. **`BNO_INT` is on GP27** and reads `pu=1 pd=0`, which **proves nothing** - `INT_EN`/`INT_MSK` reset to `0x00` and nothing enables an interrupt, so a *working* part may leave the line undriven too (only an actively driven pin says anything). What is *absent* cannot be told apart from unpowered, held in nRESET, or PS1/PS0 strapped to UART - that needs a meter, not firmware. HID-I2C is ruled out: `0x40` answers as a verified INA226. `src/tools/bno055_probe.c` (`-DCLOUDS_BUILD_TOOLS=ON`, USB CDC) discovers the strap; flash it first when a part is fitted. Verified on the carrier with no part: 119 HK in 120 s, uptime monotonic (no watchdog reset), `IMU_FAIL` set, vectors zero, rest of the bus undisturbed. **The success path has never run against real silicon** |
| Membrane solenoid | **GP26** (not GP8, unconnected) | **2 Hz**, loop-toggled via `core/sqwave`; driven from the GSE panel end to end (`MEMBRANE` duty), duty read back in HK |
| Membrane position switch | **GP30**, input, internal pull-up, switch to ground | **LOW = actuated (plunger presses the button), HIGH = resting (button released)** - `hw_membrane_pulled()` inverts the pin (2026-09-17). Downlinked as `HKV_MEMBRANE_PULLED` (bit 5 of `valve_status`, a *sensed* bit that may sit beside a drive bit); the panel's `Membrane` row reads `60 %  pulled` / `pushed`, `actuator_text` leaves it out. The **light beside Drive/Stop is a verdict, not a position**: green = drive on and `MEMBRANE_CYCLING` set (plunger following), red = drive on, an edge was due inside the 1 s packet and none came, grey = solenoid off, drive slower than the 1 Hz sample can judge, or no reading. Rate comes from the last ACKed `SET_PARAM MEMBRANE_MHZ` (`FlightPanel._membrane_hz`, default 2 Hz) - it is not in HK. At 2 Hz the 1 Hz HK sample catches a random phase, so with the drive on it alternates between packets - stuck either way against the drive is the fault it exists to show. Needs the RP2350B board header (above). **Measured 2026-09-17 with `tools/membrane_switch_probe`: follows GP26 one for one** - LOW at rest, HIGH the whole time GP26 is high, ~40 ms release lag when it drops; the H-bridge (GP17/GP18) does not move it. A first run that read LOW throughout was the solenoid not moving. **That measurement disagrees with the decode now in the firmware** (pin follows the drive, so LOW-at-rest would downlink `pulled` at rest): the inversion is the mechanical assignment as specified, and the probe needs re-running against the fitted plunger to settle it |
| CaCO₃ motor current sense | **GP46** (`ACT_HB_SENS`), ADC6 on the RP2350B | It senses the **dispersion motor**, not the membrane solenoid: `ACT_HB` is one driver channel carrying GP17/GP18 (drive) + GP46 (sense). **Downlinked raw**: 12-bit counts in `hk.hb_sense_raw` (8-sample mean, one point per 1 Hz sweep against a 5 s motor pulse). Driver is a **DRV8251A**; IPROPI mirrors the low-side current at `AIPROPI` 1500 µA/A into `R_IPROPI` 1.5 kΩ, so ground scales by `HB_SENSE_A_PER_V = 1/(R×A)` = **0.444 A/V** (3.3 V full scale = 1.47 A) - counts stay raw so a wrong resistor is correctable against a logged session. **IPROPI reads 0 in coast** (low-side current only), so 0 A ≠ no current, and zeros between releases are expected. Sentinel `HB_SENSE_INVALID` (0xFFFF) from a pico2 build, never 0. Panel row `Motor I`, timeline `Dispersion motor current`. **Not yet read against a running motor** |
| CaCO₃ dispersion motor | **GP17 fwd / GP18 rev** | one 5 s scheduled pulse per release or per `DISPERSE pulse` (key 1), seen in `valve_status` for ~5 s; runs concurrently with the membrane, measured. **Start/Stop as well** (2026-09-17): `DISPERSE run` (key 2) holds the motor on until `DISPERSE stop` (key 0), which also cuts a pulse short and is the one drive command accepted in TERMINATION/SAFE. A run is a *hold beside* `core/pulse` (`motor_held` in `hw.c`), not a queued pulse - in the queue it would delay a release's pinch valve indefinitely and keep `busy()` true through SEAL; so `HKV_DISPERSE` can sit beside a pinch bit while an operator run overlaps a release, and nothing on the MCU times a run out. **Speed is `PARAM_DISPERSE_DUTY`** (percent, default 50, floor 20): GP17 is a 20 kHz hardware PWM for the length of the drive - not `core/sqwave`, which is for the sub-9 Hz membrane - latched when a pulse is *queued* or a run starts, and re-latched at once by a `SET_PARAM` while running. The panel's Speed slider sends `SET_PARAM DISPERSE_DUTY` before a pulse or Start, and again on **any** change while running; the release path reads the same parameter, so there is no bench-only speed. It listens on `valueChanged` *and* `sliderReleased`, not the release alone - `sliderReleased` is emitted only for a drag of the handle, so until 2026-09-17 the arrow keys, the wheel and a click on the groove moved the number beside the slider and never told the MCU, leaving the panel showing a speed the motor was not turning at. `valueChanged` defers while `isSliderDown()`, so a drag still spends one SET_PARAM rather than one per step, and an unchanged duty is never re-sent. **Not in HK** - the SET_PARAM ACK is the confirmation. **not in the SED**, reverse sense untested, **current sensed on GP46 (row above) but not yet read against a running motor; on no monitored rail**, PWM path not yet run against the motor |
| STLM20 ×2 | none | **not populated**; the old `ADC_TEMP1` collided with GP26 |
| SD / SPI0 | **pinout now known** from the carrier schematic (2026-09-11): SPI_0 on GP4/GP6/GP7, `SD_1_CS` GP14 + `SD_1_SENS` GP5, `SD_2_CS` GP16 + `SD_2_SENS` GP15 | still no defines. **M-11 is no longer blocked on the schematic but on a pin conflict**: `board.h` currently gives GP4..GP7 to the equalisation valves, and an `spi_init()` would drive whatever the valve code thinks it owns. `hardware_spi` is now linked (for the chamber BME280 on **SPI_1**, a different bus with no such conflict) - that does not unblock this, which still needs FatFs and the valve pins moved |

## HK wire format

HK is **64 B** (framed 80 B against an 83 B allowance, ceiling 67 B payload -
**3 B of margin**): 54 B as below, plus `hb_sense_raw` (u16) appended after
`mission_t_s`, plus the chamber BME280's `chm_temp_cc` (i16) + `chm_rh_cpct`
(u16) + `chm_p_pa` (u32) appended after that. Each addition went on the end,
so no older field has ever moved.
Four bytes of `rail_mv[]` / `shunt_raw[]` are the reserved 24 V rail, whose
monitor is not fitted yet - a slot costs 4 B once, a wire-format change on
fit day costs the MCU, the Pi and every logged session. An unreadable rail is
`RAIL_MV_INVALID` (`0xFFFF`), never 0 - **0 mV is a real reading** for a rail
whose supply is absent, and a dead monitor is a different fault from a dead
rail. The sentinel invalidates that rail's `shunt_raw` too, so no current is
ever shown against an unknown voltage.

`HKE_*` **bits 2 and 3 have both been reused** - bit 2 is now
`HKE_NO_MEMBRANE_SENSE`, bit 3 `HKE_BME280_CHM_FAIL`. Both carried retired
sensor flags before 2026-09-11, so **a session logged before that date
decodes those two bits under the wrong names**. Read an old log against the
`HK_SIZE` its frames carry. Bit 7 is the only free one left.

So `temp1/2_cc` has **no source**. It is declared
through `error_flags` (`HKE_*` in `core/frame.h`, `HkErrors` in
`clouds_link/hk.py`, kept in step by a mirror test) rather than filled with
invented numbers. The SED baselines no IMU at all while risk MS002 is
"IMU failure" - hardware and document disagree.

## Open flight gaps

**M-15 now has a candidate sensor it does not yet use.** Seal verification
compares chamber against ambient pressure, and the chamber BME280 on SPI_1
(2026-09-17) is the chamber half. `ops_seal_ok()` is **still
`return true`** - wiring it to `chm_p_pa` was deliberately left out of that
change, because the part has never been read against real hardware and a seal
check is a flight decision. Do it once the chamber part has been shown to
answer, and only then.

**S.3 does not hold yet.** Persistence is still a RAM stub, so brownout resume
does not survive a real reset: the `fired` bit that prevents a second CaCO₃
release is lost on power loss. Largest open flight risk, blocked on the
carrier schematic.

