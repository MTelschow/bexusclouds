# Traps that have cost real time

Moved out of `CLAUDE.md` 2026-09-18. Each entry is a failure that already
happened here and looked like something else while it did.

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
