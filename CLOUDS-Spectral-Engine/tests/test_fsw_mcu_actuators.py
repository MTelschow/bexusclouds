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

    def test_hw_layer_never_sleeps(self):
        hw = _read("src", "hw", "hw.c")
        offenders = BLOCKING_CALL.findall(hw)
        assert not offenders, (
            "blocking delay in the hw layer: %s - use pulse_request() so the "
            "drive is released by the main loop" % offenders)

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
