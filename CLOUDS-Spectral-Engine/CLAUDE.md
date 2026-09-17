# CLOUDS Spectral Engine — working notes

BEXUS 38 dual-spectrometer software: a Qt **bench panel**, the **Raspberry Pi 5
flight app** (FSW-PI), the **RP2350 sequencer firmware**, and the **ground
station** (GSE), all sharing one protocol (`clouds_link/`) and one instrument
layer (`spectro/`).

`docs/` is the source of truth for design detail — `DRIVER.md` (vendor
libraries, USB glitch), `CALIBRATION.md` (pixel→nm, **data scaling**),
`SOFTWARE_SPEC.md` / `SOFTWARE_FEATURES.md` (spec + feature status),
`DEVLOG.md` (why things are as they are), `UI_STYLE.md`, `BENCH.md`.
Don't duplicate them here; update them when behaviour changes.

## Commands

`PYTHONPATH` must include the repo root, plus `gse/` and `flight/pi/` for their
packages. On Windows also `$env:PYTHONIOENCODING='utf-8'` for `verify_qt.py`.

`./run_clouds_ui.sh [flags]` is the launcher (repo venv + the three
`PYTHONPATH` entries, args passed straight through); `run_clouds_spectral.bat`
is its Windows counterpart. By hand:

```sh
# the operator interface - one window, instrument + flight (clouds_ui/)
python -m clouds_ui                     # real Duo on this machine; on macOS
                                        # this defaults to --net 192.168.100.10
python -m clouds_ui --net 192.168.100.10          # detector on the Pi
python -m clouds_ui --flight            # downlink only: HK, quick-look, commanding
python -m clouds_ui --mock              # no hardware: synthetic detector +
                                        # simulated Pi/MCU on loopback

# flight app (on the Pi, from /opt/clouds)
python3 -m clouds_fsw.main --config /etc/clouds/fsw.json
python3 -m clouds_fsw.main --mock                  # mock spectrometer + UART stub
python3 -m clouds_fsw.main --no-uart               # real detector, no RP2350 wired
python3 -m clouds_fsw.main --no-uart --bench-stream  # + serve the live panel

# ground station, headless (no display, or scripted integration use)
python -m clouds_gse.main --experiment 192.168.100.10

# checks — run all three before committing
python -m pytest tests/                 # 150+ tests, no hardware needed
python verify.py                        # driver + calibration self-checks
python -u verify_qt.py                  # offscreen UI; must end "VERIFY OK"
flight/mcu/test/run_native.sh           # firmware core (C, host compiler)
```

```sh
# RP2350 firmware (details + macOS toolchain trap in flight/mcu/README.md)
export PICO_SDK_PATH=~/pico-sdk PICO_TOOLCHAIN_PATH=~/arm-gnu-toolchain
cmake -S flight/mcu -B flight/mcu/build -DPICO_PLATFORM=rp2350   # board defaults to clouds_carrier (RP2350B)
cmake --build flight/mcu/build -j8
picotool load -f -x flight/mcu/build/clouds_fsw_mcu.uf2   # -f: no BOOTSEL needed
```

## One GUI, two data sources - read this before "opening the GUI"

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

**That 1 Hz depends on HK staying lean.** The budget leaves ~83 B for a framed
HK packet, i.e. an **HK payload ceiling of 67 B**; `hk.SIZE` is 54 B today. The
spec originally allowed ~180 B, at which size 1 Hz quick-look totals
~2.9 kbit/s and busts the limit. Grow `Housekeeping` past 67 B and you must bin
the quick-look harder or slow its cadence -
`tests/test_fsw_telemetry.py::TestDownlinkBudget` fails first, by design.

## Architecture

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
  `session_mock_*`; the stored dark frame is never written or cleared
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

## Hardware

EURECA **e9u-SPMD-350850-10-Duo**, board `e9u_LSMD-TCD1304-PRO`, **S/N
20260312-004**, INSION bench, **Toshiba TCD1304DG** 2048-px line CCD.
USB → FTDI **FT2232H** (`0403:6010`, iSerial `EU02290003`) → VCP serial. The
vendor library auto-detects the camera; no COM port or tty is hardcoded.

- **One detector carries both fibre channels.** `calibration.json`: Ch1 window
  `[0, 235]` (measurement), Ch2 `[1516, 1766]` (reference); the gap is dark.
  One shared exposure for both.
- **ADC is 12-bit**, transfer 16 bits/pixel. Identity reports
  `Dark_Pixel: 0 x 16` *before* `Pixel: 1 x 2048` — parse with care.
- `saturation_count` is **65520**, i.e. the 16-bit scale (12-bit × 16), not 4095.

### RP2350 carrier - measured, not from the drawings

`board.h` calls itself preliminary and it means it: five of its pin
assignments were wrong on the real board, and the wrong ones included two that
drive an actuator. Everything below was measured, with
the method in `docs/DEVLOG.md` (2026-08-31). **Measure before trusting that
header.** Two boards are in play; keep them apart by USB serial - bare Pico 2
`182A9FD0C5146E6F`, CLOUDS carrier `21DD2AE08840C863`.

**The carrier schematic (`pin_layout.jpeg`, 2026-09-11) confirms every measured
pin and contradicts two that were never measured.** The full net table is in
`board.h`. `PIN_PINCH_1`/`PIN_PINCH_2` (GP2/GP3) are the Pi's **`PI_RTS`/
`PI_CTS`**, and `PIN_EQ1/2_OPEN/CLOSE` (GP4..GP7) are **`SPI_0` + `SD_1_SENS`**
- so firing a pinch valve today toggles a UART flow-control line. Those defines
are **deliberately left wrong** with the contradiction written beside them: the
board's actuator channels are `ACT_R_1..4` (GP26/25/24/23), `ACT_EC`
(GP19..GP22) and `ACT_HB` (GP17/GP18/GP46), but the page names *channels, not
loads*, and guessing which relay holds pinch 1 is how an actuator gets driven
from the wrong pin. Needs the load side of the schematic or a measurement.
Also: the carrier is an **RP2350B** (GP0..GP47). The build was
`-DPICO_BOARD=pico2` (RP2350A, 30 GPIOs) until 2026-09-17, which left the
INA226 alert pins, the 24 V regulator enable, five ADC channels and
`ACT_HB_SENS` unreachable; it now defaults to `flight/mcu/boards/clouds_carrier.h`
(`PICO_RP2350A 0`), the first user being the membrane switch on **GP30**.
`-DPICO_BOARD=pico2` still builds for the bare Pico 2, with GP30 compiled out
and `HKE_NO_MEMBRANE_SENSE` set. **Reconfigure `flight/mcu/build` from
scratch** after pulling this: `PICO_BOARD` is cached.

| What | Where | State |
|---|---|---|
| i2c0 | **SDA GP28, SCL GP29** (not GP12/13, which are unconnected) | BME280 `0x76` is the only usable sensor |
| INA226 ×3 | `0x40` **V_in**, `0x44` 5 V, `0x45` 3.3 V | live and **downlinked**: bus voltage in `hk.rail_mv[]` (mV, measured 24.06 / 5.09 / 3.30 V) and the raw shunt-voltage register in `hk.shunt_raw[]` (i16, 2.5 µV/LSB). **Amps are computed on the ground**, `hk.rail_a()` over `RAIL_SHUNT_MOHM = 10, 15, 50, 50 mΩ` - the part's calibration register is left alone, so a wrong shunt value can be corrected against a logged session instead of being baked into it |
| INA226 24 V | **not fitted** | the rail holds slot 1 of `rail_mv[]` / `shunt_raw[]` and downlinks `RAIL_MV_INVALID`; the panel says `not fitted`, and `HKE_RAIL_FAIL` is **not** raised for it - an absent part is not a fault to chase (`ina226_fitted()`) |
| BNO055 IMU | `0x29` **or** `0x28` - the strap, not the part: 0x29 is the datasheet default and COM3 has an internal pull-up, so `hw/bno055.c` tries both and latches whichever returns a whole ID block | **does not answer (2026-09-11)**: 0/50 ACK at 0x28 *and* 0x29, read- and write-probe, in the same sweep where 0x40/0x44/0x45/0x76 all answer - electrically absent from i2c0, which is *not* the "sub-sensor dies dead" on record from 2026-08-31, when it answered `CHIP_ID 0xA0`. The board changed between those dates. Driven by `hw/bno055.c`: **400 ms start-up wait (TSup) before the bus is touched at all**, then reset, 650 ms boot (TPOR), ID check, 19 ms CONFIGMODE wait, 7 ms mode switch, `OPR_MODE` read-back, 30 s retry - five 1 Hz sweeps to a first sample, never sleeping. With no part it reports `HKE_IMU_FAIL` and zeroed vectors, verified on hardware. **`BNO_INT` is on GP27** and reads `pu=1 pd=0`, which **proves nothing** - `INT_EN`/`INT_MSK` reset to `0x00` and nothing enables an interrupt, so a *working* part may leave the line undriven too (only an actively driven pin says anything). What is *absent* cannot be told apart from unpowered, held in nRESET, or PS1/PS0 strapped to UART - that needs a meter, not firmware. HID-I2C is ruled out: `0x40` answers as a verified INA226. `src/tools/bno055_probe.c` (`-DCLOUDS_BUILD_TOOLS=ON`, USB CDC) discovers the strap; flash it first when a part is fitted. Verified on the carrier with no part: 119 HK in 120 s, uptime monotonic (no watchdog reset), `IMU_FAIL` set, vectors zero, rest of the bus undisturbed. **The success path has never run against real silicon** |
| Membrane solenoid | **GP26** (not GP8, unconnected) | **2 Hz**, loop-toggled via `core/sqwave`; driven from the GSE panel end to end (`MEMBRANE` duty), duty read back in HK |
| Membrane position switch | **GP30**, input, internal pull-up, switch to ground | **LOW = solenoid energized (pulled)**. Downlinked as `HKV_MEMBRANE_PULLED` (bit 5 of `valve_status`, a *sensed* bit that may sit beside a drive bit); the panel's `Membrane` row reads `60 %  pulled` / `pushed`, `actuator_text` leaves it out. At 2 Hz the 1 Hz HK sample catches a random phase, so with the drive on it alternates between packets - stuck either way against the drive is the fault it exists to show. Needs the RP2350B board header (above). **Not yet measured on the carrier** |
| Push-pull solenoid current sense | **GP46** (`ACT_HB_SENS`), ADC6 on the RP2350B | **downlinked raw**: 12-bit counts in `hk.hb_sense_raw` (8-sample mean, one point per 1 Hz sweep, so it swings with the 2 Hz cycle like the switch). Ground shows the pin **voltage** (`hb_sense_v()`, 3.3 V reference assumed) - **amps need `HB_SENSE_A_PER_V`, which is `None` until the sense gain is measured**; no guessed number reaches the panel or the log. Sentinel `HB_SENSE_INVALID` (0xFFFF) from a pico2 build, never 0 (an idle solenoid reads 0). Panel row `Solenoid I`, timeline `Solenoid sense` beside the duty. **Not yet measured on the carrier** |
| CaCO₃ dispersion motor | **GP17 fwd / GP18 rev** | one 5 s scheduled pulse per release or per `DISPERSE` command, commanded from the panel and seen in `valve_status` for ~5 s; runs concurrently with the membrane, measured; **not in the SED**, reverse sense untested, **current unmeasured - not on any monitored rail** |
| STLM20 ×2 | none | **not populated**; the old `ADC_TEMP1` collided with GP26 |
| Keller 23SY ×2 | none | **off the design** - absent at every address, and the HK fields they fed (`p_ch_pa`, `rh2_cpct`) went with them |
| SD / SPI0 | **pinout now known** from the carrier schematic (2026-09-11): SPI_0 on GP4/GP6/GP7, `SD_1_CS` GP14 + `SD_1_SENS` GP5, `SD_2_CS` GP16 + `SD_2_SENS` GP15 | still no defines. **M-11 is no longer blocked on the schematic but on a pin conflict**: `board.h` currently gives GP4..GP7 to the equalisation valves, and an `spi_init()` would drive whatever the valve code thinks it owns |

HK is **56 B** (framed 72 B against an 83 B allowance, ceiling 67 B payload):
54 B as below plus `hb_sense_raw` (u16) appended after `mission_t_s`, so no
older field moved.
The Keller pair's 6 B (`p_ch_pa` + `rh2_cpct`) became `shunt_raw[]`; the four
extra bytes over that are the reserved 24 V rail, whose monitor is not fitted
yet - a slot costs 4 B once, a wire-format change on fit day costs the MCU,
the Pi and every logged session. An unreadable rail is
`RAIL_MV_INVALID` (`0xFFFF`), never 0 - **0 mV is a real reading** for a rail
whose supply is absent, and a dead monitor is a different fault from a dead
rail. The sentinel invalidates that rail's `shunt_raw` too, so no current is
ever shown against an unknown voltage.

So `temp1/2_cc` has **no source**. It is declared
through `error_flags` (`HKE_*` in `core/frame.h`, `HkErrors` in
`clouds_link/hk.py`, kept in step by a mirror test) rather than filled with
invented numbers; bit 3 is free (it was the Keller pair's `NO_RH2`), bit 2
(`NO_CHAMBER_P`) is now `HKE_NO_MEMBRANE_SENSE`. The SED baselines no IMU at all while risk MS002 is
"IMU failure" - hardware and document disagree.

**M-15 has no sensor.** Seal verification was to compare chamber against
ambient pressure, and the chamber half is gone with the Keller parts, so
`ops_seal_ok()` needs a source that exists (a replacement chamber sensor, or
valve position sense) before it is anything but `return true`.

**S.3 does not hold yet.** Persistence is still a RAM stub, so brownout resume
does not survive a real reset: the `fired` bit that prevents a second CaCO₃
release is lost on power loss. Largest open flight risk, blocked on the
carrier schematic.

## Traps that have cost real time

**Data scaling differs by platform.** The Windows DLL returns each sample
left-shifted into 16 bits (0..65520); the **Linux `.so` returns raw 12-bit**.
`spectro/eureca_driver.py` normalises Linux up (`grab()` and `dark_value()`
share the shift; `CLOUDS_E9U_COUNT_SHIFT=0` disables). Without it every
`saturation_count` threshold breaks: clipping is undetectable and the P-09
exposure servo only ever ramps up. See `docs/CALIBRATION.md`.

**The vendor library owns the USB device exclusively.** The FSW and a
standalone `spectro.net_server` cannot both hold it. To run the flight chain and
the live panel together use `clouds_fsw.main --bench-stream`, which serves
frames the FSW already acquired and never touches the driver.

**udev rules are `ACTION=="add"`.** `udevadm trigger` defaults to `change`, so a
plain trigger applies nothing while appearing to succeed — the tty stays `0660`
with `ftdi_sio` on interface 0. Use
`udevadm trigger --action=add --subsystem-match=usb --subsystem-match=tty`, or
software-replug: `echo -n 1-1.2 | sudo tee /sys/bus/usb/drivers/usb/{unbind,bind}`.
Correct end state: one tty at `0666`, interface `:1.0` unbound.

**A charge-only USB cable** enumerates as Code 43 / `Port Reset Failed` and the
camera is invisible. Use a data cable.

**One sample is not a measurement.** A single INA226 read reported the 24 V bus
at 6046 mV under load - a 75 % collapse that does not exist; 880 samples never
left 23.9..24.0 V. A failed I2C transfer is easy to catch, a transfer that
returns plausible garbage is not, so read the part's identity registers
*during* the event (INA226 mfg `0x5449`, die `0x2260`) and profile continuously
before believing an excursion.

**`pu=1 pd=0` does not mean unconnected.** The passive pin survey read that on
GP16/17/18 and they were written up as physically unconnected; GP17/GP18 then
turned out to drive the dispersion motor. A high-impedance driver input reads
exactly like a bare pin. The survey proves "nothing holds this line", which is
weaker than "nothing is attached" - and an actuator pin with no measured
external pull is floating until `hw_init` drives it, so its boot state is
whatever its driver makes of that.

**Your instrument invents its own findings - rule the instrument out first.**
This happened twice in one day. `gpio_get()` on a pin still in
`GPIO_FUNC_I2C` returns the *controller's* drive state, not the board's, and
reported a stuck SCL that did not exist; sample idle levels as plain SIO
inputs before applying the I2C function and after `i2c_deinit`. Reading
`0xFE`/`0xFF` on the BNO055, whose page-0 map ends at `0x6A`, *caused* the
`SYS_ERR 0x05` ("register map address out of range") that the next pass then
read back as evidence of a boot failure.

**An I2C ACK is not an identity, and a completed transfer is not a valid
reading.** Guessing parts from default addresses got four of five wrong here.
Validate the checksum the part specifies (Sensirion CRC-8 over `0x0000` is
`0x81`, not `0xff`) and convert to physical units - a plausible lab
temperature and pressure is the proof. All-`0xff` payloads mean nobody is
driving the bus.

**A failed sensor read must never report a low pressure.** `autonomy_step()`
detects launch from a *drop* below `p_ground - PARAM_LAUNCH_DP_PA`, so 0 Pa
after an I2C glitch mimics a 100 kPa fall, trips launch detection on the bench
and fires valves. Hold the last good value, flag `HKE_P_AMB_STALE`, and cold
start at sea level: high is safe, low is not.

**PWM cannot go below ~9 Hz** (`clk_sys / (256 × 65536)`), and the membrane
runs at 2 Hz. Sub-floor drives are toggled from `hw_actuators_service()` via
`core/sqwave`, never clamped up to the floor - clamping runs the actuator at
the wrong frequency while reporting success. Actuator waveforms are
loop-released on purpose: an IRQ- or peripheral-driven output keeps energizing
the solenoid through a hung loop.

**stdio UART would collide with the HK downlink.** The SDK default stdio UART
is `uart0` on GP0/GP1 - the exact UART and pins `hw/uart_io.c` uses for framed
HK. `pico_enable_stdio_uart` must stay **0** or a `printf` corrupts telemetry.
USB stdio is on instead, which also brings the picotool reset interface, so
reflashing needs no BOOTSEL - but `pico_enable_stdio_usb` alone is inert
without a `stdio_init_all()` call: the driver is compiled and then discarded,
which looks exactly like success.

**PyQt5 aborts the process** on an unhandled exception in a slot.
`clouds_ui/window.py` calls `set_times_us()` / `grab()` from a timer slot
without a guard, so a driver that raises there kills the window — never make a
driver method fail where the UI cannot handle it. The flight half's own timer
slot (`_tick_flight`) is wrapped for exactly this reason: a downlink problem
must not be able to take the instrument half down with it.

**`socketserver.shutdown()` blocks forever if `serve_forever()` never ran.**
Guard `stop()` on "was it started", or an error path unwinding before `start()`
hangs the app instead of exiting.

**A command ACK is only worth what enforced it.** Before `core/link.c` the
MCU acted on any `CMD_RELEASE` that passed CRC-16, and the Pi answered ground
`OK` as soon as it had written to the UART - so a release the MCU ignored
(wrong state, already fired) and one it never received looked identical to a
success on the console. The rule now: each end answers with what *it* decided,
and the Pi waits for the MCU's answer before speaking for it.

**Sequence numbers are per packet type**, on both the MCU (`hk_seq_no`,
`ev_seq_no`) and the Pi (`Downlink._next_seq`). A single shared counter makes
every interleaved packet of another type look lost. `EVENT` has two independent
emitters (MCU-relayed and Pi-origin), so it is in
`clouds_link.frames.UNSEQUENCED_TYPES`: counted, never charged as loss.

**On the Pi, `pkill -f` / `pgrep -f` match your own command line** — including
strings inside `echo`. Bracket the pattern (`"clouds_fs[w].main"`) *and* keep the
literal name out of surrounding messages, or the shell kills itself mid-script.

## Bench setup (PC ↔ Pi)

Direct Ethernet, no switch, no DHCP, no gateway — host-to-host only, so both
machines keep their normal default route (the Pi's internet is `wlan0`).

| End | Address | Ports |
|---|---|---|
| PC (ground) | `192.168.100.1/24` static | — |
| Pi (experiment) | `192.168.100.10/24` static, `eth0` | UDP 4000 downlink, TCP 4001 commands, TCP 4010 bench frames |

Addresses match `FswConfig.ground_host` and the GSE `--experiment` default, so
both run with no host flags. `pi.local` resolves to the **WiFi** address —
address `192.168.100.10` explicitly for the cable, and check `$SSH_CONNECTION`.
Pi config is persistent in `/etc/netplan/90-NM-75a1216a-*.yaml`.

**The bench Pi is a Raspberry Pi 4 Model B Rev 1.2**, not the Pi 5 the SED
and every README baseline (`cat /proc/device-tree/model`). It matters for the
UART: the Pi 5 route is `dtparam=uart0=on` / the `uart0-pi5` overlay, while
what this board needed was the Pi-4 route below. Same disagreement class as
the IMU - hardware and document differ, and the document is the one that has
not been updated.

**Enabling the RP2350 UART on the bench Pi** took three changes and two
reboots, and the intermediate state looks like success:

```sh
# /boot/firmware/config.txt
enable_uart=1
dtoverlay=disable-bt        # without this serial0 -> ttyS0, the mini-UART
# /boot/firmware/cmdline.txt: drop console=serial0,115200
```

`enable_uart=1` alone gives `/dev/serial0 -> ttyS0`: the **mini-UART**, whose
baud follows the core clock, with Bluetooth holding the PL011 as `ttyAMA1`.
There is no `/dev/ttyAMA0` at all in that state, so `uart_port` in
`/etc/clouds/fsw.json` fails and the service crash-loops. `disable-bt` frees
the PL011 and `serial0 -> ttyAMA0` appears. Then delete the `--no-uart` in
`/etc/systemd/system/clouds-fsw.service.d/10-bench.conf`, which exists only
for a Pi with no MCU wired.

Pi is **Debian 13 / Python 3.13, PEP 668** — install deps with apt
(`python3-numpy python3-scipy python3-serial`), not pip; pip would build scipy
from source on ARM. Deployment lives in `/opt/clouds` with `clouds_fsw/`,
`clouds_link/`, `spectro/` side by side and **`calibration.json` as a sibling of
`spectro/`** (`_DEFAULT_JSON` resolves to `spectro/../calibration.json`).
Vendor library: `/usr/local/lib/libe9u_LSMD.so` via
`drivers/e9u_LSMD_LIB_Linux/install.sh`.

## Conventions

- **The bench runs the same settings as flight.** `sample_interval_s` is 1 Hz in
  both — never tune it up for bench use. For a faster trace use the exclusive
  `spectro.net_server`, not a settings change. The one shared-hardware exception
  is exposure: a bench client changes it on the real detector, so it is logged
  and the configured `exposure_us` is restored when the last client disconnects.
- Calibration lives in `calibration.json`, never hardcoded in the UI.
- Storage first, then downlink (O.3) — see `FlightApp._on_spectrum`.
- Don't commit unless asked; the default branch is `main`.
- New hardware findings belong in `docs/`, with the measurement that showed it.
