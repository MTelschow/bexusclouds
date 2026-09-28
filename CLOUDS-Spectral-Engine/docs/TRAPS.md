# Traps that have cost real time

Moved out of `CLAUDE.md` 2026-09-18. Each entry is a failure that already
happened here and looked like something else while it did.

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

