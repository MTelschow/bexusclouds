# Traps that have cost real time

Moved out of `CLAUDE.md` 2026-09-18. Each entry is a failure that already
happened here and looked like something else while it did.

**Never drain a free-running PIO FIFO "until empty".** The encoder counter
(`hw/quadrature_encoder.pio`) pushes its count every ~7 PIO cycles, faster
than the CPU can pop, so `while (!pio_sm_is_rx_fifo_empty()) pio_sm_get()`
never exits. On the carrier (2026-09-28) that looked like a dead board: no HK
on the Pi, USB CDC appearing and vanishing - a 2 s watchdog reset loop. Read
`pio_sm_get_rx_fifo_level()` once and pop that many. `picotool load -x
<uf2> --ser <serial> -f` still catches the board in its brief USB window.

**New HK fields read "no data" when the carrier runs an older image.** The
ground decodes a shorter known layout rather than dropping it, so after an
HK change and no reflash the panel looks healthy and the new rows just say
"no data", which reads as a sensor fault (2026-09-28, chamber BNO055). Check
`link.hk_reject_reason` in `gse_sessions/session_*_summary.json`, or listen on
UDP 4000 with the GUI closed and compare `len(payload)` with `hk.SIZE`. The Pi
forwards raw HK frames, so only the MCU needs reflashing.

**GP28/GP29 are not 0x28/0x29.** GP28/GP29 are i2c0's SDA/SCL pins, which
every part on the bus shares. 0x28/0x29 are the chamber/ambient BNO055
addresses. The numbers coincide, nothing more; `bno055_probe` settles what
is actually on the bus.

**Data scaling differs by platform.** The Windows DLL returns each sample
left-shifted into 16 bits (0..65520); the **Linux `.so` returns raw 12-bit**.
`spectro/eureca_driver.py` normalises Linux up (`grab()` and `dark_value()`
share the shift; `CLOUDS_E9U_COUNT_SHIFT=0` disables). Without it every
`saturation_count` threshold breaks: clipping is undetectable and the P-09
exposure servo only ever ramps up. See `docs/CALIBRATION.md`.

**The Pi runs `/opt/clouds`, not your working tree.** On 2026-09-18 the panel
clipped at every exposure and the driver in the repo already had the fix:
`/opt/clouds/spectro/{driver,eureca_driver}.py` were two weeks older than the
rest of the deployment, so the flight app imported the pre-fix driver while
`git log` said the bug was solved. The frames it serves over `--bench-stream`
come from *that* copy. Before debugging detector behaviour from the panel,
compare what is deployed against the tree — `md5sum` both, or `grep` for the
symbol you just added — and redeploy `spectro/` before concluding anything.

**The camera's own `minimum_exposure()` is not a minimum.** It reports 10 µs;
below ~60 µs the camera stops running integrations and hands back either a
frame collapsed to ~1 700 ct (covered gap included) or the previous exposure
again, with the frame counter advancing either way. An exposure servo asked to
escape a bright scene walks straight into that hole and reads whatever comes
back as a measurement. The floor is `spectro/driver.py`'s `MIN_EXPOSURE_US`
(100 µs), enforced in the driver and used as the UI rail. `docs/HARDWARE.md`.

**"The first frame after a pause carries the pause" did not reproduce.** The
idle-flush in `grab()` was written against that theory (see `docs/DRIVER.md`).
Re-measured 2026-09-18 on S/N 20260312-004 at 100 µs / 1 ms / 10 ms, one grab
1.0 s after the previous readout against three back to back: **equal within
noise**, with the flush on, off (`CLOUDS_E9U_FLUSH=0`) and on the pre-fix
driver that never had one. So it is not the explanation for a saturated live
trace, and the next such report should be measured before the flush is
trusted to have handled it. The flush stays — it costs one frame per idle grab
and the original observation is not disproved for every firmware — but it is a
belt, not the diagnosis.

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

**The carrier does not enumerate through a hub.** On 2026-09-28 a reflash of
the RP2350 found no device at all: `picotool info -a` said "No accessible
RP-series devices in BOOTSEL mode were found", `/dev/cu.usbmodem*` did not
exist, and the Mac's `ioreg -p IOUSB` tree was byte-identical across a cable
swap and a BOOTSEL attempt - same registry ids, same busy timers, so nothing
had enumerated or de-enumerated either time. Plugged straight into the host it
came up immediately as `Pico@00100000` and `picotool load -f -x` flashed it
(serial `21DD2AE08840C863`). Two mid-session USB2 hubs was one too many.

The misleading part is that the board is *running* throughout: HK and `ACK`s
keep coming over the UART, so the MCU looks healthy from the Pi while being
unreachable for flashing. Diagnose with `ioreg -p IOUSB -w0 -l | grep '+-o '`,
not with the absence of a serial node - an unchanged tree across a replug means
the host never saw the event, which rules out the image and the BOOTSEL state
and leaves the physical path. A missing `stdio_init_all()` (below) produces the
same empty `picotool` result but *does* change the tree on replug.

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

**macOS dark mode leaks into every widget without a stylesheet colour.**
The Sensors readings were white on the white sidebar and half the spin boxes
drew black - and `verify_qt.py` never saw it, because offscreen Qt has no dark
mode. Setting the palette on the window was not enough: macOS registers
per-class application palettes that outrank inheritance, so the sidebar
under the splitter stayed white-on-white. `CloudsWindow.__init__` sets
`style.light_palette()` on the `QApplication` (which clears those) and on the
window. Check UI changes with a native (cocoa) grab, not only offscreen.

**A box layout's sizeHint ignores heightForWidth.** A sidebar column laid
out `AlignTop` gets its hint, and a section ending in a wrapped note wants
more; the deficit came out of the rows above (the timeline checkboxes ran
into each other). `SectionFlow.relayout` floors each column holder at
`column_heights()`. Separately, the macOS style sizes a `QCheckBox` from the
native indicator, not the 15 px styled one - `checkbox_style()` carries a
`min-height`.

**A styled `QCheckBox` paints 20 px tall and measures 13.** The `min-height`
above fixes what is *drawn*; on macOS it never reaches the *layout*. A
`QCheckBox` carrying `checkbox_style()` paints 20 px tall while its
`QWidgetItem` reports 13, so a `QGridLayout` at 2 px vertical spacing packed
the Timeline series toggles 16 px apart and every row overlapped the one below
it by 4 px. `setMinimumHeight`, `setFixedHeight` and removing the `min-height`
from the stylesheet all leave the layout item at 13 - only
`QGridLayout.setRowMinimumHeight` moves it, which is what `sections.ToggleGrid`
does (row = the box's polished `sizeHint().height()` + `TL_ROW_GAP`).
**Offscreen the layout item is 20 and none of this is visible**, so neither a
`QT_QPA_PLATFORM=offscreen` screenshot nor `verify_qt.py` on its default
platform can catch it. `verify_qt.py` carries the geometry assertion
("timeline: the series toggles do not overlap"); run it as
`QT_QPA_PLATFORM=cocoa python -u verify_qt.py` after touching the sidebar - the
platform is a `setdefault`. Measured 2026-09-28.

**A widget that has a layout cannot answer `heightForWidth`.** Qt5's
`QWidgetItem::heightForWidth` asks the widget's *layout*, never the widget, and
a plain `QGridLayout` answers -1. So overriding `heightForWidth` on a container
does nothing, and additionally advertising `hasHeightForWidth` makes the
enclosing box layout route the size hint through the same path and get 0 - the
Timeline section collapsed to its header alone. `ToggleGrid` therefore pins
`sizeHint()` to the arrangement at `SectionFlow.COL_W`, which is the narrowest
a sidebar column goes and so the tallest the group ever is: over-reporting
costs a row of air, under-reporting costs a scrollbar.

**`socketserver.shutdown()` blocks forever if `serve_forever()` never ran.**
Guard `stop()` on "was it started", or an error path unwinding before `start()`
hangs the app instead of exiting.

**A command ACK is only worth what enforced it.** The Pi used to answer ground
`OK` as soon as it had written to the UART - so a command the MCU ignored and
one it never received looked identical to a success on the console. The rule
now: each end answers with what *it* decided, and the Pi waits for the MCU's
answer before speaking for it. This matters more, not less, since the gates
were removed (2026-09-18): `OK` now means "executed", and the only refusal
left, `INVALID`, means the firmware could not act on the frame at all.

**Sequence numbers are per packet type**, on both the MCU (`hk_seq_no`,
`ev_seq_no`) and the Pi (`Downlink._next_seq`). A single shared counter makes
every interleaved packet of another type look lost. `EVENT` has two independent
emitters (MCU-relayed and Pi-origin), so it is in
`clouds_link.frames.UNSEQUENCED_TYPES`: counted, never charged as loss.

**On the Pi, `pkill -f` / `pgrep -f` match your own command line** — including
strings inside `echo`. Bracket the pattern (`"clouds_fs[w].main"`) *and* keep the
literal name out of surrounding messages, or the shell kills itself mid-script.

**`STOP` outlives the link.** Automatic mode (spec §5) is what runs the
experiment when ground is unreachable, and a `STOP` keeps it off - including
through the dropout that would have started it. That is deliberate: the
alternative is an operator's explicit "do nothing" being overridden by
silence. But it means an operator who stops and then loses the link has left
the electronics passive with no way to lift it. `MCUF_STOPPED` is in every HK
packet; check it before the link is the thing you are worried about.

Two follow-ons, both deliberate. A manual `MEMBRANE` or `DISPERSE` after a
`STOP` wakes the state out of `SAFE` - the hardware really is energized - but
does **not** lift the inhibit, so the panel can read `RUNNING` with
`MCUF_STOPPED` still set. Only `START` clears it. And `HOLD`/`RESUME`
(`0x02`/`0x03`) are retired as of 2026-09-28: an older ground station gets
`ACK_INVALID`, not a silent remap onto `STOP`, because an old `HOLD` asked
for the actuators to keep running and `STOP` shuts them off.


**Two parts on one SPI bus, two frame widths.** SPI_1 carries the chamber
BME280 (bytes) and the BMV080 (16-bit words: a header word then payload
words). `spi_set_format()` at bus init sets whichever the last driver to touch
the bus wanted, so it is not called there at all - `bme280.c` and
`bmv080_port.c` each set their own width inside `cs_select()`, before pulling
CS low. The failure if you hoist it back is not a clean one: the BME280 would
read plausible garbage compensated from a garbage trim block, and the BMV080's
library would report a chip-id mismatch that looks exactly like a wiring
fault.

**`PICO_STACK_SIZE` alone cannot give you a big stack on an RP2350.** The SDK
puts core 0's stack in SCRATCH_Y, which is 4 kB, so asking for 16 kB fails at
link time with `region SCRATCH_Y overflowed by 12288 bytes`. The BMV080's
vendor library wants 10 kB. The fix is to move the *regions*, not to override
the SDK's linker fragments: `set_memory_locations.incl` reads every origin and
length from a linker symbol if one is defined, so four `--defsym`s grow
SCRATCH_Y downward out of the scratch banks and shrink RAM to match, leaving
all of the SDK's `__StackTop` / `__StackLimit` / heap arithmetic correct -
including the `ASSERT(__StackLimit >= __HeapLimit)` that keeps the heap out of
it. `flight/mcu/CMakeLists.txt` has the numbers. Check `.scratch_x` /
`.scratch_y` are still 0 bytes in the map before doing this again: SCRATCH_X
is zero-length on purpose so a future `__scratch_x` placement fails the link
instead of landing inside the stack.

**Bosch ship two Cortex-M33 archives and only one links.** `arm_cortex_m33f`
is tagged `Tag_ABI_VFP_args: VFP registers` (hard float); the Pico SDK builds
RP2350 `-mfloat-abi=softfp`, so it wants the plain `arm_cortex_m33` archive,
which carries no VFP-args tag. Check with
`arm-none-eabi-readelf -A <lib_bmv080.a> | grep Tag_ABI_VFP_args`. And
`lib_bmv080.a` and `lib_postProcessor.a` reference each other's symbols, so
they go inside one `-Wl,--start-group … --end-group`: a single pass in either
order leaves undefined references.

**A particulate reading of 0 is not the absence of one.** Every other field on
this wire has a sentinel - `RAIL_MV_INVALID`, `HB_SENSE_INVALID`, a zeroed
vector behind a flag - because the absent case can be given a value no sensor
produces. 0 µg/m³ is what clean air reads, so the BMV080 has none available.
That is the whole reason `pm_status` exists as a byte, and why nothing may
render `pm2_5_ugm3` without consulting it: `hk.pm_text` and `hk.pm_measured`
are the only correct readers. A panel showing `0 ug/m3` for a dead sensor is
the one wrong answer nothing else on screen contradicts.

**A chip-select sweep that reads 0x00 everywhere tells you nothing about the
chip selects.** On 2026-09-28 the carrier's SPI_1 returned 0x00 for the
BME280's chip id on all four selects, in both modes, at both bauds, including
the bit-banged swapped-pair read, and 107 from `bmv080_open()` on every select.
The tempting reading is "wrong chip select, try the next one". Every select
returns the same answer when nothing is on the bus, so the sweep cannot
distinguish them. `tools/bme280_probe` now runs three bus-integrity tests
first, and those are the ones to read.

**Two ways a pin measurement lies, both found the same afternoon.**

*One: you measured your own peripheral.* The probe reported GP8 held low
against its internal pull-up. It was not the board — the other two bus pins
had been left on `GPIO_FUNC_SPI`, so `spi1`'s MOSI was idling low and reaching
GP8. **Park every pin not under test as a high-impedance input**
(`gpio_disable_pulls`, direction in, function SIO) or the reading is about the
SPI block, not the carrier.

*Two: an RP2350 floating pad does not read as a float.* One on this project
latched high against its own internal pull-down (2026-09-11,
`sensor-driver/pico_bringup`), and a latched high-impedance input is nudged by
a neighbour through a few pF — which a cross-short test reports as "TIED
TOGETHER" when nothing is tied, and a drive test reports as "cannot be driven
high". **Drive and cross-short results are meaningless until the net is known
not to be floating.** Settle that physically: unplug the harness and re-run
(output that does not change was never about the sensor), or fit an external
10 kΩ pull-up and see whether the pin then behaves. Do not go looking for a
solder bridge on the strength of a firmware test alone.

**An unconfigured RP2350 GPIO is not idle - it is a pulled-down input, and an
active-low chip select left there is asserted.** `PADS_BANK0_GPIOx` resets to
`0x116` (PDE=1). The flight image drove GP9 high before clocking SPI_1 and left
GP12 to a later driver and GP13/GP47 to nobody, so with parts fitted two
slaves would have been selected during the chamber BME280's bring-up and a
part behind an undriven select would never have seen a falling edge. **Park
every select on a bus as a driven-high output before the first clock edge**,
in `hw_init()` and in every probe tool, and name the unused selects in
`board.h` so the parking loop can reach them (2026-09-28,
`spi1_park_chip_selects`).

**Init-once drivers never recover a part that missed its boot probe.** A
`(void)bme280_init()` in `hw_init()` and a `dev->ready` that nothing sets
again means one I2C glitch at power-up, or a harness plugged in after boot,
is a sensor that stays failed until the next power cycle - and for the ambient
BME280 that is `p_amb_pa` pinned at the cold-start value behind
`HKE_P_AMB_STALE` for the whole flight. If the bring-up is a few
timeout-bounded transfers, re-run it from the sweep on a slow cadence
(`SENSOR_RETRY_MS`); if it sleeps (BMV080), it cannot be retried and the doc
must say so (2026-09-28).

**A single RS-422 leg on a GPIO counts, but not cleanly - time the edges
before believing a count.** The dispersion motor encoder's TIA-422 pairs reach
the carrier without a receiver. One leg (GP19) is a clean square wave with an
~80 ns low glitch on ~37 % of its periods (crosstalk from the legs that are
not on a pin): a raw edge count over-reads by a third, and the x4 decoder,
fed that plus a "B" that is really the resistor midpoint of both channels,
read 0 rpm on a turning shaft. Edge counts and a state histogram
(`encoder_pin_probe`) could not tell this apart; a timestamped trace
(`encoder_trace_probe`, 80 ns resolution, analysed on the host) settled it in
one run. Deglitch in the PIO (hold, re-read), sample direction only where the
midpoint is solid (the other channel's level at A's falling edge), and count
x1 (2026-09-28, `hw/quadrature_encoder.pio`).

**A host-side CDC reader opened before a reflash dies with the old port.**
`read failed: [Errno 6] Device not configured` - the device it opened was the
previous image's. The probes wait for `stdio_usb_connected()` before doing
anything, so nothing is lost: reopen after the reboot (or make the reader
retry on error).
