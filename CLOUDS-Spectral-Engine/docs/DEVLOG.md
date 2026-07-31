# Development log

A narrative record of *why* each feature is built the way it is, and the evidence
that it works — written so a later paper / report / SED section can be assembled
without re-deriving anything. Newest entries first.

**Where the rest of the record lives**
- **Git history** — every change is a commit with a rationale-carrying message.
- **`docs/`** — `BENCH.md` (Home-Assistant light/shutter QC rig), `DRIVER.md`
  (vendor-library wrappers + USB-glitch story), `CALIBRATION.md` (pixel→nm),
  `UI_STYLE.md`.
- **`verify.py` / `verify_qt.py`** — the executable spec. Every feature below has
  matching checks there; both must end `VERIFY OK` (currently 100+ checks, plus a
  `--live` path that runs the same UI against the real EURECA Duo).
- Hardware facts (detector = Toshiba **TCD1304DG**, gain ≈1.36 e⁻/count from
  firmware `CG1.36`, sat ≈65520, the 5 m-USB transfer glitch) are established in
  `DRIVER.md` / `CALIBRATION.md` and not repeated here.

---

## 2026-07-31 — The valve drive could reset the MCU mid-release (M-06/S.9)

**Why.** Reading the MCU hardware layer against its own constants: the valves want
a 5 s drive (`VALVE_PULSE_MS 5000`, USS-MSV00025 datasheet) and the hardware
watchdog bites at 2 s (`WATCHDOG_TIMEOUT_MS 2000`, S.9). The drive was a blocking
`sleep_ms(VALVE_PULSE_MS)` inside `ops_fire_pinch` / `valve_pulse`, reached from
`seq_step` → `send_hk` in the 1 Hz loop — the only place that kicks the watchdog.

**What that means in flight.** Every actuation blocks past the watchdog: a pinch
fire for 5 s, `close_eq_valves` for 10 s (two lines, sequentially). So the RP2350
resets *during* the first release. And because persistence is still the RAM stub
(M-11), `.bss` is zeroed on that reset and `hw_restore_persist` returns false — the
resume path loses the fired bits and can fire again. The persist-before-fire
invariant (S.3) is exact and correct; the hardware layer was undoing it. Nothing
caught this because `src/hw/` is the one part the native suite cannot compile, and
the mock ops in `test_core` return instantly.

**Fix — schedule the drive instead of sleeping through it.** New portable module
`core/pulse.c`: `pulse_request(pin, interlock)` queues a timed drive,
`pulse_service(now_ms, …)` starts the due one and ends the expired one, and the
main loop calls it every 10 ms pass. Properties worth recording:

- **One drive at a time.** Requests queue and run in order, so peak actuator
  current stays at one solenoid — the same sequential behaviour the blocking
  version had, without owning the CPU.
- **The interlock survived.** The pair line is still forced low in the same call
  that energizes its partner (S.8), now asserted on the recorded edge order
  rather than trusted.
- **Requests coalesce per pin.** The 1 Hz seal retry re-commands lines that are
  still driving; with 6 slots for 6 drivable outputs the queue provably cannot
  overflow (`dropped` is asserted 0 across a full simulated flight).
- **The seal check had to learn to wait.** `close_eq_valves` used to return only
  after 10 s of real driving, so `seal_ok()` read the chamber at rest by accident.
  Non-blocking would have had it read the pressure *while the valves were still
  moving* — and burn all three retries in three seconds. `seq_ops_t` gained an
  optional `busy()`; `ST_SEAL` commands the close, then holds off judging until
  the lines stop. M-15 lands on a hook that is now correct by construction.

**Verified — no hardware.** 5 new native tests (22 → 27, all 27 pass, gcc 16.1
`-Wall -Wextra` clean): the pulse is held for the full `VALVE_PULSE_MS` and
released within one loop pass; the two EQ closes serialise with never more than
one output high; repeat requests coalesce; the seal is judged exactly once and
only after ≥ 2 × 5 s of drive; and the whole X-03 autonomous double release runs
a second time with real drive timing — one fire each, nothing energized once SAFE
is reached, no request dropped. The 22 pre-existing tests still pass unchanged,
which is what clears the `ST_SEAL` restructure.

The seal test was checked against a deliberately reverted `ST_SEAL` (judge in the
same step as the close): it fails there on `first_seal_ms >= 2 × VALVE_PULSE_MS`,
so it is a real guard rather than a description.

That run also exposed two flaws in `test/unity_min/unity.h` (the plain-`cc`
Unity shim, not real Unity): `RUN_TEST` printed `PASS` unconditionally after the
test function returned, so a *failing* test printed both `FAIL` and `PASS` — the
failure count was right but the per-test lines lied. Fixed by comparing the
failure counter across the call; `UNITY_BEGIN` lost its stray comma expression at
the same time, leaving the native build warning-free.

Because `src/hw/hw.c` cannot be compiled natively, the invariant is also guarded
at source level in `tests/test_fsw_mcu_actuators.py` (4 tests, pytest): the hw
layer contains no `sleep_ms`/`busy_wait_*`, both actuator ops go through
`pulse_request` rather than `gpio_put`, and the loop calls
`hw_actuators_service()` next to the watchdog kick. Confirmed non-vacuous — all
three checks fail against the pre-fix `hw.c` from git.

> Still open on this path: **M-06 actuation verify** (current sense / pressure
> response) and the power-budget question the change exposes — a pinch drive can
> now overlap the membrane PWM starting one tick later, where the blocking
> version serialised them by accident. The scheduler serialises valve drives
> against each other, not against the membrane.

---

## 2026-07-31 — Three instruments, one driver interface: EDU board + Linux port (P-01)

Two hardware strands landed together, because they turn out to be the same
question — *which vendor library, on which platform?* — and answering it once in
the factory kept three drivers from growing three sets of platform branches.

**The factory grew a `kind`.** `open_driver(mock=...)` became
`open_driver(mock=..., kind=...)`, where `kind` is `"std"` (the Duo) or `"edu"`,
resolved from the argument → `CLOUDS_SPECTRO_KIND` → `"std"` and *validated*
rather than silently falling through to the Duo — a typo in a flight config
should fail at load, not surface as a wrong-instrument connect at altitude
(`FswConfig.load` calls `resolve_kind` for exactly that reason). The UI exposes
it as `--edu`; the FSW as `spectro_kind`. Nothing else in the UI, the FSW, or the
GSE learned a second code path.

**EDU: a different device family, not a DLL swap.** The single-channel
e9u_LSMD-TCD1304-EDU board exports `e9u_LSMD_EDU_*` symbols with different
arities (`get_pixel_pointer` takes one arg, not two; exposure has no separate
frame time) and talks over an FTDI VCP UART instead of the Duo's async USB link.
So it got its own wrapper, not a parameter. Two consequences worth recording:

- It reads out **3648 px on one fibre**, so `calibration.json` — two windows on a
  2048-px detector — would slice a *phantom* reference channel out of an EDU
  frame and cheerfully compute transmission against noise. `--edu` therefore
  loads `calibration_edu.json` by default (an explicit `CLOUDS_CALIBRATION` or
  the Calibrate dialog still wins, and the dialog's *reset* now returns to the
  instrument's own factory file rather than always the Duo's). Its pixel
  geometry is a hardware fact — `e9u_LSMD_EDU_get_pixel_count` reports 3648 —
  but its **polynomial is a placeholder**, flagged as such in the file itself.
- The vendored EDU SDK ships a Windows backend and DLL but **no Linux source**,
  so the driver raises a `DriverError` naming the alternative instead of dying
  in `os.add_dll_directory` (Windows-only) with an `AttributeError`.

**Linux (P-01): one wrapper, not a second driver.** The vendor's
`e9u_lsmd_camera_library-2.4.02` source builds the *same* `e9u_LSMD_*` API into
`libe9u_LSMD.so` from the *same* `lib/src/*.c` as the Windows DLL —
`e9u_LSMD_Linux.c` / `e9u_LSMD_Windows.c` are the only backend difference. So
`eureca_driver.py` stayed one file and grew a platform-aware loader
(`WinDLL` + `add_dll_directory` vs `CDLL`, `CLOUDS_E9U_DLL_DIR` vs
`CLOUDS_E9U_LIB_DIR` → `vendor/` → `/usr/local/lib` → the dynamic loader). The
source is vendored as the unmodified tarball plus an `install.sh` that
configures `--disable-gui`: the Pi has no business building a GTK reference GUI,
and dropping it drops the whole GTK dependency chain from the flight image.

Three things the headers settled that guesswork had got wrong:

1. **`get_dark_value` and `get_frame_counter` were mis-bound.** The Windows
   wrapper declared both as one-argument calls; the headers say
   `(cam, channel, x, y)` and `(cam, channel)`. A short ctypes call doesn't
   fail — it passes whatever is in the argument registers as `channel`, indexes
   the library's per-channel arrays with it, and returns junk (or worse). Both
   are wrapped in `try/except → None`, so this had been failing *quietly*. Fixed
   from the vendored headers, which is the point of vendoring them.
2. **The identity string needs an explicit C-level flush on Linux.**
   `search_for_camera` reports the camera by `printf` and the driver reads it off
   a redirected fd 1. Redirected to a file, glibc block-buffers, so the text can
   still be sitting in the C buffer when we read it — `fflush(NULL)` on the
   process libc (shared with the `.so`) pushes it out. Best-effort by design:
   losing it costs the identity fields, never the connect result, which comes
   from the return code. The parse itself needed no change — the vendor prints
   `using device /dev/ttyUSB0:` where Windows prints `\\.\COM3:`, and the
   existing regex is agnostic.
3. **udev is load-bearing, and the shipped rules are incomplete.** The FT2232H
   has two interfaces; the rules grant tty access (`MODE="0666"`) *and* unbind
   `ftdi_sio` from interface 0 — but only for board types
   `e9u_LSMD-TCD1304-{ECO,STD,TRG,PRO}`, while the library's own board table
   (`lib/src/e9u_LSMD_interface.c`) also knows `-PCB`. An unlisted type still
   works, because `search_for_camera` walks `/dev/ttyUSB99…0` and handshakes each
   one, so this is a "probes a spare tty first" bug, not a blocker — but it is
   exactly the kind of thing that reads as a hardware fault at 2 a.m.

**Status honesty.** P-01 stays ◐, not ✔. Everything above is code and vendor
documentation; none of it has run against the camera on a Pi. The two things a
desk cannot settle are the ones listed in `flight/pi/README.md`: tty permissions
under the service user, and whether the 5 m-cable USB glitch reappears on the
flight harness.

---

## 2026-07-05 — Flight + ground segment: FSW-MCU, FSW-PI, GSE (SED 4.11 v1.2)

Implemented the three software items from `docs/SOFTWARE_SPEC.md` in one pass,
sharing a single wire protocol so nothing can drift apart:

- **`clouds_link/`** — the packet schema (feature X-01): 14-byte header +
  CRC-16/CCITT-FALSE, COBS on UART, self-delimiting on TCP/UDP. The C mirror
  (`flight/mcu/src/core/frame.c`) embeds the same check vectors
  (`"123456789"` → `0x29B1`, canonical COBS examples), and the HK layout test
  pins byte offsets on both sides — cross-language drift fails a test, not a flight.
- **`flight/mcu/`** — the RP2350 sequencer as a *portable C core* (no hardware
  includes) + thin Pico SDK layer. Design invariants are enforced in the core and
  proven natively: **persist-before-fire** (the mock logs interleaved persist/fire
  order), **no re-fire after reset** (resume from a mid-RELEASE snapshot goes to
  MEASURE), and **autonomy by default** — the X-03 harness flies a compressed
  BEXUS pressure profile through the full double release with *zero* ground
  commands (T-07 rehearsal). 22 tests, run via `pio test -e native`,
  `test/run_native.sh`, or (as here, no toolchain) `python -m ziglang cc`.
- **`flight/pi/`** — Python/systemd app. MCU frames are **relayed byte-identical**
  to the ground (MCU CRC + seq survive end-to-end); spectra go to CRC'd
  10-min-rotated binary files *before* any downlink copy; the TCP command server
  is the authoritative arm/execute enforcer (RELEASE without ARM never reaches
  the UART). One deliberate wrinkle: **PING is forwarded to the MCU**, so the
  MCU's link-loss latch keys off real end-to-end traffic — a dead Pi and a dead
  E-Link correctly look identical to the sequencer.
- **`gse/`** — receiver/commander/session-log cores (tested against the *real*
  FSW-PI command server for interop) + console REPL + PyQt5 dashboard reusing
  `spectro` calibration for the quick-look wavelength axis. Ground interlock
  (S.10) starts engaged; `release()` does the ARM handshake.
- **`tests/test_e2e.py`** (X-04 bench): fake MCU ↔ real FSW-PI ↔ real GSE over
  real transports — HK relay, quick-looks, PISTATUS, ARM+RELEASE traversal,
  timesync, then storage read-back with CRC verification. 82 Python tests total.

Found-by-test fixes worth remembering: COBS decode initially accepted zeros
*inside* group data (only the code byte was checked); `_RotatingFile` needed a
lock + idempotent `FlightApp.shutdown()` because the run-loop and an external
caller can both shut down concurrently (surfaced as a thread-exception warning
in the e2e test, not a failure — warnings are signal).

Hardware halves still open (marked `TODO` in `flight/mcu/src/hw/`): SD/FatFs
stack (persistence is a RAM stub until then — S.3 depends on replacing it),
BME280/Keller/IMU drivers, seal-divergence check, self-tests, and the Linux
port of the EURECA vendor DLL for the Pi (P-01). Status per feature:
`docs/SOFTWARE_FEATURES.md`.

---

## 2026-06-14 — Code review + QC pass (technical + visual)

**Why.** A full review round: adversarial multi-dimension code review (each finding
independently re-verified), the mock QC harnesses, and a visual inspection of the
rendered UI.

**Visual.** UI rendered offscreen in counts / transmission / absorbance / log /
tracking / single-channel states. Clean and consistent — CLOUDS branding, readable
stats overlay, well-organised control panel, correct axis labels, no clipping. Minor
notes only (stats caption reads "LIVE" even on a single shot; the mock's *deterministic*
comb makes shoulder spikes at high exposure that don't occur on the real, random-glitch
cable — and the robust peak marker correctly avoids them).

**Code review.** 38 candidate findings → **30 confirmed** real after independent
verification. One genuine **blocker**: single-channel **export + session logging
crashed** with `KeyError('reference')` — when single-channel support was added to the UI
(`_ref()`), `export.py` never got the same treatment. Fixed via
`Calibration.by_role_optional()`; CSV writes blank ref/T/A columns, the PDF skips the
reference plot, the logger writes blank ref fields; a `verify_qt` regression test now
covers it. Hardening also landed: `Engine.closeEvent` (tear down timer + driver on
window close), symmetric auto-exposure confirm band, **despike-each-frame-before-median**
in `average_frames` (so the live trace + servo are glitch-clean at any navg, not just the
odd-count auto-exposure probe), `common_grid` non-overlap guard, `saturation_count > 0`
validation, capture paths honouring the `clean` flag, and connect-failure cleanup.
Deferred (documented, low impact): boxcar edge bias on the peak *index* (M4),
deadband-edge persistence (M5), the `eps = 1.0` ratio floor that can mask weak-reference
absorption (M6), synchronous export on the GUI thread (L2). Verdict: **solid, ship-worthy
after the export fix** — nothing threatened nominal dual-channel acquisition. Mock QC:
`verify.py` 51 + `verify_qt.py` 61 green.

---

## 2026-06-14 — Noise measured; default averaging raised to 8 (cable-specific)

**Why.** "How well does the noise suppression work?" — measured directly on the real Duo
(fixed exposure, 120 raw frames, temporal noise in a signal-free region).

**Findings.** Two distinct noises:
- **USB glitch (dominant).** ~7%/frame of pixels pinned to ~51% FS. Single-frame despike
  barely helps (×1.3) — at that density glitches *cluster* into 3+ px runs interpolation
  can't fix. The frame **median** rejects them, but only with a quorum, and the threshold
  is sharp:

  | navg | flat-region noise | vs navg 1 |
  |---|---|---|
  | 1 | 7 960 ct | ×1 |
  | 4 | **2 860 ct** | ×2.8 |
  | 8 | **8.9 ct** | ×900 |
  | 16 | 5.6 ct | ×1400 |

  At navg ≤ 4 a pixel can be glitched in *half* the frames so the median averages it in;
  at **navg 8 the glitch floor collapses ~900×**. Peak SNR on the spectrum rises from ~9
  (navg 4) to ~4600 (navg 16) purely from this.
- **Read noise (once glitches are gone).** ~9 ct (12 e⁻) at navg 8, ~6 ct (8 e⁻) at navg
  16, scaling ~1/√N as expected — an excellent floor.

**Change.** `NAVG_DEFAULT` 4 → **8** (one named constant at the top of `clouds_spectral.py`).
This is **environment-specific**: it's the glitch-rejection quorum for the *current* ~5 m
bench cable. On a healthy short cable the glitch is gone and the normal default of 4 (or
less) is fine — **revert that one number**. Capture paths already scale up (dark =
`max(8, navg)`, reference = `max(16, navg)`). Exposure control is unaffected (the
auto-expose probe uses its own 7-frame median + `robust_peak`).

**Tooling.** The measurement is reproducible from `qc_live.py`'s building blocks; the
noise table above is the record.

---

## 2026-06-14 — Full smart-home live QC sweep + glitch-robust exposure control

**Why.** "Test every feature that controllable light can actually prove." A panel
designed an exhaustive, code-grounded test matrix (each feature → how to drive it
with the Hue lamp / shutter → a quantitative pass criterion → the failure it catches),
implemented as one hardware harness that walks the whole pipeline in blocks ordered to
minimise light transitions.

**Final result after the fixes below: 28 PASS, 0 FAIL, 3 NOTE** on the real Duo
(reproducible; the harness is committed as `qc_live.py`, see `BENCH.md`). The 3 NOTEs
are honestly out-of-scope for light alone: the two sample-in-beam tests
(transmission/absorbance need a fibre physically blocked) and the on-chip dark register
the DLL doesn't export (`dark_value()` → None, offset no-ops gracefully). The first run
flagged **three** glitch-related failures (D3, then B8 + F2 on the re-run) — and they
all share one root cause: **glitch artifacts fooling peak detection**.

- **D3 (auto-expose from underexposed) was a real, important bug** the light test caught
  that mock never could. From a 0.1 ms start at a bright lamp, auto-expose stopped at
  ~9% FS instead of climbing to ~70%. **Root cause (diagnosed directly):** at the 5 m
  cable's ~7.6% glitch density, an **even-count (4-frame) median averages a 2-of-4
  glitch into a ~17–33 k-count artifact** (`(real+glitch)/2`) that `_despike` can't
  fully clear when artifacts cluster, and `max()` latches onto it. At low exposure the
  real signal (2–7% FS) is far below the artifact (~39–53% FS), so a probe lands "in
  band" on a glitch and the hunt stops. Diagnostic, real vs control peak:

  | exp | control peak (old) | real signal |
  |---|---|---|
  | 0.1 ms | 39% FS | **2.4%** |
  | 6.4 ms | 53% FS (→ stops here) | **7.2%** |
  | 100 ms | 79% | 73% |

  **Fix:** a glitch-robust control peak — `P.robust_peak()` = despike **+ a 5-px boxcar**
  (real lines are ≥3.7 px FWHM and survive; a 1–3 px glitch artifact is diluted below
  them) — and the auto-expose probe now medians **7 frames (odd)** instead of 4 (a pixel
  must glitch in ≥4 of 7 to survive, vs the even-median averaging-in at 4). Both
  `_auto_expose` and the tracking servo's per-frame `_last_peak` use it. The diagnostic's
  "7-median + 5-px boxcar" column tracked the real signal perfectly (2.4 → 7.2 → 73% FS,
  monotonic). **Verified live after the fix:** auto-expose from 0.1 ms now lands 67–70% FS
  on every repeat (was stochastic).

- **B8 (smoothing) and F2 (colour) then failed on the re-run — same root, different
  place.** The *reported / displayed* peak (`_peak_nm` in `_process`, the marker in
  `_draw_peak`, the stats card) still used a plain `argmax`, so at dim exposure it
  latched onto a glitch and jumped around run-to-run (F2's warm peak was 667 nm one run,
  665 the next; B8's raw peak was a 725 nm glitch that savgol then "moved" to the real
  665). **Fix extended:** `P.robust_peak_index()` (despike + 5-px boxcar argmax) now backs
  every peak readout — `_peak_nm`, `_draw_peak`, and the stats meas/ref lines — so the
  marker and numbers track the real line, not a glitch.

- **F2 colour response, done honestly.** Auto-exposure normalises brightness away and the
  red caps clamp the peak *wavelength* into the red, so the conclusive test is **fixed
  exposure, intensity ratio**: at one integration time, warm 3000 K gives **1.54× the
  signal of cool 6500 K** (warm's red passes the caps; cool's blue is blocked) — exactly
  what physics predicts, and a clean proof the instrument registers colour. (The earlier
  "34 nm peak shift" was a glitch artifact, not real.)

**Verified — mock:** `verify.py` gains `robust_peak` / `robust_peak_index` unit tests
(dilutes a surviving glitch cluster vs plain `max`; preserves a real ≥5 px line; the
index marks the real line past a spike). All mock QC green.

**Lessons for the write-up:** (1) the even-vs-odd median count matters on a glitchy cable
— an even median *averages in* a minority glitch, an odd median rejects it; (2) **every**
peak operation (control, marker, reported nm, stats) must be glitch-robust, not just the
one that happened to fail first; (3) colour response through the red caps shows up as an
**intensity ratio at fixed exposure**, not a peak shift. None of this is visible in the
mock — it took driving the real, glitchy cable with controllable light to find it.

---

## 2026-06-14 — Continuous auto-exposure ("track" mode)

**Why.** The one-shot **Auto** button (below) sets the integration time once. For a
*changing* scene — pointing the fibre around the room, a source that brightens or
dims — the exposure then goes wrong until you press Auto again. We wanted a live
mode that keeps the exposure right as the light changes.

**What.** A `track exposure (continuous auto)` checkbox. While live it runs a
per-frame servo (`_track_exposure`) that nudges the integration time so the
brightest of the two fibre channels stays near 65 % of full scale. Enabling it
**snaps once** (reusing the Auto hunt) to get in range from a cold start, then
hands off to the smooth servo. Dragging the integration slider disables tracking
(manual override). Status overlay shows `TRACK`, and `(scene too dim @ 1000 ms)` /
`(scene too bright @ floor)` only at the true rails.

**Control law (and how it was chosen).** The design was pressure-tested by an
independent 3-lens review (stability / fast-transient / field-robustness) before
implementation. Key results:
- **Log-proportional, dead-beat.** `factor = target/frac` on a plant where signal
  is linear in integration time is the exact inverse-plant step: the latency-included
  error map collapses to zero in one step, loop gain exactly 1 → **provably
  non-oscillatory**. The slew clamp only ever *shrinks* steps, preserving that.
- **Symmetric *log* deadband `0.54 ≤ frac ≤ 0.78`** (≈ ±0.18 nepers around 0.65).
  The naive linear band `[0.45, 0.80]` is asymmetric in log space, so peak-max noise
  rectifies into a steady downward pull and visible hunting on a *static* scene; the
  symmetric band removes that, and the 0.78 ceiling stays out of the TCD1304 knee.
- **Saturation cut keyed off the saturated-pixel *fraction*, slew-exempt.** When
  clipping, `frac` is pinned and useless; the multi-pixel saturated fraction says how
  far over you are, so a scaled jump (0.06 / 0.20 / 0.50) escapes deep saturation in
  ~2 ticks instead of ~8 (the genuine worst case: parked at 1000 ms / ~1 fps, a 100×
  brightening = several seconds of white frames under a blind ÷2). Gating on
  `saturated_fraction > 0` also means a residual 1-px glitch can't fake a hard cut.
- **2-tick persistence on small (non-rail) corrections** — a single-tick noise spike
  (prob p) becomes p² ≈ 0; big moves / rails are exempt so room-sweeps stay snappy.

Decisions **rejected** (and why): auto-driving `navg` (couples a 2nd loop, breaks the
glitch-rejection guarantee mid-sweep); sub-clip pedestal subtraction (<2.5 % FS, sits
inside the deadband); an in-tick convergence loop (defeats the point of one smooth
nudge/frame — the snap-on-toggle covers cold start); "give up" back-off on a dim
scene (1000 ms *is* the right destination for a faint target — we only stop *claiming*
to track, via the rail hint).

**Verified — mock** (`verify_qt.py`, deterministic via a scriptable `_shape`):
dead-beat into band on a static scene with **0 exposure changes over 20 ticks**
(no hunting); recovery from 10× dimming; **escape from deep saturation in 2 ticks**;
1-px-glitch immunity (no cut when saturated-fraction = 0); rail-honesty + message
when too dim; slider-drag disables tracking.

**Verified — live (real EURECA Duo, hands-off while the light changed):**

| scene change | re-converged | integration | peak | saturated |
|---|---|---|---|---|
| cold start 1000 ms, lamp 100 % | 4 ticks | 98 ms | 68 % FS | 0 % |
| lamp → 50 % | 8 ticks | 261 ms | 57 % | 0 % |
| lamp → 20 % | 12 ticks | 1000 ms (rail) | 58 % | 0 % |
| lamp → 60 % | 6 ticks | 252 ms | 68 % | 0 % |
| lamp → 100 % | 5 ticks | 66 ms | 55 % | 0 % |
| lamp OFF → ambient | 15 ticks | 1000 ms | 52 % | 0 % |
| daylight, shutter 100 % | 4 ticks | 159 ms | 66 % | 0 % |
| daylight, shutter 60 % | 4 ticks | 159 ms | 56 % | 0 % |
| daylight, shutter 30 % | 9 ticks | 1000 ms (rail) | 56 % | 0 % |
| daylight, shutter 80 % | 7 ticks | 96 ms | 57 % | 0 % |

The servo followed every step, held 52–68 % FS, **never saturated**, moved the
integration time inversely with brightness, and rode the 1000 ms rail only when the
scene was genuinely too dim. (Light driven over Home Assistant per `BENCH.md`;
shutter restored to as-found, lamp off afterwards.)

---

## 2026-06-14 — Auto-exposure (one-shot) made glitch- and flicker-robust

**Why.** The first `Auto` implementation was inconsistent on live hardware: a stray
USB transfer glitch landing in the target band could stop the hunt early, and fixed
×-stepping ran out of iterations on dim sources.

**Symptom (live, before):** lamp 100 % landed **39 % FS from a 1 ms start but 77 %
from a 1000 ms start** — the answer depended on where it began — and daylight through
the open shutter collapsed to **6 % FS** (badly underexposed).

**Fix.** Rework `_auto_expose`: (1) measure the peak on a **glitch-despiked, 4-frame
median** so a spike can't terminate the search; (2) **proportional jump**
(`exp × target/frac`) so it converges in ~2 steps from any start; (3) a candidate in
the sweet spot is **confirmed by a second probe** (conservative min) before being
accepted, so a brief flicker on a fluctuating source (daylight) can't stop it early.

**Verified (live, after).** Reading the peak the way the hunt targets it (brighter of
the two fibres): lamp 100 % from a **1 ms start lands on 70.0 % FS**, from 1000 ms on
82 %; lamp 40 % on 51 % (≈5× the exposure, as expected); daylight at 100 % / 50 %
shutter both climb into the 51–55 % band — **nothing saturates** and the result no
longer depends on the starting exposure. The earlier 6 %-FS collapse is gone.

> Measurement note that bit us once: `_auto_expose` targets the **brighter of both
> channels**. The two fibres "just lay next to the lamp" and couple very differently,
> so a test that reads only the *measurement* channel's % FS understates and looks
> erratic; read max-over-channels to judge convergence.

Commit: *Auto-exposure: glitch-robust proportional hunt with confirm-probe*.

---

## Earlier milestones (see git history + docs for detail)

- **EURECA feature parity.** Matched the EURECA Easy* scripts and ~95 % of the GTK
  GUI: dual-trace counts/transmission/absorbance, nm/pixel axis, dark capture +
  subtract, on-chip dark-pixel & subtract-minimum offset modes, stored-reference
  flat-field, Savitzky-Golay/boxcar smoothing, mean/σ stats, log & √ y-scales,
  spectral-region zoom, live fps + hardware frame-counter drop detection, peak marker
  + cursor readout, CSV/PDF export + session logging.
- **Single-channel support.** The same app runs an EDU/STD 1-fibre unit via a
  reference-less calibration (`calibration_single.json`): ratio views fall back to
  counts, stats/cursor show `ref --`.
- **USB transfer-glitch handling.** Characterised the 5 m-cable glitch (random pixels
  pinned to a fixed code) and cleaned it with median-combine + 1/2-px spike despike,
  *proven not to touch real lines* (instrument-resolution 3.7-px line preserved 100 %).
  See `DRIVER.md`.
- **Radiometric light budget.** pW-class detection floor at the fibre; the LCU's
  2.5 mW is ~10⁸× over the floor → light is not the constraint, attenuation is.
  See `BENCH.md` / the power-estimate tooling.
- **Driver + identity + branding + mock.** ctypes wrapper over `libe9u_LSMD_x64.dll`
  (no COM hardcoding), printf-identity parse, firmware-safe (no flash/erase calls),
  synthetic Duo for hardware-free CI. See `DRIVER.md`.
