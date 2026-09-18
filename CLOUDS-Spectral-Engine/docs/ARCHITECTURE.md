# Architecture

Moved out of `CLAUDE.md` 2026-09-18.

- **Strict driver/UI split.** UI and FSW talk only to
  `spectro.driver.SpectrometerDriver` via `open_driver(mock=, kind=)`. Kinds:
  `std` (Duo), `net` (remote — `spectro/net_driver.py` over TCP to
  `spectro.net_server` or the FSW's `--bench-stream`). Construction must
  stay side-effect-free; reaching hardware is `connect()`'s job
  (`tests/test_driver_factory.py` enforces this). **`--edu` is gone**
  (removed 2026-09-11) and a stale `CLOUDS_SPECTRO_KIND=edu` now raises.
  **`--mock` is back** (2026-09-16), on purpose and labelled everywhere:
  outside it a detector spectrum is always real light off the Duo, and it
  refuses to run with `--net`. It is the whole chain, not just the driver -
  `clouds_ui/mock_stack.py` starts the real `FlightApp` (mock spectrometer)
  against `clouds_fsw/sim_mcu.py`, a simulated RP2350 that emits HK and
  answers commands with the sequencer's own verdicts, all on ephemeral
  loopback ports. Constraints that keep it from contaminating real work:
  window title, plot banner and device line all say MOCK; session logs are
  `session_mock_*` - the ground station's and, since 2026-09-18, the
  instrument's own `output/session_mock_*.csv`; the stored dark frame is
  never written or cleared
  (`persist_dark=False`, a separate switch from `mock=` so `verify_qt.py`
  can still exercise the store); its data directory is temporary.
- **`spectro/` is shared** by bench app, FSW and GSE — calibration, processing,
  export. The GSE swaps the USB driver for a downlink source.
- **`clouds_link/`** is one schema for MCU, Pi and GSE: CRC-16/CCITT-FALSE,
  COBS, 14-byte frame header, HK, commands.
- **The Pi never sequences the experiment** (S.7). Losing it degrades the
  mission; it cannot block the release. The MCU is autonomous; the Pi's command
  server is authoritative for arm/execute and the ground interlock — and both
  are re-checked on the MCU (`core/link.c`) and against MCU housekeeping
  (`FLIGHT_ONLY`), because each of those enforcers can be bypassed on its own.
- **Every command is confirmed end to end.** The MCU answers each `CMD` with an
  `ACK` carrying its own verdict; the Pi correlates it by sequence number and
  relays that to ground. A UART write is not evidence a command was executed,
  and a missing ACK is a rejection.

Env vars: `CLOUDS_SPECTRO_KIND`, `CLOUDS_SPECTRO_HOST`, `CLOUDS_CALIBRATION`,
`CLOUDS_DARK` (stored dark frame, see `docs/CALIBRATION.md`),
`CLOUDS_E9U_DLL_DIR` / `CLOUDS_E9U_LIB_DIR`, `CLOUDS_E9U_COUNT_SHIFT`.

