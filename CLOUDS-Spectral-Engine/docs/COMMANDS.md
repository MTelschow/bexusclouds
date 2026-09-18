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
