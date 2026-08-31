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
