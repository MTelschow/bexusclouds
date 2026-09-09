"""FSW-MCU actuator path: no blocking drive can outlive the watchdog (S.9).

`flight/mcu/src/hw/` is the one part of the firmware the native suite cannot
compile (it needs the Pico SDK), so the invariant is guarded here at source
level instead: VALVE_PULSE_MS (5 s) is longer than WATCHDOG_TIMEOUT_MS (2 s),
therefore a drive must be *scheduled* (`core/pulse`) and never slept through.
A blocking pulse resets the MCU mid-actuation and, because the fired bit is
persisted first, the resume path would fire a second time.

The timing behaviour itself is tested natively in
`flight/mcu/test/test_core/test_main.c`.
"""
import glob
import os
import re

import pytest

MCU = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "flight", "mcu")

BLOCKING_CALL = re.compile(r"\b(sleep_ms|sleep_us|busy_wait_\w+|sleep_until)\s*\(")


def _read(*parts):
    with open(os.path.join(MCU, *parts), encoding="utf-8") as fh:
        return fh.read()


def _define(text, name):
    m = re.search(r"^#define\s+%s\s+(\d+)" % name, text, re.M)
    assert m, "%s is not defined" % name
    return int(m.group(1))


@pytest.fixture(scope="module")
def board():
    return _read("src", "hw", "board.h")


class TestNoBlockingActuation:
    def test_pulse_outlives_the_watchdog(self, board):
        """The premise: if this ever stops holding, revisit the design."""
        assert _define(board, "VALVE_PULSE_MS") > _define(board,
                                                          "WATCHDOG_TIMEOUT_MS")

    @pytest.mark.parametrize("src", sorted(
        os.path.basename(p) for p in glob.glob(os.path.join(MCU, "src", "hw",
                                                            "*.c"))))
    def test_hw_layer_never_sleeps(self, src):
        """Every file in src/hw/, not just hw.c: the 1 Hz sweep runs under the
        same 2 s watchdog whether the delay hides in an actuator path or in a
        sensor driver."""
        offenders = BLOCKING_CALL.findall(_read("src", "hw", src))
        assert not offenders, (
            "blocking delay in src/hw/%s: %s - schedule the work across loop "
            "passes instead of sleeping" % (src, offenders))

    def test_drives_go_through_the_scheduler(self):
        hw = _read("src", "hw", "hw.c")
        # every actuator op schedules; none touches gpio_put directly
        for op in ("ops_fire_pinch", "ops_close_eq_valves", "ops_disperse"):
            body = hw.split("static void %s" % op, 1)[1].split("\n}", 1)[0]
            assert "pulse_request(" in body, "%s does not schedule" % op
            assert "gpio_put(" not in body, "%s drives a pin directly" % op

    def test_main_loop_services_the_drives(self):
        main = _read("src", "main.c")
        # pulses only end if the loop keeps calling this
        assert "hw_actuators_service(" in main
        loop = main.split("for (;;)", 1)[1]
        assert "hw_actuators_service(" in loop
        assert "hw_watchdog_kick(" in loop


class TestSensorFailureIsSafe:
    """M-09: a failed sensor read must not look like flight.

    `autonomy_step` detects launch from a *drop* below
    `p_ground_pa - PARAM_LAUNCH_DP_PA`, so reporting 0 Pa when the BME280
    read fails would mimic a 100 kPa fall and trip launch detection on the
    bench - firing valves. The hardware layer must hold the last good value
    instead, and say so via HKE_P_AMB_STALE.
    """

    def test_failed_read_holds_pressure_and_flags_it(self):
        hw = _read("src", "hw", "hw.c")
        body = hw.split("void hw_read_sensors", 1)[1]
        fallback = body.split("} else {", 1)[1].split("}", 1)[0]
        assert "last_p_amb_pa" in fallback, (
            "the failure path must hold the last good ambient pressure")
        assert "HKE_P_AMB_STALE" in fallback, (
            "a held pressure must be flagged so ground can see it is stale")
        assert not re.search(r"p_amb_pa\s*=\s*0\b", fallback), (
            "never report 0 Pa on failure: it reads as a launch")

    def test_cold_start_pressure_is_not_low(self):
        """Before any successful read the held value must be high: launch
        detection needs a fall, so a high default cannot trigger it."""
        hw = _read("src", "hw", "hw.c")
        assert _define(hw, "P_AMB_COLD_START_PA") >= 100000


class TestErrorFlagsMirror:
    """X-01: the HKE_* bits are one schema across MCU, Pi and GSE."""

    def test_c_and_python_error_bits_agree(self):
        from clouds_link.hk import HkErrors

        frame_h = _read("src", "core", "frame.h")
        c_bits = dict(
            (m.group(1), int(m.group(2)))
            for m in re.finditer(r"#define HKE_(\w+) \(1u << (\d+)\)", frame_h))
        py_bits = dict((e.name, e.value.bit_length() - 1) for e in HkErrors)
        assert c_bits == py_bits, (
            "frame.h HKE_* and clouds_link.hk.HkErrors disagree: %s vs %s"
            % (c_bits, py_bits))


class TestActuatorStatusMirror:
    """The HKV_* bits are one schema across MCU, Pi and GSE - and they are
    what the panel shows for a commanded drive, so a renumbered bit reports
    the wrong actuator to the operator."""

    def test_c_and_python_valve_bits_agree(self):
        from clouds_link.hk import ValveStatus

        frame_h = _read("src", "core", "frame.h")
        c_bits = dict(
            (m.group(1), int(m.group(2)))
            for m in re.finditer(r"#define HKV_(\w+) \(1u << (\d+)\)", frame_h))
        py_bits = dict((e.name, e.value.bit_length() - 1) for e in ValveStatus)
        assert c_bits == py_bits, (
            "frame.h HKV_* and clouds_link.hk.ValveStatus disagree: %s vs %s"
            % (c_bits, py_bits))


class TestEventCodeMirror:
    """X-01: `enum seq_event` was the one C enum with no Python mirror, so
    every event reached the operator as a bare number - `[1] 12: membrane
    on`. Naming them is only safe if the two ends cannot drift."""

    def test_c_and_python_event_codes_agree(self):
        from clouds_link.frames import EventCode

        seq_h = _read("src", "core", "sequencer.h")
        body = seq_h.split("enum seq_event {", 1)[1].split("};", 1)[0]
        c_codes = dict(
            (m.group(1), int(m.group(2), 16))
            for m in re.finditer(r"EV_(\w+)\s*=\s*(0x[0-9A-Fa-f]+)", body))
        # The Pi's own codes (0x10..) have no C side; compare the MCU half.
        py_codes = dict((e.name, int(e)) for e in EventCode if e < 0x10)
        assert c_codes == py_codes, (
            "sequencer.h EV_* and clouds_link.frames.EventCode disagree: "
            "%s vs %s" % (c_codes, py_codes))

    def test_an_unknown_code_stays_readable(self):
        """A newer MCU must not blank out the event list on an older ground
        station: an unnamed code shows as its hex value."""
        from clouds_link.frames import event_name

        assert event_name(0x7f) == "0x7f"
        assert event_name(0x0c) == "MANUAL_DRIVE"


class TestActuatorStateReachesHousekeeping:
    """Both fields existed in HK for a long time while the MCU left them at
    zero, so the panel showed a membrane at 0 % and no valve activity while
    the hardware was moving. The operator drives are unusable without them:
    a 5 s motor pulse is over before anyone can see it any other way."""

    def test_membrane_duty_and_valve_status_are_filled(self):
        main = _read("src", "main.c")
        body = main.split("static void send_hk", 1)[1].split("\n}", 1)[0]
        assert re.search(r"hk\.membrane_duty\s*=\s*seq\.membrane_duty", body), (
            "HK must report the duty the sequencer commanded")
        assert re.search(r"hk\.valve_status\s*=\s*hw_actuator_status\(", body), (
            "HK must report which actuator line is energized")

    def test_actuator_status_reads_the_scheduler_not_a_shadow_copy(self):
        """The truth about what is driving lives in core/pulse: a separate
        flag set when a drive is *requested* would report a queued pulse as
        an active one, and stay set if the drive never ran."""
        hw = _read("src", "hw", "hw.c")
        body = hw.split("uint8_t hw_actuator_status", 1)[1].split("\n}", 1)[0]
        assert "pulses.active_pin" in body
        for pin in ("PIN_PINCH_1", "PIN_PINCH_2", "PIN_EQ1_CLOSE",
                    "PIN_EQ2_CLOSE", "PIN_DISPERSE_FWD"):
            assert pin in body, "%s has no HK bit" % pin


class TestManualActuatorDrives:
    """M-07 operator drives. The membrane and the motor are commandable from
    the panel; the safety rules that make that acceptable are asserted here
    so a later edit has to be deliberate about changing them."""

    def test_manual_drives_are_not_armed_or_ground_interlocked(self):
        from clouds_link.commands import (ARMED_COMMANDS, FLIGHT_ONLY,
                                          GROUND_INTERLOCKED,
                                          MANUAL_ACTUATORS, MCU_CONFIRMED,
                                          Command)

        assert MANUAL_ACTUATORS == {Command.MEMBRANE, Command.DISPERSE}
        for cmd in MANUAL_ACTUATORS:
            # Neither drive is irreversible, and driving them on the bench is
            # the point - unlike RELEASE, which stays armed and interlocked.
            assert cmd not in ARMED_COMMANDS
            assert cmd not in GROUND_INTERLOCKED
            assert cmd not in FLIGHT_ONLY
            # But ground must still hear the MCU's own verdict, not "the Pi
            # wrote to the UART".
            assert cmd in MCU_CONFIRMED
        assert Command.RELEASE in ARMED_COMMANDS & GROUND_INTERLOCKED

    def test_termination_and_safe_refuse_both_drives(self):
        """An abort must not be reversible from the panel. The behaviour is
        tested natively; this pins the states it keys off."""
        seq_c = _read("src", "core", "sequencer.c")
        body = seq_c.split("static bool actuators_commandable", 1)[1] \
                    .split("\n}", 1)[0]
        assert "ST_TERMINATION" in body and "ST_SAFE" in body
        for cmd in ("CMD_MEMBRANE", "CMD_DISPERSE"):
            case = seq_c.split("case %s:" % cmd, 1)[1].split("case ", 1)[0]
            assert "actuators_commandable(s)" in case, (
                "%s must be state-checked" % cmd)


class TestLinkSchemaMirror:
    """X-01: the Pi/GSE and the firmware must agree on the link vocabulary.

    These are the values a wrong edit breaks silently - a renumbered ACK
    result turns a refusal into an OK on the ground display, and a
    SET_PARAM key that means different things at each end writes the wrong
    threshold into a flight parameter.
    """

    def test_ack_results_agree(self):
        from clouds_link.frames import AckResult

        frame_h = _read("src", "core", "frame.h")
        block = re.search(r"enum ack_result \{(.*?)\};", frame_h, re.S)
        assert block, "enum ack_result is missing"
        c_vals = dict((m.group(1), int(m.group(2))) for m in
                      re.finditer(r"ACK_(\w+)\s*=\s*(\d+)", block.group(1)))
        py_vals = dict((e.name, int(e.value)) for e in AckResult)
        assert c_vals == py_vals, (
            "frame.h enum ack_result and clouds_link.frames.AckResult "
            "disagree: %s vs %s" % (c_vals, py_vals))

    def test_set_param_keys_agree(self):
        from clouds_link.commands import Param

        config_h = _read("src", "core", "config.h")
        c_vals = dict((m.group(1), int(m.group(2))) for m in
                      re.finditer(r"PARAM_(\w+)\s*=\s*(\d+)", config_h))
        py_vals = dict((e.name, int(e.value)) for e in Param)
        assert c_vals == py_vals, (
            "config.h enum param and clouds_link.commands.Param disagree: "
            "%s vs %s" % (c_vals, py_vals))

    def test_command_codes_agree(self):
        from clouds_link.commands import Command

        frame_h = _read("src", "core", "frame.h")
        block = re.search(r"enum command \{(.*?)\};", frame_h, re.S)
        c_vals = dict((m.group(1), int(m.group(2), 16)) for m in
                      re.finditer(r"CMD_(\w+)\s*=\s*(0x[0-9A-Fa-f]+)",
                                  block.group(1)))
        c_vals.pop("NONE", None)          # internal sentinel, never on the wire
        py_vals = dict((e.name, int(e.value)) for e in Command)
        assert c_vals == py_vals

    def test_arm_window_matches_the_pi(self):
        from clouds_link.commands import ARM_WINDOW_S

        link_h = _read("src", "core", "link.h")
        m = re.search(r"#define\s+LINK_ARM_WINDOW_MS\s+(\d+)", link_h)
        assert m, "LINK_ARM_WINDOW_MS is not defined"
        assert int(m.group(1)) == int(ARM_WINDOW_S * 1000), (
            "the MCU arm window must match ARM_WINDOW_S, or a release armed "
            "on the Pi can be NOT_ARMED on the MCU")

    def test_pi_silence_threshold_is_the_documented_60_s(self):
        """M-13: continue alone if the Pi is silent > 60 s. The Pi's own beat
        is TIMESYNC every 10 s, so the default must stay several beats wide."""
        config_c = _read("src", "core", "config.c")
        m = re.search(r"\[PARAM_PI_SILENT_S\] = \{(\d+),", config_c)
        assert m and int(m.group(1)) == 60


class TestPiLinkIsNeverAGate:
    """S.7: losing the Pi may not delay or prevent any state transition, so
    the liveness monitor must only ever touch flags and events."""

    def test_link_step_does_not_reach_the_sequencer(self):
        link_c = _read("src", "core", "link.c")
        for forbidden in ("seq_", "->ops", "fire_", "membrane", "enter("):
            assert forbidden not in link_c, (
                "core/link.c must not be able to act on the sequence: found "
                "%r" % forbidden)

    def test_uplink_drain_is_bounded(self):
        """Every command is answered with a blocking ACK write, so draining
        the UART without a bound lets a flood of frames hold the loop past
        the 2 s watchdog."""
        main_c = _read("src", "main.c")
        assert re.search(r"#define\s+MAX_FRAMES_PER_PASS\s+\d+u?", main_c)
        assert re.search(r"while\s*\([^)]*MAX_FRAMES_PER_PASS[^)]*"
                         r"uart_io_poll", main_c), (
            "the poll loop must be bounded, not a bare while(uart_io_poll())")

    def test_main_loop_does_not_condition_the_sequence_on_the_pi(self):
        main_c = _read("src", "main.c")
        # the HK step (which calls seq_step) must not sit behind a pi_ok test
        assert not re.search(r"if\s*\([^)]*pi_ok[^)]*\)\s*\{?\s*send_hk",
                             main_c)
        assert "MCUF_PI_OK" in main_c    # reported, though


class TestMembraneDrive:
    """M-07: the membrane must actually oscillate, and be off when idle.

    GP26 was measured driving the push-pull solenoid (a 0.5 Hz then 2 Hz
    square wave visibly actuated it); board.h previously named GP8, which is
    unconnected. The drive also used to run at the default divider with
    wrap=999, i.e. 150 kHz, where a solenoid only sees a DC average. The
    numeric side is tested natively in test_core/test_main.c; these guard the
    wiring the native build cannot compile.
    """

    def test_membrane_pin_is_the_measured_one(self, board):
        assert _define(board, "PIN_MEMBRANE_PWM") == 26

    def test_membrane_pin_is_de_energized_at_boot(self):
        """It must be an SIO output driven low by hw_init, not left to the
        external pull-down on the driver input."""
        hw = _read("src", "hw", "hw.c")
        body = hw.split("void hw_init", 1)[1]
        out_pins = body.split("out_pins[] = {", 1)[1].split("}", 1)[0]
        assert "PIN_MEMBRANE_PWM" in out_pins, (
            "the membrane pin must be driven low with the other actuators")

    def test_membrane_edges_are_released_by_the_loop(self):
        """At 2 Hz the drive is a repeating waveform, so the same rule as the
        valve pulses applies: edges come from hw_actuators_service, never from
        an interrupt or a free-running peripheral, so a hung loop cannot leave
        the solenoid energized."""
        hw = _read("src", "hw", "hw.c")
        body = hw.split("void hw_actuators_service", 1)[1].split("\n}", 1)[0]
        assert "sqwave_service" in body, (
            "the membrane waveform must be advanced from the loop")

    def test_membrane_below_pwm_floor_uses_the_loop_not_a_clamp(self):
        """The default is 2 Hz, under the PWM floor. Clamping it up to the
        floor would silently run the membrane at the wrong frequency."""
        hw = _read("src", "hw", "hw.c")
        body = hw.split("static void ops_membrane", 1)[1].split("\nstatic ", 1)[0]
        assert "pwmdiv_min_hz" in body and "sqwave_start" in body
        assert not re.search(r"hz\s*=\s*floor_hz", body), (
            "a sub-floor frequency must be toggled, not clamped")

    def test_membrane_frequency_comes_from_config(self):
        hw = _read("src", "hw", "hw.c")
        body = hw.split("static void ops_membrane", 1)[1].split("\n}", 1)[0]
        assert "PARAM_MEMBRANE_HZ" in body, (
            "frequency must come from config, not be left to the default "
            "divider - that is the 150 kHz bug")
        assert "pwmdiv_solve" in body or "membrane_program" in body
        assert not re.search(r"pwm_set_wrap\s*\(\s*\w+\s*,\s*999\s*\)", hw), (
            "wrap=999 with an unset divider is the 150 kHz regression")

    def test_membrane_off_releases_the_pin_low(self):
        """duty 0 must actively drive the pin low and stop the waveform, not
        merely disable the PWM slice and leave the pad to the external
        pull-down. Both off-paths go through the same helper."""
        hw = _read("src", "hw", "hw.c")
        body = hw.split("static void ops_membrane", 1)[1].split("\nstatic ", 1)[0]
        zero = body.split("duty_pct == 0", 1)[1].split("return;", 1)[0]
        assert "membrane_release_pin_low" in zero, (
            "duty 0 must go through the release helper")

        helper = hw.split("static void membrane_release_pin_low", 1)[1] \
                   .split("\n}", 1)[0]
        assert re.search(r"gpio_put\s*\(\s*PIN_MEMBRANE_PWM\s*,\s*0\s*\)",
                         helper), "the helper must drive the pin low"
        assert "sqwave_stop" in helper, (
            "the helper must stop the waveform, or the loop keeps toggling")
        assert "pwm_set_enabled" in helper


class TestDispersionMotor:
    """The CaCO3 dispersion motor on GP17/GP18, measured on the carrier.

    Driving GP17 high with GP18 low ran the motor. It is not in the SED, and
    the reverse sense was never verified, so the firmware drives only the
    forward line and holds the other low. GP17/GP18 used to be named as SD
    pins; those defines are gone, because an spi_init() on them would run the
    motor.
    """

    def test_pins_are_the_measured_pair(self, board):
        assert _define(board, "PIN_DISPERSE_FWD") == 17
        assert _define(board, "PIN_DISPERSE_REV") == 18

    def test_no_other_pin_claims_the_motor_lines(self, board):
        """The SD block owned GP17/GP18 on paper while the motor owns them in
        copper. Any define landing back on those numbers is that collision."""
        motor = {17, 18}
        for m in re.finditer(r"^#define\s+(PIN_\w+)\s+(\d+)", board, re.M):
            name, pin = m.group(1), int(m.group(2))
            if name.startswith("PIN_DISPERSE"):
                continue
            assert pin not in motor, (
                "%s maps to GP%d, which drives the dispersion motor" % (name,
                                                                        pin))

    def test_both_lines_are_de_energized_at_boot(self):
        """Unlike the membrane's driver input, these pins have no measured
        external pull: before hw_init they float and the motor's state is
        whatever its driver makes of that."""
        hw = _read("src", "hw", "hw.c")
        body = hw.split("void hw_init", 1)[1]
        out_pins = body.split("out_pins[] = {", 1)[1].split("}", 1)[0]
        for pin in ("PIN_DISPERSE_FWD", "PIN_DISPERSE_REV"):
            assert pin in out_pins, "%s must be driven low at boot" % pin

    def test_drive_is_scheduled_forward_only_and_interlocked(self):
        hw = _read("src", "hw", "hw.c")
        body = hw.split("static void ops_disperse", 1)[1].split("\n}", 1)[0]
        assert re.search(
            r"pulse_request\(&pulses,\s*PIN_DISPERSE_FWD,\s*PIN_DISPERSE_REV\)",
            body), ("the forward line must be driven with the reverse line as "
                    "its interlock, so the pair is never energized together")

    def test_the_queue_has_a_slot_for_both_new_lines(self):
        """A dropped request is an actuation that silently never happens."""
        pulse_h = _read("src", "core", "pulse.h")
        assert _define(pulse_h, "PULSE_SLOTS") >= 8

    def test_the_sequencer_disperses_on_every_release(self):
        """Same failure mode as the GP8 membrane bug: a drive nothing calls
        looks like working firmware and does nothing in flight."""
        seq = _read("src", "core", "sequencer.c")
        body = seq.split("static void fire(", 1)[1].split("\n}", 1)[0]
        assert "disperse" in body, (
            "fire() must run the dispersion motor, or the motor never turns "
            "in flight")
        assert "!= NULL" in body, (
            "disperse is optional - a board without the motor must still "
            "sequence")


class TestUnsourcedSensorsAreFlagged:
    """A missing sensor must report nothing plus a flag, never a fabricated
    reading from a floating input."""

    def test_no_adc_sampling_while_stlm20_is_unpopulated(self):
        hw = _read("src", "hw", "hw.c")
        assert "adc_read()" not in hw, (
            "sampling an unconnected pin yields a confident wrong temperature")
        assert "adc_gpio_init" not in hw

    def test_temperatures_are_flagged_unsourced(self):
        hw = _read("src", "hw", "hw.c")
        body = hw.split("void hw_read_sensors", 1)[1]
        assert "HKE_NO_TEMP" in body

    def test_membrane_pin_does_not_collide_with_an_adc_channel(self, board):
        """GP26 cannot be both the solenoid and ADC_TEMP1."""
        pin = _define(board, "PIN_MEMBRANE_PWM")
        for name in ("ADC_TEMP1", "ADC_TEMP2"):
            m = re.search(r"^#define\s+%s\s+(\d+)" % name, board, re.M)
            if m:
                assert 26 + int(m.group(1)) != pin, (
                    "%s maps to GP%d, which is the membrane pin"
                    % (name, 26 + int(m.group(1))))


class TestRailMonitors:
    """M-09: the INA226 rails are the health of the power tree, and the amps
    are the half of it that depends on an assumption."""

    def test_no_calibration_register_is_programmed(self):
        """The part can compute current itself, from a calibration register
        holding the shunt resistance. Programming that would bake the shunt
        value into every downlinked amp - and if the value is wrong, nothing
        on the ground can undo it. The raw shunt voltage goes down instead."""
        ina = _read("src", "hw", "ina226.c")
        assert "REG_CAL" not in ina
        assert not re.search(r"write_reg\([^;]*0x0?5", ina), (
            "register 0x05 is the calibration register: leave it unprogrammed")
        assert "REG_SHUNT_V" in ina, "the shunt voltage is what ground needs"

    def test_a_rail_reports_voltage_and_current_or_neither(self):
        """A shunt reading kept next to an invalid rail_mv is a current for a
        rail whose voltage is unknown, and a display has no way to say so."""
        hw = _read("src", "hw", "hw.c")
        body = hw.split("void hw_read_sensors", 1)[1]
        loop = body.split("INA_RAIL_COUNT", 1)[1]
        ok, fail = loop.split("} else {", 1)
        assert "ina226_read_bus_mv" in ok and "ina226_read_shunt_raw" in ok
        assert "&&" in ok, "both reads must have to succeed together"
        assert "RAIL_MV_INVALID" in fail and "shunt_raw[i] = 0" in fail
        assert "HKE_RAIL_FAIL" in fail

    def test_the_shunt_register_keeps_its_sign(self):
        """Current can flow either way through a shunt: a rail pushing back
        into its supply is real data, and an unsigned read would report it as
        a large forward current instead."""
        ina = _read("src", "hw", "ina226.c")
        body = ina.split("ina226_read_shunt_raw", 1)[1]
        assert "(int16_t)" in body
        assert "0x7FFF" not in body, (
            "masking the top bit off would discard the sign, not the noise")
