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
        for op in ("ops_fire_pinch", "ops_close_eq_valves"):
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
        hw = _read("src", "hw", "hw.c")
        body = hw.split("static void ops_membrane", 1)[1].split("\n}", 1)[0]
        zero = body.split("duty_pct == 0", 1)[1].split("return;", 1)[0]
        assert "gpio_put" in zero and "0" in zero, (
            "duty 0 must actively drive the pin low")


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
