# CLOUDS FSW-PI — Raspberry Pi 5 flight application

Data & communications node (spec: [docs/SOFTWARE_SPEC.md](../../docs/SOFTWARE_SPEC.md)):
spectrometer acquisition at 1 Hz (P.3), CRC'd onboard storage (O.3, S.5),
UDP telemetry downlink within the 2 kbit/s budget (O.4), TCP command
uplink with arm/execute (S.8), UART link + time sync to the RP2350 (S.4).
**Never sequences the experiment** — losing the Pi degrades the mission,
it cannot block the release (S.7).

## Layout

| Path | Role |
|---|---|
| `clouds_fsw/main.py` | wiring + periodic loop (quicklook, pistatus, timesync, watchdog) |
| `clouds_fsw/spectro_source.py` | 1 Hz acquisition, saturation flags, reconnect-on-failure (P-10) |
| `clouds_fsw/storage.py` | CRC'd binary spectra records, 10-min rotation, comms log |
| `clouds_fsw/telemetry.py` | HK relay (byte-identical), quick-look binning, budget meter |
| `clouds_fsw/command_server.py` | TCP uplink: ACK, arm/execute enforcement (authoritative) |
| `clouds_fsw/uart_link.py` | COBS framing over pyserial / in-memory pipe (tests) |
| `clouds_fsw/watchdog.py` | systemd sd_notify (S.9) |
| `clouds_fsw/bench_stream.py` | **bench only** (`--bench-stream`, off in flight): serves already-acquired frames so the live panel runs alongside the downlink |
| `systemd/clouds-fsw.service` | unit file: `Type=notify`, `WatchdogSec=15`, restart always |
| `systemd/10-bench.conf` | drop-in adding `--no-uart`, for a bench Pi with no RP2350 wired |
| `config/fsw.example.json` | the deployed `/etc/clouds/fsw.json`, all defaults made explicit |

Depends on the repo-root packages `clouds_link/` (protocol) and
`spectro/` (driver interface + calibration + processing, hardware-proven
by the bench app).

## Run

```sh
# bench, no hardware (mock spectrometer + loopback UART):
cd flight/pi && PYTHONPATH=../..:. python -m clouds_fsw.main --mock

# bench with the REAL spectrometer but no RP2350 wired up: stub only the UART.
# (SerialTransport opens uart_port eagerly, so plain startup would fail.)
cd flight/pi && PYTHONPATH=../..:. python -m clouds_fsw.main --no-uart

# ...and serve the live bench panel from the SAME process and detector, so the
# GSE dashboard and clouds_spectral.py --net can run at once (bench only):
cd flight/pi && PYTHONPATH=../..:. python -m clouds_fsw.main --no-uart --bench-stream

# on the Pi: deploy clouds_fsw/, clouds_link/, spectro/ to /opt/clouds,
# install systemd/clouds-fsw.service, config in /etc/clouds/fsw.json

# real spectrometer on the Pi: build + install the vendor library once
drivers/e9u_LSMD_LIB_Linux/install.sh          # + udev rules, see its README
```

## Deploy as a service

```sh
# 1. code -> /opt/clouds (flattened: the three packages sit side by side)
# 2. config
sudo install -d /etc/clouds
sudo install -m 0644 config/fsw.example.json /etc/clouds/fsw.json
sudo install -d /data/clouds                      # data_dir; created lazily otherwise
# 3. unit
sudo install -m 0644 systemd/clouds-fsw.service /etc/systemd/system/
# 3b. BENCH ONLY - no RP2350 wired: without this the unit crash-loops on the
#     missing /dev/ttyAMA0, because SerialTransport opens the port eagerly.
sudo install -d /etc/systemd/system/clouds-fsw.service.d
sudo install -m 0644 systemd/10-bench.conf /etc/systemd/system/clouds-fsw.service.d/
# 4. enable
sudo systemctl daemon-reload && sudo systemctl enable --now clouds-fsw
```

Validate the config before enabling anything — `load()` rejects unknown keys,
and it is nicer to learn that from a shell than from a restart loop:

```sh
PYTHONPATH=/opt/clouds python3 -c \
  'from clouds_fsw.config import FswConfig; print(FswConfig.load("/etc/clouds/fsw.json"))'
```

Going to flight: delete the drop-in and `daemon-reload`. The Pi also needs a
real UART — `enable_uart=1` in `/boot/firmware/config.txt`, `console=serial0`
removed from `cmdline.txt` (the serial console owns it by default), and
`dtoverlay=disable-bt` to put `ttyAMA0` on GPIO14/15 rather than the mini-UART.

`WatchdogSec=15` covers a hung *process*. A hung *kernel* needs the hardware
watchdog as well: `RuntimeWatchdogSec=15` in `/etc/systemd/system.conf`. That
is system-wide, not part of this unit, and is not set by the steps above.
Note `systemctl show -p WatchdogUSec` reads `infinity` while the unit is
inactive and `15s` only once it is running — the stopped value is not a fault.

The unit sets no `User=`, so the service runs as **root**. The vendor udev
rules put `MODE="0666"` on the EURECA tty, so a non-root `User=` is plausible
but unproven (see Open points).

Only one process can hold the spectrometer. A bench `spectro.net_server` and
the service will fight over `/dev/ttyUSB*`; stop the former before starting
the latter, or the FSW sits in its `reconnect_s` loop logging
`Device or resource busy`.

`spectro_kind` in the config selects the hardware family — `"std"` (default,
the Duo; the only one with a Linux library) or `"edu"`. It is validated at
config load, not at the first connect attempt.

Tests live in the repo-root suite: `python -m pytest tests/` — unit tests
per module plus the end-to-end chain (`tests/test_e2e.py`, feature X-04):
fake MCU ↔ this app ↔ real GSE over real pipe/UDP/TCP transports.

## Open points

- **P-01 driver port**: the code half is done — `spectro/eureca_driver.py` now
  loads either the Windows DLL or the Linux `libe9u_LSMD.so`, no libftdi
  reimplementation needed. Still to prove on hardware: udev/tty permissions
  under the service user, and whether the USB glitch (`docs/DRIVER.md`) shows
  up on the flight cable. `--mock` exercises the identical interface meanwhile.
- **P-11 camera**: only if F.7 is confirmed (CSI + thumbnail downlink).
- RTC: fit the battery-backed RTC and sync NTP before roll-out (S.4).
