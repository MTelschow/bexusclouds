# One GUI, two data sources — read before "opening the GUI"

Moved out of `CLAUDE.md` 2026-09-18. Also holds the downlink budget arithmetic
that fixes the quick-look cadence and the HK size ceiling.

There is **one** operator interface, `python -m clouds_ui`. It used to be two
(`clouds_spectral.py` and `clouds_gse.main --gui`) and they were split for a
real reason, which has not gone away - it is now handled inside the one window
instead of by making the operator run the right application:

| Source | What it is | Rate |
|---|---|---|
| **Detector** | `spectro.driver` direct - every pixel in the channel window. The only path that can *change* the hardware (exposure). **Bench only.** | continuous |
| **Downlink** | the 2 kbit/s telemetry - HK, events, commanding, and a quick-look mean-binned to 29+31 points per channel. The only path that exists in flight. | 1 Hz |

`self.source` picks which one the spectrum draws, it is **the operator's
explicit choice, and nothing in the app changes it**, because the failure this
guards against is reading a binned 1 Hz quick-look as a live instrument view.
The plot carries a banner naming the source and its rate, and the stats card
says `LIVE` or `QUICK-LOOK`. Reaching the detector from the ground at all
depends on the Pi's `--bench-stream`, which is **off in flight**.

`quicklook_interval_s` is **1.0 s - the 2 kbit/s budget maximum** (1.894
kbit/s with HK), and it is the only knob that spends downlink budget:
`sample_interval_s` and `exposure_us` are independent of it. Each interval
sends **two** packets, one per channel.

## Downlink budget

**That 1 Hz depends on HK staying lean, and it is no longer lean.** The budget
leaves ~83 B for a framed HK packet, i.e. an **HK payload ceiling of 67 B**.
`hk.SIZE` is **80 B**, framed 96 B, total **2.102 of 2.0 kbit/s** - so the
continuous budget is **over by ~5 %** and `TestDownlinkBudget` is red.

That is a decision, not an accident, and it happened in two steps on
2026-09-28: the chamber BNO055's 12 B went on by operator instruction to get
both IMUs on screen (76 B, 2.070 kbit/s), and the BMV080's 2 B followed
(78 B), then the dispersion motor encoder's 2 B speed (80 B, 2.102 kbit/s).
The budget was explicitly deferred each time. The spec originally
allowed ~180 B, at which size 1 Hz quick-look totals ~2.9 kbit/s.

**Settling it means one of three things**, and the test stays red until one is
chosen: bin the quick-look harder, slow its cadence below 1 Hz, or drop
fields. The last is the cheapest if the chamber IMU is not earning its 12 B -
it is six i16 where the BMV080 spends 2 B on the one number its whole vendor
library exists to produce. `tests/test_fsw_telemetry.py::TestDownlinkBudget`
is the arithmetic; it fails first, by design, and is doing exactly that.

