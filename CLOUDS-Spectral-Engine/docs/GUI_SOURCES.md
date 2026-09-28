# One GUI, two data sources — read before "opening the GUI"

Moved out of `CLAUDE.md` 2026-09-18. Also holds the E-Link budget: the limits,
what the flight mix costs against them, and what the Pi does when it is over.

There is **one** operator interface, `python -m clouds_ui`. It used to be two
(`clouds_spectral.py` and `clouds_gse.main --gui`) and they were split for a
real reason, which has not gone away - it is now handled inside the one window
instead of by making the operator run the right application:

| Source | What it is | Rate |
|---|---|---|
| **Detector** | `spectro.driver` direct - every pixel in the channel window. The only path that can *change* the hardware (exposure). **Bench only.** | continuous |
| **Downlink** | the E-Link telemetry (~3 kbit/s of a 100 kbit/s allowance) - HK, events, commanding, and a quick-look mean-binned to 29+31 points per channel. The only path that exists in flight. | 1 Hz |

`self.source` picks which one the spectrum draws, it is **the operator's
explicit choice, and nothing in the app changes it**, because the failure this
guards against is reading a binned 1 Hz quick-look as a live instrument view.
The plot carries a banner naming the source and its rate, and the stats card
says `LIVE` or `QUICK-LOOK`. Reaching the detector from the ground at all
depends on the Pi's `--bench-stream`, which is **off in flight**.

**Selecting Downlink stops Run, and Run is refused on the downlink source**
(2026-09-29). Both draw into the same `last_proc`; before this the detector's
60 ms live loop kept writing full-resolution, dark-subtracted frames over the
29+31-point quick-look and the plot flipped between the two grids. `_start()`
is the one choke point (reconnect resume, tracking, the exposure hunt and
`restart()` all go through it), `_finish_tick` / `_process` drop a detector
frame while the source is the downlink, and flat-field only applies on the
detector (its reference is a full-resolution capture). Selecting Detector
again draws the last live frame at once and resumes Run if it was live when
Downlink was selected; if Run was off, it stays off.

**The quick-look is despiked on the Pi, not dark-subtracted.** The USB
transfer pins ~9 % of pixels per frame to ~33514 ct (`calibration.json`
notes); an 8-px plain mean of a raw frame therefore carried a +4 k ct hit in
about half of its bins, moving every second. `QuicklookSender` now runs the
frame through `spectro.processing.average_frames(clean=True)` before
`bin_channel` - the same rejection the bench view uses. Storage keeps the raw
frame. **The stored dark comes off on the ground** (2026-09-29): the window
bins its 2048-px dark with the Pi's own edges (`spectro.processing.bin_mean`,
the one function both sides use) and subtracts it from the quick-look under
the same exposure guard as the detector path - the packet names the exposure
the frame was taken at (whole ms on the wire), and a dark taken at another
one is held back, with the Dark frame section saying "... on the Pi". One
capture therefore serves both views, **taken at the flight exposure**
(`exposure_us` in `/etc/clouds/fsw.json`, 100 ms; bench = flight settings).
The stats card shows `-dark` after the Pi exposure when it was taken off.
Saturation is still judged on the raw counts.

`quicklook_interval_s` is **1.0 s - a cadence choice, not a link limit**
(the whole flight mix is ~3.2 kbit/s of the 100 kbit/s the E-Link allows), and
it is the only knob that spends downlink: `sample_interval_s` and
`exposure_us` are independent of it. Each interval sends **two** packets, one
per channel.

## Downlink budget

**The limits are the E-Link's** (BEXUS user manual Table 6-3; operator
decision 2026-09-29, replacing the self-imposed "2 kbit/s continuous" figure
and the 67 B HK ceiling derived from it): **downlink 100 kbit/s on average
and 400 kbit/s at any time, uplink 1 kbit/s**. "Average" is a 60 s sliding
window, "at any time" a 1 s one, and the uplink is a 60 s average too (one
command transaction is already ~1040 bit, more than a 1 s window holds).
Everything is counted **on the wire**: +42 B per UDP datagram, +54 B per TCP
segment. The numbers live in one place, `clouds_link/linkrate.py`, and the
Pi, the ground station and the panel all use its `LinkMeter`, so the rate on
screen is the rate the Pi enforces.

What the flight mix costs, from real encoded frames (`hk.SIZE` 80 B):

| Packet | Frame | Wire | Cadence | Rate |
|---|---|---|---|---|
| HK | 96 B | 138 B | 1 Hz | 1.10 kbit/s |
| Quick-look, both channels (29 + 31 bins) | 80 + 84 B | 122 + 126 B | 1 Hz | 1.98 kbit/s |
| PISTATUS (26 B payload) | 42 B | 84 B | 0.1 Hz | 0.07 kbit/s |
| **Total** | | | | **~3.2 kbit/s of 100**; worst second ~4 kbit/s of 400 |

`tests/test_fsw_telemetry.py::TestDownlinkBudget` is that arithmetic, header
overhead included, and is green with a wide margin. HK has no size ceiling
any more: 80 B is 1.1 % of the average allowance.

**The Pi enforces the downlink limits** (`clouds_fsw.telemetry.Downlink`).
Every packet is metered before it is sent and one that would exceed either
window is **dropped, not queued** - the storage copy already has everything,
and a queue that fills at 400 kbit/s is a delay nobody asked for. Quick-look
is the bulk class and stops at 90 % of either limit; HK, events and Pi status
go up to the limit itself, so they are never the packets that go. A dropped
Pi-origin packet takes no sequence number (the ground's `lost` still means
"the link lost it"); a dropped relayed HK keeps the MCU's, so it shows as a
gap, and `down_dropped_priority` says why. Drops come down in PISTATUS
(`down_dropped`, `down_dropped_priority`, plus the Pi's own `down_avg_bit_s`
and `up_bit_s`) and as a `DOWNLINK_SHAPED` WARNING event at most once a
minute; the panel's link line shows `pi dropped N`. In flight the shaper is a
guard, not a governor - `downlink_avg_kbit_s` / `downlink_peak_kbit_s` in
`fsw.json` can be lowered on the bench to watch it act.

**The ground enforces the uplink limit** (`clouds_gse.commander.Commander`).
A command that would exceed 1 kbit/s over 60 s is refused at once with
`CommandError("uplink budget: ... retry in N s")` - never delayed, because the
panel sends from the GUI thread - and logged as a `RATE_LIMITED` row in the
session's command file. A window's worth of 5 s heartbeats (~1.6 kB) is
reserved ahead, so an operator's burst cannot starve the beat the MCU's
link-loss latch watches; that leaves ~45 operator commands a minute. The Pi
counts the uplink too, for PISTATUS, and refuses nothing.

The Ethernet indicator in the sidebar shows the same meters: **Down** as
`avg / peak` against 100 k / 400 k (every Pi -> ground byte, the command ACKs
included), **Up** against 1 kbit/s (every ground -> Pi byte), amber over
either. A 60 s average ramps for its first minute after start; that is what
it is.
