# Commands — run, check, build

Moved out of `CLAUDE.md` 2026-09-18.

## PYTHONPATH

`PYTHONPATH` must include the repo root, plus `gse/` and `flight/pi/` for their
packages. On Windows also `$env:PYTHONIOENCODING='utf-8'` for `verify_qt.py`.

`./run_clouds_ui.sh [flags]` is the launcher (repo venv + the three
`PYTHONPATH` entries, args passed straight through); `run_clouds_spectral.bat`
is its Windows counterpart. By hand:

## Applications

```sh
# the operator interface - one window, instrument + flight (clouds_ui/)
python -m clouds_ui                     # real Duo on this machine; on macOS
                                        # this defaults to --net 192.168.100.10
python -m clouds_ui --net 192.168.100.10          # detector on the Pi
python -m clouds_ui --flight            # downlink only: HK, quick-look, commanding
python -m clouds_ui --mock              # no hardware: synthetic detector +
                                        # simulated Pi/MCU on loopback

# flight app (on the Pi, from /opt/clouds)
python3 -m clouds_fsw.main --config /etc/clouds/fsw.json
python3 -m clouds_fsw.main --mock                  # mock spectrometer + UART stub
python3 -m clouds_fsw.main --no-uart               # real detector, no RP2350 wired
python3 -m clouds_fsw.main --no-uart --bench-stream  # + serve the live panel

# ground station, headless (no display, or scripted integration use)
python -m clouds_gse.main --experiment 192.168.100.10
```

## Reading a session back

```sh
python plot_session.py                 # the newest session in ./gse_sessions
python plot_session.py --list          # every session found, newest first
python plot_session.py gse_sessions/session_20260918_110620_events.csv
                                       # that session - naming any one of its
                                       # files plots all of them
python plot_session.py output/session_20260918_205940.csv   # instrument log
python plot_session.py --save out.pdf  # write instead of show (headless: it
                                       # writes to output/ by itself and says so)
```

One stacked plot per unit on a shared time axis, with events and commands as
marked lines across all of them. `--gap S` sets when a dropout breaks a trace
(default 5 s, widened automatically for a slower stream like Pi status);
`--no-marks` leaves the event/command overlay off.

## Checks — run all four before committing

```sh
python -m pytest tests/                 # 150+ tests, no hardware needed
python verify.py                        # driver + calibration self-checks
python -u verify_qt.py                  # offscreen UI; must end "VERIFY OK"
flight/mcu/test/run_native.sh           # firmware core (C, host compiler)
```

## RP2350 firmware

Details + the macOS toolchain trap are in `flight/mcu/README.md`.

```sh
export PICO_SDK_PATH=~/pico-sdk PICO_TOOLCHAIN_PATH=~/arm-gnu-toolchain
cmake -S flight/mcu -B flight/mcu/build -DPICO_PLATFORM=rp2350   # board defaults to clouds_carrier (RP2350B)
cmake --build flight/mcu/build -j8
picotool load -f -x flight/mcu/build/clouds_fsw_mcu.uf2   # -f: no BOOTSEL needed
```

`PICO_BOARD` is cached — **reconfigure `flight/mcu/build` from scratch** after
a board-header change.

The build needs the Bosch BMV080 archives from the sibling `sensor-driver/`
tree (`-DCLOUDS_BMV080_SDK_DIR=` to point elsewhere); `flight/mcu/README.md`
says why and which archive.

## Bench probes (sensor bring-up, never flight images)

Gated behind `-DCLOUDS_BUILD_TOOLS=ON` so a normal build cannot emit a `.uf2`
that is not the flight image. Each prints to USB CDC and commands no actuator.

```sh
cmake -S flight/mcu -B flight/mcu/build-tools -DPICO_PLATFORM=rp2350 \
      -DCLOUDS_BUILD_TOOLS=ON
cmake --build flight/mcu/build-tools -j8
picotool load -f -x flight/mcu/build-tools/bme280_probe.uf2   # chip id 0x60?
picotool load -f -x flight/mcu/build-tools/bmv080_probe.uf2   # sensor id + PM
picotool load -f -x flight/mcu/build-tools/bno055_probe.uf2
picotool load -f -x flight/mcu/build-tools/membrane_switch_probe.uf2
picotool load -f -x flight/mcu/build-tools/encoder_pin_probe.uf2     # which pins move with the shaft (DRIVES THE MOTOR)
picotool load -f -x flight/mcu/build-tools/encoder_trace_probe.uf2   # 80 ns trace of GP19..GP22 (DRIVES THE MOTOR)
```

`bme280_probe` sweeps all four SPI_1 chip selects at two modes and two bauds,
plus i2c0, and bit-bangs a read in case MOSI/MISO are crossed.
`bmv080_probe` does raw 16-bit reads per free chip select, then
`bmv080_open()` per select, then PM lines — and prints what to check when
nothing answers.

### Reading `bme280_probe`, in order

It prints three bus-integrity tests **before** the chip-id table, because the
table is meaningless while the bus cannot carry a transaction — every chip
select returns `0x00` when nothing is on the bus, so the sweep cannot tell
them apart (`docs/TRAPS.md`).

| Test | Question | How to read it |
|---|---|---|
| **(a)** | does asserting a chip select **change** what MISO reads? | The baseline must be `1` — an idle bus with a pull-up. A select that *changes* it has something behind it. A select that merely *reads* `1` says nothing |
| **(b)** | can each bus pin be driven high **and** low at the pad? | `cannot drive it high` = held by something low-impedance. **Only meaningful if the pin is not floating** |
| **(c)** | are any two bus pins tied together? | Same caveat, and it is the one that misleads: an unconnected RP2350 pad latches and couples to neighbours, which prints as `TIED TOGETHER` |

**Confirm the harness is plugged in and the part powered before believing (b)
or (c)** — the probe says so under its own output. Anything reporting
`UNSTABLE` changed under the five samples, which is a result, not noise.
