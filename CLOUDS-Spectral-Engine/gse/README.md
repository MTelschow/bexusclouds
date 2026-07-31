# CLOUDS GSE — ground station

Python ground station (SED 4.12; features G-01..G-08): live telemetry,
command uplink with **arm/execute + ground interlock**, session logging
with CSV/JSON export. The downlink-fed sibling of the bench app at the
repo root — same `clouds_link` protocol, same `spectro` calibration +
processing, with the UDP receiver in place of the USB driver.

## Run (from the repo root)

```sh
# console monitor + command REPL
python -m clouds_gse.main --experiment 192.168.100.10

# PyQt5 dashboard (HK grid, state banner, quick-look spectrum, commands)
python -m clouds_gse.main --experiment 192.168.100.10 --gui

# monitoring only (no command link)
python -m clouds_gse.main --listen-only
```

(`PYTHONPATH` must include the repo root and `gse/`; running from the
repo root with `python -m` does this via `gse/` on the path — or
`set PYTHONPATH=.;gse` on Windows, `export PYTHONPATH=.:gse` elsewhere.)

## Safety (S.10, S.8)

- The **ground interlock starts engaged**: RELEASE and START are refused
  locally and never leave the laptop until the operator enables flight
  mode (`--flight-mode`, the `flight-mode` REPL command, or the GUI
  toggle). Verified in `tests/test_gse.py`.
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
| `clouds_gse/app.py` | PyQt5 dashboard (CLOUDS design language) |

Session logs land in `./gse_sessions/` (`--log-dir` to change).

Tests: `python -m pytest tests/test_gse.py tests/test_e2e.py` — the
commander is tested against the real FSW-PI command server (interop), and
the e2e test drives this receiver from a live FSW-PI instance.

## Open points

- G-06 calibration interface (offset adjustment UI) — before T-01/T-03.
- G-08 post-recovery bulk download tool (SD merge is pre-flight tool R-03).
