# BMV080 bring-up firmware (RP2350 / Pico 2)

Standalone Pico SDK firmware that brings up a Bosch **BMV080** particulate
matter sensor over SPI and reports what it finds on a USB CDC console. It is a
bench tool, not flight software — it lives here, next to the vendor SDK, rather
than in `CLOUDS-Spectral-Engine/flight/mcu`, so the proprietary Bosch archives
stay out of the flight build until the sensor is actually integrated.

## Build and flash

```sh
export PICO_SDK_PATH=~/pico-sdk PICO_TOOLCHAIN_PATH=~/arm-gnu-toolchain
cmake -S . -B build -DPICO_PLATFORM=rp2350 -DPICO_BOARD=pico2
cmake --build build -j8
picotool load -f -x build/bmv080_bringup.uf2   # -f: no BOOTSEL needed
```

Console: USB CDC, 115200 (the rate is ignored by CDC), e.g.
`screen /dev/cu.usbmodem1101 115200`.

`-DPICO_PLATFORM=rp2040 -DPICO_BOARD=pico` builds for an RP2040 Pico instead;
CMake picks the matching vendor archive.

## Pins

Defaults are the dev board's (`src/board_pins.h`), and every one is
overridable, because the sensor moves to the CLOUDS carrier later:

| Signal | Dev board | Override |
|---|---|---|
| MISO | GP16 | `-DBMV080_PIN_MISO=` |
| CS 1 | GP17 | `-DBMV080_PIN_CS1=` |
| SCK  | GP18 | `-DBMV080_PIN_SCK=` |
| MOSI | GP19 | `-DBMV080_PIN_MOSI=` |
| CS 2 | GP20 | `-DBMV080_PIN_CS2=` (255 = not fitted) |

Also `-DBMV080_SPI_INSTANCE=0|1`, `-DBMV080_SPI_CLK_HZ=`, and
`-DMEASUREMENT_READINGS=n` (0, the default, measures the first sensor forever
and so never reaches a second one — pass a count to exercise both).

The three bus pins must belong to one SPI instance. On RP2350A:

```
spi0: RX GP0/GP4/GP16/GP20   SCK GP2/GP6/GP18/GP22   TX GP3/GP7/GP19/GP23
spi1: RX GP8/GP12/GP24/GP28  SCK GP10/GP14/GP26      TX GP11/GP15/GP27
```

Chip selects are plain SIO and can be any free GPIO.

The sensor's hardware IRQ is not wired here, so the driver is polled at 100 ms.
The vendor API demands at least one `bmv080_serve_interrupt()` per second.

## Which vendor archive, and why it matters

Bosch ship two Cortex-M33 builds and **only one links against a Pico SDK
image**. The SDK builds RP2350 with `-mfloat-abi=softfp` — FPU instructions,
arguments in core registers — while `api/lib/arm_cortex_m33f` is tagged
`Tag_ABI_VFP_args: VFP registers`, i.e. hard float, and the linker refuses it.
`api/lib/arm_cortex_m33` carries no VFP-args tag (base AAPCS) and is the one to
use. Check any candidate before trusting it:

```sh
arm-none-eabi-readelf -A api/lib/<arch>/arm_none_eabi_gcc/release/lib_bmv080.a \
  | grep Tag_ABI_VFP_args
```

`lib_bmv080.a` and `lib_postProcessor.a` reference each other's symbols, so they
are linked inside `-Wl,--start-group … --end-group`; a single pass in either
order leaves undefined references.

## What the firmware prints

1. **Passive pin survey** — each bus pin read as a plain SIO input with the
   internal pull up, down, and off, *before* the SPI function is applied. A pin
   already in `GPIO_FUNC_SPI` reads back the controller's drive state, not the
   board's. This says what holds a line; it cannot prove a part is absent,
   because a high-impedance sensor input reads exactly like a bare pin.
2. **Active drive-back** — the RP2350 drives each line and reads its own pin. A
   line that will not follow its driver is shorted or fought. MISO is included
   deliberately: microseconds of contention is the only way to tell a hard
   short to GND from a sensor output. This drives into a short for ~50 µs per
   pin, once per boot.
3. **Cross-short** — one pin driven at a time, all others read. Separates a
   solder bridge between two GPIOs from a short to a supply rail, which the
   drive-back test alone cannot do.
4. **Raw SPI** — words clocked out with CS asserted, printed with no
   interpretation, and no guessing at the register map. All-`0000` or
   all-`FFFF` means nobody is driving MISO.
5. **Vendor probe** per chip select — `open` / `reset` / `get_sensor_id`,
   parameter defaults, and a set-then-read-back of `measurement_algorithm` so
   the write path is proven and not just the read path.
6. **Continuous measurement** — PM1 / PM2.5 / PM10 mass and number
   concentrations, obstruction and out-of-range flags, one line per reading.

## Safety guard

If the drive-back test finds a bus pin that will not follow its own driver, the
firmware prints the diagnostics and then **stops without starting SPI**. A pin
tied to a rail means every transfer drives an RP2350 pad straight into 3V3 or
GND at the bus clock, for as long as the firmware runs — a way to lose a pad,
or to brown out whatever holds the rail. The diagnostics have already extracted
everything the bus can tell you at that point. `-DBMV080_FORCE_BUS=1` overrides
it.

## Bench result, 2026-09-11 — no sensor on the bus

Bare Pico 2, USB serial `E273FB5C22FF6E70`. `bmv080_open` returned **107**
(`E_BMV080_ERROR_MISMATCH_CHIP_ID`) on both chip selects. The cause is the
wiring, not the sensor and not the firmware:

| Line | Passive | Driven | Reading |
|---|---|---|---|
| MISO GP16 | unstable between runs | follows its driver | **floating** — nothing is attached, or the sensor end is not connected |
| MOSI GP19 | low | **stuck low** (driven high, reads 0) | tied to GND, or driven low by something else |
| SCK GP18 | high | **stuck high** (driven low, reads 1) | tied to 3V3, or driven high by something else |
| CS1 GP17 | high | follows | free |
| CS2 GP20 | high | follows | free |

Raw SPI returned all-`0000` on one boot and all-`FFFF` on the next — the
signature of an undriven MISO, not of a part answering badly.

**Neither SCK nor MOSI is an output on a BMV080**; both are slave inputs.
Nothing on a correctly wired sensor can hold them at a rail, and the
cross-short test rules out a bridge between the bus pins themselves. The
pattern — SCK at 3V3, MOSI at GND, MISO open, both selects free — is what a
harness plugged one position off at the sensor end looks like.

Verified working in the same run: the toolchain, the softfp/hardfp archive
choice, the link group, the SPI block (1.000 MHz actual), CS control, and the
vendor library itself (`bmv080_get_driver_version` reports **24.2.0.b8c488edbf8.0**,
which runs library code and needs no sensor).

### Second run after a wiring check — byte-identical, and the instrument is ruled out

Rerun after the wiring was checked: same readings, same status 107. Two further
tests were added first, because a measurement that does not change is exactly
what a broken measurement looks like:

- **Control pins.** GP2, GP3, GP10, GP11, GP21 and GP22 — GPIOs outside the
  harness, on the same chip, through the same code — all follow their drivers.
  The method is sound, so the two stuck pins are a real external fault.
- **Drive-strength escalation.** GP18 and GP19 do not move at 2, 4, 8 or
  12 mA. A pull resistor or a translator output would have given way. They are
  tied to a rail.

So `SCK` sits on 3V3 and `MOSI` sits on GND, at full strength, while `MISO` is
open and both chip selects are free. Nothing on the Pico side is adjacent to
either rail on the header, which puts the fault at the sensor end of the
harness or on the breakout: the pattern is what a connector one position off,
or a breakout whose pad order differs from the assumed one, produces. Resolving
it needs a meter on the breakout pads, or the breakout's part number.

### Third run, with rail logging — shorts gone, still no sensor

The two rail ties are **no longer present**. All five bus pins follow their
drivers, at every drive strength, and the SPI guard does not trip. Whatever was
holding `SCK` at 3V3 and `MOSI` at GND is off the board.

The sensor still does not answer: raw SPI reads all-`FFFF` on both selects and
`bmv080_open` still returns 107. Nothing is driving MISO, so as far as the bus
is concerned there is no part attached — consistent with a harness that is now
disconnected, or a sensor with no power.

Rails, across the same run (5 s profiles, 51 samples each):

| | baseline | after the pin tests |
|---|---|---|
| VSYS | 4.810 V mean, 5 mV span | 4.810 V mean, 7 mV span |
| die | 19.2 C | 19.2 C |
| VBUS | present throughout | present throughout |

4.81 V is USB 5 V less the Pico's input Schottky, and the die reads close to
room temperature — the cross-check in `rails.h` says a collapsed 3V3 would show
up as an implausibly *cold* die, and it does not. No damage signature from the
earlier shorting, and the pin tests cost nothing measurable.

### The passive survey's "held HIGH" was an artifact

Measured, not looked up: the same passive survey run on GP2, GP3, GP10, GP11,
GP21 and GP22 — all unconnected on a bare Pico 2 — reports every one of them as
`pu=1 pd=1 float=1`. **On this RP2350 a floating input latches high despite the
internal pull-down.** So "reads high with the pull-down on" cannot tell an
external pull-up from a bare pin, and the earlier `held HIGH by the board`
verdicts for SCK, CS1 and CS2 said nothing.

Reading *low* against the internal pull-up stays meaningful — something has to
sink that current — so the original `MISO held LOW` observation was real.

The stuck-pin findings never rested on the survey: they came from the
drive-back and drive-strength tests, where the pad drives and the leakage is
irrelevant. Those stand. `survey_pin()` now reports the ambiguous case as
inconclusive rather than as a finding, and the control pins are surveyed
alongside the bus so the artifact is visible in every run.

## Porting to the CLOUDS carrier

Pass the carrier's pins as `-D` overrides; nothing in the sources is
board-specific except the defaults in `src/board_pins.h`. Two things to carry
over when this moves into `flight/mcu`:

- `pico_enable_stdio_uart` must stay **0**. The SDK's default stdio UART is
  `uart0` on GP0/GP1, which is the HK downlink on the carrier, and a `printf`
  there corrupts telemetry.
- The carrier is an **RP2350B** (GP0..GP47) built as `-DPICO_BOARD=pico2`
  (RP2350A, 30 GPIOs). Pins above GP29 are unreachable in that build.

## `backup/`

`backup/Clouds_chaimber_test_E273FB5C22FF6E70.uf2` is the full 8 MB flash image
that was on this Pico 2 before the first load here (program name
`Clouds_chaimber_test`, built Jul 27 2026, SDK 2.3.0). Its source is not in any
repo under `repos/active`. Restore with `picotool load -f -x <that file>`.
