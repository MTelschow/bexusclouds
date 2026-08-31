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

**Not yet proven on hardware.** The Pi was off the network for this work
(`192.168.100.10` unreachable, `arp` incomplete on a link that was up), so
everything above is desk-verified plus firmware running on the carrier. What
the bench still owes: HK arriving over the real GP0/GP1 wire, an
`ARM`+`RELEASE` round trip returning the MCU's own ACK, `MCUF_PI_OK`
appearing in the GSE `link=` field, and pulling the UART to watch it clear
after 60 s. `flight/pi/README.md` has the commands.

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
internal sensor dies do not, so it is unusable as it stands. Those three
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
