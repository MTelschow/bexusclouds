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
| `systemd/clouds-fsw.service` | unit file: `Type=notify`, `WatchdogSec=15`, restart always |

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

# on the Pi: deploy clouds_fsw/, clouds_link/, spectro/ to /opt/clouds,
# install systemd/clouds-fsw.service, config in /etc/clouds/fsw.json

# real spectrometer on the Pi: build + install the vendor library once
drivers/e9u_LSMD_LIB_Linux/install.sh          # + udev rules, see its README
```

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
