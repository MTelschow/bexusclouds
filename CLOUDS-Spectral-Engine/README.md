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
  hardcoded) on **Windows or Linux**, or a single-channel EURECA
  e9u_LSMD_EDU board (`--edu`, Windows only). See `docs/DRIVER.md`.
* Live dual-trace view - measurement (Ch1) and reference (Ch2) on a shared
  wavelength axis, with a wavelength colour strip (single-trace on the EDU board).
* Single shared integration time (1-1000 ms) + per-channel frame averaging.
* Auto-exposure: **Auto** (one-shot, set ~70% full scale) and **track** (continuous
  servo that holds the exposure as the scene brightness changes - point it around).
* Dark-frame capture and subtraction; live per-channel saturation/clipping flag.
* Factory INSION pixel -> wavelength calibration (Ch1/Ch2 polynomials).
* Views: Counts, Transmission (meas/ref), Absorbance (-log10); nm or pixel axis.
* Export: timestamped CSV + branded PDF report; optional session logging to CSV.
* Headless `verify.py` / `verify_qt.py` run with no hardware (mock driver).

## Quick start

* Desktop: double-click **CLOUDS Spectral Engine** (`run_clouds_spectral.bat`,
  which pins the correct Python interpreter).
* Terminal: `python clouds_spectral.py`
* Single-channel EDU board: `python clouds_spectral.py --edu`
* No hardware? `python clouds_spectral.py --mock` runs against a synthetic Duo.
* Fresh machine: Python 3.13 + `pip install -r requirements.txt`.
* On Linux (incl. the Pi) build the vendor library first:
  `drivers/e9u_LSMD_LIB_Linux/install.sh` — see that folder's README.

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
| `clouds_spectral.py`                          | Qt control panel + live dual-trace spectrum view                                        |
| `spectro/driver.py`                           | `SpectrometerDriver` interface + `open_driver(mock=, kind=)` factory                |
| `spectro/eureca_driver.py`                    | ctypes wrapper over the Duo vendor library — Windows DLL or Linux`.so`               |
| `spectro/eureca_edu_driver.py`                | ctypes wrapper over`libe9u_LSMD_EDU_x64.dll` (single-channel EDU board, Windows only) |
| `spectro/mock_driver.py`                      | synthetic Duo frames for hardware-free testing                                          |
| `spectro/calibration.py`                      | `calibration.json` → pixel→nm, channel split, dark subtract                         |
| `spectro/processing.py`                       | averaging, ratio / transmission / absorbance, saturation flags                          |
| `spectro/export.py`                           | CSV session log + branded PDF report                                                    |
| `calibration.json` / `calibration_edu.json` | factory INSION pixel→wavelength polynomials (Duo / EDU, versioned)                     |
| `vendor/`                                     | EURECA Duo Windows DLL (`libe9u_LSMD_x64.dll`) + runtime deps + licence               |
| `drivers/e9u_LSMD_LIB_Linux/`                 | EURECA Duo**Linux** vendor source + build/udev installer (feature P-01)           |
| `drivers/e9u_LSMD_EDU_LIB/`                   | EURECA EDU vendor SDK (headers, C source,`libe9u_LSMD_EDU_x64.dll`)                   |
| `verify.py` / `verify_qt.py`                | headless driver/calibration checks / offscreen UI exercise — run before committing     |
| `run_clouds_spectral.bat`                     | branded launcher;**hardcodes the interpreter path**                               |
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
python -m clouds_gse.main --gui    # ground station — defaults already match
```

### Which GUI: live instrument view vs flight downlink view

Two GUIs, and picking the wrong one looks like a broken system:

| Want to… | Use | Rate |
|---|---|---|
| **look at the detector** — trace responds to light immediately | `run_clouds_spectral_pi.bat` → `clouds_spectral.py --net <pi>` | continuous |
| watch the **flight downlink** — HK, events, commanding, budget | `python -m clouds_gse.main --gui` | quick-look 1 Hz, binned to 29+31 pts |

The GSE dashboard is deliberately *not* a live instrument view: each quick-look
is mean-binned to 29+31 points per channel (`quicklook_bin`) rather than the
2048-px trace, and with no RP2350 attached its HK grid stays empty. Working as
specified — just not what you want when checking the spectrometer.

**Downlink cadence.** `quicklook_interval_s` is **1.0 s**, the maximum the
2 kbit/s continuous E-Link limit allows, and it is the *only* knob that spends
budget — acquisition (`sample_interval_s`) and `exposure_us` are independent of
it, so transmitting more often changes nothing on the instrument. Measured frame
sizes: quick-look cycle 164 B (80 + 84, both channels), PISTATUS 28 B, HK 60 B.

| | rate |
|---|---|
| quick-look @ 1 Hz | 1.312 kbit/s |
| HK @ 1 Hz (`HK_PERIOD_MS`, relayed from the MCU) | 0.480 kbit/s |
| PISTATUS @ 0.1 Hz | 0.022 kbit/s |
| **total, full flight mix** | **1.814 kbit/s** of 2.0 |
| total with no RP2350 attached (bench today) | 1.334 kbit/s |

Halving the interval would reach 3.1 kbit/s and bust the limit;
`tests/test_fsw_telemetry.py::TestDownlinkBudget` asserts both directions from
real encoded frame sizes, so a payload or cadence change cannot quietly exceed
it. The headroom assumes HK stays at its implemented 44 B payload — the spec
allows ~180 B, which would force the interval back to ~2.4 s.

### Both at once, one detector

The vendor library owns the USB device **exclusively**, so the flight app and a
standalone frame server cannot both hold it. `--bench-stream` resolves that by
serving the frames the FSW has *already acquired*:

```sh
# Pi — flight chain and live view from one process
python3 -m clouds_fsw.main --no-uart --bench-stream

# PC — run both simultaneously
python -m clouds_gse.main --gui --experiment 192.168.100.10   # downlink view
run_clouds_spectral_pi.bat                                    # live view
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

`calibration_edu.json` is the single-channel counterpart for the 3648-px EDU
board (`--edu`); its pixel geometry is a hardware fact but its polynomial is a
**placeholder** — recalibrate it against your unit.

## Verification

* `python verify.py` — driver (mock) + calibration self-checks, no hardware
* `$env:PYTHONIOENCODING='utf-8'; python -u verify_qt.py` — headless offscreen
  UI exercise (must end `VERIFY OK`; writes `output/qt_panel.png`)

Run both after any change to the driver, calibration, or panel.
