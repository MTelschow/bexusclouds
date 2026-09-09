# CLOUDS GSE — ground station

Python ground station (SED 4.12; features G-01..G-08): live telemetry,
command uplink with **arm/execute + ground interlock**, session logging
with CSV/JSON export. The downlink-fed sibling of the bench app at the
repo root — same `clouds_link` protocol, same `spectro` calibration +
processing, with the UDP receiver in place of the USB driver.

> **This is not a live instrument view.** Its quick-look spectrum updates at
> **1 Hz** — `quicklook_interval_s`, the 2 kbit/s E-Link budget maximum
> (1.894 kbit/s with HK) — and each update is mean-binned to 29+31 points per
> channel (`quicklook_bin`, 8), not the 2048-px trace. The HK grid stays empty
> with no RP2350 attached. That is the flight downlink working as specified.
>
> To *look at the detector* — continuous trace, responds to light
> immediately — switch the operator interface's **Spectrum source** to
> Detector (`python -m clouds_ui --net <pi>`). Start the Pi with
> `clouds_fsw.main --no-uart --bench-stream` and one window can hold both the
> downlink and the live detector off the one detector.

## Run (from the repo root)

```sh
# console monitor + command REPL
python -m clouds_gse.main --experiment 192.168.100.10

# monitoring only (no command link)
python -m clouds_gse.main --listen-only
```

**The dashboard lives in `clouds_ui` now.** HK grid, state banner, quick-look
spectrum, commands and the actuator drives are the flight half of the one
operator interface — `python -m clouds_ui --flight` — which also carries the
instrument controls, so a spectrum on screen always says which source it came
from. This package is the protocol and the headless path: it is what
`clouds_ui` imports, and the REPL above is still the right tool with no
display.

(`PYTHONPATH` must include the repo root and `gse/`; running from the
repo root with `python -m` does this via `gse/` on the path — or
`set PYTHONPATH=.;gse` on Windows, `export PYTHONPATH=.:gse` elsewhere.)

## Safety (S.10, S.8)

- The **ground interlock starts engaged**: RELEASE and START are refused
  locally and never leave the laptop until the operator enables flight
  mode (`--flight-mode`, the `flight-mode` REPL command, or the Flight mode
  toggle in `clouds_ui`). Verified in `tests/test_gse.py`.
- `Commander.release(n)` performs the ARM → RELEASE handshake; the Pi's
  command server is the authoritative enforcer.
- The heartbeat PING (every 5 s) is what keeps the MCU's link-loss latch
  (O.2) released — stop the GSE and the experiment continues autonomously.

## Modules

| Path | Role |
|---|---|
| `clouds_gse/receiver.py` | UDP decode, latest-state cache, seq-gap stats (G-07) |
| `clouds_gse/commander.py` | TCP client: ACK-checked commands, interlock, heartbeat |
| `clouds_gse/session_log.py` | HK/events CSV + quick-look JSONL + summary export (G-05) |
| `clouds_gse/monitor.py` | headless console + command REPL |

Session logs land in `./gse_sessions/` (`--log-dir` to change).

Tests: `python -m pytest tests/test_gse.py tests/test_e2e.py` — the
commander is tested against the real FSW-PI command server (interop), and
the e2e test drives this receiver from a live FSW-PI instance.

## Open points

- G-06 calibration interface (offset adjustment UI) — before T-01/T-03.
- G-08 post-recovery bulk download tool (SD merge is pre-flight tool R-03).
