# CLOUDS Spectral Engine

Ground-test & bench software for the **CLOUDS** dual-spectrometer (BEXUS 38) — a EURECA
**e9u-SPMD-350850-10-Duo** micro-spectrometer (INSION optical bench, **Toshiba
TCD1304DG** 2048-px CCD) read out over USB through the vendor library
(`libe9u_LSMD_x64.dll` on Windows, `libe9u_LSMD.so` on Linux/Pi). One detector
carries **two fibre channels** — a measurement path and a reference path —
ratioed in software.

Built to the CLOUDS design language (`docs/UI_STYLE.md`), sharing the look and
Qt patterns of the *CLOUDS Raytracing Engine*.

## Features (v0.1.0)

* Connect / identify the EURECA Duo (auto-detect, no COM number or tty
  hardcoded) on **Windows or Linux**, locally or over the bench cable
  (`--net HOST`). See `docs/DRIVER.md`.
* Live dual-trace view - measurement (Ch1) and reference (Ch2) on a shared
  wavelength axis, with a wavelength colour strip.
* Single shared integration time (1-1000 ms) + per-channel frame averaging.
* Auto-exposure: **Auto** (one-shot, set ~70% full scale) and **track** (continuous
  servo that holds the exposure as the scene brightness changes - point it around).
* Dark-frame capture and subtraction, **kept across restarts**: a capture is
  stored as the default (`dark_frame.npz`, `CLOUDS_DARK` to move it) and comes
  back with the exposure it was taken at; at any other exposure it is withheld
  rather than silently applied. `Clear` drops it and the stored file.
* Live per-channel saturation/clipping flag.
* Factory INSION pixel -> wavelength calibration (Ch1/Ch2 polynomials).
* Views: Counts, Transmission (meas/ref), Absorbance (-log10); nm or pixel axis.
* Export: timestamped CSV + branded PDF report; optional session logging to CSV.
* Headless `verify.py` / `verify_qt.py` run with no hardware (mock driver).

## Quick start

* Desktop (Windows): double-click **CLOUDS Spectral Engine**
  (`run_clouds_spectral.bat`) — finds an interpreter, sets the three
  `PYTHONPATH` entries, and passes every flag below straight through. Full
  Windows setup, including the bench Ethernet, is
  [below](#windows-from-a-fresh-machine).
* Terminal (macOS / Linux): `./run_clouds_ui.sh` — **builds the environment if
  there isn't one**, then sets the three `PYTHONPATH` entries and passes every
  flag below straight through. Full macOS setup, including the bench Ethernet,
  is [below](#macos-from-a-fresh-machine). Both launchers are thin wrappers;
  the app itself is `python -m clouds_ui`.
* Terminal, by hand: `PYTHONPATH=.:gse:flight/pi python -m clouds_ui`
* Detector on the flight Pi: `python -m clouds_ui --net 192.168.100.10` — and
  this is the **default on macOS**, which has no EURECA vendor library, so a
  bare `./run_clouds_ui.sh` there already reaches the detector over the bench
  cable (`CLOUDS_SPECTRO_HOST` moves the address). The Pi must be serving
  frames: `clouds_fsw.main --bench-stream`, or `spectro.net_server`.
* Ground station (downlink only, no detector): `python -m clouds_ui --flight`
* No hardware at all (demo, training, a UI change you want to see):
  `./run_clouds_ui.sh --mock`

Apart from `--mock`, a spectrum on that screen is always real light off the
Duo — there is no other synthetic-detector route, and `--mock` refuses to run
alongside `--net`.

`--mock` fakes exactly two things: the light on the detector, and the silicon
on the UART. Everything between them is real — the actual flight app
(`clouds_fsw`) with a synthetic spectrometer, a simulated RP2350 answering its
UART (`clouds_fsw/sim_mcu.py`), and the real ground station decoding real UDP
and TCP on loopback. So housekeeping, events, the quick-look, the timeline and
the whole arm/execute command path behave as they do on the bench: `START`
flies a compressed ascent, `ARM`+`RELEASE` fires once and never twice, an
`ABORT` locks the actuators out.

Because a simulated spectrum that looked real would be the worst failure this
app has, the mock says so in the window title, in the plot's source banner and
on the device line; its session logs are named `session_mock_*`; and it never
writes or clears the stored dark frame, which is shared with real sessions.
Ports are ephemeral and bound to loopback, so a mock run cannot collide with a
real GSE on UDP 4000 or take a command from off the machine.
* Fresh machine: Python 3.13 + `pip install -r requirements.txt`.
* On Linux (incl. the Pi) build the vendor library first:
  `drivers/e9u_LSMD_LIB_Linux/install.sh` — see that folder's README.

### macOS, from a fresh machine

```sh
./run_clouds_ui.sh
```

That is the whole install. On a machine with no environment yet the script
picks a base interpreter, creates the repo-local `.venv`, installs
`requirements.txt` into it, and starts the window. Nothing outside `./.venv` is
touched and nothing is ever installed into a system interpreter — `rm -rf
.venv` undoes all of it, and `CLOUDS_NO_SETUP=1` turns the whole behaviour off
in favour of printing the commands.

It also **rebuilds a `.venv` that has stopped working**, which on a Mac is the
normal end of one: `brew upgrade python` moves the base interpreter out from
under it and leaves `.venv/bin/python` as a dangling symlink.

> **Gotcha:** the interpreter has to be **Python 3.11–3.13**, and `python3` on
> a current Mac is not in that window — Homebrew is on 3.14, and `numpy==2.2.6`
> ships no cp314 wheel. A plain `pip install -r requirements.txt` there either
> fails the version solve or starts building numpy and scipy from source. The
> script searches `python3.13` → `3.12` → `3.11`, on `PATH` and in the
> Homebrew, python.org and pyenv install roots, and if it finds none it prints
> `brew install python@3.13` rather than guessing. Widen `PY_MIN_MINOR` /
> `PY_MAX_MINOR` in the script when the pins in `requirements.txt` move.

> **Gotcha:** an activated `$VIRTUAL_ENV` is used as-is and never modified —
> `deactivate` first if you want the script to manage `./.venv` for you.

**There is no EURECA vendor library for macOS**, so unlike Windows the
detector is *only* ever reachable over the bench cable — `--net`, which is
already the default here. No cable, no spectrum. One command sets it up and
one checks it:

```sh
./setup_macos_net.sh --apply     # asks for sudo
./setup_macos_net.sh             # check, changes nothing
./setup_macos_net.sh --list      # every service, its device, link state, address
```

`--apply` picks the adapter itself when the answer is unambiguous: the service
already holding the bench address, else the only wired one, else the only wired
one with a **live link**. A dock or a pair of USB adapters shows two or three
identical-looking wired services and only the one with the cable in it — and a
powered Pi on the far end — reads `status: active`. When that is still
ambiguous it lists the candidates and stops rather than guessing; name one with
`--service "AX88179B"`.

`--apply` sets `192.168.100.1/24` on that service **with no router**, which is
the design and not an omission: with no gateway here the Mac keeps its default
route over Wi-Fi, so internet, ssh and brew all keep working with the cable
attached. Putting `192.168.100.10` in the Router field is the classic mistake —
it installs a default route to a Pi that forwards nothing.

With no arguments the script only *reports*: service and BSD device, address,
whether a router crept in, link state, ping, TCP 4001/4010 to the Pi, the
application firewall, and what is bound to UDP 4000. `--revert` puts the
service back on DHCP.

> **Gotcha:** two Macs cannot both be `192.168.100.1` on the same cable, and
> the Pi has one `eth0`. Move the cable, or give the second Mac
> `--ip 192.168.100.2`.

The launcher itself pings the Pi before it starts (unless you passed
`--flight`, `--no-link`, `--mock` or your own `--net`) and points at this
script if there is no reply — otherwise the window opens and sits in a
reconnect loop with the reason buried in a status label.

### Checks and packaging

`requirements.txt` is what the operator interface needs to draw a spectrum,
and nothing else. The documented pre-commit checks and `build_exe.py` need a
little more, kept separate so a bench machine is not carrying a test runner:

```sh
.venv/bin/python -m pip install -r requirements-dev.txt   # pytest, pyserial, pyinstaller
```

`verify.py` and `verify_qt.py` need nothing beyond `requirements.txt`.

### Windows, from a fresh machine

The Duo's vendor library is a **Windows** DLL and it is already in the repo
(`vendor/libe9u_LSMD_x64.dll`, with its mingw runtime DLLs beside it), so
Windows is the one platform that runs the detector locally with nothing to
build. Three steps:

```bat
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
run_clouds_spectral.bat
```

`run_clouds_spectral.bat` takes the first interpreter it finds of
`%CLOUDS_PYTHON%` → `.venv\Scripts\python.exe` → `%VIRTUAL_ENV%` → `py -3` →
`python`, checks that it can import PyQt5 and matplotlib before it starts
anything, and sets `PYTHONPATH` to the repo root + `gse` + `flight\pi`. All
three entries are needed: `clouds_gse` and `clouds_fsw` are not on the root,
and without them the app dies on `No module named 'clouds_gse'` the moment it
opens the downlink.

> **Gotcha:** the script also does `chcp 65001` and sets `PYTHONIOENCODING`.
> The console is cp1252 by default, the UI prints `µ` and `Ω`, and
> **PyQt5 aborts the process** on an unhandled exception in a slot — so a
> `UnicodeEncodeError` inside a timer tick closes the window with no message.

> **Gotcha:** PyQt5 has no wheel for the newest CPython. If pip starts
> *building* it, you are on a too-new interpreter — use 3.13 in the repo venv.

**Ethernet to the flight Pi** (`--net`, and the flight downlink) is one
elevated command, then a re-check that needs no privileges:

```powershell
powershell -ExecutionPolicy Bypass -File setup_windows_net.ps1 -Apply -InterfaceAlias Ethernet
powershell -ExecutionPolicy Bypass -File setup_windows_net.ps1
```

`-Apply` sets `192.168.100.1/24` on that adapter (no gateway — see [Bench link to the flight
Pi](#bench-link-to-the-flight-pi)) and adds an inbound **UDP 4000** firewall rule.
With no switch it only *checks*, and prints why each part is down: adapter
state, the address, the network profile, ping and TCP 4001/4010 to the Pi, the
firewall rule, and what is bound to UDP 4000. `-Revert` puts the adapter back
on DHCP and removes the rule. Run it without `-InterfaceAlias` first and it
lists the candidate adapters rather than guessing — picking the wrong one
takes the machine off its own network.

Then: `run_clouds_spectral_pi.bat` for the live panel with the detector on the
Pi, or `run_clouds_spectral.bat --flight` for the downlink-only ground station.

## Documentation

| Doc                                           | Covers                                                                                             |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| [`docs/DRIVER.md`](docs/DRIVER.md)           | Driver architecture, all three vendor libraries, detector facts, USB-glitch mechanism & mitigation |
| [`docs/CALIBRATION.md`](docs/CALIBRATION.md) | Pixel → wavelength fit, data scaling, validation                                                  |
| [`docs/BENCH.md`](docs/BENCH.md)             | Home-Assistant-driven light/shutter QC rig + findings                                              |
| [`docs/UI_STYLE.md`](docs/UI_STYLE.md)       | CLOUDS design language, shared widgets/patterns                                                    |
| [`docs/DEVLOG.md`](docs/DEVLOG.md)           | Why each feature is built as it is, with the mock/live evidence                                    |

## Repository layout

| Path                                            | Role                                                                                    |
| ----------------------------------------------- | --------------------------------------------------------------------------------------- |
| `clouds_ui/`                                  | **the** operator interface: one window, instrument controls + flight downlink/commanding |
| `spectro/driver.py`                           | `SpectrometerDriver` interface + `open_driver(mock=, kind=)` factory                |
| `spectro/eureca_driver.py`                    | ctypes wrapper over the Duo vendor library — Windows DLL or Linux`.so`               |
| `spectro/mock_driver.py`                      | synthetic Duo frames for hardware-free testing                                          |
| `spectro/calibration.py`                      | `calibration.json` → pixel→nm, channel split, dark subtract                         |
| `spectro/processing.py`                       | averaging, ratio / transmission / absorbance, saturation flags                          |
| `spectro/export.py`                           | CSV session log + branded PDF report                                                    |
| `calibration.json`                            | factory INSION pixel→wavelength polynomials (Duo, versioned)                          |
| `vendor/`                                     | EURECA Duo Windows DLL (`libe9u_LSMD_x64.dll`) + runtime deps + licence               |
| `drivers/e9u_LSMD_LIB_Linux/`                 | EURECA Duo**Linux** vendor source + build/udev installer (feature P-01)           |
| `drivers/e9u_LSMD_EDU_LIB/`                   | EURECA EDU vendor SDK - **unused**, kept for reference (the EDU board was dropped)    |
| `verify.py` / `verify_qt.py`                | headless driver/calibration checks / offscreen UI exercise — run before committing     |
| `run_clouds_spectral.bat`                     | branded Windows launcher: interpreter discovery +`PYTHONPATH`, args passed through |
| `run_clouds_spectral_pi.bat`                  | the same, pointed at the Pi's frame stream (`--net`)                                 |
| `setup_windows_net.ps1`                       | Windows bench Ethernet: check / apply / revert the static link + UDP 4000 rule        |
| `run_clouds_ui.sh`                            | macOS/Linux launcher: builds`.venv` if missing, `PYTHONPATH`, args passed through |
| `setup_macos_net.sh`                          | macOS bench Ethernet: check / apply / revert the static link                          |
| `requirements-dev.txt`                        | pytest + pyserial + pyinstaller — the checks and the standalone build                 |
| `assets/`                                     | logo, icon, Futura-Bold.ttf (shared with the engine)                                    |

This is **ground / bench** software — the balloon spectrometer itself is run by
the **Raspberry Pi** flight software below, which now shares the *same* real
driver (`spectro/eureca_driver.py` loads the Linux `.so` on the Pi). A strict
**driver / UI split** keeps `verify.py` runnable without hardware and lets the
**Ground Support Equipment** (GSE) reuse the `spectro/` modules (calibration,
processing, export) with a downlink source in place of the USB driver.

## Flight & ground segment

The flight and ground-station software (built to
[docs/SOFTWARE_SPEC.md](docs/SOFTWARE_SPEC.md), status in
[docs/SOFTWARE_FEATURES.md](docs/SOFTWARE_FEATURES.md)) lives alongside:

| Path             | Role                                                                                                                                                                             |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `clouds_link/` | shared packet protocol (CRC-16, COBS, frames, HK, commands) — one schema for MCU, Pi, GSE                                                                                       |
| `flight/mcu/`  | **RP2350 sequencer firmware** (C, Pico SDK): autonomous double release, persist-before-fire, watchdog — native tests via `pio test -e native` or `test/run_native.sh` |
| `flight/pi/`   | **Raspberry Pi 5 flight app** (Python, systemd): 1 Hz spectra, CRC'd storage, UDP downlink, TCP commands, UART to MCU                                                      |
| `gse/`         | **ground station** (Python): telemetry monitor + PyQt5 dashboard, arm/execute commanding, ground interlock, session export                                                 |
| `tests/`       | pytest suite for all Python parts incl. the fake-MCU ↔ Pi ↔ GSE end-to-end chain                                                                                               |

Run everything hardware-free: `python -m pytest tests/` (Python) and
`flight/mcu/test/run_native.sh` (firmware core).

## Bench link to the flight Pi

The Pi 5 flight computer (`flight/pi/`) is reachable over a **direct Ethernet
cable** from the bench PC — no switch, no DHCP server, no WiFi in the path. The
addressing deliberately mirrors **E-Link (Table 6-3)** so that `FswConfig` and
the GSE talk over the cable on their *defaults*, with no host flags:

| End                       | Address               | Matches                                                        |
| ------------------------- | --------------------- | -------------------------------------------------------------- |
| Bench PC (ground station) | `192.168.100.1/24`  | `FswConfig.ground_host` (`flight/pi/clouds_fsw/config.py`) |
| Pi (experiment),`eth0`  | `192.168.100.10/24` | `--experiment` default (`gse/clouds_gse/main.py`)          |

| Port     | Direction | Carries                              |
| -------- | --------- | ------------------------------------ |
| UDP 4000 | Pi → PC  | telemetry downlink (`ground_port`) |
| TCP 4001 | PC → Pi  | commands (`cmd_port`)              |

```sh
ssh clouds@192.168.100.10          # shell on the flight Pi
python -m clouds_ui --flight       # ground station — defaults already match
```

### One GUI, two sources: instrument vs flight downlink

There used to be two GUIs here, and picking the wrong one looked like a broken
system. There is now one — `python -m clouds_ui` — and it makes you choose the
*source* instead, which is the thing that actually differs:

| Want to… | Source | Rate |
|---|---|---|
| **look at the detector** — trace responds to light immediately | Detector (`--net <pi>` for the Pi's) | continuous, full resolution |
| watch the **flight downlink** — HK, events, commanding, budget | Downlink (`--flight` starts here) | quick-look 1 Hz, binned to 29+31 pts |

The choice is explicit and the app never changes it for you: the plot carries a
banner naming the source and its rate, and the stats card reads `LIVE` or
`QUICK-LOOK`. The downlink quick-look is deliberately *not* an instrument view —
each one is mean-binned to 29+31 points per channel (`quicklook_bin`) rather
than the 2048-px trace, and with no RP2350 attached the HK grid stays empty.
Working as specified — just not what you want when checking the spectrometer.

**Downlink cadence.** `quicklook_interval_s` is **1.0 s**, the maximum the
2 kbit/s continuous E-Link limit allows, and it is the *only* knob that spends
budget — acquisition (`sample_interval_s`) and `exposure_us` are independent of
it, so transmitting more often changes nothing on the instrument. Measured frame
sizes: quick-look cycle 164 B (80 + 84, both channels), PISTATUS 28 B, HK 66 B.

| | rate |
|---|---|
| quick-look @ 1 Hz | 1.312 kbit/s |
| HK @ 1 Hz (`HK_PERIOD_MS`, relayed from the MCU) | 0.528 kbit/s |
| PISTATUS @ 0.1 Hz | 0.022 kbit/s |
| **total, full flight mix** | **1.894 kbit/s** of 2.0 |
| total with no RP2350 attached (bench today) | 1.334 kbit/s |

Halving the interval would reach 3.1 kbit/s and bust the limit;
`tests/test_fsw_telemetry.py::TestDownlinkBudget` asserts both directions from
real encoded frame sizes, so a payload or cadence change cannot quietly exceed
it. The headroom assumes HK stays at its implemented 54 B payload (44 B before
the INA226 rail voltages, 50 B before the reserved 24 V rail slot) — the spec
allows ~180 B, which would force the interval back to ~2.4 s.

### Both at once, one detector

The vendor library owns the USB device **exclusively**, so the flight app and a
standalone frame server cannot both hold it. `--bench-stream` resolves that by
serving the frames the FSW has *already acquired*:

```sh
# Pi — flight chain and live view from one process
python3 -m clouds_fsw.main --no-uart --bench-stream

# PC — one window; switch Spectrum source between Detector and Downlink
python -m clouds_ui --net 192.168.100.10 --experiment 192.168.100.10
```

The live view updates at the FSW's acquisition cadence, which is **1 Hz on the
bench exactly as in flight** (`sample_interval_s`). The bench runs the same
config as flight — no faster sampling, no bench-only tuning — so what you watch
here is the real flight cadence, and there is one less difference between the
tested and flown configuration.

One setting is unavoidably shared: the panel sets the exposure on the single
physical detector, so it does change the *flight* exposure while connected. Every
change is logged to the comms log, and the FSW **restores the configured
`exposure_us` when the last bench client disconnects**, so a bench session cannot
silently leave the flight app on different settings. The flag is off by default.

For maximum frame rate with no flight chain running, the exclusive server still
exists and reaches **26 fps** at 20 ms exposure (~50 KB/s), versus ~12 fps with
the detector local — the cable is not the bottleneck:

```sh
python3 -m spectro.net_server        # port 4010, full 2048-px frames, exclusive
```

`spectro/net_driver.py` implements `SpectrometerDriver`, so the UI cannot tell
the difference; the `"net"` kind is selectable anywhere `kind=` is (or via
`CLOUDS_SPECTRO_HOST`). Bench only — it ignores the downlink budget and assumes
a direct link.

Neither end has a gateway on this link — it is host-to-host only, so both
machines keep their normal default route (the Pi over `wlan0`) and `apt`/`pip`
still work with the cable attached. Round-trip is **<1 ms**, versus 12–220 ms
over WiFi.

**Pi side** is persistent, in netplan (NetworkManager renderer) —
`/etc/netplan/90-NM-75a1216a-9d1a-30cd-8aca-ace5526ec021.yaml`, `dhcp4: false`,
`addresses: [192.168.100.10/24]`, no `gateway4`. The `wlan0` profile is a
separate file, so re-applying this one never drops a WiFi SSH session.

**PC side** is a static address on the Ethernet adapter (elevated PowerShell;
`-InterfaceIndex` from `Get-NetAdapter`):

```powershell
New-NetIPAddress -InterfaceIndex 3 -IPAddress 192.168.100.1 -PrefixLength 24
```

> **Gotcha:** `pi.local` still resolves to the **WiFi** address (mDNS answers
> from `wlan0`), so `ssh clouds@pi.local` does *not* use the cable. Address
> `192.168.100.10` explicitly, and check `$SSH_CONNECTION` to confirm which
> path you got.
>
> **Gotcha:** Windows classifies this gateway-less link as a **Public**
> network, where inbound is blocked by default. On this bench it works because
> `python.exe` already has enabled inbound Allow rules (the usual "allow this
> app" prompt) — check with
> `Get-NetFirewallApplicationFilter | ? Program -like '*python*'`. On a machine
> without them the GSE's UDP 4000 listener never sees the downlink; allow the
> port explicitly (elevated):
> `New-NetFirewallRule -DisplayName "CLOUDS downlink" -Direction Inbound -Protocol UDP -LocalPort 4000 -Action Allow`
>
> **Gotcha:** setting the static address **disables DHCP** on that adapter. To
> use the port on a normal network again: `Set-NetIPInterface -InterfaceIndex 3 -Dhcp Enabled` plus `Remove-NetIPAddress -InterfaceIndex 3 -IPAddress 192.168.100.1`.
>
> **Gotcha:** if `netplan apply` leaves `eth0` on a *volatile* NM profile
> (`nmcli -f NAME,DEVICE con show --active` shows a bare `eth0` instead of
> `netplan-eth0`, and the address is stale), NM has adopted the interface as
> externally managed — that state lives in `/run` and dies at reboot. Force the
> real profile on: `sudo nmcli con up netplan-eth0`.

## Hardware

EURECA e9u-SPMD-350850-10-Duo, S/N 20260312-004. USB → FTDI FT2232H
(`VID_0403 / PID_6010`) → FTDI VCP serial port. The vendor library auto-detects
the camera (`e9u_LSMD_search_for_camera`) — no COM number or tty is hardcoded;
it walks `COM99…COM0` on Windows and `/dev/ttyUSB99…0` on Linux.

> **Gotcha:** a *charge-only* USB cable enumerates as `Unknown USB Device (Port Reset Failed)` / Code 43 and the camera is invisible. Use a real
> **data** cable. The FTDI VCP driver ships in Windows' DriverStore and
> auto-installs on enumeration — it is never the blocker.
>
> **Linux gotcha:** the vendor udev rules are not optional — they grant access
> to the tty (`MODE="0666"`) and unbind `ftdi_sio` from the FT2232H's unused
> first interface. `drivers/e9u_LSMD_LIB_Linux/install.sh` installs them.

## Calibration

Pixel→wavelength is a 2nd-order fit per channel (`nm = a·x² + b·x + c`),
shipped in `calibration.json` from the INSION factory data sheet. Both
channels live on one 2048-px detector (Ch1 low pixels, Ch2 high pixels; the
gap is dark) and share a single exposure. Full polynomial coefficients, data
scaling, and validation are in [`docs/CALIBRATION.md`](docs/CALIBRATION.md) —
the single source of truth, not duplicated here.

## Verification

* `python verify.py` — driver (mock) + calibration self-checks, no hardware
* `$env:PYTHONIOENCODING='utf-8'; python -u verify_qt.py` — headless offscreen
  UI exercise (must end `VERIFY OK`; writes `output/qt_panel.png`)

Run both after any change to the driver, calibration, or panel.
