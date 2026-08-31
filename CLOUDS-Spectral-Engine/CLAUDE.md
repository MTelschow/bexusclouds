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

```sh
# bench panel (detector on this machine)
python clouds_spectral.py               # real Duo
python clouds_spectral.py --edu         # single-channel EDU board (Windows only)
python clouds_spectral.py --mock        # synthetic, no hardware
python clouds_spectral.py --net 192.168.100.10    # detector on the Pi

# flight app (on the Pi, from /opt/clouds)
python3 -m clouds_fsw.main --config /etc/clouds/fsw.json
python3 -m clouds_fsw.main --mock                  # mock spectrometer + UART stub
python3 -m clouds_fsw.main --no-uart               # real detector, no RP2350 wired
python3 -m clouds_fsw.main --no-uart --bench-stream  # + serve the live panel

# ground station
python -m clouds_gse.main --gui --experiment 192.168.100.10

# checks — run all three before committing
python -m pytest tests/                 # 150+ tests, no hardware needed
python verify.py                        # driver + calibration self-checks
python -u verify_qt.py                  # offscreen UI; must end "VERIFY OK"
flight/mcu/test/run_native.sh           # firmware core (C, host compiler)
```

```sh
# RP2350 firmware (details + macOS toolchain trap in flight/mcu/README.md)
export PICO_SDK_PATH=~/pico-sdk PICO_TOOLCHAIN_PATH=~/arm-gnu-toolchain
cmake -S flight/mcu -B flight/mcu/build -DPICO_PLATFORM=rp2350 -DPICO_BOARD=pico2
cmake --build flight/mcu/build -j8
picotool load -f -x flight/mcu/build/clouds_fsw_mcu.uf2   # -f: no BOOTSEL needed
```

## Which GUI — read this before "opening the GUI"

| Goal | Use | Rate |
|---|---|---|
| **look at the detector**, see it respond to light | `clouds_spectral.py --net <pi>` (`run_clouds_spectral_pi.bat`) | continuous |
| flight **downlink**: HK, events, commanding, budget | `clouds_gse.main --gui` | quick-look 1 Hz, binned |

The GSE dashboard is **not** a live instrument view: each quick-look is
mean-binned to 29+31 points per channel (`quicklook_bin` 8) rather than the
2048-px trace, and its HK grid stays empty without the RP2350.
`quicklook_interval_s` is **1.0 s — the 2 kbit/s budget maximum** (1.814 kbit/s
with HK), and it is the only knob that spends downlink budget:
`sample_interval_s` and `exposure_us` are independent of it.

**That 1 Hz depends on HK staying lean.** The budget leaves ~83 B for a framed
HK packet, i.e. an **HK payload ceiling of 67 B**; `hk.SIZE` is 44 B today. The
spec originally allowed ~180 B, at which size 1 Hz quick-look totals
~2.9 kbit/s and busts the limit. Grow `Housekeeping` past 67 B and you must bin
the quick-look harder or slow its cadence —
`tests/test_fsw_telemetry.py::TestDownlinkBudget` fails first, by design.
That is correct behaviour, but it looks broken if you wanted the instrument.
"The GUI" in this project means the **bench panel**.

## Architecture

- **Strict driver/UI split.** UI and FSW talk only to
  `spectro.driver.SpectrometerDriver` via `open_driver(mock=, kind=)`. Kinds:
  `std` (Duo), `edu` (EDU board), `net` (remote — `spectro/net_driver.py` over
  TCP to `spectro.net_server` or the FSW's `--bench-stream`). Construction must
  stay side-effect-free; reaching hardware is `connect()`'s job
  (`tests/test_driver_factory.py` enforces this).
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

| What | Where | State |
|---|---|---|
| i2c0 | **SDA GP28, SCL GP29** (not GP12/13, which are unconnected) | BME280 `0x76` is the only usable sensor |
| INA226 ×3 | `0x40` 24 V, `0x44` 5 V, `0x45` 3.3 V | live, but **no field in the 44-byte HK** |
| BNO055 IMU | `0x28` | answers with valid chip id / SW rev; **sub-sensor IDs read 0x00**, unusable |
| Membrane solenoid | **GP26** (not GP8, unconnected) | **2 Hz**, loop-toggled via `core/sqwave` |
| CaCO₃ dispersion motor | **GP17 fwd / GP18 rev** | one 5 s scheduled pulse per release; runs concurrently with the membrane, measured; **not in the SED**, reverse sense untested, **current unmeasured - not on any monitored rail** |
| STLM20 ×2 | none | **not populated**; the old `ADC_TEMP1` collided with GP26 |
| Keller 23SY ×2 | none | **absent at every address** |
| SD / SPI0 | **pinout unknown**; the old map's GP17/GP18 drive the motor | no card answered `CMD0` there; defines deleted, **M-11 blocked on the schematic** |

So `p_ch_pa`, `rh2_cpct`, `temp1/2_cc` and the IMU vectors have **no source**.
They are declared through `error_flags` (`HKE_*` in `core/frame.h`, `HkErrors`
in `clouds_link/hk.py`, kept in step by a mirror test) rather than filled with
invented numbers. The SED baselines no IMU at all while risk MS002 is "IMU
failure" - hardware and document disagree.

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
`clouds_spectral.py` calls `set_times_us()` / `grab()` from a timer slot without
a guard, so a driver that raises there kills the panel — never make a driver
method fail where the UI cannot handle it.

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
