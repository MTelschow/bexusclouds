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

## 2026-09-17 (newest) - An Ethernet traffic indicator: is the cable carrying anything

**Asked for:** a traffic indicator in the GUI showing the Ethernet up- and
downlink.

**The gap it fills.** Everything on the panel until now reported *decoded*
telemetry: HK age, sequence gaps, command RTT. All three read the same on a
link that is delivering nothing and on a Pi that is simply quiet, and none of
them move at all when the bytes arriving are corrupt. The operator's question
on the bench is cruder than any of them - *is the cable carrying anything* -
and answering it meant a terminal and `tcpdump`.

**What it shows.** `clouds_ui/traffic.py`, three lanes in the sidebar header:

* **Down** - UDP telemetry into `Receiver` (HK, events, quick-look, Pi
  status), counted where the datagram lands rather than after decode. A link
  delivering nothing but CRC failures spent the same budget and must not read
  as idle. This is the lane with the 2 kbit/s allowance and it goes **amber**
  over it - the same limit `tests/test_fsw_telemetry.py` enforces on the Pi,
  in front of the operator instead of only in CI (a test asserts the two
  numbers are one number).
* **Up** - the TCP command socket: commands plus the PING heartbeat, which is
  all it carries when nobody is commanding. Its ACK bytes ride back on that
  same socket and are counted into this lane, *not* into Down - an ACK is not
  downlink telemetry and must not inflate the budget reading.
* **Bench** - the `--net` frame stream (TCP 4010) when the spectrum comes
  from a remote detector. ~50 kB/s, three orders of magnitude above the
  flight downlink; summed into Down it would make the budget lane
  meaningless, so it is its own row and stays grey for a USB detector, which
  is not Ethernet at all.

**Why a light and a number.** The light is the NIC LED: it says *a packet
arrived in this window*. HK is 1 Hz and the poll is 500 ms, so a healthy link
blinks - and a link that has been silent for 3 s goes **red**, which is the
state the age fields could never distinguish from "quiet". The number is the
load, smoothed with a 3 s time constant, because the instantaneous rate of a
1 Hz burst read against a 500 ms window alternates between zero and a spike.
A lane with no source at all (no downlink in this session, no command link,
no remote detector) is **grey with a dash**, never a red alarm: not having a
link is a normal shape of this application, not a fault.

**Where it sits.** In the sidebar header, above the collapsible sections
rather than in one. It is the one indicator whose job is to be visible when
nothing else is updating, and a fold that hides it turns "the link died" back
into "the numbers stopped, why". It polls itself on its own 500 ms timer
instead of riding the flight tick, because an instrument-only session over
`--net` has Ethernet traffic and no downlink at all - and the flight timer
does not run there. The far end is named next to it (`192.168.100.10:4001`,
or a loopback port under `--mock`), so the operator can see which link they
are looking at.

**The counters.** Plain ints on `Receiver`, `Commander` and `NetDriver`,
written by the thread that owns each socket and read from the GUI thread -
the receiver still never touches Qt. Totals are the session's: Restart
rebinds the lanes and zeroes them, and the Bench lane resets itself when the
window re-opens its driver, or a reconnect would read as a burst followed by
a stall. `net_protocol.send_request`/`send_response` now return the bytes
they put on the wire, which is where that lane's tx comes from.

**Checks.** `tests/test_traffic.py` drives the lane maths in fake time (rate
convergence, the blink, silence vs idleness, over-budget, no-source, and the
first poll not inventing a rate from a counter that was already high);
`tests/test_gse.py` asserts the wire counters themselves, including that an
undecodable datagram is still counted and that a command refused by the S.10
interlock costs no uplink bytes; `verify_qt.py` checks the rendered lanes
against the receiver's and commander's own numbers, the peer line, and that
Restart starts the totals over.

---

## 2026-09-17 - The membrane frequency goes to tenths of a hertz: PARAM_MEMBRANE_HZ becomes PARAM_MEMBRANE_MHZ

**Asked for:** membrane frequencies like 0.1 to 0.9 Hz.

**The constraint.** `SET_PARAM` carries an int32 and `PARAM_MEMBRANE_HZ`
was whole hertz, floor 1. No decimal can travel on that wire, and widening
the frame for one knob is not worth a wire-format change. So the **unit**
changed instead: key 9 is now **`PARAM_MEMBRANE_MHZ`, millihertz**, default
2000, range **100..400000** (0.1 Hz to 400 Hz). The name changed with the
unit on purpose - a reader who sees `MHZ` cannot mistake the number for
hertz, and the mirror test (`config.h` vs `commands.Param`) makes both ends
rename together. The key *number* did not change, so a stale sender's "2"
arrives as 2 mHz and is refused by the 100 mHz floor rather than driving a
500 s cycle.

**Firmware.** `sqwave_start()` takes millihertz: `period_ms = 1000000 /
mhz`, so 0.1 Hz is a 10 s cycle, 6 s high at 60 %, and 400 Hz still hits the
2 ms floor. `ops_membrane()` compares against `pwmdiv_min_hz() * 1000` to
pick the loop-toggled path, and hands the PWM slice whole hertz rounded from
mHz for the >= 9 Hz case, where 0.5 Hz of rounding is under 6 % and the
mechanism does not care. Native test
`test_membrane_frequency_is_millihertz_down_to_a_tenth` pins 0.1 / 0.5 /
400 Hz timing and the range check including the old-unit "2".

**Ground.** `Commander.membrane_hz(hz: float)` is the one place the
conversion lives (`round(hz * 1000)`, range-checked to 0.1..400). The panel's
frequency box is a `QDoubleSpinBox`, one decimal, step 0.1, 0.1..400 Hz,
default 2.0; `Drive` sends it through `membrane_hz()` before `MEMBRANE`. The
headless monitor gained `membrane_hz <hz>`; `set MEMBRANE_MHZ <n>` still
works raw. `sim_mcu` honours the key with the MCU's limits and cycles its
simulated switch at the set rate, so `--mock` at 0.2 Hz shows the light
alternating slowly, as the carrier would.

**Checks.** `run_native.sh` 61/61; `pytest` 302 passed; firmware
cross-compiles for the carrier, clean; `verify_qt.py` drives at 0.5 Hz and
requires `SET_PARAM MEMBRANE_MHZ 500` on the wire before `MEMBRANE 70`.
**On the carrier** (peer session reflashed the working-tree image at 21:57;
direct downlink receiver, commands over TCP 4001):

```
membrane_hz(0.2) OK, membrane(60) OK      16 HK:  pulled  -PP--PPP--PPP--P
                                                  cycling .C..CC..CCC..C.C
membrane_hz(2.0) OK, membrane(60) OK       6 HK:  pulled  PPPPPP   cycling .CCCCC
membrane(0) OK                             3 HK:  pulled  ---
membrane_hz(0.05)                          ValueError on the ground, never sent
```

At 0.2 Hz the plunger is lifted three packets and pressed two, one 5 s cycle
at 60 %, exactly the wave `sqwave_start(200, 60)` describes, and the switch
light on the panel would alternate at that pace. At 2 Hz the position sample
is the constant fixed-phase reading and `cycling` carries the motion, as
before. The MCU's floor was checked by the peer over the same link: `SET_PARAM
9 = 50` (0.05 Hz) answers `INVALID`.

---

## 2026-09-17 - The membrane switch gets a light on the panel

**Asked for:** an indicator in the GUI showing whether the GP30 button is
pressed or not.

**What.** A coloured dot and a line of text under the membrane `Drive` /
`Stop` buttons in the Actuators section (`FlightPanel._set_switch`):

```
●  switch lifted - solenoid actuated, cycling     green   (MEMBRANE_PULLED set)
●  switch pressed - plunger resting               navy    (bit clear, switch readable)
●  switch: no telemetry | stale telemetry | no reading (MCU build without GP30)   grey
```

**Why a light when the `Membrane` HK row already says `pulled`/`pushed`.**
That row is one word in a column of monospaced text, and it changes at the
same visual weight as `Uptime`. The operator exercising the solenoid on the
bench is looking at the mechanism, not the row; the light sits next to the
buttons that move it and changes colour. Same information, second place,
different reader.

**Rules kept from the rest of the panel.** Grey with a reason rather than a
default colour when there is no reading: no HK yet, HK older than
`STALE_HK_S`, or `HKE_NO_MEMBRANE_SENSE` from a pico2 build - the always-clear
bit of a build that cannot reach GP30 must not render as "pressed". Reset to
`no telemetry` on the window's Restart with the other readouts. `cycling` is
appended from the peer's `MEMBRANE_CYCLING` latch when it is set, because the
position alone is one fixed-phase sample of the 2 Hz cycle.

**Checks.** `verify_qt.py` sends the three cases and the restart and reads
the label text and the dot's colour back: lifted+cycling green, unsourced
grey with the build reason, pressed navy after restart, `no telemetry` on
reset. `VERIFY OK`.

---

## 2026-09-17 - The dispersion motor gets Start/Stop beside its pulse

**The request.** The motor was drivable from the panel only as the 5 s pulse a
release schedules. For bench work - finding the speed that disperses the
powder, reading the GP46 current sense against a turning motor - the operator
wants to start it, watch, adjust, and stop it, and still be able to rehearse
the exact flight drive. So: **Start**, **Stop** and **One pulse**.

**The wire.** No new command. `CMD_DISPERSE`'s key names the request:
`DISPERSE_STOP 0`, `DISPERSE_PULSE 1` (unchanged), `DISPERSE_RUN 2`
(`frame.h`, mirrored by `commands.DisperseKey`, pinned by
`test_disperse_keys_mirror_the_firmware`). Anything above 2 is `ACK_INVALID`,
so a speed sent as the key is still a bad command, not a drive. Speed stays
`PARAM_DISPERSE_DUTY`; a `SET_PARAM` of it while the motor runs now
re-latches at once (`set_motor(s, true)` in `seq_command`), otherwise the
panel would show a speed the motor is not turning at until the next Stop/Start.

**Why the run is not a long pulse.** The obvious implementation - a pulse with
no deadline in `core/pulse` - breaks two invariants. The queue drives one line
at a time, so a held motor in it would park a release's pinch valve behind an
unbounded drive until the operator pressed Stop; and `ops_busy()` would stay
true, stalling the SEAL step's `seal_ok` wait (S.1: no state waits on ground).
So the run is a **state beside the queue**, like the membrane: `hw.c`
`motor_held` + `ops_disperse_run(on)` drive GP17 directly (reverse line forced
low first, same interlock), `drive_pin()` ignores the pulse scheduler's
release edge on GP17 while held, `ops_disperse()` queues nothing while held
(the motor is already turning), and `hw_actuator_status()` sets `HKV_DISPERSE`
for the hold - which means the "one drive bit at a time" note in `frame.h` now
has an exception: a run overlapping a release shows `DISPERSE | PINCH_n`.

**Stop is always honoured and also cuts a pulse short.** New
`pulse_cancel(sched, pin, drive, ctx)`: ends the pin if it is the one driving
(one low edge, now) and drops it from the queue, other pins untouched
(`test_cancel_cuts_one_line_short_and_leaves_the_rest`). Without it a Stop
during a 5 s pulse is a button that does nothing for up to 5 s. Stop is the one
drive command accepted in TERMINATION and SAFE, because it can only
de-energize; Run and Pulse are refused there like before, and TERMINATION now
calls `set_motor(s, false)` next to `set_membrane(s, 0)`, so an abort takes a
held motor down (`test_termination_stops_a_running_motor`). A Pulse while a
run is on answers `ACK_REJECTED` - the bounded drive it asks for cannot happen,
and ground should hear that rather than an OK for nothing.

**What is not there.** Nothing on the MCU times a run out: a run lasts until
Stop, an abort, or a reset - the same as the membrane drive today, and a
deliberate non-decision (a bench timeout that fires mid-observation is worse
than none; a flight one has no use case since flight never sends `run`).
Worth revisiting if the motor turns out to have a duty-cycle limit.

**Panel and console.** `clouds_ui/flight.py`: the CaCO3 group is Speed slider,
**Start | Stop**, **One pulse** (was one *Run one pulse* button). Start and
pulse send `SET_PARAM DISPERSE_DUTY` first, as before; while running, letting
go of the slider sends one `SET_PARAM` (`sliderReleased`, one per drag - not
per step, which would spend uplink on values nobody chose). GSE console:
`disperse [pulse|run|stop]`, bare `disperse` still the pulse. `sim_mcu.py`
mirrors run/stop, the hold in `valve_status`, the cancel, and the drop at
TERMINATION, so `--mock` and `tests/test_sim_mcu.py` exercise the whole chain.

**Evidence.** `run_native.sh` 60 tests (3 new), `pytest tests/` 302 passed,
`verify_qt.py` VERIFY OK with five new `flight:` checks (Start = `SET_PARAM`
then `DISPERSE 2`, live speed only while running, Stop = `DISPERSE 0`).
**Not yet run against the motor** - same status as the PWM path; the first
thing to read on the bench is `hb_sense_raw` during a run, which today's
session (other terminal) found at 0 for every membrane drive, as expected for
a sense that belongs to this motor and not to the solenoid.

## 2026-09-17 - ACT_HB_SENS is the CaCO3 motor's current, in amps

**The correction.** The GP46 sense added earlier today was written up, named
and displayed as the **push-pull membrane solenoid's** current. It is not: on
the carrier `ACT_HB` is one driver channel that carries **GP17/GP18 (the
dispersion motor's drive lines) together with GP46**, so the ADC pin measures
the motor. The membrane solenoid is GP26 and has no current sense at all. Every
comment that reasoned about the sense "swinging with the membrane's 2 Hz cycle"
was reasoning about the wrong actuator - the motor runs in bounded 5 s pulses,
so at 1 Hz a run is a handful of in-pulse samples and a legitimate zero between
releases.

**And the scale exists.** The driver is a **DRV8251A**, which has integrated
current sensing rather than a power shunt: an internal current mirror on the
low-side FETs drives IPROPI with `I_motor x AIPROPI` (**1500 uA/A** typ, the
`AERR` spec covering offset and gain together), and the carrier turns that into
a voltage across **R_IPROPI = 1.5 kOhm** to ground, which GP46 reads. So

    I_motor [A] = V_pin / (R_IPROPI * AIPROPI) = V_pin * 0.444

and the ADC's 3.3 V full scale is **1.47 A**. `HB_SENSE_A_PER_V` is no longer
`None`; the panel row (`Motor I`), the timeline series (`Dispersion motor
current`, A) and `to_row()` all carry amps. Counts still ride the wire raw, as
the INA226 shunts do: if the resistor is a different value than the schematic
says, or this part's gain is measured, every logged session is re-derivable.
The volts path stays in place and `hb_sense_text` falls back to it if the gain
is ever cleared - a wrong current is worse than an honest voltage.

**The one thing the reading does not say.** IPROPI mirrors only current
flowing drain-to-source through a **low-side** FET. In coast, where the winding
current freewheels through the body diodes, it reads **zero with current still
flowing**. The dispersion drive is forward (GP17 PWM high side, GP18 low) and
coasts between pulses, so 0 A means "no low-side current", not "no current" -
recorded in `board.h`, `hk.py` and on the panel note, because that is exactly
the number an operator would otherwise read as a dead motor.

**What this does not fix.** Nothing is measured yet: the gain is a datasheet
typ and a schematic resistor, the ADC reference is the SDK's nominal 3.3 V, and
GP46 has still never been read against a running motor. The first real pulse is
what turns this from plumbing into a measurement. The entry below - "the
motor's current is still unmeasured, on no monitored rail" - is superseded in
its first half only: the motor is still on no INA226 rail.

**Verified.** `pytest tests/` 297 passed (`TestMotorCurrentSense`, the IPROPI
chain test, the sim now driving the sense from `DISPERSE` instead of the
membrane phase), `verify_qt.py` VERIFY OK (`Motor I` reads `0.537A` for 1500
counts, `0.000A` idle, `-` from a pico2 build), `run_native.sh` 57 tests. No
wire-format change: `hb_sense_raw` is the same u16 in the same place.

---

## 2026-09-17 - The CaCO3 motor has a speed, and the panel a slider

**The change.** The dispersion motor's forward line (GP17) was driven fully on
for the 5 s of its pulse - a motor with one speed, and no way to find out on
the bench how fast it has to turn to disperse the powder rather than throw it.
It is now a PWM output: `hw.c` hands GP17 to its PWM slice for the length of
the drive at **20 kHz**, with the duty taken from the new
**`PARAM_DISPERSE_DUTY`** (percent), and takes the pin back as an SIO output
driven low when the pulse ends. The GSE panel grew a **Speed slider** in the
CaCO3 group; pressing *Run one pulse* sends `SET_PARAM DISPERSE_DUTY` and then
`DISPERSE`, the same order (and for the same reason) as the membrane's
`SET_PARAM MEMBRANE_HZ` before its drive.

**Why 20 kHz and not the membrane's mechanism.** The membrane runs at 2 Hz,
below the ~9 Hz PWM floor, which is why `core/sqwave` toggles it from the loop.
A motor is the opposite case: chopping a brushed motor at a few hundred Hz
whines, heats the driver and does not turn it any faster, so the drive wants to
be well above audible and the hardware PWM is the right mechanism. At 20 kHz on
a 150 MHz `clk_sys` `pwmdiv_solve()` lands on a period of a few thousand
counts, so the duty resolution is far finer than the 1 % the parameter carries.

**Why a parameter and not the command key.** `CMD_DISPERSE`'s key stays `1`.
The speed sits in the config instead, so the pulse the **release path**
schedules runs at the same speed as one commanded from the panel - there is no
bench-only setting to forget before flight. The duty is latched in
`ops_disperse()` when the pulse is *queued*, not read when it starts: the drive
is one 5 s shot that cannot be changed mid-run, so the speed the panel showed
at the press is the speed that runs.

**Envelope.** `{default 100, min 20, max 100}`. The default is the full-on
drive the pin had before it was a PWM, so an unconfigured system behaves
exactly as it did. The 20 % floor is not a safety limit but a usefulness one -
below it a brushed motor draws current and does not turn, which on the panel
reads as a drive that ran and dispersed nothing.

**What is not in this.** HK carries no motor-duty field: the speed is confirmed
by the `SET_PARAM` ACK and echoed in the panel's status line
(`disperse 40 % -> OK`), and a byte on the wire costs the MCU, the Pi and every
logged session. If the motor turns out to need in-flight verification of its
speed, that is the moment to spend it. The motor's **current is still
unmeasured** and it is on no monitored rail, so what a given duty does to the
draw is not observable from the ground - unchanged by this.

**Verified.** `flight/mcu/test/run_native.sh` 57 tests (new:
`test_disperse_duty_defaults_to_full_and_is_bounded`), `pytest tests/` 294
passed, `verify_qt.py` VERIFY OK with two new checks - the button sends
`SET_PARAM DISPERSE_DUTY 40` before `DISPERSE 1`, and the slider's label
follows the handle. Firmware builds clean for `clouds_carrier`. **Not yet run
against the motor on the bench**: the PWM path is untested on real silicon, and
the speed at which the powder actually disperses is unknown.

---

## 2026-09-17 - The push-pull solenoid's current is sensed on GP46

> **Superseded the same day**: the sensed actuator is the **CaCO3 dispersion
> motor**, not the membrane solenoid, and the scale is known (DRV8251A IPROPI,
> 0.444 A/V) - see the entry at the top. The mechanism below (raw counts, 8
> sample mean, `HAVE_HB_SENSE` guard, sentinel) is unchanged and still
> accurate; the actuator it is attributed to, and every "2 Hz phase" argument
> in it, are not.

**The change.** The carrier schematic names `ACT_HB_SENS` on **GP46**, the
sense output of the actuator bridge, and it carries the current of the
membrane push-pull solenoid. On the RP2350B GP46 is **ADC6** (ADC base pin
GP40), so `hw.c` now runs `adc_init()`, `adc_gpio_init(PIN_HB_SENSE)` and, in
each 1 Hz sweep, eight `adc_read()` conversions averaged into
`hk_t.hb_sense_raw`. That is the second feedback the firmware has from that
actuator, after the GP30 position switch of the same day: the switch says
whether the plunger moved, the sense says whether the coil drew current. A
drive whose switch reads pulled but whose current stays at zero, or the
reverse, is one row disagreeing with itself.

**Raw counts on the wire, scaling on the ground - again.** The field is the
12-bit ADC value, appended as a u16 after `mission_t_s` (HK **54 → 56 B**,
framed 72 B against the 83 B allowance; no older field moved, so a logged
session decodes with the same offsets). It is not an amp value because the
sense gain is not known: the schematic page we have names the net and
nothing about the shunt, amplifier or proportional-output resistor behind
it, and a guessed constant in firmware would put a confident wrong current
on every panel and in every log with no way back. So
`clouds_link/hk.py` carries `HB_SENSE_A_PER_V = None`; `hb_sense_v()`
gives the pin voltage against the 3.3 V ADC reference (itself an
assumption until measured), `hb_sense_a()` returns `None` until the gain is
set, and the panel row `Solenoid I` and the timeline series `Solenoid sense`
show volts meanwhile. When the gain is measured, setting one constant turns
every logged `hb_sense_raw` into amps.

**The sentinel is 0xFFFF, not 0.** A 12-bit sample cannot exceed 4095, and
0 counts is exactly what an idle solenoid reads, so a build with no GP46
(pico2 / RP2350A) downlinks `HB_SENSE_INVALID` and the ground shows `-`.
Guarded by `HAVE_HB_SENSE (PIN_HB_SENSE < NUM_BANK0_GPIOS)`, the same
pattern as the switch; the SDK asserts on `adc_gpio_init()` outside its
ADC range, so the pico2 build compiles the read out rather than trip it.

**What the reading is expected to do.** One sample per second against a
2 Hz drive lands at a random phase, so with the membrane on the value should
swing between the coil's hold current and ~0 from packet to packet - the
same shape as the switch bit, and `sim_mcu.py` produces it (counts ~1500
during the on-phase, ~12 otherwise) so `--mock` shows it. Averaging across
the cycle is a job for the logged series, not for the sample.

**Tests.** The STLM20 guard `test_no_adc_sampling_while_stlm20_is_unpopulated`
used "no ADC at all" as its proxy; it now checks its intent - the only
`adc_gpio_init` is `PIN_HB_SENSE`, the only `adc_read()` is inside
`hw_hb_sense_raw()`. New: `TestSolenoidCurrentSense` (pin, guard, raw
downlink, wire mirror), three `TestHousekeeping` cases (roundtrip and
scaling, amps appear once the gain is set, sentinel vs idle), a `sim_mcu`
case that the sense follows the drive, `test_main.c` checks offset 54, and
`verify_qt.py` renders `1.208V` / `0.000V` / `-`.

**Checks.** `run_native.sh` 56/56; `pytest` 293 passed, 1 skipped;
`verify.py` and `verify_qt.py` `VERIFY OK`; firmware builds clean for both
`clouds_carrier` (sense live) and `pico2` (sense compiled out). **Not yet run
on the carrier**: the ADC reference, the sense gain and the polarity of the
reading against a real drive are the three things a bench session has to
fill in.

## 2026-09-17 - The stored dark frame is committed, and a lit dark now says so

**The problem, reported from a second machine.** `dark_frame.npz` was not in
the repository, so a clone on another Mac came up with no dark at all. It was
`.gitignore`d on purpose, with the argument written into `spectro/dark.py`:
instrument state, regenerable in one button press. That argument holds on the
bench and nowhere else - the button needs the EURECA Duo *and* a darkened room,
neither of which a laptop has. The result was the failure mode the dark store
was built to prevent, one machine at a time: counts with a ~24 000 ct pedestal
(37 % of full scale) left in them.

**The change.** `dark_frame.npz` is tracked (10 kB, npz, no pickle). The
committed frame is the bench dark of S/N 20260312-004, 10 ms, x16, captured
2026-09-11. A capture overwrites it, `Clear` deletes it, `git checkout
dark_frame.npz` brings the baseline back. Nothing else moves: `--mock` still
runs `persist_dark=False`, `verify_qt.py` and `qc_live.py` still point
`CLOUDS_DARK` at scratch files under `output/`, so neither can write the
tracked one.

**Two guards had to come with it, because a shared file is a file that reaches
an instrument it was not taken on.**

* **Serial.** The startup restore runs before Connect, so the only check it
  could make was the pixel count - and two 2048 px Duos pass that. `serial`
  already travelled with the frame; `DarkFrame.serial_conflict()` now compares
  it, and `_drop_dark_from_another_detector()` runs it at Connect, where the
  detector has finally said who it is. A mismatch drops the dark, clears the
  checkbox and names both serials. Unknown on either side is *not* a conflict -
  darks captured before the field existed, and drivers that report no serial,
  must not start refusing themselves. The mock answers `MOCK-0001`, so the same
  rule is what keeps the committed bench dark out of a mock session.
* **Light leak.** The committed frame is the one 2026-09-11 already caught with
  room light reaching both fibres - it is the only one there is, and shipping
  it silently would be shipping a lie. `DarkFrame.light_leak()` compares each
  channel window's 99th percentile against the covered inter-channel gap's
  (px 236-1515 cannot see light by construction, so it is the reference for
  what "no light" costs on this detector): **Ch1 +3.1 k, Ch2 +13.7 k** over it.
  The 99th percentile, not the mean, because **a leak is lines, not a level** -
  40 lit pixels out of 251 move the window mean by ~1.9 k, which reads as
  noise. `LEAK_MARGIN_CT` is 2000 ct: the gap's own 99th percentile runs ~2.5 k
  over its median here (hot pixels at the window edges), so a tighter margin
  would call every good dark a leak.

It **names** the frame rather than refusing it. A leak is a bench mistake, not
a corrupt file, and the pedestal is still right everywhere nothing leaked - Ch1
is usable, Ch2 is an over-subtraction. So the Dark frame section carries
`light leak: ... - retake it with the fibres blocked` on every load, and the
hint says it on restore and on capture. It goes away the moment somebody
retakes it blocked.

**Evidence.** 20 tests in `tests/test_dark_frame.py` (9 new): serial conflict
both ways and both unknown-side cases; a clean dark reported clean; a lit
channel named with its excess; the mean shown to miss what the percentile
catches; no-gap and no-window cases claiming nothing; and the committed file
asserted present, 2048 px, and carrying the `calibration.json` serial - so
losing it again fails the suite instead of being discovered on another laptop.

## 2026-09-17 - The membrane solenoid gets a position switch on GP30, and the build learns it is an RP2350B

**The change.** A push button now sits against the membrane push-pull
solenoid's plunger, one side on **GP30**, the other on ground: closed while
the solenoid is energized (pulled), open while released (pushed). Read as an
input with the internal pull-up, so **LOW means pulled**. This is the first
feedback the firmware has from that actuator - until now `membrane_duty` in
HK was the *commanded* duty echoed back, and the only proof the solenoid
moved was watching it.

**Where it goes in HK.** Bit 5 of `valve_status`, `HKV_MEMBRANE_PULLED`. The
byte was "one drive line at a time" and this bit is not a drive, so the
contract changed to "at most one *drive* bit, plus the sensed bit", written at
the definition in `core/frame.h` and mirrored in `clouds_link.hk.ValveStatus`.
On the ground it is deliberately kept out of `actuator_text` (the `Driving`
row and the headless monitor's `drive=`), because a sensed plunger printed in
a list of held lines reads as the MCU holding a line. It appears where the
check is: the `Membrane` row now reads `60 %  pulled` / `60 %  pushed`
(`Housekeeping.membrane_text`), duty and position side by side, so a drive
above zero whose switch never reads pulled - or a duty of zero whose switch
does - is visible as one row disagreeing with itself. At the membrane's 2 Hz
the 1 Hz HK sample lands at a random phase of the cycle, so with the drive on
the row is *expected* to alternate between packets, pulled about `duty_pct`
of the time; `sim_mcu.py` does the same so `--mock` shows the real shape.

**Why the build had to change.** GP30 does not exist on an RP2350A. The
carrier is an RP2350B (QFN80, GP0..GP47 - schematic 2026-09-11, `picotool
info` `package: QFN80`), but the firmware was built with
`-DPICO_BOARD=pico2`, which is RP2350A: `NUM_BANK0_GPIOS` is 30, the ADC base
pin is GP26, and `gpio_init(30)` either trips the SDK's parameter assert or
writes past the bank. Nothing in use was above GP29, so this had cost nothing
- the 2026-09-11 entry noted it and moved on. Now `flight/mcu/boards/
clouds_carrier.h` sets `PICO_RP2350A 0` with the pico2 UART and flash
defaults and *no* SDK default I2C/SPI/LED pins (pico2's default SPI chip
select is GP17, the dispersion motor; nothing here uses those macros, and a
board header that names an actuator as a bus default is a trap for the next
`spi_init()`). `CMakeLists.txt` selects it by default and adds `boards/` to
`PICO_BOARD_HEADER_DIRS` *before* the SDK import, because the header is
resolved during `pico_sdk_init()`. The flash size is pico2's 4 MB and is an
**assumption** about the carrier's QSPI part - it bounds the linker region
only, and the image is ~200 kB; `picotool info -a` will settle it.

`-DPICO_BOARD=pico2` still builds, for the bare Pico 2. On it the read is
compiled out behind `#if PIN_MEMBRANE_SENSE < NUM_BANK0_GPIOS` and
`hw_read_sensors()` raises **`HKE_NO_MEMBRANE_SENSE`** (error bit 2, the old
`NO_CHAMBER_P` slot), so the ground side shows the duty alone rather than
reading an always-clear bit as "pushed". Same rule as `HKE_NO_TEMP`: no
source, say so, never a plausible number.

**A cached `PICO_BOARD` is the trap.** `build/` configured for pico2 keeps
building pico2 after this change; a `cmake --build` there succeeds and
produces firmware that reports `NO_MEMBRANE_SENSE` on the carrier. Delete and
reconfigure.

**Checks.** Both boards, both targets (`clouds_fsw_mcu`, `bno055_probe`),
`-Wall -Wextra` clean. `tests/test_fsw_mcu_actuators.py::TestMembraneSense`
pins GP30, input + pull-up, active-low decode, the `NUM_BANK0_GPIOS` guard and
the carrier default; the HKV/HKE mirror tests cover the new bits;
`test_link.py` covers the row text and the unsourced case; `verify_qt.py`
sends `DISPERSE | MEMBRANE_PULLED` and requires `Membrane = 70 %  pulled`,
`Driving = DISPERSE`.

**Measured on the carrier (`21DD2AE08840C863`), same evening.** Firmware from
HEAD (carrier board header, HK 56 B) flashed over USB; the Pi's `/opt/clouds`
brought up to the same commit (its `clouds_link` was still the 50-byte
Keller-era layout, so nothing it decoded would have been right) and the
service restarted. Ground side was the running `clouds_ui`, whose session log
`gse_sessions/session_20260917_185712_hk.csv` records every HK row; commands
went in over a second TCP 4001 client.

```
baseline, MEMBRANE 0        10 HK   membrane_pulled True 10/10   duty 0
MEMBRANE 60  -> ACK OK      25 HK   membrane_pulled True 25/25   duty 60
MEMBRANE 0   -> ACK OK      10 HK   membrane_pulled True 10/10   duty 0
error_text                  IMU_FAIL NO_TEMP  (no NO_MEMBRANE_SENSE: the build reaches GP30)
valve_status                0b100000 in all 200 rows of the session
V_in                        23.95 V, 0.195 A flat through all three phases
```

The chain is right: the bit is read, packed, relayed, decoded and rendered,
and the duty follows each command. The *reading* is wrong: LOW in every
packet, drive on or off. HK alone cannot say why, so
`src/tools/membrane_switch_probe.c` (built with `-DCLOUDS_BUILD_TOOLS=ON`,
USB CDC, same pattern as the IMU probe) was flashed for one run:

```
GP30: pu=0 pd=0 -> held LOW externally      GP31: pu=1 pd=0 floating   GP32: pu=1 pd=0 floating
GP26=0 (released):  GP30 high  0/20   x3
GP26=1 (energized): GP30 high  0/20   x3
2 Hz / 60 % on GP26, 6 s, 20 ms samples: GP26 ###############.......... GP30 .................. every line
```

**What that first run established.** GP30 is wired and held low at rest -
with the internal pull-up it still reads 0 - and nothing the MCU drove
changed it. The operator then supplied the missing piece: **the button sits
under the plunger and is pressed while the solenoid rests; actuating the
solenoid lifts the plunger off it.** So LOW is the *resting* state, HIGH is
*actuated*, the opposite of the first spec ("active is expected to be low"),
and in that first run the solenoid had simply not moved. Polarity fixed:
`hw_membrane_pulled()` returns `gpio_get()` without the `!`, and the bit,
the panel text and the docs mean "lifted / actuated".

**Second run, with the solenoid actually moving** (same probe, plus an
H-bridge phase and a read of the 24 V regulator pins):

```
GP30: pu=0 pd=0 held LOW at rest          GP39 VR_24V_EN: pu=0 pd=0 (held low)   GP40 VR_24V_PG: pu=1 pd=1 (driven high)
GP26=0 (rest):      GP30 high  0/20   x3
GP26=1 (energized): GP30 high 20/20   x3
2 Hz / 60 % on GP26, 20 ms samples, all six seconds identical:
     GP26 ###############..........###############..........
     GP30 #################........#################........
H-bridge GP17 fwd / off / GP18 rev / off, x2:   GP30 high 0/20 in every state
```

GP30 follows GP26 one for one: high the whole time the drive is high, and it
stays high for **two more 20 ms samples** after the drive drops - the plunger
takes ~40 ms to fall back onto the button, which is the mechanical release
time and a useful number in itself. The H-bridge (GP17/GP18, the dispersion
motor) does not move the plunger at all, so the membrane solenoid really is
the GP26 (`ACT_R_1`) load, as the 2026-08-31 measurement said, and the
"push-pull is on the H-bridge" reading of the schematic's `ACT_HB_SENS` net
is not supported by this switch. `VR_24V_PG` reads driven high and
`VR_24V_EN` held low while the solenoid works - so the enable's polarity
is either active-low or the regulator is enabled elsewhere; not touched.

Flight image (HEAD 6ce2615 + the polarity fix) restored afterwards and the
bit checked end to end through HK - see the figures below this entry's
checks. A note for the peer session working on the same pin the same
evening: the 1 Hz HK sample and the 2 Hz wave run off the same loop, so at
60 % duty a single `MEMBRANE_PULLED` sample lands at a fixed phase and reads
one constant value; their `MEMBRANE_CYCLING` latch is the answer to that,
and the steady `MEMBRANE 100` / `MEMBRANE 0` states are what this bit alone
can verify.

---

## 2026-09-17 - A detector that was late at startup stayed missing all session

**The report.** "Sometimes the connection to all sensors and motors works but
the spectrometer data is not displayed. A restart fixes this most of the
time."

That shape - flight half fine, instrument half blank, restart cures it - is
the signature of a *one-shot* startup step, and there was exactly one:

```python
if not args.flight:
    win._connect()          # clouds_ui/main.py
    if win.connected:
        win._start()
```

`_connect()` on a `DriverError` posted the reason in the sidebar label and
returned. Every **other** driver failure in the window arms the 3 s retry
(`_on_driver_error` -> `_reconnect_timer`), and `_connect()` deliberately
*stops* that timer on the way in, so the one failure the app could not
recover from was the first one. The flight half is on its own sockets - UDP
4000, TCP 4001 - and comes up regardless, so HK, events, valves and the motor
all looked healthy while the spectrum stayed empty. Restarting worked because
whatever was late had arrived by then.

Reproduced offscreen against a closed port, before the fix:

```
connected: False
reconnect timer active: False        # <- nothing would ever try again
conn err label: cannot reach spectrometer server at 127.0.0.1:9 ...
```

**What is late, and why it is intermittent.** On this bench the detector is
reached over the cable (`--net`, the default on macOS), so the startup
connect is a TCP connect to the Pi's `--bench-stream` on 4010 - a port that
only exists once the flight app is up, and one the GUI races on every boot of
the pair. The local path has its own version: the vendor library's
`search_for_camera` can miss on the first call after a replug (`DRIVER.md`).
Both are transient by nature, which is precisely why a terminal first attempt
was the wrong policy.

**The fix.** `CloudsWindow.start_detector()` is now the startup path, and
`main()` calls it instead of the `_connect()`/`_start()` pair: it arms the
same retry the rest of the app uses, and records live as the standing intent
(`_resume_on_reconnect`), so the attempt that gets through connects *and*
starts the trace with no operator action. `_connect(retry=False)` also hands
back a retry it interrupted rather than dropping it - a Connect click that
comes a second too early must not disarm the loop that would have got there
on its own - and it prints the reason to the terminal the window was launched
from, where the old red label was easy to miss.

Verified end to end offscreen: window opened against a dead port (refused,
retry armed), a `net_server` then started on that port, and the window
reconnected by itself - `connected=True running=True frame=(2048,)`. Two new
`verify_qt.py` checks hold the behaviour: the startup failure arms the retry,
and a manual click does not disarm it. `pytest` 264 passed, `verify.py` and
`verify_qt.py` both `VERIFY OK`.

**Three more ways the same screen could lie, found next to it and fixed in
the same pass.** All three are on the `--net` path, i.e. the only way this
bench sees the detector at all.

* **The stream could serve the same frame twice as if it were new.**
  `FrameHub.wait_for_new` returned `(self._n, self._frame, ...)` even when the
  wait timed out with `_n <= since`, and the handler sent it - so a stalled
  acquisition thread showed as a *frozen trace that still looked live*. Over
  this stream `frame_counter` is `None`, so the panel's own duplicate
  detection could not catch it either, and nothing else on screen would have
  moved. `wait_for_new` now returns `(n, frame, exposure_us, fresh)`: the flag
  is in the tuple rather than left to the caller to infer from `n`, because
  inferring it is exactly what the first version failed to do. A stale wait is
  answered with an error naming the stall, never with a frame; the client
  reconnects and recovers by itself when acquisition resumes.
* **The client gave up before the server answered.** `NetDriver`'s socket
  timeout is 10 s; `bench_stream._WAIT_TIMEOUT_S` was 30 s. Every stalled
  detector therefore reported as "link failed during grab" - a *network*
  fault, pointing at the cable - instead of the server's own message, which
  names the detector. The wait is now **5 s**, comfortably over the 1 Hz
  flight cadence and well under the client's timeout, and a test asserts that
  ordering rather than leaving it to two constants in two packages
  (`test_the_wait_is_shorter_than_the_client_timeout`). The handler also
  passes the timeout explicitly instead of taking the default argument, which
  is bound at `def` time and could not be shortened from a test.
* **`identity` succeeded when there was no detector.** `info_provider` is
  `lambda: self.source.info`, `None` until the FSW's first successful connect;
  the handler `getattr`ed past it and answered with an empty model/serial and
  a default 2048 px. The panel therefore said "connected" against a Pi with no
  camera and only the first `grab` said otherwise. It now refuses, naming the
  cause, so the panel stays visibly disconnected and retries - which is the
  honest state and, with the fix above, a self-healing one.

While fixing the last of those, two socket bugs in `NetDriver` that it makes
reachable: a `connect()` whose identity exchange fails left the socket open
(one leaked descriptor per 3 s retry against a server behaving correctly), and
a transport failure - a timeout mid-exchange - left a half-finished exchange
in the socket. `dark_value()` and `frame_counter()` swallow `DriverError` by
design, so that one would have desynced every later response by one, and a
JSON body read as a frame is silent garbage until the tag check trips.
Both now close the socket on the way out; the next call fails cleanly and the
panel's retry opens a new one.

`pytest` 268 passed, `verify.py` and `verify_qt.py` `VERIFY OK`.

---

## 2026-09-17 - Auto integration time froze the window, and the Auto button never converged

**The report.** "Auto Integration time crashes the GUI or takes really long."
Two independent bugs, plus a third found next to them that is worse than
either.

**1. The `Auto` button passed its own `checked` flag as the target.**

```python
self.btn_auto.clicked.connect(self._auto_expose)      # the bug
```

`QPushButton.clicked` carries a `bool checked`, and PyQt5 binds a signal
argument to the first parameter of any slot that will accept one. Verified in
this repo's venv against a slot with the same shape as `_auto_expose`:

```
args passed: [(False, 0.02, 1000.0, 8)]
```

So the hunt ran with `target=False`, `tgt = saturation_count * 0 = 0`, and its
proportional step

```python
new = exp * min(max(tgt / max(pk, 1.0), 0.2), 8.0)
```

clamped to the **0.2 floor on every iteration**. The factor could never exceed
1: the hunt could only divide. From any starting point outside 60-80 % FS it
ran all 8 iterations down to the 0.02 ms rail and returned a black spectrum -
including in a scene that was too *dim*, where the correct move is up. Only a
first probe that happened to land in the band ever stopped it. The checkbox
path (`_on_track` -> `_auto_expose()`, no arguments) was always correct, which
is why the servo behaved and the button did not.

The fix is `lambda: self._auto_expose()`, with the trap written beside it. The
signature stays usable from code, and `verify_qt.py` now clicks the real button
rather than calling the method, so the binding is what is checked.

**2. The hunt ran on the GUI thread.** It is not one driver call. Each probe is
`set_times_us` + settle discards + a median stack, and the loop is up to
`iters` probes, each of which may take a second confirm probe - at the old
2 + 7 frames that is **9 grabs per probe, 144 per hunt**.

Over `--net` against the FSW's `--bench-stream`, every `grab()` blocks on
`FrameHub.wait_for_new`, paced to `sample_interval_s` - **1 Hz, the flight
cadence, never tuned up for bench use**. 144 grabs is ~144 s with the main
thread never returning to the event loop. macOS marks the process
unresponsive; the operator force-quits; the report says "crashes". The local
Duo is no safer: `set_times_us` sets `frame_us = exposure_us`, so a grab costs
about one integration time and a hunt near the 1000 ms rail lands in the same
place.

The live tick already solved this - `_AcquisitionWorker` exists because calling
a bench-stream `grab()` straight from the 60 ms timer slot froze the window
between frames. The hunt now uses it too, and:

- the live loop is **paused for the duration**, because `_track_exposure` would
  otherwise be steering the same exposure from the other direction, and resumed
  when the hunt lands (carrying the result hint past `_start()`'s own);
- a `budget_s=15` wall-clock bound sits on top of `iters`, so a scene that
  cannot be solved gives back the best exposure found **and says so** instead
  of holding the detector;
- the probe stack drops 7 median frames to 3 (`_AUTO_STACK`; `robust_peak`
  already despikes) - 5 grabs per probe, not 9;
- `_single()` and `Capture dark` decline while a hunt is in flight rather than
  blocking the GUI thread on the driver lock, and `Auto` / `Single` grey out.

`verify_qt.py` checks the freeze directly: with `grab()` slowed to 50 ms the
event loop must keep turning during a hunt (1456 turns, vs. 0 before).

**3. `_disconnect_ui()` closed the driver out from under the live worker.**
Found while tracing the error path. `_stop()` only stops the QTimer - a tick
already handed to `_AcquisitionWorker` is still inside `grab()`. The close then
ran unlocked:

```python
self._stop()
try:
    self.driver.close()          # no lock
```

`EurecaDriver.close()` calls `e9u_LSMD_stop_camera` / `close_camera` and nulls
`_lib` and the pixel-buffer pointer, so a worker mid-`get_next_frame()` is a
ctypes call into a stopped camera reading a freed buffer - a segfault with no
Python traceback, and one that only appears where the vendor library is real
(Pi, Windows), not on the Mac's `--net`. `closeEvent()` already waits on the
worker for exactly this reason; `_disconnect_ui()` did not. It now takes the
(re-entrant) driver lock, which serialises against the worker without waiting
on a hunt that may have seconds left.

**Not changed.** The hunt's algorithm - despiked peak, proportional jump,
confirm-before-accept - is untouched; so is the 60-80 % band, the 1 Hz bench
cadence, and the servo. `verify_qt.py` still reports the same convergence
(48.7 ms, sat 0.01) from the same saturated start.

---

## 2026-09-16 - `--mock` is back, and it is the whole chain

**The ask.** `./run_clouds_ui.sh --mock` should run the interface with no
connection to any hardware. The flag was deliberately removed on 2026-09-11
(entry below) and the reason it was removed has not gone away: a synthetic
spectrum that an operator reads as a measurement is the worst failure this
app can have. So it comes back with that failure engineered against, rather
than with the argument re-litigated.

**Not just the driver.** The obvious implementation - `open_driver(mock=True)`
and stop - produces an interface whose flight half is dead: no housekeeping,
no events, no quick-look, and every command timing out, because the flight
half is fed by the Pi and there is no Pi. That is not "no hardware", it is
"broken hardware", and it teaches an operator the wrong reflexes. So `--mock`
stands up the real chain in-process (`clouds_ui/mock_stack.py`): the actual
`clouds_fsw.FlightApp` with a mock spectrometer, talking real UDP and TCP on
loopback to the window's own receiver and commander, with a **simulated
RP2350** (`flight/pi/clouds_fsw/sim_mcu.py`) on the far end of its UART pipe.
Exactly two things are fake - the light on the detector and the silicon on
the UART. The framing, the packets, the sockets, the interlocks and the
storage path are the flight ones.

`SimMcu` mirrors `core/sequencer.c` and `core/link.c` where it matters to
ground: HK at 1 Hz, an ACK carrying its own verdict for every CMD, the
arm/execute window, `RELEASE` rejected on the pad and refused a second time
once `fired` is set (S.3), actuator drives locked out in TERMINATION/SAFE,
one actuator line energized at a time. It is **not** a second source of truth
and not flight timing: ascent and the measurement phases are compressed to
demo length (45 s / 60 s against 480 s), and the ascent pressure is a decaying
exponential, not an atmosphere. When the C and the sim disagree, the C is
right. The sensor picture it reports is this carrier as measured - BME280 and
three INA226 rails live, the 24 V slot `RAIL_MV_INVALID`, `NO_TEMP` and
`IMU_FAIL` set - because a mock that invents an IMU trains an operator to
expect one.

**Where the labelling lives.** Anything that could later be mistaken for a
measurement says otherwise at the point it would be misread: the window title
(`MOCK: SIMULATED DATA, NO HARDWARE`), the plot's source banner in its own
colour rather than a shade of the detector one, the device line, and the
launcher's own startup lines. `--mock` and `--net` are refused together - one
promises no detector anywhere, the other names a real one, and picking a
winner would leave the operator looking at the other.

**Contamination, which is where the real bugs were.** Three paths let a mock
session reach a real one, and all three are closed:
- **The stored dark frame.** Capture persists it as the default, and the next
  session loads it - so a synthetic dark would be silently subtracted from
  real light, a wrong measurement nobody would think to suspect. `--mock`
  neither writes nor clears the store. This is a **separate switch**
  (`persist_dark=`) rather than `not mock`, because `verify_qt.py` runs a mock
  window and is the only thing that *can* test the store; wiring it to `mock`
  broke nine of its checks, which is how the distinction was found.
- **The downlink port.** A real GSE on UDP 4000 and a mock one are the same
  socket. The mock binds `127.0.0.1:0` - ephemeral, loopback-only - so it
  cannot collide with a real session and cannot take a command from off the
  machine. A test asserts the command port refuses a non-loopback connect.
- **The files left behind.** Session logs are named `session_mock_*`, and the
  FSW's data directory is a temp dir removed on exit.

**Checks.** `pytest` 265 passed, including `tests/test_sim_mcu.py` (13 cases
on the verdicts ground actually sees) and `tests/test_ui_mock.py` (the flag
rules, the chain downlinking, an end-to-end ARM+RELEASE, the loopback-only
port, the temp dir). `verify.py` `VERIFY OK`. `verify_qt.py` `VERIFY OK` -
including the ten checks the entry below left failing: `_parse` no longer
overwrites an explicit `--net` (it only fills in the default when nothing was
given), and the nine `dark:` checks pass again now that persistence is its own
switch. Five new `mock:` / `args:` checks cover the labelling and the dark
guard.

---

## 2026-09-16 - The Mac launcher builds its own environment

**What was broken.** `run_clouds_ui.sh` assumed an environment already
existed. On a Mac with none it fell through to `python3`, failed the PyQt5
import, and printed
`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` - advice
that does not work on a current Mac. `python3` from Homebrew is **3.14**, and
`numpy==2.2.6` ships no cp314 wheel (checked: `pip download --only-binary`
offers 2.3.2 upward and nothing pinned), so that command either fails the
version solve or starts building numpy and scipy from source. PyQt5 is not the
blocker on macOS that it is elsewhere - 5.15.11 is an `abi3` wheel and installs
on 3.14 quite happily, which makes the failure land on numpy instead, one line
further down, after a long wait.

**The supported window is Python 3.11-3.13** and it comes from the pins, not
from taste: scipy 1.16 needs >= 3.11, and numpy 2.2.6 / matplotlib 3.10.8 stop
at cp313. The script searches `python3.13` → `3.12` → `3.11`, on `PATH` and by
path in the Homebrew, python.org and pyenv roots (a python.org or pyenv install
is routinely not on `PATH`, and finding it is the difference between "run one
brew command" and "unsupported"). With none of them it says
`brew install python@3.13` rather than guessing.

Having found one it builds `./.venv` and installs `requirements.txt`. The
boundary is deliberate: **nothing outside `./.venv` is touched and nothing is
installed into a system interpreter**, so `rm -rf .venv` undoes the lot, and an
activated `$VIRTUAL_ENV` is used as-is and never modified - that one belongs to
the operator. `CLOUDS_NO_SETUP=1` turns the behaviour off.

It also rebuilds a venv that has *stopped* working, which on a Mac is how one
normally ends: `brew upgrade python` moves the base interpreter and leaves
`bin/python` as a dangling symlink. That case needs `[ -d .venv ]`, not
`[ -e .venv/bin/python ]` - `-e` follows the link, so the dead venv tested as
absent and produced the wrong message. Caught by breaking one on purpose.

**Verified by demolition, not by reading.** The venv was moved aside and the
script run: it chose `/opt/homebrew/bin/python3.12` over the 3.14 on `PATH`,
built `.venv`, installed, and opened the window. Then `bin/python` was replaced
with a dangling symlink and it rebuilt. Both from the state a fresh clone is
in.

**`requirements-dev.txt`.** The fresh venv could not run `pytest tests/` - the
old one had pytest installed by hand and `requirements.txt` never listed it, so
the documented pre-commit check did not survive a rebuild. Split rather than
merged: `requirements.txt` stays what the interface needs to draw a spectrum,
and pytest / pyserial / pyinstaller move to `requirements-dev.txt`, so a bench
machine is not carrying a test runner and PyInstaller. (`verify.py` and
`verify_qt.py` need neither - they were already self-contained.)

**The cable: `setup_macos_net.sh`.** macOS is the platform where this is not
optional. There is no EURECA vendor library for it at all, so the detector is
*only* reachable over the bench cable - `--net` is already the default here,
and with no cable there is no spectrum. Same three modes as the Windows
script: check by default, `--apply`, `--revert`.

`--apply` runs `networksetup -setmanual "<service>" 192.168.100.1
255.255.255.0` with **no router argument**, and the check flags a router if one
appears. That is the whole design: with no gateway on this service the Mac
keeps its default route over Wi-Fi, so internet, ssh and brew keep working with
the cable attached, and a `192.168.100.10` in the Router field installs a
default route to a Pi that forwards nothing.

Two things the first version got wrong, both found by running it:
`networksetup -listallhardwareports` keys on the **hardware port**, not the
service name, so two of six services showed no device - a service can be
renamed and the two only coincide by default. `-listnetworkserviceorder` is the
mapping that actually holds. And the "no service named X" error was printed
inside a `$( )`, where it was captured instead of shown, leaving a wrong
message about an unconfigured adapter; the name is now validated before that
substitution.

The launcher pings the Pi before starting (skipped for `--flight`,
`--no-link`, `--mock` and an explicit `--net`) and points at the script if
there is no reply - otherwise the window opens and sits in a reconnect loop
with the reason buried in a status label.

**Picking the adapter.** First contact with a second Mac produced the one
question the script could not answer: two wired services, `AX88179A` and
`AX88179B`, neither configured, and no way to tell which had the cable. The
order is now the service already holding the bench address, then the only
wired service, then the only wired service whose device reads
`status: active`. Link state is the signal that separates two identical USB
adapters - a port with nothing in it is never active - and it is also the one
that catches the other half of the question, since with the cable out
*nothing* is active and the script can say so instead of listing six services
and shrugging. `--list` shows the column, so the answer is visible rather than
inferred. It still refuses to decide when two links are live.

**Checks.** Against a live bench - Pi answering on 192.168.100.10 at 0.5 ms,
TCP 4001 and 4010 both open - `setup_macos_net.sh` reports every line
correctly, and `--list`, an unknown service and a real-but-unconfigured service
each behave. `pytest` 246 passed and `verify.py` `VERIFY OK` on the rebuilt
venv. **`verify_qt.py` fails 10 checks**, all of them in the concurrent
`--mock` work and none in this: `clouds_ui/main.py`'s new `_parse` overwrites
`args.net` with `_default_net()` whenever `--mock` is absent, so an explicit
`--net 1.2.3.4` comes back as `192.168.100.10` ("args: --net always wins"),
and the nine `dark:` checks build a `CloudsWindow(mock=True)` and then assert
the dark frame *was* stored, which the mock stack now deliberately refuses.
Left for whoever is writing that feature.

---

## 2026-09-16 - Windows runs the GUI again, cable included

**What was broken.** `run_clouds_spectral.bat` ran on exactly one machine. It
pinned an absolute interpreter path under one developer's profile
(`C:\Users\kai-w\AppData\Local\...\python.exe`) and set **no
`PYTHONPATH`**, so on any other Windows box it either found no Python or found
one and then died on `ModuleNotFoundError: No module named 'clouds_gse'`. That
import is real and unavoidable: `clouds_gse` lives under `gse/` and
`clouds_fsw` under `flight/pi/`, neither on the repo root, and
`clouds_ui.main` imports `clouds_gse` on every start that is not `--no-link`.
The POSIX launcher had solved this a while ago; the batch file had never been
brought level with it.

The same absolute path had a second copy in `spectro/eureca_driver.py` as the
last Windows candidate for the vendor DLL. It never *helped* - `vendor/` is
checked first and the DLL is in the repo - but when `vendor/` was missing it
turned the error into "vendor DLL not found:
`C:\Users\kai-w\projects\EURECA_e9u\...`", i.e. it sent the operator
looking for a folder that had never existed on their machine.

**What the launcher does now.** First interpreter of `%CLOUDS_PYTHON%` →
`.venv\Scripts\python.exe` → `%VIRTUAL_ENV%` → `py -3` → `python`; then an
import check for PyQt5 and matplotlib *before* anything starts, printing the
pip line rather than a Qt traceback; then the three `PYTHONPATH` entries; then
every argument straight through. Same shape and the same reasoning as
`run_clouds_ui.sh`, which is the point - the two launchers now fail the same
way for the same reasons.

It also sets `chcp 65001` and `PYTHONIOENCODING=utf-8`, which is not cosmetic.
The console is cp1252 by default, the UI prints `µ` and `Ω`, and **PyQt5 aborts
the process** on an unhandled exception in a slot - so a `UnicodeEncodeError`
inside a timer tick takes the window down with nothing on screen to say why.

**The cable: `setup_windows_net.ps1`.** The bench link is deliberately
gateway-less (README, "Bench link to the flight Pi") so both machines keep
their normal default route. Windows classifies exactly that shape of link as a
**Public** network, where inbound is blocked - and the symptom is the quiet
one: the adapter is up, `ping 192.168.100.10` replies, TCP 4001 and 4010 work
because they are outbound, and only the **UDP 4000 downlink** silently never
arrives. The script's default mode changes nothing and reports each link in
turn (adapter, address, network profile, ping, TCP 4001/4010, the firewall
rule, what is bound to UDP 4000); `-Apply` sets `192.168.100.1/24` and adds the
inbound UDP 4000 rule; `-Revert` puts the adapter back on DHCP. Without
`-InterfaceAlias` it lists candidate adapters and stops rather than guessing,
because guessing wrong takes the machine off its own network.

It prefers a **port** rule over the "allow this app" inbound rules Windows
creates for `python.exe`: those name one program, and a venv `python.exe` is a
different program, so the bench stays working while a fresh checkout does not -
the check reports that case as a warning rather than an OK.

**Receiver hardening, same platform.** `Receiver` now clears
`SIO_UDP_CONNRESET` on its socket and treats `ConnectionResetError` from
`recvfrom` as continue-worthy. On Windows an ICMP port-unreachable for a
datagram that already left is reported by failing the *next* `recvfrom` of a
connectionless socket; the old `except OSError: return` took that as fatal and
ended the downlink thread for the rest of the session, silently. A failed
`bind` now also says what to do about it instead of surfacing WSAEADDRINUSE
raw.

**`build_exe.py`** got `--paths` for the same three entries plus
`--collect-submodules`. The frozen exe had the launcher's bug in a worse form:
PyInstaller's static analysis reaches neither `clouds_gse` nor the path it is
on (the import is inside `main()`), so the build succeeded and the exe died on
first start.

**Checks.** `pytest` 246 passed, `verify.py` and `verify_qt.py` both
`VERIFY OK`, `setup_windows_net.ps1` parses clean under `pwsh`. None of this is
Windows-*verified* - it was written and checked on macOS, and the batch file
and the PowerShell script have not been executed on Windows.

## 2026-09-11 - The sidebar packs into columns instead of scrolling

**What was asked.** "Rework the UI so open panels by default are visible all
at once without scrolling."

**Measured first, because the fix depends on the number.** Offscreen, with
`fold_for(False)` and the shipped `DEFAULT_OPEN` set, the sections were
77 px (Spectrum source), **325** (Sensors), 189 (Commands), 214 (Actuators),
**217** (Events) and 19 per folded heading - **~1500 px of sidebar** with
margins, spacing, wordmark and hint. The old layout was one 410 px column in
a `QScrollArea`, so against a laptop's ~870 px that is off by about 2x: the
open sections could not all be on screen at any window size, and the two
halves of the interface - the command you send and the housekeeping that
answers it - were never visible together. No amount of tightening one
section closes a 2x gap; **the column count is the variable**.

**`sections.SectionFlow`.** The sidebar is now N columns of 340 px, packed
greedily in order and then evened out: once the column count is known, the
smallest per-column height that still yields that count is found by
bisection, which also minimises the tallest column. Order is preserved - a
break moves a section sideways, never past its neighbours. Heights come from
`heightForWidth` at the column width, not `sizeHint()` alone, because several
sections end in a wrapped note that is two lines at 340 px where the hint
assumed one. The count is the *fewest that fit*, so a tall screen still gets
one column and gives the width back to the spectrum.

**The split is the operator's: a horizontal `QSplitter`.** The first cut
pinned the sidebar with `setFixedWidth` to exactly the columns it wanted, and
that is wrong twice over. It takes the choice away - a calibration pass wants
the trace, a commanding pass wants the controls - and a fixed-width sidebar
*is* the window's minimum width, so a cap computed from the window's own
width is a feedback loop: three columns force the window wider, the wider
window permits three columns, and the window can no longer be shrunk.
Measured while it was wrong: asking for 1280x720 left the window 2274 px wide
with 173 px of spectrum. Now the handle sets the width, the sidebar is
clamped between one column and `MAX_COLS` (3), the spectrum has a floor of
`MIN_PLOT_W` = 420 px, and `columns_for_width` turns whatever width it is
given into a column count - so dragging the sidebar out adds a column instead
of adding empty space, and dragging it in gives the trace the room back.
Columns widen past 340 px to fill the width, and because several sections end
in a wrapped note, a wider sidebar is not only wider: it can shorten the
columns enough to drop one. The vertical scrollbar's width is reserved
whether or not it is showing, or a bar that appears would narrow the sidebar
by its own width, drop a column, make the content fit, and vanish again.

**Fitting 1440x870 took the columns *and* four trims**, because two columns
of 808 px still came up ~110 px short in the flight shape (Housekeeping open
as well):

* the **wordmark is a flow item**, not a header above the flow. A header is
  ~100 px the columns never get to use.
* **Sensors is one line a row** - name, part, value in a 3-column grid -
  instead of a two-line `name\npart` label: 325 -> 251 px. The part name
  stays, because it is what makes a reading judgeable (`Accel` looks like
  instrument data until you know it comes from a BNO055 that does not
  answer).
* the **Events list is `setFixedHeight(140)`**, not a 120 px minimum with a
  ~250 px hint. Five events visible and the rest scrolling is what a log
  does; the height it was claiming was empty rows.
* a **run of folded sections packs at `TIGHT_GAP` = 4 px**, not 12. Seven
  folded headings in a row are a list of one-line labels, not seven blocks -
  worth ~50 px at the bottom of a column, and it reads better.

**`FlightPanel` stopped being a container.** It was a `QWidget` stacking its
five sections in its own `QVBoxLayout`, which would have pinned the whole
flight half into one column. It is now a `QObject` that builds sections and
owns their slots and exposes `sections` for the sidebar to pack - the update
logic is untouched. Its one dialog re-parents to `sec_cmd`, a real widget
(`QMessageBox` needs a widget parent, and a `QObject` is not one).

**Folding re-packs, batched.** `fold_for` sets fourteen sections in a row;
without `SectionFlow.held()` the operator would watch the columns rearrange
thirteen times before landing. `_set_hint` re-packs too: the hint spans the
sidebar and wraps, so a long one is height the columns no longer have.

**Result, on the 1440x870 screen this was measured against.** The window
opens with the handle set to two columns where there is room for them: 743 px
of sidebar, 697 px of spectrum, **no scrollbar in either shape** - content
715 px on the bench and 804 px in flight against an 870 px viewport; tallest
column 666 / 755 px against a 808 px budget. Dragging the handle re-packs
live: 400 px -> one column, 760 px -> two, 1016 px -> two columns 476 px
wide. The window's default size went 1420x920 -> 1720x980, clamped to the
screen. `verify_qt.py` checks the packing directly - tallest column within
budget, every item placed exactly once, one column when the height is there -
alongside the existing "the sidebar is not clipped horizontally".

---

## 2026-09-11 - Three BNO055 bugs the missing part was hiding, and the carrier schematic (M-09)

**What was asked.** "The BNO055 sensors are not working, fix this" - this time
with `pin_layout.jpeg` (the carrier's RP2350B page) and the Bosch datasheet
(BST-BNO055-DS000-18 rev 1.8).

**The part is still absent, and no firmware change makes an absent part
answer.** The entry below this one has the evidence: 0/50 ACK at both 0x28 and
0x29, both probe shapes, in the same sweep in which 0x40, 0x44, 0x45 and 0x76
all answer. That has not changed and is not a software question.

**But the driver written against that absent part had three defects, each of
which would keep a *fitted* one dead**, and they were invisible precisely
because there was nothing on the bus to expose them. All three come straight
out of the datasheet, which had not been read against the code.

**1. The address was one board's strap, written up as the part's address.**
`bno055.c` hardcoded `0x28`. Table 4-7 makes **0x29 the default** and 0x28 the
*alternative*, selected by pulling COM3 low; Table 4-6 gives COM3 a 20-60 kOhm
**internal pull-up to VDDIO**, so a COM3 left open - the common case on a
module - reads high and the part answers at 0x29. The 2026-08-31 survey found
a part at 0x28 and that address was then treated as a property of the BNO055.
A part fitted with COM3 open would have answered a bus scan at 0x29 all day
while the flight build never spoke to it, and at the HK bit that is
indistinguishable from no part at all. Both addresses are now tried and the
one that returns a whole ID block is latched - identity, not an ACK, as in
`ina226.c`, because 0x28 and 0x29 are ordinary addresses another part could
hold. `stand_down()` forgets the address again, so a reseated module on the
other strap is found by the next retry.

**2. There are two boot numbers and only one was honoured.** Table 0-2 gives
**TSup = 400 ms "From Off to configuration mode"** *and* TPOR = 650 ms "From
Reset to Config mode". The driver waited the 650 ms and ignored the 400 ms.
The IMU and the MCU share the 3V3 rail, so `hw_init()` runs while the BNO055
is still inside its own start-up: the `RST_SYS` write issued there went to a
part that could not acknowledge it, **no reset happened**, and the 650 ms
timer was then measured from an instant that meant nothing. The fix is a new
`ST_POWER_WAIT` that touches nothing at all until TSup has elapsed, after
which the reset is issued to a part awake enough to hear it and TPOR is timed
from there. `bno055_init()` consequently writes nothing and no longer returns
a bool - there was no hardware verdict to give at that point, and returning
one invited it to be read as evidence.

**3. The configuration writes landed inside the 19 ms the part needs to reach
CONFIGMODE.** Table 3-6: 7 ms CONFIGMODE -> operation mode, **19 ms the other
way**, and section 3.3.1 says only `OPR_MODE` and the interrupt registers are
writable outside CONFIGMODE. The old `configure()` wrote `OPR_MODE = CONFIG`
and then `PWR_MODE`, `SYS_TRIGGER` and `UNIT_SEL` back to back, inside that
window, where the part ACKs them on the wire and drops them. This only bites
on the re-reset path (after a reset the part is already in CONFIGMODE), which
is exactly the path that runs after a bus glitch in flight. The `OPR_MODE`
read-back would have caught the result and called it a failed part. Split into
`enter_config()` and `configure()` across a new `ST_CONFIG_WAIT`.

Bring-up is now five 1 Hz sweeps to a first sample - power wait, boot wait,
config wait, mode wait, run - and still never sleeps, so the 2 s watchdog
(S.9) is untouched. The I2C timeout went 4 ms -> 10 ms because section 4.6
says **the BNO055 uses clock stretching**, alone among the parts on this bus;
worst case is six transfers a sweep, 60 ms.

**A way to tell "not fitted" from "fitted but silent", which is the actual open
question.** The schematic has **`BNO_INT` on GP27** - the IMU is in the
design and wired to the MCU, whatever is or is not soldered today. INT is a
push-pull output idling low (Table 5-1 pin 14), so `bno055_probe.c` now samples
GP27 as a plain SIO input with each pull in turn, before it touches the bus:
driven low means something is present and powered, which no absent part can
fake; floating means not fitted, unpowered, **or held in reset**, so a high
reading narrows the fault without closing it. Printed as `pu=? pd=?` with that
caveat in the output, because `pu=1 pd=0` has already been mistaken for
"nothing attached" once on this board (GP17/GP18, which drive the motor).

**The schematic also settles four things that were open, and opens one.**

| Net | Pin | Against the firmware |
|---|---|---|
| `SDA_0` / `SCL_0` | GP28 / GP29 | confirms the measurement |
| `ACT_HB_IN1` / `IN2` | GP17 / GP18 | confirms the dispersion motor, and names it an H-bridge |
| `ACT_R_1` | GP26 | confirms the membrane |
| `SPI_1_CS2` / `CS3` | GP12 / GP13 | not the i2c0 the old map claimed |
| `SPI_0` + SD | GP4/6/7, CS GP14/GP16, sense GP5/GP15 | **M-11's pinout, which was the blocker** |
| `PI_RTS` / `PI_CTS` | GP2 / GP3 | **`PIN_PINCH_1` / `PIN_PINCH_2`** |
| `SPI_0_MISO` .. `MOSI` | GP4..GP7 | **`PIN_EQ1/2_OPEN/CLOSE`** |

The last two are serious and are **not** fixed here. Firing a pinch valve
today toggles a Pi UART flow-control line; driving an equalisation valve
toggles the SD bus. The board's actuator channels are `ACT_R_1..4`
(GP26/25/24/23), the `ACT_EC` driver (GP19..GP22) and the `ACT_HB` bridge
(GP17/GP18/GP46) - but this page names *channels, not loads*: it does not say
which relay holds pinch 1 or which holds an equalisation valve. Guessing that
is how an actuator ends up driven from the wrong pin, which is the failure
`board.h` already carries at the top. They need the load side of the
schematic, or a measurement in the manner of 2026-08-31, and until then the
wrong numbers stay in place with the contradiction written next to them rather
than being replaced by better-looking guesses. M-11 stays blocked for the same
reason: GP4..GP7 cannot be both SPI_0 and the valve pins, and an `spi_init()`
would drive whatever the valve code thinks it owns.

**The carrier is an RP2350B** (80-pin, GP0..GP47); the build is
`-DPICO_BOARD=pico2`, i.e. RP2350A with 30 GPIOs. Nothing in use today is
above GP29 so nothing is broken, but both debug lines, all four INA226 alert
pins, the 24 V regulator enable and power-good, five ADC channels and the
H-bridge current sense are unreachable from this firmware. The full net table
is in `board.h`.

**Checks.** `cmake --build flight/mcu/build` clean for both targets
(`clouds_fsw_mcu`, `bno055_probe`), no warnings; `run_native.sh` 56/56;
`pytest` 246 passed; `verify.py` and `verify_qt.py` both `VERIFY OK`.

**Run on the carrier** (`21DD2AE08840C863`; `picotool info` reports
`package: QFN80`, which confirms the schematic's RP2350B independently of the
drawing). The board was carrying a `clouds_fsw_mcu` built 2026-08-31 - before
the driver existed at all.

*The probe, 175 s of USB CDC:*

```
-- watching i2c0 for 120 s (reseat/repower now) --
t=  0 s: 0x40 0x44 0x45 0x76   (no IMU)

-- is a part fitted at all? --
BNO_INT (GP27): pu=1 pd=0 -> floating: NOT FITTED, unpowered, or held in reset
i2c0 read-probe : 0x40 0x44 0x45 0x76
i2c0 write-probe: 0x40 0x44 0x45 0x76
0x28: 0/50 read-ACK, 0/50 write-ACK
0x29: 0/50 read-ACK, 0/50 write-ACK
no CHIP_ID 0xA0 at either 0x29 or 0x28
```

The address set never changed once across the full 120 s watch, so this is a
**stable** absence and not an intermittent part. The ID block reads `00` at all
eight points across the boot curve with the transfer itself failing (`[-1]` =
address-phase NACK), which is the signature of nothing answering - distinct
from the 2026-08-31 reading, where the transfers *succeeded* and returned
`A0 00 00 00`.

**What this does and does not establish.** It establishes that no BNO055
answers I2C on i2c0. It rules out a bus fault (four parts answer in the same
sweep), a scan artefact (both probe shapes, 50 attempts each, stable over
120 s), and the HID-I2C strap (PS0 high would put the part at `0x40`, where a
device answers with INA226 mfg `0x5449` and die `0x2260` - so that is the
current monitor and not a mis-strapped IMU). It does **not** distinguish, and
nothing reachable from the MCU can: no part fitted; VDD or VDDIO absent;
nRESET (pin 11) held low; nBOOT_LOAD_PIN (pin 4) low, which boots the part
into its bootloader; or PS1/PS0 (pins 5/6) strapped to UART rather than the
`0b00` that selects I2C. The UART strap in particular would leave a perfectly
healthy part invisible here and not disturb the bus, since a UART-mode BNO055
transmits only when addressed and idles high, like the I2C bus itself. The
datasheet is explicit that PS1/PS0 may not be left floating (4.5).

**Closing it needs a meter on the board, not more firmware:** is a part on the
footprint at all; VDD 2.4-3.6 V and VDDIO 1.7-3.6 V at its pins (Table 0-1);
nRESET and nBOOT_LOAD_PIN both high; PS1 and PS0 both at GNDIO and neither
floating; COM0/COM1 (pins 20/19) continuous to GP28/GP29. COM3 (pin 17) then
says which address to expect - open or high is `0x29`, and the driver now
handles either.

**GP27 reads `pu=1 pd=0` - and that is worth nothing, which took a second
reading of the datasheet to establish.** It was written up here first as the
decisive presence test, on the reasoning that BNO_INT is the sensor's *output*
and so a powered part would hold it low - the asymmetry that was supposed to
make it admissible where the GP16/17/18 survey's identical `pu=1 pd=0` was
not. **That reasoning is unsourced and the datasheet contradicts its premise.**
`INT_EN` and `INT_MSK` both reset to `0x00` (4.4.8/4.4.9), every interrupt
disabled, and neither the driver nor the probe writes them; 3.8.1 says only
that INT "is set to high" once an interrupt occurs, and gives **no idle level
and no output stage** for the pin. A healthy, powered, correctly strapped
BNO055 sitting in ACCGYRO with no interrupt enabled may leave GP27 undriven,
reading exactly as it does now.

So the useful form of the test is one-sided: a pin found actively **driven**,
either way, proves something is there; a pin that follows its pull proves
nothing and is what a working part may well give. The probe now prints it that
way and `board.h` says so. **This is the third time on this board that an
instrument produced its own finding** (the `GPIO_FUNC_I2C` phantom stuck SCL,
the `0xFE`/`0xFF` reads that caused the `SYS_ERR 0x05` they were then read as
evidence of), and the first where the bad inference was this log's.

*The flight firmware, 120 s of live downlink* (MCU -> Pi -> UDP 4000 on
`192.168.100.1`), which is what proves the rewritten state machine is safe to
fly with no part present:

```
hk #  1 uptime=  163s accel=(0,0,0) gyro=(0,0,0) err=IMU_FAIL NO_TEMP
hk #105 uptime=  268s accel=(0,0,0) gyro=(0,0,0) err=IMU_FAIL NO_TEMP
frame types seen: {HK: 119, QUICKLOOK: 239, PISTATUS: 12}
HK packets: 119 over 120 s
uptime 163 -> 282 s (delta 119 over 120 s elapsed)
last rails: (19990, 65535, 5092, 3298)
```

- **119 HK in 120 s, and uptime advances 119 s over 120 s elapsed.** No drop,
  so no watchdog reset (S.9) across ~2 minutes in which the 30 s retry fired
  four times, each running the full `ST_POWER_WAIT` -> `ST_BOOT_WAIT` ->
  `stand_down()` cycle. The extra states and the 10 ms timeout cost the 1 Hz
  sweep nothing measurable.
- `IMU_FAIL NO_TEMP` throughout, vectors flat zero: the flag reaches ground and
  no number is invented for a part that is not there.
- Nothing else on the bus is disturbed by the wider timeout or the extra
  transfers - V_in 19.99 V (the bench is still on the 20 V supply), 5 V
  5.092 V, 3.3 V 3.298 V, the unfitted 24 V monitor `65535` =
  `RAIL_MV_INVALID` with no `RAIL_FAIL` raised against it, and no
  `BME280_FAIL`.

**Still untested: the success path.** `identify()` -> `enter_config()` ->
`configure()` -> samples has never run against real silicon, because there is
none to run it against. All three fixes above are read off the datasheet and
verified only in that they compile, do not disturb the bus, and fail in the
documented direction. When a part is fitted, flash the probe first - it now
answers whether anything is on GP27 at all, which strap, which die, which
clock and which mode in one pass - and only then judge the driver.

---

## 2026-09-11 - The BNO055 has a driver, and the part is no longer on the bus (M-09)

**What was asked.** "The BNO055 sensors are not working, fix this."

**What was actually there.** No driver. `flight/mcu/src/hw/` had `bme280.c` and
`ina226.c` and nothing for the IMU; `hw_read_sensors()` set `HKE_IMU_FAIL`
unconditionally and zeroed `accel_mg` / `gyro_ddps` on every packet. So the
sensors were not failing - nothing had ever asked them for a reading. The 2026-08-31
survey's verdict ("fitted, talking, sub-sensor dies dead") had been written
straight into the firmware as a constant.

**Why that verdict does not hold.** The survey read `CHIP_ID` = `0xA0`,
`SW_REV` = `0x0311`, `BL_REV` = `0x15` - all correct - and `ACC_ID` / `MAG_ID` /
`GYR_ID` = `0x00` where a working part gives `0xFB` / `0x32` / `0x0F`, and
concluded the fault sits between the BNO055's M0 and its three sensor dies.
The split is real but it has a second explanation the probe could not rule out:
**the BNO055 needs 650 ms from power-on reset before it is configured**
(datasheet 3.3), the probe ran from a Pico that boots in milliseconds, and the
three constants that read correctly are exactly the ones its ROM and bootloader
serve immediately, while the three that read `0x00` are the ones the boot
sequence writes when it brings the accel, mag and gyro dies up. `OPR_MODE` also
read `0x10`, outside its valid `0x00`-`0x0C` range and unexplained at the time -
which is what an un-booted register file looks like, and not what a booted part
in CONFIGMODE (`0x00`) looks like. Reading the ID block at t=0 cannot tell a
dead die from an un-booted one. This is the same class of error as the
`GPIO_FUNC_I2C` stuck-SCL and the self-inflicted `SYS_ERR 0x05` in the entry
below: the instrument produced the finding.

**What was built.** `hw/bno055.c` + `.h`, a non-blocking driver whose whole
shape is that timing argument:

- `bno055_init()` issues `SYS_TRIGGER` `RST_SYS` and arms a 750 ms timer. It
  does not wait - the part NACKs partway through its own reset, so that write's
  return value says nothing and is ignored.
- The bring-up runs from `hw_read_sensors()` at 1 Hz, not from `hw_init()`.
  Two reasons: nothing in the hardware layer may sleep (S.9, 2 s watchdog), and
  a bring-up that lives in the sweep can also recover a part that drops out in
  flight.
- Only after the full boot does it read the ID block and require `CHIP_ID`,
  `ACC_ID` and `GYR_ID`. `MAG_ID` is read but not required: nothing here uses
  the magnetometer, and refusing to deliver acceleration over a sensor no one
  reads would be its own invented failure.
- Mode is **ACCGYRO (`0x05`)**, non-fusion. `hk_t` carries acceleration and
  angular rate and nothing else; every fusion mode needs a magnetometer
  calibration this flight has no opportunity to perform, next to a dispersion
  motor, and launch/float detection wants acceleration, not attitude.
- `SYS_TRIGGER` is explicitly written `0x00` after the reset, i.e. **internal
  oscillator**. A missing or non-oscillating 32.768 kHz crystal with `CLK_SEL`
  asserted is the classic cause of this exact signature, and the carrier's
  crystal is unconfirmed - so the driver never asserts it.
- `OPR_MODE` is **read back** before the first sample is believed. A part whose
  dies never came up can accept the write and sit in CONFIGMODE, where the data
  registers are all zero - precisely the reading that must never be passed off
  as a measurement.
- Nothing reads above `0x3F`. The page-0 map ends at `0x6A`, and the earlier
  probe's `0xFE`/`0xFF` reads are what provoked the `SYS_ERR 0x05` it then
  read back as evidence.
- Failure handling: one failed transfer is a bus glitch, three consecutive ones
  force a re-reset, and a part that fails bring-up is retried every 30 s. An IMU
  is not on the release path (S.7, MS002), so hammering a wedged device every
  second buys nothing and costs bus time.

**What did not change, on purpose.** If the dies really are dead, the ID check
fails, `HKE_IMU_FAIL` is raised exactly as before and the vectors stay zero.
No number is invented either way. What changed is that the flag now reports a
measurement taken at a time when the answer means something, instead of a
constant compiled into the firmware.

**Units, and a bug the dead IMU was hiding.** `UNIT_SEL` bit 0 selects mg, so
`accel_mg` is a copy rather than a conversion. The gyro has no deci-dps unit:
the part gives 16 LSB/dps and the wire field is deci-dps, so it is `x5/8` in
32-bit (the numerator reaches 160 000 at the +-2000 dps full scale). On the
ground, **both the Sensors row and the timeline plotted `gyro_ddps` raw and
labelled it `dps`** - a rate ten times the real one, which nothing on screen
would have contradicted. Nobody noticed because the field was always zero.
Fixed in `clouds_ui/flight.py` and `clouds_ui/timeline.py`.

**Verified on the carrier, and the answer is not the one the hypothesis
predicted: the BNO055 does not answer at all any more.** Flashed to the
carrier (`21DD2AE08840C863`) with the bench chain live - MCU -> Pi -> ground,
HK landing in `gse_sessions/`. `HKE_IMU_FAIL` stayed set through the whole run.
So a register-level probe was built to say *which* step failed, since one HK
bit cannot: `src/tools/bno055_probe.c`, a bench-only target behind
`-DCLOUDS_BUILD_TOOLS=ON`, printing over USB CDC (never UART - those are the
downlink's pins).

```
i2c0 read-probe : 0x40 0x44 0x45 0x76
i2c0 write-probe: 0x40 0x44 0x45 0x76
0x28: 0/50 read-ACK, 0/50 write-ACK
0x29: 0/50 read-ACK, 0/50 write-ACK
```

Every register read returns the address-phase NACK, at both BNO055 addresses,
under both probe shapes, 50 attempts each - **in the same sweep in which the
three INA226 and the BME280 all answer**. That rules the instrument out the way
this project has had to learn to: the bus works, the pull-ups work, the scan
works, and nothing is at 0x28.

**So the part is electrically absent from i2c0, which is a different fault from
the one on record.** On 2026-08-31 it answered with `CHIP_ID` = `0xA0`,
`SW_REV` = `0x0311` and `BL_REV` = `0x15`; today it does not acknowledge its
own address. The board changed between those two dates - unpopulated, on a
module that is not currently mated, or lost its supply - and that is a
hardware question, not a firmware one. The boot-timing hypothesis is therefore
**neither confirmed nor refuted**: it cannot be tested against a part that is
not on the bus. It stays the first thing to re-test when one is, because the
probe now reads the ID block at eight points across the boot and would show the
sub-IDs filling in.

**What the hardware run does prove**, which is the absent-part path end to end:

- HK keeps flowing at 1 Hz with the new driver in it; uptime runs 0 -> 44 s
  and 0 -> 16 s across two boots with no gap and no reset, so the bring-up,
  its 750 ms timer and the 30 s retry never push the sweep into the 2 s
  watchdog (S.9).
- `error_flags` reads `IMU_FAIL NO_TEMP` and the vectors stay `0, 0, 0` - the
  flag reaches ground correctly and no number is invented for a part that is
  not there.
- Nothing else on the bus is disturbed: `V_in 19.99 V 0.20 A`, `5 V 5.09 V
  0.73 A`, `3.3 V 3.30 V 0.04 A`, no `BME280_FAIL`, link `GND PI` up.

**Untested: the success path.** `identify()` -> `configure()` -> samples has
never run against a real BNO055. When a part is fitted, flash the probe first -
it answers which die, which clock and which mode in one pass - and only then
judge the driver.

**V_in reads 19.99 V, not the 24.06 V of 2026-09-09, because the bench is
temporarily on a 20 V supply.** Recorded so a later reader of this session does
not chase it as a rail sag. It does not bear on the missing IMU: the 5 V and
3.3 V rails read nominal (5.09 / 3.30 V) throughout.

---

## 2026-09-11 - The dark frame survives a restart (P-04)

**What was asked.** Capture a dark frame now and make it the GUI's default, so
a restart does not mean re-taking it; still changeable later.

**Why a dark is worth persisting here.** The pedestal on this unit is huge.
The inter-channel gap (px 236-1515) is covered - it cannot see light - and it
reads **~24 000 ct at 10 ms**, 37 % of the 65520 full scale. Every count above
that is signal, so the dark is not a refinement; without it the numbers mean
nothing. And capturing one needs a darkened bench, which is a physical
errand - exactly the kind of work a default should not make the operator redo
on every start.

**What is stored, and why each field is on the wire.** `spectro/dark.py`
writes `dark_frame.npz` (numpy, `allow_pickle=False`, beside
`calibration.json`; `CLOUDS_DARK` moves it; `.gitignore`d, because it is
instrument state that one button press regenerates). With the counts go
`exposure_us`, `navg`, `clean`, `captured_t`, `model`, `serial`, `source`. Two
of those are guards, not metadata:

- **The exposure.** Dark current scales with integration time, so a 10 ms dark
  subtracted off a 200 ms frame removes the wrong pedestal - and the result
  still looks like a spectrum, which is what makes it dangerous. A restored
  dark brings its exposure back with it, and the auto-integration servo is
  switched **off** on restore, because a servo that moves the exposure would
  invalidate the restored dark within a frame or two. Those three are one
  setting. Change the exposure and the subtraction is withheld - not silently,
  the Dark frame section reads `held back: dark is 10 ms, exposure is 250 ms`.
- **The pixel count.** A stored frame that is not this detector's length is a
  different instrument and raises `DarkError` rather than being broadcast onto
  the wrong geometry.

`Capture dark` persists on the spot rather than behind a second "save" click -
the expensive half (a dark bench) is already paid for. `Clear` drops the frame
**and deletes the file**: leaving it would resurrect a dark the operator just
dropped on the next start, which is the one thing a default must never do.

**Captured on hardware, and it is honest about being imperfect.** Taken
through the UI's own `_capture_dark` over the cable (`--net`, 16 frames, clean,
10 ms) off `e9u_LSMD-TCD1304-PRO` S/N 20260312-004: measurement 25 399 ct mean,
reference 31 038, covered gap 24 142. So Ch1 sits at the gap - a clean pedestal
- while **Ch2 is ~6.9 k above it**, i.e. light was still on that fibre. That
is a real defect of this particular capture, not of the mechanism: subtracting
it over-corrects Ch2 and inflates transmission. Retaking it with the fibre
blocked is one button press and overwrites the default. Recorded here because
a dark taken in light is invisible downstream - nothing in the trace says so.

**One thing the change had to be careful about.** `verify_qt.py` and
`qc_live.py` both call `_capture_dark`, which now writes the operator's
default. Both now point `CLOUDS_DARK` at a scratch file under `output/`: a QC
run that replaced the bench's working dark would be a nasty way to learn that
capture persists.

**Evidence.** 233 tests pass (11 new in `tests/test_dark_frame.py` - roundtrip,
wrong-detector refusal, unreadable file, exposure tolerance, env override);
`verify_qt.py` adds 10 checks covering store, restore, servo-off, withholding
at another exposure, and `Clear` removing the file, and still ends `VERIFY OK`;
a bare `./run_clouds_ui.sh` on this Mac comes up with the stored dark loaded,
subtraction on, exposure 10 ms.

---

## 2026-09-11 - The operator interface lost `--mock` and `--edu` (P-01)

> **Superseded in part on 2026-09-16** (top of this file): `--mock` is back,
> for demo and training away from the one Duo and the one Pi. The reasoning
> below stands and is what the new flag is built against - it is labelled in
> the title bar, the source banner and the device line, and it cannot write
> the shared dark frame. `--edu` is still gone.

**What was asked.** Remove the mock version and the `--edu` board from the
operator interface, so connecting to the spectrometer is the direct path.

**Why the flag was worth removing, not just hiding.** `clouds_ui --mock`
draws a synthetic spectrum in the same window, the same plot, the same stats
card as the real detector. The window already carries one guard of this class -
the source banner and the `LIVE` / `QUICK-LOOK` badge exist because reading a
binned 1 Hz quick-look as a live instrument view is a mistake that costs a
measurement - and a synthetic trace is the same mistake one step further: the
`[MOCK]` tag in the identity line is the only thing separating invented light
from real light. On a bench where the operator interface is the instrument,
that flag has no job that the checks do not already do better.

**The mock driver itself stays.** `open_driver(mock=True)` is what makes 226
tests, `verify.py`, `verify_qt.py` and `clouds_fsw.main --mock` runnable with
no hardware attached, and `CloudsWindow(mock=True)` is how `verify_qt.py`
exercises the real widget tree offscreen. So the removal is of the *command
line*, not of the capability: nothing in `spectro/mock_driver.py` changed, and
the UI's `mock=` keyword survives with a docstring saying it has no CLI route.
Deleting `MockDriver` outright would have left the repo with no hardware-free
check at all - a much worse trade than the one it was meant to buy.

**The EDU board went entirely.** `spectro/eureca_edu_driver.py`,
`calibration_edu.json`, `tests/test_calibration_edu.py`, the `"edu"` kind and
its per-kind default calibration in `clouds_ui/window.py` are deleted. The
board was a single-fibre 3648-px unit whose vendored SDK ships a Windows
backend and no Linux source (DEVLOG 2026-07-31), so it could never run on the
Pi and was never a flight path; what it cost was a second pixel geometry in
the shared instrument layer, including a `_CAL_BY_KIND` indirection that now
collapses to `Calibration.load()`. The vendor SDK stays under
`drivers/e9u_LSMD_EDU_LIB/` for reference, loaded by nothing.

**A retired kind must fail, not fall back.** `KINDS` is `("std", "net")` and
`resolve_kind("edu")` raises. That matters for a stale
`CLOUDS_SPECTRO_KIND=edu` in a shell profile or a `spectro_kind` left in an
FSW config: falling back to the Duo would slice Ch1 `[0, 235]` and Ch2
`[1516, 1766]` out of a detector that has neither, and report transmission
against noise. `tests/test_driver_factory.py` now asserts the rejection, and
`FswConfig.load` still validates the kind at load rather than at first
connect.

**A bare run now finds the detector on macOS.** With `--mock` gone, a
flagless `./run_clouds_ui.sh` on this Mac opened `kind="std"` - a local USB
Duo - and EURECA ships a Windows DLL and a Linux `.so` and nothing else, so
that open cannot succeed on the platform at all. It failed into the 3 s
reconnect loop, which reads as a broken app rather than as the wrong machine.
The detector is on the Pi here (cable, `--bench-stream` on port 4010), so
`--net` now **defaults** to the bench Pi on `sys.platform == "darwin"` and to
nothing (this machine) everywhere else; `CLOUDS_SPECTRO_HOST` moves it,
`--net HOST` overrides it, `--flight` opens no detector. The default lives in
`clouds_ui/main.py`, not in the launcher, because it follows from a platform
fact rather than from one operator's habit - and `run_clouds_ui.sh` stays a
wrapper that invents nothing. The macOS `DriverError` also stopped advising
`--mock`, a flag that no longer exists, and names the working route instead.
Proven on hardware: a bare run holds `192.168.100.1:->192.168.100.10:4010`
and `:4001`, with real frames off `e9u_LSMD-TCD1304-PRO` S/N 20260312-004.

**Evidence.** `python -m pytest tests/` 225 passed (the EDU calibration file's
own suite is gone with the file); `python verify.py` and `python -u
verify_qt.py` both end `VERIFY OK`, the latter with the kind checks replaced
by "the retired EDU board is refused, not silently the Duo".

---

## 2026-09-09 - V_in is not the 24 V rail, and the shunt values were wrong (M-09, G-01)

**What was asked.** Rename the monitored 24 V rail to `V_in`, leave a
placeholder for the real 24 V rail, which has no monitor fitted yet, and
correct the shunt resistances to **V_in 10 mΩ, 24 V 15 mΩ, 5 V 10 mΩ,
3.3 V 50 mΩ**.

**The 0x40 monitor was never on the 24 V rail.** It sits on `V_in`, the
incoming gondola bus. The two are different nets, and the panel had been
naming one after the other since M-09 - which is the same class of mistake as
a field with no part behind it: the number is real, the label says it belongs
to something else.

**The placeholder is on the wire, not only on the panel.** `rail_mv[]` and
`shunt_raw[]` grew to four entries and HK went 50 B → **54 B** (framed 70 B
against the 83 B allowance, payload ceiling 67 B, so the 1 Hz quick-look is
untouched). The alternative - a UI-only row - means the wire format changes on
the day the part is fitted, across the MCU, the Pi, the GSE and every session
already logged. Four bytes now is the cheaper of the two.

**An unfitted part is not a failure.** The 24 V slot downlinks
`RAIL_MV_INVALID`, but `ina226_fitted()` keeps it out of `HKE_RAIL_FAIL`: a
flag set on every packet from now to launch is a flag nobody reads. The panel
renders that rail as `not fitted`, distinct from `no monitor` (a part that
should have answered and did not) and from `0.00 V` (a rail that is genuinely
down). Three states, three different faults to chase.

**The old shunt values make the earlier power numbers wrong.** The
2026-09-09 rail-current entry below, and the power table in it, were derived
with 10 / 10 / 15 mΩ. The 3.3 V rail is 50 mΩ, so its currents there are
**3.33× too high**; V_in and 5 V are unchanged. This is exactly why the
firmware sends the raw shunt register and not amps - the logged
`shunt_raw` re-derives cleanly, which a firmware-computed amp value could
not. The table has been left as it was recorded; re-derive from the logs
rather than trusting its 3.3 V column.

**Checks.** `226 passed`, `VERIFY OK` (the rail checks now cover `V_in`, the
`not fitted` row, and a 50 mΩ 3.3 V current), and the firmware core's
`56 tests, 0 failures` with the HK layout pinned at the new offsets -
`rail_mv[]` at 30, `shunt_raw[]` at 38, `mission_t_s` at 50.

---

## 2026-09-09 - Rail current, and the Keller pair leaves the packet (M-09, G-01, M-15)

**What was asked.** Drop the two Keller 23SY sensors, and show current as well
as voltage for the three INA226 monitors.

**What the Keller removal actually costs.** The pair was the only source for
`p_ch_pa` (chamber pressure) and `rh2_cpct` (chamber humidity), and both were
still in the 50-byte HK packet, flagged `NO_CHAMBER_P` / `NO_RH2` and rendered
as `not fitted` rows on the panel. Two requirements lean on them: SED F.6 wants
humidity in two locations, and M-15 verifies the chamber seal from a
chamber-vs-ambient pressure divergence. Neither had a part any more, so both
were being kept alive by a wire field nothing could fill.

The fields went with the parts. A field that can only ever hold a zero is read
as a measurement by everything downstream - it is the same failure this project
has already been bitten by twice, one step earlier in the chain: `p_ch_pa` was
deliberately mirroring ambient so a future M-15 would err towards "not sealed",
which on a display is exactly what an intact seal looks like. `seq_step()` lost
its `p_ch_pa` parameter too (it was already `(void)`-cast unused): a parameter
no sensor can source invites a caller to pass something plausible. M-15 is now
`☐ needs a sensor` in SOFTWARE_FEATURES rather than `◐` - the retry-and-flag
logic around the check is written and tested, the reading is what is missing.

**Where the amps come from.** The INA226 has a current register, and it is the
wrong one to use. The part computes it from a calibration register that has to
be programmed with the shunt resistance; a wrong value there produces
confident, wrong amps that nothing on the ground can undo afterwards. The
shunt-voltage register next to it is absolute - 2.5 uV/LSB, signed, no
calibration involved - so that is what is downlinked, raw, and Ohm's law is
applied on the ground where the resistances live
(`clouds_link/hk.py RAIL_SHUNT_MOHM = 10, 10, 15 mOhm`, measured shunts for the
24 V, 5 V and 3.3 V rails). If one of those numbers turns out wrong, a logged
session can be re-derived from `shunt_raw`; an amp value computed in firmware
could not be.

**The packet did not grow.** `shunt_raw[3]` is i16 x 3 = 6 B, exactly what
`p_ch_pa` + `rh2_cpct` gave back, so `hk.SIZE` is still 50 B and the downlink
budget is untouched at 1.862 of 2.0 kbit/s. That is luck, not design, but it is
the reason this change needed no cadence argument. The retired `HKE_*` bits 2
and 3 were left unused rather than compacted, so an older session log still
decodes and `error_text` shows anything unknown as a mask.

**A rail is read as a pair.** Bus voltage and shunt voltage come from the same
part over the same bus microseconds apart, so `hw_read_sensors()` requires both
to succeed: on any failure the rail is `RAIL_MV_INVALID` with `shunt_raw` 0 and
`HKE_RAIL_FAIL` set. A shunt reading kept next to an invalid voltage would be a
current for a rail whose voltage is unknown, and the panel has no way to say
that. Same reasoning as the existing sentinel: `0.000 A` is what an *idle* rail
reads, so a dead monitor must not produce one.

**On screen.** Each rail row is now `24.06 V   -0.129 A`, right-aligned in
fixed width - the rows render in the monospaced face, so the three rails read
as a column instead of three differently indented sentences. The sign is
printed as it comes: a negative current means the rail is sourcing back into
its supply, and hiding it hides that. Under the section is
`current derived: shunt voltage over 10, 10, 15 mΩ`, because the shunts are the
one number in that reading that was not measured - if one is wrong, every amp
on the panel is wrong with it, and an operator has to be able to see which
assumption to doubt.

**Evidence.** 226 pytest, 56 native firmware tests, `verify_qt.py`
`VERIFY OK` with four new rail checks: a live rail shows volts and amps, a
rail that is genuinely down still reads `0.00 V   +0.000 A`, an unmonitored one
reads `no monitor`, and a negative current keeps its sign.

**On the carrier.** Flashed to `21DD2AE08840C863`, relayed by the bench Pi,
30 consecutive HK packets decoded on the ground in `STANDBY`
(`error_flags` = `IMU_FAIL NO_TEMP` - the two Keller bits are gone, as
intended):

| Rail | Bus | Current | min..max | sd | Power |
|---|---|---|---|---|---|
| 24 V | 24.063 V | 0.173 A | 0.170..0.177 | 1.8 mA | 4.16 W |
| 5 V | 5.095 V | 0.737 A | 0.731..0.755 | 5.7 mA | 3.75 W |
| 3.3 V | 3.297 V | 0.134 A | 0.133..0.135 | 0.4 mA | 0.44 W |

Quiet and stable - 0.4 to 5.7 mA of spread over 30 s, against a quantisation
of 0.25 mA (10 mOhm) and 0.17 mA (15 mOhm), so the numbers are resolution-
limited rather than noisy.

**The apparent over-unity was my arithmetic, and the rails answered it.**
5 V + 3.3 V is 4.20 W against 4.16 W on the 24 V bus, which is impossible if
all three are parallel loads on that bus - so they are not. Two measurements
on the live packets settle the topology, without a meter:

- **The 5 V rail is fed from the 24 V bus.** Over 60 samples the two currents
  correlate at **+0.96**, and a least-squares fit gives
  `dI24/dI5 = 0.2101` against `V5/V24 = 0.2117` - a marginal efficiency of
  ~100 %, i.e. the slope is what a step in 5 V load *must* produce on the
  24 V side. A rail fed from somewhere else (the USB cable this was flashed
  over, say) could not track like that.
- **The 3.3 V rail hangs off the 5 V rail, not the bus.** Its current is flat
  to 0.39 mA sd and uncorrelated with either (-0.04 against 24 V), and its
  0.44 W is therefore *already inside* the 5 V figure rather than additive.
  Which makes the chain 24 V -> 5 V -> 3.3 V at **90 % total efficiency** -
  a real converter number, where the additive reading gave 101 %.

So the shunt values are consistent with the hardware: the slope pins the
*ratio* of the 24 V and 5 V shunts to within ~1 %, and the resulting
efficiency is physical. What it cannot see is a **common scale error** - both
being 12 mOhm rather than 10 would shift every current by 20 % and leave
every relationship above intact. That is the one thing still worth a bench
meter, and it is cheap to fix after the fact: `shunt_raw` is logged raw, so a
corrected resistance re-derives the sessions already recorded.

**The actuators are not on these rails.** A load step - `MEMBRANE 60 % @
2 Hz`, `OK`, `membrane_duty` reading back 60 for nine packets - moved no rail
by more than the noise (24 V -0.2 mA, 5 V -2.8 mA, 3.3 V -0.2 mA). The
membrane solenoid draws through its own inverter stage, as the dispersion
motor does, so the three monitors watch the avionics and **not** the
actuators. Worth knowing before anyone reads a flat 24 V current as evidence
that a valve did not fire - `valve_status` is what says that, and it is why
that field exists.

---

## 2026-09-09 (earlier) - The rail voltages are in housekeeping (M-09, G-01)

**What was there.** Three INA226 monitors on i2c0 - `0x40` 24 V, `0x44` 5 V,
`0x45` 3.3 V - measured during the August bring-up and then left alone,
because `hk_t` had no field for them. `hw.c` said so in a comment: "no field
in hk_t (HK is 44 B against a 67 B ceiling), so not sampled here." Ground
therefore never saw a bus voltage, on a mission whose largest measured
power-tree surprise so far was an INA226 reporting the 24 V bus at 6046 mV
that was not real.

**Bus voltage only, and that is a decision.** The bus-voltage register is
absolute: 1.25 mV/LSB, no calibration needed. Current and power are not - the
part computes them from its calibration register, which must be programmed
with the shunt resistance, and the shunt value is on the carrier schematic
that M-11 is still blocked on. A guessed shunt yields confident wrong amps,
which is the exact failure this log already records twice. When the schematic
lands, the honest addition is the shunt-voltage register (also absolute,
2.5 uV/LSB, and i16 exactly) so the conversion happens on the ground where
the resistance is known.

**The sentinel is the interesting part.** `rail_mv[i] == RAIL_MV_INVALID`
(`0xFFFF`) means no reading, and it is deliberately not 0, because **0 mV is a
legitimate measurement**: the 24 V bus reads 0 whenever the carrier runs from
USB with no supply attached. Collapsing "the monitor did not answer" and "the
rail is down" into one value would throw away the distinction ground most
needs when a rail looks wrong. 0xFFFF is 65.535 V, above the part's 36 V
input rating, so it cannot collide with a real reading. `HKE_RAIL_FAIL`
(bit 6) says *some* rail is unreadable - which one is in the field itself,
because `error_flags` is one byte and six bits were already spent.

Identity is checked before anything is believed: both the manufacturer
(`0x5449`) and die (`0x2260`) registers must match at init, not merely an ACK
at the expected address. Guessing parts from default addresses got four of
five wrong on this board.

**Budget.** `hk.SIZE` 44 -> 50 B, framed 66 B against the ~83 B the 2 kbit/s
continuous limit allows beside a 1 Hz quick-look. Total 1.862 kbit/s of 2.0,
margin 0.138. `TestDownlinkBudget` computes this from real encoded frames, so
it checked the growth rather than being told about it. The 67 B payload
ceiling now has 17 B of headroom, not 23.

**Measured on the carrier**, first packets after the reflash:

```
HK len=50  rails: 24 V 24.06  5 V 5.09  3.3 V 3.30   raw=(24063, 5095, 3297)
err=NO_CHAMBER_P NO_RH2 IMU_FAIL NO_TEMP        <- no RAIL_FAIL: all three answered
```

All three plausible, stable across samples, and the 24 V figure agrees with
the 880-sample profile from August (23.9..24.0 V). Physical units that make
sense are the proof the part is real, per the rule this log set.

**In the panel.** One `Sensors` row per rail, named with its part and address
(`Rail 24 V / INA226 0x40`), so a failing rail is identifiable at a glance
rather than parsed out of one packed line. A rail with no monitor reads
`no monitor`; a rail genuinely at zero reads `0.00 V`. Three `verify_qt.py`
checks hold that apart, and one of them caught the fixture in the
"fully sourced packet" check that had no rails set and was therefore asserting
against the sentinel.

**Evidence.** 218 pytest (was 213), 56 native, `verify_qt.py` VERIFY OK,
clean `-Wall -Wextra` build, reflashed to carrier `21DD2AE08840C863`, and the
17-check merged-UI hardware pass re-run green after the schema change.

---

## 2026-09-09 (later still) - The sensor readings are on screen, and the ones with no sensor say so (G-01)

**What was wrong.** The panel showed `T1 / T2  0.0 / 0.0 C` and
`p chamber  992.6 hPa`, and displayed neither of the two things it should
have. `bme_temp_cc` - the **only working temperature on the carrier**, from
the BME280 that is the only usable sensor on i2c0 - was in the 44-byte packet
and had no row at all. Nor did `accel_mg`, `gyro_ddps` or `uptime_s`. So four
downlinked fields were invisible while two dead ones were rendered as
readings.

The chamber pressure is the sharper half. `hw_read_sensors()` sets
`p_ch_pa = p_amb_pa` on purpose, so that a future M-15 seal check reads
"not sealed" rather than the huge fake divergence a 0 would produce. That is
the right call in the firmware and the wrong number to put on a panel: a
chamber pressure equal to ambient is exactly what a real intact seal looks
like. The operator had `HKE_NO_CHAMBER_P` in the Errors row to cross-reference
against, which is not the same as not being misled.

**What it does now.** A `Sensors` section, one row per reading, each labelled
with the part that produces it - `Ambient T / BME280`, `Chamber p / Keller
23SY`, `T1 T2 / STLM20 x2`, `Accel / BNO055`. The part name is load-bearing:
it is what tells an operator which numbers to believe. Each row also carries
the `HkErrors` bit that means "no sensor behind this", and when it is set the
row says `not fitted` / `not populated` / `unusable` instead of a number. The
firmware's zero-fill is left alone; what changed is that a zero is no longer
dressed up as data.

`p_amb_pa` is the exception that proves the rule: it is *held* rather than
zeroed on a failed read, because 0 Pa mimics a 100 kPa fall and trips launch
detection. A held value is real data, just old, so it is shown - and labelled
`(held, stale)`.

**Live on the bench.** `Ambient p 992.5 hPa`, `Ambient T 34.2 C`,
`Ambient RH 30.0 %`, everything else declared unsourced. Note the 34.2 C: the
BME280 is on the carrier next to the RP2350 and the power tree, so it reads
board temperature, not cabin air - about 12 C above the room. Worth knowing
before it is used for anything but health.

**Still not shown, because it is not in the protocol.** The three INA226 rail
monitors (0x40 24 V, 0x44 5 V, 0x45 3.3 V) are live on i2c0 and have no field
in the 44-byte packet, so `hw_read_sensors()` never reads them and ground
never sees a bus voltage. Adding them is a schema change, not a UI one:
3 rails x (u16 mV + i16 mA) is 12 B, taking `hk.SIZE` from 44 B to 56 B, still
inside the 67 B ceiling the 1 Hz quick-look budget leaves. The panel says so
in the section rather than leaving it as an absence, because "where are the
bus voltages" is the first question the section invites.

**Evidence.** 213 pytest, 56 native, `verify_qt.py` VERIFY OK with five new
checks - that an unsourced row renders no digits, that the chamber row does
not echo ambient, that the BME280 numbers do appear, that a held pressure is
shown and marked, and that a fully sourced packet renders every row (so the
unsourced path cannot pass by blanking everything).

---

## 2026-09-09 (later) - One operator interface: the two GUIs are one window (G-01..G-04)

**Why.** There were two UIs and a documented warning telling you which to
open, because opening the wrong one "looks like a broken system": the bench
panel drove the detector directly at 2048 px, the GSE dashboard drew a 1 Hz
quick-look mean-binned to ~30 points per channel. The warning existed because
the two spectra are easy to mistake for each other, and a note in a README is
a weak defence against that. An operator on console also had to run two
applications to watch a trace and command the experiment.

**What the merge does and does not change.** The two data paths are still
completely separate and still enforced - the detector half talks only to
`spectro.driver`, the flight half only to `clouds_gse.Receiver` /
`Commander`, and neither file imports the other's. What changed is that they
share a window, and that the thing which actually differs is now a control
rather than a choice of program: `Spectrum source` is Detector or Downlink,
**explicit, and never switched by the app**. Auto-detecting it was the
tempting option and is the wrong one - a plot that silently becomes a
different measurement when a link drops is precisely the misreading the old
split was warning about. The plot carries a banner naming the source, its
rate and its binning ("DOWNLINK 1 Hz mean-binned 8x - not an instrument
view"), and the stats card says `LIVE` or `QUICK-LOOK`.

Reaching the detector from the ground was never possible in flight anyway: it
depends on the Pi's `--bench-stream`, which is off there. So `--flight` opens
no driver and starts on the downlink, and the instrument sections stay built
but folded - hiding them would quietly make the one UI two again.

**Layout.** `docs/UI_STYLE.md`'s spectrum + one 410 px sidebar, kept: the
sidebar now stacks Flight sections above Instrument ones and each is a
collapsible `Section` (`clouds_ui/sections.py`), so what fits on a laptop is
the two or three groups you are using. Folding is display only - a folded
housekeeping grid keeps updating, because "not on screen" must never mean
"not tracked". The old dashboard's stock-Qt widgets were restyled from one
palette (`clouds_ui/style.py`); it used to be a light OS-default sidebar
beside a dark plot, two half-themed halves in one window.

**Two bugs the merge exposed.**

The uniform-width fix for the command buttons, made earlier today, was wrong
in a way that only showed up in a narrower sidebar. Pinning all three grid
columns to the widest button's hint does produce equal widths - and 3 x
"ARM + RELEASE 1" is ~470 px inside a 410 px scroll area whose horizontal
scrollbar is off, so the far button was silently clipped and the rest of the
sidebar went off the visible edge with it (the Stop button and the frequency
spinbox too - one cause, three symptoms). Six columns with the short commands
spanning 2 and the release pair spanning 3 spreads a long label across
columns instead of widening one. `verify_qt.py` now asserts the sidebar is
not clipped, which is the assertion that would have caught it.

And the source banner quoted the bin factor, which does not exist until the
first quick-look arrives - so it said "waiting for a quick-look" forever. Its
own test caught that one.

**Retired.** `clouds_spectral.py` (moved to `clouds_ui/window.py`, history
preserved) and `clouds_gse.main --gui` (`gse/clouds_gse/app.py` deleted).
`clouds_gse` keeps everything that is not a window - receiver, commander,
session log, and the headless console REPL, which is still the right tool
with no display and is what `clouds_ui` imports. `run_clouds_spectral.bat`
keeps its filename so the desktop shortcut still works; it invokes
`-m clouds_ui` now.

**Evidence.**

```
python -m pytest tests/          213 passed
python -u verify_qt.py           VERIFY OK  (flight half + source switch)
flight/mcu/test/run_native.sh    56 tests, 0 failures
python -m clouds_ui --mock --no-link          bench: 48 mock frames, sections fold
python -m clouds_ui --flight --experiment ... against the real Pi + carrier
```

The hardware pass drove the real chain from the merged window: housekeeping
and named errors rendering, `MEMBRANE` 45 % accepted and read back in HK,
`DISPERSE` visible in `valve_status` for its 5 s, events named
`[INFO] MANUAL_DRIVE`, `RELEASE` refused on the pad with no dialog, and the
source switch leaving no stale downlink trace on the axis when moved to a
detector that is not connected.

**Worth noting.** The downlink quick-look clips flat at `saturation_count`
above ~640 nm on the bench (`exposure_us` 100 ms, `auto_exposure` false). The
old dashboard gave no sign of that; the merged stats card computes saturation
for the downlink too and now says `43.3 %  CLIPPING`, which is how the
clipping got noticed at all.

---

## 2026-09-09 (bench, after the actuator work) - The Pi <-> MCU link runs on real hardware, and naming things exposed two dead fields

**The link is proven.** Everything the 2026-08-31 entry listed as still owed
is now measured on the bench, with the RP2350 carrier
(`21DD2AE08840C863`) on GP0/GP1 and the Pi on GPIO14/15:

```
raw wire, HK decoded off /dev/ttyAMA0     state=STANDBY p_amb=992.5 hPa err=0x003c
GSE UDP 4000                              HK 1 Hz relayed, QUICKLOOK 2/s, PISTATUS, lost 0
HK link= field                            GND PI      (MCUF_PI_OK set by the 10 s TIMESYNC)
MEMBRANE 40 % -> 80 % -> off              ACK OK, HK membrane_duty follows each one
DISPERSE                                  ACK OK, valve_status = DISPERSE for ~5 s
ARM + RELEASE on the pad, flight mode on  ARM OK, RELEASE INTERLOCK (the Pi's enforcer)
FSW stopped 60 s (M-13)                   link= GND, MCUF_PI_OK cleared; GND PI again on restart
```

The two-enforcer interlock (S.10) is the one worth calling out: with the GSE's
own gate disabled the Pi still refused the release, because fresh HK said
`STANDBY`. Both ends answered for themselves, which is the whole point of the
ACK path.

**Getting there took a Pi that is not the Pi in the documents.** The bench
machine is a **Raspberry Pi 4 Model B Rev 1.2**; the SED and every README say
Pi 5. That is why `enable_uart=1` was not enough: it left
`/dev/serial0 -> ttyS0`, the mini-UART, with Bluetooth holding the PL011 and
no `/dev/ttyAMA0` in existence - a state where `uart_port` fails and the
service crash-loops while `config.txt` looks correct. `dtoverlay=disable-bt`
frees the PL011. Steps and the trap are in `CLAUDE.md`; the Pi-5 route
(`uart0-pi5`) is a different one, so this will need redoing on flight
hardware.

**Then the panel was read properly for the first time, and two fields turned
out to carry nothing.**

`error_flags` was rendered as `0x003c`. It is now `NO_CHAMBER_P NO_RH2
IMU_FAIL NO_TEMP` - the list of what has no source on this carrier, which is
what that row is actually for. A mask is not a list.

Worse, `enum seq_event` was the **one C enum with no Python mirror**, so every
event ever shown to an operator was a bare number: `[1] 12: membrane on`.
`clouds_link.frames.EventCode` now mirrors it (0x01..0x0F) and carries the
Pi's own codes (0x10..) in the same space, since ground sees one EVENT stream;
a mirror test keeps the two ends together, and an unknown code degrades to its
hex value rather than blanking, so a newer MCU stays readable on an older
ground station. `main.py`'s private `_EV_*` constants are now that enum.

Naming the severity is what exposed the second dead field: `main.c` passed a
hardcoded `1` to `event_pack`, so **every** MCU event downlinked as WARNING -
an abort and a routine state change at the same level, a field that could
never sort anything. `event_severity()` (in `core/sequencer.c`, where the
event codes live; `frame.c` is the layer below and must not know them) maps
abort to CRITICAL, self-test and seal failure to ERROR, reset/autonomous/Pi-
lost to WARNING, and progress - including an operator's own drive - to INFO.
Two native tests: the mapping, and that not every code returns one level,
because a blanket `return` would satisfy half the assertions on its own.

**Two UI defects, both visible in the panel screenshot.** The Commands box
held buttons at three different widths: a full row of three, a part-filled row
whose two buttons stretched wider, and the release pair wider still. Equal
column stretch does not fix it - stretch splits only the *spare* width, on top
of each column's own minimum, so `ARM + RELEASE 1` kept pushing its column
out. Pinning every column to the widest button's hint is what makes them one
size, and `verify_qt.py` now asserts exactly one distinct width.

And `_release()` opened its "Arm and fire pinch valve 1?" confirmation
*before* checking the ground interlock, so on the pad - every press until
launch - the operator confirmed an irreversible action and was then told it
was refused. A confirmation that routinely means nothing is worse than none.
The interlock is checked first now. This one had survived because
`verify_qt.py` never exercised the release path; it does now.

**Evidence.**

```
flight/mcu/test/run_native.sh        56 tests, 0 failures   (was 54)
python -m pytest tests/              213 passed             (was 211)
python -u verify_qt.py               VERIFY OK              (+4 GSE checks)
cmake --build flight/mcu/build       clean, -Wall -Wextra
picotool load -f -x ...uf2           carrier 21DD2AE08840C863
GSE panel vs the real Pi + MCU       all drives, HK read-back and both interlocks
```

**Still open.** The GSE window is half-themed - a stock-Qt sidebar on the host
palette beside a dark `#12141a` plot, no branding, no wavelength ramp - while
`docs/UI_STYLE.md` defines a light panel and the bench app implements it. The
docstring claimed it followed that language; it now says what it actually
does. Also: the quick-look clips flat at 65520 above ~640 nm on the bench
(`exposure_us` 100 ms, `auto_exposure` false) and the panel gives no
indication, unlike the bench app's `sat %` readout. And the Pi has no RTC and
no NTP on the cable, so its clock was ~5 weeks behind during all of this -
harmless here, but every timestamp above is the Pi's.

---

## 2026-09-09 - The dispersion actuators are commandable, and their state reaches ground (M-07, G-01, G-03)

**Why.** Both dispersion actuators existed, were measured, and ran - but only
as a side effect of a release step. There was no way to drive the membrane
solenoid or the CaCO3 motor on their own. That is the wrong shape for two
reasons: on the bench the mechanism has to be exercised without faking a
release, and in flight a release whose automatic drive does not do its job
leaves no fallback.

**Two commands, deliberately unarmed.** `MEMBRANE` (key = duty percent, 0 =
off) and `DISPERSE` (key = 1, one pulse) join the set, and unlike `RELEASE`
they carry no arm/execute handshake and no ground interlock. The reason is
what the actuators are: the pinch valve is a one-shot with a persisted
`fired` bit, so it is irreversible and gets both gates; the solenoid
oscillates only while it is told to and stops on the next command, and the
motor drive is bounded on the MCU (`VALVE_PULSE_MS`, 5 s). Interlocking them
on the ground would block exactly the case they exist for. They are in
`MANUAL_ACTUATORS` and `tests/test_fsw_mcu_actuators.py` asserts that
membership against `ARMED_COMMANDS` / `GROUND_INTERLOCKED` / `FLIGHT_ONLY`,
so a later edit that quietly arms or frees one has to argue with a test.

The one hard state rule: both are refused in `TERMINATION` and `SAFE`
(`actuators_commandable()`). An abort means the actuators are off and stay
off, and no panel button may undo that.

**What HK was reporting.** `membrane_duty` and `valve_status` had been in the
44-byte payload from the start and the MCU never wrote either, so the panel
showed a membrane at 0 % while the solenoid was audibly oscillating, and
`Valves 0000` throughout. Harmless while nothing could be commanded;
unusable as soon as it can, because a commanded drive is a 5 s pulse that is
over before the next 1 Hz packet - the HK field is the *only* place ground
sees it happen at all. Both are now filled from the two places that know:
`seq.membrane_duty`, recorded by the single `set_membrane()` path every
caller goes through, and `hw_actuator_status()`, which reads
`pulses.active_pin` rather than a shadow flag set when a drive is *requested*
(a request that never ran would otherwise report as an active drive). The
`HKV_*` bits are mirrored in `clouds_link.hk.ValveStatus` and kept in step by
a mirror test, like `HKE_*` before them.

**UI.** A separate **Actuators** box in the GSE dashboard - membrane duty and
frequency with Drive/Stop, one motor pulse - kept apart from the Commands box
so the armed, interlocked release does not sit beside two drives that are
neither. Frequency goes out as `SET_PARAM MEMBRANE_HZ` *before* the drive
starts, because `ops_membrane()` reads that parameter when it starts: sending
it afterwards would leave the solenoid running at the old rate while the
panel showed the new one. The console monitor gained `membrane <duty|off>`
and `disperse` for the no-display path. Every slot is guarded - an unhandled
exception in a PyQt5 slot aborts the process, and "no command link" is a
normal state in `--listen-only`.

**Evidence.** 54 native firmware tests (four new: manual drive and stop, the
motor pulse and its `NULL`-ops refusal, both drives refused after an abort,
and the duty the sequencer records), 211 pytest, and a new GSE section in
`verify_qt.py` that drives the real panel offscreen against a local
`CommandServer` with a stub MCU forward - the real command server class, not
the real Pi - and checks the commands that leave it, the HK it renders back,
and that a missing command link reports instead of raising.

Fixed along the way, both visible in the panel screenshot: the HK grid had
**two rows labelled "Link"** (MCU link flags and downlink statistics) - the
second is now "Downlink"; and the command buttons were ragged because a grid
column is only as wide as its own content, so `HOLD`, alone in the last
column, rendered at half the width of `PING` beside it.

---

## 2026-08-31 (link work, after the motor bring-up) - The Pi <-> MCU conversation: confirmed commands, an arm gate on both ends, Pi liveness (M-13)

**Why.** The two processors were wired together and could talk, but the
conversation made two claims neither end had earned.

The first was on the Pi. `CommandServer` answered ground `OK` the moment
`self.uart.send()` returned, so "the release was accepted" and "the release
was written into a UART with nothing on the other end" were the same message
on the console. The MCU had no way to disagree: it never sent an `ACK`,
`PKT_ACK` existed in the schema and no code produced one, and `seq_command()`
returned `void`. A `CMD_RELEASE` arriving in STANDBY, or naming a valve
already fired, was silently ignored - correct behaviour, invisible to the
operator, and indistinguishable from success.

The second was on the MCU. It acted on any `CMD_RELEASE` that passed CRC-16,
because the Pi was "authoritative for arm/execute". One enforcer, on the far
side of a wire, for the one irreversible action in the experiment.

And `MCUF_PI_OK` was a flag in the schema that nothing ever set: M-13 asked
for a Pi-liveness monitor and there was none, so a dead Pi and a live one
produced identical housekeeping.

**What changed.**

`flight/mcu/src/core/link.c` (new, pure, native-tested) holds both halves of
what the MCU needs to know about its peer:

- *Liveness.* Any valid frame refreshes the link; `PARAM_PI_SILENT_S`
  (default 60 s, against the Pi's 10 s `TIMESYNC` beat) clears `MCUF_PI_OK`
  and raises exactly one `EV_PI_LINK_LOST`. A cold boot with the UART
  unplugged emits nothing: never-seen is not the same as lost.
- *Arm gate.* `ARM` is answered by the gate itself, `RELEASE` needs one
  inside `LINK_ARM_WINDOW_MS` (10 s, mirroring `ARM_WINDOW_S`), and one arm
  authorises exactly one execute.

`seq_command()` now returns an `enum ack_result`, `main.c` answers every
command frame with that verdict, and the Pi's `mcu_link.py` correlates the
`ACK` back to the command's sequence number and hands the result to ground.
The Pi also forwards `ARM` now - it did not before, and with a latch on the
MCU a swallowed `ARM` would have made every release `NOT_ARMED` there.

The ground interlock (S.10) gained a second enforcer for the same reason the
arm latch did: `G-04` lives on a laptop and anything can open TCP 4001. The
Pi refuses `RELEASE` unless *fresh* housekeeping shows the MCU between
ASCENT and MEASURE_2 - no HK, stale HK and STANDBY all resolve to "on the
ground" - and refuses it *before* consuming the arm latch, so a refusal does
not quietly cost the operator their ARM.

**What the link is still not allowed to do.** Nothing here may gate the
sequence (S.7). That is not a comment, it is two tests:
`core/link.c` is grepped for any route into the sequencer (`seq_`, `->ops`,
`fire_`, `membrane`, `enter(`), and `main.c` for an `if (pi_ok)` in front of
the HK/step call. Losing the Pi clears a flag and emits an event; the
experiment carries on.

**One thing the ACK broke that had to be fixed with it.** Every command now
costs a blocking ACK write (~2 ms at 115200) inside a `while (uart_io_poll())`
that had no bound. A flood of uplink frames - a stuck Pi, a noisy line - could
therefore hold the loop past the 2 s watchdog, which the old drain could not
do as cheaply. `MAX_FRAMES_PER_PASS` (8 per 10 ms pass, 800/s, far above any
real command rate) bounds it; the rest wait in the FIFO for the next pass.

**Evidence.**

```
flight/mcu/test/run_native.sh        50 tests, 0 failures   (was 39)
python -m pytest tests/             198 passed
python verify.py                    VERIFY OK
python -u verify_qt.py              VERIFY OK
cmake --build flight/mcu/build      clean, -Wall -Wextra
picotool load -f -x ...uf2          carrier 21DD2AE08840C863, running clouds_fsw_mcu
```

The new coverage is the interesting part, not the count: the ACK/verdict path
end to end (`tests/test_e2e.py` now fails a command the fake MCU rejects, and
proves a release is refused `INTERLOCK` on the pad and accepted once the MCU
reports ASCENT), ACK correlation by sequence number with two commands in
flight and the answers returned out of order, a stop() that releases a caller
blocked on an ACK, and four schema mirrors between C and Python (ACK results,
`SET_PARAM` keys, command codes, the arm window) so a renumbered enum fails a
test instead of turning a refusal into an OK on the ground display.

**Not yet proven on hardware** at the time of writing. The Pi was off the
network for this work (`192.168.100.10` unreachable, `arp` incomplete on a
link that was up), so everything above was desk-verified plus firmware
running on the carrier. **Since closed** by the 2026-09-09 bench entry above:
HK over the real GP0/GP1 wire, the `ARM`+`RELEASE` round trip returning the
MCU's own ACK, `MCUF_PI_OK` in the GSE `link=` field, and the 60 s clear
(stopping the FSW drops `PI` from `link=`, restarting it brings it back).
`flight/pi/README.md` has the commands.

## 2026-08-31 (latest) - Motor and membrane solenoid driven together (M-07)

**Why.** The dispersion motor and the membrane solenoid now fire in the same
release step, and `core/pulse` deliberately serialises its own drives to keep
peak actuator current at one solenoid. The membrane is not in that queue - it
is loop-toggled `core/sqwave` edges - so motor + solenoid is the one pairing
the current budget never covered. Two questions: do both drives actually run
at once or does one starve the other, and what does the power tree do about it.

**Method.** A throwaway image linking the real `src/` (no copies, no edits):
`hw_init()`, then `hw_seq_ops.membrane()` and `hw_seq_ops.disperse()` with
`ops.ctx = &cfg` exactly as `main.c` wires them, serviced by
`hw_actuators_service()` on the flight loop's 10 ms cadence with the real 2 s
watchdog enabled. Pads sampled every 1 ms - 10x finer than the cadence that
makes the edges - and the 24 V / 5 V / 3.3 V INA226s (0x40/0x44/0x45) polled
every 25 ms. The pinch valves were not fired: they are one-shot, and the
release ordering is already covered natively.

**They run concurrently, and the membrane does not lose time.**

```
GP17 held 5001 ms                       (VALVE_PULSE_MS = 5000)
GP18 edges while GP17 drove: 0          (interlock held)
GP26+GP17 both energized: 3000 ms       (= 60 % duty x 5 s, exactly)

membrane alone       high 300000 us  low 200000 us  period 500000 us -> 2.00 Hz
membrane with motor  high 300077 us  low 200000 us  period 500083 us -> 1.99 Hz
```

The 83 us the period grows under load is 0.017 % of a 500 ms cycle, far inside
the ~10 ms loop quantisation the 2 Hz drive already accepts. A 5 s scheduled
pulse and a 2 Hz loop-toggled waveform coexist in one `hw_actuators_service()`
without either starving the other. The 2 s watchdog survived the 5 s drive
across three consecutive flashes, and GP17/GP18/GP26 all read 0 afterwards.

**Confirmed visually on the bench: both actuators moved during the joint
drive.** That observation is doing real work here. Every number above comes
from `gpio_get()` on a driven output, which reports the pad level and so proves
the *drive* wins - it cannot prove a solenoid or a motor is attached to that
pad and turning. GP8 read back its driven level perfectly while nothing was
connected to it. Electrical evidence plus a witness that the mechanism moved is
what closes M-07's drive half; either alone is what the GP8 bug looked like.

**The power tree does not notice the motor.** 880 samples over 22 s, with each
phase driven separately:

| phase | 24 V bus | 24 V shunt | 5 V | 3V3 |
|---|---|---|---|---|
| idle | 23995..23997 mV | 1245..1402 uV | 5092 mV | 3296 mV |
| motor alone | 23988..23998 mV | 1247..1775 uV | 5092 mV | 3296 mV |
| membrane alone | **23907**..23997 mV | 1255..1667 uV | 5092 mV | 3296 mV |
| both | **23905**..23997 mV | 1172..1752 uV | 5092 mV | 3296 mV |

The only phase-correlated signature on the 24 V rail is a ~90 mV dip that
belongs to the **membrane**, and "both" is indistinguishable from the membrane
alone. So the pairing costs nothing measurable, but the reason is not that the
motor is cheap: **the motor's supply is not on any rail the carrier monitors.**
Its 5 V and 3.3 V shunt readings vary as widely with everything off as they do
mid-drive (USB/stdio activity), so nothing there is attributable to it either.
The motor is externally fed, and its current remains **unmeasured** - a bench
PSU reading or a clamp is still owed before it can enter the power budget.

**Correction, and the trap it belongs to.** A first pass sampled the rail once
per phase and reported **6046 mV** on the 24 V bus with both actuators
energized - a 75 % collapse. It is not real. 880 samples across every phase
never went below 23.5 V, and the INA226's manufacturer and die IDs
(`0x5449` / `0x2260`) were read back correct *during* each drive, so the part
was answering properly throughout. The 6046 mV was one bad I2C transfer, and
the reason it got as far as being written down is that a single unvalidated
sample was allowed to stand as a measurement. `ina_read()` returning 0 on a
failed transfer only catches the transfers that fail outright, not the ones
that return plausible garbage. This is the same rule as the phantom stuck SCL
and the BNO055 `SYS_ERR`: rule the instrument out first, and never from one
sample.

---

## 2026-08-31 (latest) - A CaCO3 dispersion motor exists on GP17/GP18 (M-07)

**Why.** Reported from the bench: a motor is now wired to the carrier and turns
under this firmware image -

```c
gpio_init(17); gpio_set_dir(17, GPIO_OUT);
gpio_init(18); gpio_set_dir(18, GPIO_OUT);
while (true) { gpio_put(17, 1); gpio_put(18, 0); sleep_ms(5000); }
```

GP17 high with GP18 low ran it. That is a two-line driver pair, the same shape
as the valve open/close lines, and its job is CaCO3 dispersion alongside the
membrane solenoid.

**The motor is not in the SED.** `pdftotext` over
`BX38_CLOUDS_SED_v1-0_14Jan2026.pdf` finds no motor, pump or stirrer anywhere
in the document, and `docs/` had no mention either. So this is hardware the
carrier grew after the design document, and the firmware treats it as
optional: `seq_ops_t.disperse` may be NULL and the release sequence still runs
(`test_release_works_without_a_dispersion_motor`).

**Three things GP17/GP18 broke.**

1. `board.h` gave GP17 to `PIN_SD_CS_A` and GP18 to `PIN_SD_SCK`. Those numbers
   are now known to drive a motor, so an `spi_init()` on the old map would run
   it while probing for a card. The SD defines are **deleted**, not corrected:
   M-11 has to take its pinout from the schematic. The earlier SD probe getting
   `CMD0 = 0xff` on both chip selects reads differently now - it was talking to
   a motor driver, not to an absent card.
2. Neither pin was in `hw_init`'s output list, so before this change both
   floated as inputs at boot and the motor's state was whatever its driver made
   of two floating inputs. The membrane pin was safe in that window because its
   driver input carries a measured external pull-down (GP26 reads pu=0 pd=0);
   GP17/GP18 have no such measurement. Both are now driven low in `hw_init`
   with the valves.
3. **The passive pin survey cannot prove a pin unconnected.** GP16/17/18 all
   read `pu=1 pd=0` and were written up as "physically unconnected". A
   high-impedance driver input reads exactly the same way. `pu=1 pd=0` means
   "nothing holds this line", which is weaker than "nothing is attached" - the
   same class of error as trusting `gpio_get()` through `GPIO_FUNC_I2C`.

**How it is driven.** `ops_disperse()` hands one `pulse_request(PIN_DISPERSE_FWD,
PIN_DISPERSE_REV)` to `core/pulse`, so the drive is the same 5 s scheduled,
loop-released pulse the valves get and cannot outlive the 2 s watchdog. Only
the forward line is ever driven: the reverse sense was never tested, so GP18
serves as the interlock - forced low before GP17 goes high - which is safe
whichever way that half is actually wired. `PULSE_SLOTS` went 6 → 8 so the two
new lines cannot displace a valve request; a dropped request is an actuation
that silently never happens.

`fire()` calls it on each release, after `fire_pinch` and alongside the
membrane. The scheduler runs one drive at a time, so a release is a 5 s pinch
pulse followed by a 5 s motor pulse, with the membrane oscillating across both
on its own loop-toggled path. Peak actuator current stays at one drive
(`test_release_serialises_the_pinch_valve_and_the_motor`).

**Why it is wired into `fire()` at all.** The alternative - defining the pins
and leaving the sequencer alone - is exactly the GP8 membrane bug: firmware
that builds, flashes and does nothing in flight. A drive nothing calls is
indistinguishable from working code until the flight.

**Open, and deliberately not guessed:**

- The reverse direction is untested. If the motor needs to run both ways, that
  is a second `pulse_request` and a measurement first.
- Whether the motor replaces or supplements the membrane for dispersion is a
  hardware question. Both run today; if the motor replaces it, drop the
  `membrane()` call from `fire()` rather than leaving two mechanisms firing.
- 5 s comes from the valve drive time, not from a motor datasheet. The bench
  image above held GP17 energized indefinitely, which is a stall risk on a
  motor that reaches an end stop - the flight path never does that.
- The part is undocumented: no datasheet, no SED entry, no current figure, so
  it is absent from the power budget.

---

## 2026-08-31 (later still) - The membrane runs at 2 Hz, which PWM cannot do (M-07)

**Why.** The operating frequency was specified as **2 Hz**. That is below the
PWM hardware floor established earlier the same day - `clk_sys / (256 * 65536)`,
about **9 Hz** at 150 MHz - so the hardware PWM path simply cannot produce it.
The previous entry left this as the open question; the answer is that the drive
has to be released by the main loop.

**What.** `core/sqwave.c` generates the square wave and `hw_actuators_service()`
advances it, exactly as `core/pulse` releases the valve drives.
`PARAM_MEMBRANE_HZ` default is now **2**. `ops_membrane` picks the mechanism by
comparing the configured frequency against `pwmdiv_min_hz()`: below the floor it
toggles from the loop, at or above it programs the PWM slice. Both off-paths run
through one `membrane_release_pin_low()` helper that stops the waveform,
disables the slice, and drives the pad low.

**Why loop-driven and not an interrupt or a free-running peripheral.** A
repeating waveform that outlives a hung main loop would keep energizing the
solenoid. Loop-released edges stop when the loop stops: the 2 s watchdog resets
the part and `hw_init()` drives the pin low. This is the same reasoning that
keeps the 5 s valve pulse out of a blocking sleep (S.8, S.9), and it is why the
faster PWM option is deliberately not used at the frequency the membrane
actually runs at.

The cost is that edges quantise to the loop period, ~10 ms, which at 2 Hz is
2 % of a 500 ms cycle. A late service pass stretches its cycle rather than
firing a burst of catch-up edges, because the pass that ran late is the one
where the loop had real work to do.

**Measured on the carrier**, through `hw_seq_ops.membrane()` with
`hw_actuators_service()` on the flight loop's 10 ms cadence, reading the pad:

```
PARAM_MEMBRANE_HZ=2 DUTY=60%  -> loop-toggled (sqwave) path
edges=11  high avg=300 ms (n=6)  low avg=200 ms (n=5)
period=500 ms -> 2.00 Hz
after off: pin=0
```

300 ms high / 200 ms low is exactly 2 Hz at the configured 60 % duty.

**A sub-floor frequency is toggled, never clamped.** An earlier version clamped
a request below the PWM floor up to the floor, which would have silently run the
membrane at 9 Hz instead of the specified 2 Hz - a wrong frequency reported as
success. `tests/test_fsw_mcu_actuators.py` now fails if that clamp returns, and
the native suite fails if the default rises above the floor, because that would
silently change which mechanism drives the solenoid.

`PARAM_MEMBRANE_HZ` keeps its 1-400 range: the two mechanisms together cover it,
loop-toggling below ~9 Hz and PWM above. Only the mechanism selection changes
with the value, and the native tests check both sides of the boundary.

---

## 2026-08-31 (later) - The membrane solenoid is on GP26 and was being driven at 150 kHz (M-07)

**Why.** A throwaway 0.5 Hz blink was asked for on GP26 purely as a pin smoke
test. `board.h` claimed GP26 was `ADC_TEMP1`, STLM20 #1's analog output, so the
test was run under a warning about fighting that sensor's output stage. The
solenoid moved instead: **GP26 drives the membrane push-pull solenoid.** That
one observation invalidated three things in the pin map at once.

**What the blink measured.** 1 s high / 1 s low, then 250 ms / 250 ms, with
`gpio_get()` read back on the driven output - which returns the actual pad
level, so it reports whether the drive wins:

| Requested | Measured period | Pad high | Pad low |
|---|---|---|---|
| 0.5 Hz | 2.000 s | 1 | 0 |
| 2 Hz | 0.500 s (f=1.999 Hz) | 1 | 0 |

The ~0.05 % slow reading at 2 Hz is real `sleep_ms` plus printf overhead in a
software-timed loop, not measurement error.

**Three corrections to the pin map.**

1. `PIN_MEMBRANE_PWM` was **8**; GP8 measures as unconnected (`pu=1 pd=0`).
   The membrane is GP26. **M-07 would have silently done nothing in flight**:
   the sequencer would start the drive, the pin would toggle, and no solenoid
   would be attached to it.
2. `ADC_TEMP1` claimed GP26 and so collided with the solenoid. The STLM20 pair
   is **not populated**, so `hw_read_sensors` no longer samples the ADC at all
   and raises `HKE_NO_TEMP` instead. A floating input yields a confident wrong
   temperature, which is worse than reporting none.
3. `hw_init` now drives the membrane pin low as a plain SIO output alongside
   the valves, and the PWM function is applied only while a drive runs. The
   old code applied `GPIO_FUNC_PWM` at init and relied, unknowingly, on the
   external pull-down measured on that driver input (`pu=0 pd=0`) to keep the
   solenoid off. That pull-down is real and was the only reason the boot state
   was safe; it is now safe by the firmware's own action as well.

**The 150 kHz bug.** `PARAM_MEMBRANE_HZ` defaults to 50 Hz (range 1-400) and
the SED says "start membrane PWM (frequency/duty from config)", but
`ops_membrane` set `wrap=999` with the **default clock divider**: on a 150 MHz
RP2350 that is **150 kHz**, 3000x too fast. A push-pull solenoid at 150 kHz
never oscillates, it only sees a DC average - so even on the right pin the
membrane would not have dispersed anything. The code's own `TODO` admitted the
divider was never plumbed. `PARAM_MEMBRANE_HZ` now reaches the driver through
`seq_ops_t.ctx`, which `main.c` points at `cfg`.

**The arithmetic lives in `core/pwmdiv.c`, not in `hw/`.** The bug was a wrong
output frequency, and `hw/` is the one directory the native suite cannot
compile, so the solver is portable and unit-tested: the default really produces
50 Hz, every reachable value in the configured range lands within 1 %, and
`cfg_default()` is checked against `cfg_defaults()` so the fallback frequency
cannot drift from the table. Reintroducing the old `div=1, wrap=999` as a
mutant makes those tests report `expected 50 +/- 1, got 150000`.

**A range the hardware cannot honour.** The RP2xxx divider tops out at
255+15/16 and the counter at 16 bits, so the slowest achievable frequency is
`clk_sys / (256 * 65536)`, about **8.95 Hz** at 150 MHz. `PARAM_MEMBRANE_HZ`
permits 1 Hz. Requests below the floor are clamped to it, deliberately, rather
than silently becoming some other frequency - `pwmdiv_min_hz()` reports the
floor so the clamp is visible. If the membrane genuinely needs single-Hz
oscillation, that has to be driven from the main loop the way `core/pulse`
drives the valves, not from a PWM slice; the blink that started all this is
proof the mechanism works at 0.5 Hz.

**Still unknown: where the STLM20s go when they are fitted.** GP27 also reads
externally driven, but with GP26 now accounted for, the old `ADC_TEMP*`
mapping has no measured support at all. `temp1_cc` and `temp2_cc` stay zero
with `HKE_NO_TEMP` set until the schematic says otherwise.

---

## 2026-08-31 - i2c0 is on GP28/GP29 and carries the power tree (M-09); M-11 blocked on the SD pinout

**Why.** M-09 (BME280 / Keller 23SY / IMU drivers) is still a `TODO` in
`hw_read_sensors`, and `board.h` carries the disclaimer "preliminary - track
the PCB". Before writing any sensor driver against that pin map it was worth
asking the board itself where the bus is and what sits on it, rather than
trusting a header that says not to.

**Measurement 1 - passive pin survey.** A throwaway RP2350 image configured
GPIO 0..29 as *inputs only*, never driving a pin, and read each one three
times: internal pull-up, internal pull-down, no pull. The valve drivers were
populated and powered at the time, so nothing may be driven - `pu=1 pd=0`
means nothing is attached and the internal pull-up wins, `pu=1 pd=1` means an
external pull-up holds the line up regardless, `pu=0` means something holds
it down.

`PIN_I2C_SDA 12` and `PIN_I2C_SCL 13` both came back `pu=1 pd=0`: **physically
unconnected on this carrier.** Two pin pairs showed an external pull-up on
*both* members, which is the I2C signature - GP6+GP7 (i2c1) and GP20+GP21
(i2c0) - and GP28+GP29 (i2c0) did too. GP28/GP29 is the real bus, confirmed by
the scan below. GP23/24/25 low and GP29 high also reflect the Pico 2's own
onboard functions (power-mode, VBUS sense, LED, VSYS divider), so read that
survey against the board schematic, not in isolation.

**Measurement 2 - address scan.** `i2c0` at 100 kHz on SDA=GP28, SCL=GP29,
1-byte read per address over 0x08..0x77 (0x00-0x07 and 0x78-0x7f are reserved
and never probed), address counted as present when the read returns >= 0.
Five devices answer:

Five devices answer: `0x28`, `0x40`, `0x44`, `0x45`, `0x76`.

**Measurement 3 - what those five actually are.** Guessing parts from default
addresses got every one of them except the BME280 wrong, so the identities
below come from ID registers and from readings in physical units. The first
guess had `0x44`/`0x45` as the two RH channels and `0x40`/`0x28` as the two
Keller 23SY - all four wrong:

| 7-bit | identified as | evidence | HK field |
|---|---|---|---|
| `0x76` | **BME280** | `chip_id`(0xD0)=`0x60`; calib `dig_T1=28323 dig_P1=37257 dig_H1=75`; compensated 29.17 degC / 99396 Pa / 41.15 %RH | `bme_temp_cc`, `rh1_cpct`, `p_amb_pa` |
| `0x40` | **INA226** | `man_id`(0xFE)=`0x5449` "TI", `die_id`(0xFF)=`0x2260`; bus reads **24.003 V** | none (see below) |
| `0x44` | **INA226** | same IDs; bus reads **5.092 V** | none |
| `0x45` | **INA226** | same IDs; bus reads **3.298 V** | none |
| `0x28` | **BNO055 IMU, faulted** | three constants match a genuine part: `CHIP_ID`=`0xA0` at the BNO055's own default address, `SW_REV`=`0x0311` (3.17, the shipped fusion firmware), `BL_REV`=`0x15`. But `ACC_ID`/`MAG_ID`/`GYR_ID` all read `0x00` where a working part gives `0xFB`/`0x32`/`0x0F` | none; `HKE_IMU_FAIL` |

So the bus carries **the power tree, not the humidity sensors**: three INA226
watching 24 V, 5 V and 3.3 V. `hk_t` has no voltage or current field and HK is
44 B against a 67 B ceiling, so they are not sampled by `hw_read_sensors`;
adding them is a protocol change, not a driver change.

**There is no chamber pressure sensor and no second RH channel on this bus,
and no Keller 23SY at any address.** The IMU is fitted and answers, but its
internal sensor dies do not, so it is unusable as it stands. *(Superseded
2026-09-11: this probe read the ID block before the part's 650 ms boot could
have written those three registers, so it cannot distinguish a dead die from
an un-booted one - see the newest entry.)* Those three
sub-sensor IDs are the whole case: they are fixed constants readable in any
mode, and `CHIP_ID` read correctly in the same byte-wise loop, so the I2C path
works and the fault sits inside the package between the M0 and its accel, mag
and gyro dies.

**Do not cite `SYS_STAT`/`SYS_ERR` here as evidence - the probe caused them.**
An early draft of this entry offered `SYS_STAT=0x01` (system error) and
`SYS_ERR=0x05` as proof the part had failed to boot. The BNO055's page-0
register map ends at `0x6A`, and the probe had just read `0xFE`/`0xFF` at this
address while checking for a TI manufacturer ID. `SYS_ERR 0x05` is precisely
*"register map address out of range"*: the next pass read back the error the
previous pass provoked. Second instance in one day of an instrument
manufacturing its own finding (see the `GPIO_FUNC_I2C` trap above) - when a
diagnostic reports a fault, rule out the diagnostic first.

**Untested hypotheses for the dead dies**, in the order worth checking, all
needing the schematic: a missing or non-oscillating external 32.768 kHz crystal
with `CLK_SEL` asserted (the classic cause of exactly this signature),
VDD/VDDIO power sequencing, or a counterfeit part - remarked BNO055s are common
and known to report `CHIP_ID` while the sub-IDs misbehave. A proper retest must
assert `nRESET`, wait the full ~650 ms boot, read the ID block once, and never
touch a register above `0x6A`. `OPR_MODE` also read `0x10`, outside the valid
`0x00`-`0x0C` range, which is unexplained.

**The SED does not baseline an IMU at all.** Section 4.7a lists only the e9u
spectrometer, `STLM20W87F` x2, `BME280` x1 and `Keller 23SY` x2 - no IMU part
number, no schematic detail - while the prose promises one and risk **MS002 is
"IMU failure (failure to detect float phase)"**. So this is off-baseline
hardware with nothing to verify an integration against. MS002's own mitigation
is "experiment activation without IMU detection", which the float-timer fallback
and pressure criterion in `core/autonomy.c` already implement: a dead IMU
degrades the mission, it does not block the release. `p_ch_pa`,
`rh2_cpct`, `accel_mg` and `gyro_ddps` therefore have no source; they are
flagged through `error_flags` rather than filled with invented numbers.

**Trap: an ACK is not an identity, and a completed transfer is not a valid
reading.** The first probe declared "CONFIRMED" whenever a write and a read
both returned >= 0, which is true of any device that acknowledges its address.
It reported SHT3x parts at `0x44`/`0x45` that do not exist and a working Keller
protocol at `0x40`/`0x28` that never replied - the payloads were all-`0xff`,
i.e. nobody driving the bus. Validate the checksum the part specifies (Sensirion
CRC-8 over `0x0000` is `0x81`, not `0xff`) and convert to physical units: a
plausible lab temperature and pressure is the proof, not a return code.

**Trap: never read a pin level while it is in `GPIO_FUNC_I2C`.** The first
version of the scan called `gpio_get()` on the I2C pins to report bus idle
state and printed `SCL idle=0`, which reads exactly like a shorted clock line
and sent the investigation after a hardware fault that did not exist. In that
pin function `gpio_get()` returns the *controller's* drive state, and the
controller was still holding SCL down after the aborted probe transfers. Sample
idle levels before applying the I2C function and again after `i2c_deinit`, as
plain SIO inputs - that is what produced the trustworthy `pu=1 pd=1` readings
above. Use `i2c_read_timeout_us`, not `i2c_read_blocking`, or a genuinely stuck
clock hangs the scan instead of reporting it.

**Consequence for the code.** `PIN_I2C_SDA` / `PIN_I2C_SCL` in
`flight/mcu/src/hw/board.h` moved from 12 / 13 to **28 / 29**. Nothing was
broken before the change - `hw_init()` never called `i2c_init()` and no test
asserts those constants - but M-09 built on 12/13 would have found an empty
bus. Note this spends ADC2/ADC3; only ADC0/ADC1 (GP26/GP27, the two STLM20s)
are used, so there is no conflict, and the survey saw both of those pins
externally driven as expected.

**M-09, the half that exists.** `src/hw/bme280.c` drives the BME280 in normal
(continuous) mode, so a sample is always waiting and reading it costs one
register burst with no delay - that is what lets the sweep stay inside the 2 s
watchdog without a single sleep in `src/hw/` (the no-sleep test now covers the
whole directory, not just `hw.c`). Compensation is the datasheet fixed-point
reference, and the driver was run on the board before being committed:
`bme_temp_cc=2915  rh1_cpct=4152  p_amb_pa=99411`, stable over repeated reads.

**Why a failed sensor read holds the pressure instead of zeroing it.** This is
the sharp edge of M-09. `autonomy_step()` detects launch from a *drop* below
`p_ground_pa - PARAM_LAUNCH_DP_PA`, so reporting 0 Pa after an I2C glitch would
mimic a 100 kPa fall, trip launch detection on the bench and fire valves. The
hardware layer keeps the last good value, flags it `HKE_P_AMB_STALE`, and starts
from sea-level pressure on a cold start - high is safe, low is not, because only
a fall can trigger anything. `tests/test_fsw_mcu_actuators.py::
TestSensorFailureIsSafe` pins all three properties at source level, and
`error_flags` finally has defined bits (`HKE_*` in `frame.h`, `HkErrors` in
`clouds_link/hk.py`, kept in step by a mirror test per X-01).

**M-11 is blocked on the same class of problem, and must not be guessed at.**
`board.h` maps SPI0 to `SCK 18, MOSI 19, MISO 16, CS_A 17, CS_B 20`, but the
passive survey read GP16, GP17 and GP18 as unconnected, and an SD probe on
exactly those pins got `CMD0` = `0xff` on both chip selects - nothing driving
MISO. An empty socket with pull-ups would still hold MISO high, so the evidence
points at the pin map rather than at missing cards. Writing FatFs against a map
that has now been wrong once already would repeat this entry's whole mistake, so
persistence stays the RAM stub and **S.3 brownout resume still does not survive
a real reset**: the `fired` bit that prevents a second CaCO3 release is lost on
power loss. That is the largest open flight risk and it needs the carrier
schematic, not more probing.

**Hardware.** Two distinct RP2350 boards are in play, worth keeping apart by
USB serial: the bare Pico 2 `182A9FD0C5146E6F` (carries `clouds_fsw_mcu.uf2`)
and the CLOUDS carrier `21DD2AE08840C863`, which was running an unrelated
`first_test` v0.1 image. Its flash was saved with `picotool save` before the
scan images were loaded and restored afterwards; `picotool save` / `load -f -x`
makes a scan on someone else's board non-destructive, so there is no reason to
skip that step.

---

## 2026-08-05 — Auto integration time defaults on; band raised to 60-80 %

**Why.** The continuous auto-exposure servo (2026-06-14, below) landed as an
opt-in checkbox holding ~65 % FS. Requested: make it on by default, and move
the target band to 60-80 % FS so the peak sits a bit higher up the dynamic
range.

**What.** `chk_track` (relabelled "auto integration time (continuous)") now
starts checked. `_track_exposure`'s deadband moved from `[0.54, 0.78]` (target
0.65) to `[0.60, 0.80]` (target 0.70); the one-shot `_auto_expose` target and
accept band moved the same way, so the button and the servo agree on where
"in range" is.

The 0.80 ceiling stays inside the 0.78 knee guard from the 2026-06-14 entry
below (TCD1304 nonlinearity near saturation) - close to it, but not past it.

**Regression caught and reverted the same day: no eager snap on connect.**
First version also called `_auto_expose()` from `_connect()` when tracking is
on, to get in range immediately instead of waiting for the servo to converge
over a few live frames. `_auto_expose` hunts over several *blocking* driver
round-trips (2 settle grabs + a 7-frame average per probe, up to 8 iterations,
confirmed twice) - fine for the ~1 ms USB round-trip the design was verified
against, but `main()` calls `_connect()` unconditionally on startup, and over
`--net` (TCP to the Pi's `net_server`/`--bench-stream`) each of those round-trips
pays real network latency - 100+ round-trips stalled the window opening for
seconds. Removed; the continuous servo now converges gradually once the user
presses Run instead, no upfront hunt on connect.

**Verified - mock** (`verify_qt.py`): same coverage as 2026-06-14 (dead-beat,
10x-dimming recovery, deep-saturation escape, glitch immunity, rail-honesty,
slider-drag override), with the in-band assertions shifted to the new
60-80 % target.

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
