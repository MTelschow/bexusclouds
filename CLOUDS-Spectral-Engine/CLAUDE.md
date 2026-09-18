# CLOUDS Spectral Engine — working notes

BEXUS 38 dual-spectrometer software: a Qt **bench panel**, the **Raspberry Pi
flight app** (FSW-PI), the **RP2350 sequencer firmware**, and the **ground
station** (GSE), all sharing one protocol (`clouds_link/`) and one instrument
layer (`spectro/`).

`docs/` is the source of truth. Don't duplicate it here; update it when
behaviour changes.

| doc | what is in it |
|---|---|
| `docs/COMMANDS.md` | **`PYTHONPATH`, launchers, app flags, the four pre-commit checks, firmware build** |
| `docs/ARCHITECTURE.md` | driver/UI split, `--mock` stack, `clouds_link/`, command-ACK rule, env vars |
| `docs/GUI_SOURCES.md` | detector vs downlink source, quick-look cadence, **downlink budget + HK ceiling** |
| `docs/HARDWARE.md` | detector, **RP2350 carrier pinout (measured)**, HK wire format, open flight gaps |
| `docs/TRAPS.md` | failures that already cost time here — read before debugging hardware or UI |
| `docs/PI_SETUP.md` | bench network PC↔Pi, UART enable, `/opt/clouds` deployment |
| `docs/DRIVER.md` | vendor libraries, USB glitch |
| `docs/CALIBRATION.md` | pixel→nm, **data scaling** |
| `docs/SOFTWARE_SPEC.md`, `docs/SOFTWARE_FEATURES.md` | spec + feature status |
| `docs/DEVLOG.md` | why things are as they are |
| `docs/UI_STYLE.md`, `docs/BENCH.md` | UI conventions, **bench = flight settings**, lamp/QC bench tools |

## Critical rules

- **A failed sensor read must never report a low pressure** — it mimics launch
  detection and fires valves. Hold last good, flag `HKE_P_AMB_STALE`.
- **Every command is confirmed end to end.** A UART write is not evidence of
  execution; a missing ACK is a rejection.
- **The Pi never sequences the experiment** (S.7). The MCU is autonomous;
  interlocks are re-checked on both ends.
- **A pinch valve never fires unattended.** Automatic mode (10 min of ground
  silence → the motor/solenoid/wait cycle) drives only reversible actuators;
  `RELEASE` stays arm-gated and ground-only. `docs/SOFTWARE_SPEC.md` §5.
- **`board.h` is preliminary and five pins were wrong.** Measure before
  trusting it; `PIN_PINCH_*` / `PIN_EQ*` are deliberately still wrong and
  documented as such. `docs/HARDWARE.md`.
- **Never `printf` on the MCU's `uart0`** — `pico_enable_stdio_uart` stays 0,
  it is the HK downlink.
- **HK payload ceiling is 67 B**; `hk.SIZE` is 64 B — **3 B of margin**. One
  more `uint32_t` in `Housekeeping` busts the 2 kbit/s budget;
  `tests/test_fsw_telemetry.py::TestDownlinkBudget` fails first, by design.
- **Two spectrum sources, operator's explicit choice.** Detector (live, every
  pixel, bench only) vs downlink quick-look (1 Hz, mean-binned). Nothing in the
  app may switch `self.source` on its own. `docs/GUI_SOURCES.md`.
- **The vendor library owns the USB device exclusively** — use
  `clouds_fsw.main --bench-stream`, never a second `spectro.net_server`.

## Conventions

- The bench runs the same settings as flight — `docs/BENCH.md`.
- Calibration lives in `calibration.json`, never hardcoded in the UI.
- Storage first, then downlink (O.3) — see `FlightApp._on_spectrum`.
- Don't commit unless asked; the default branch is `main`.
- New hardware findings belong in `docs/HARDWARE.md`, with the measurement that
  showed it; new failure modes in `docs/TRAPS.md`.
