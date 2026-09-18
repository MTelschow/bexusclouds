"""Duo integration time: what the camera is asked for, and what it runs.

Hardware-free - the vendor library is replaced by `FakeLib`, which reproduces
the clamping in its own `set_times_us` (drivers/e9u_LSMD_LIB_Linux, macros.c):
frame time floored to a step multiple, raised to `minimum_frame`, then the
*exposure* clamped to no more than the frame time. That last clamp is why a
frame time equal to the exposure is not a harmless default, and the frame lag on
the exposure timestamps is why a timing change cannot be trusted on the next
frame.
"""
import ctypes

import pytest

from spectro import eureca_driver as ed
from spectro.eureca_driver import EurecaDriver

# the PRO on this bench (vendor type table, 0x02290003)
MIN_EXP, STEP_EXP, MIN_FRAME, STEP_FRAME = 10, 10, 3750, 10
LAG_FRAMES = 1          # frames before the camera reports a new exposure


class FakeLib:
    """The vendor library's timing behaviour, and nothing else."""

    def __init__(self, registers=True):
        self.reg_exp = MIN_FRAME            # start_camera_async leaves exp = frame = min
        self.reg_frame = MIN_FRAME
        self.hw_exp = MIN_FRAME             # what the camera's timestamps report
        self.pending = None                 # exposure waiting out its frame lag
        self.frames = 0
        self.asked = []                     # (exposure_us, frame_us) as passed in
        if not registers:                   # an older library: no register access
            self.e9u_LSMD_get_reg32 = None
            self.e9u_LSMD_diff32 = None

    # -- limits ---------------------------------------------------------
    def e9u_LSMD_minimum_exposure(self, cam):
        return MIN_EXP

    def e9u_LSMD_step_exposure(self, cam):
        return STEP_EXP

    def e9u_LSMD_minimum_frame(self, cam):
        return MIN_FRAME

    def e9u_LSMD_step_frame(self, cam):
        return STEP_FRAME

    # -- timing ---------------------------------------------------------
    def e9u_LSMD_set_times_us(self, cam, exp, frame):
        self.asked.append((exp, frame))
        frame = (frame // STEP_FRAME) * STEP_FRAME          # vendor floors
        frame = max(frame, MIN_FRAME)
        exp = frame if exp == 0 else min(exp, frame)        # vendor clamps to the frame
        exp = max((exp // STEP_EXP) * STEP_EXP, MIN_EXP)
        self.reg_exp, self.reg_frame = exp, frame
        self.pending = exp                                  # not live until a frame runs
        return 0

    def e9u_LSMD_get_next_frame(self, cam):
        self.frames += 1
        if self.pending is not None and self.frames > LAG_FRAMES:
            self.hw_exp, self.pending = self.pending, None
        return 0xF0

    def e9u_LSMD_get_reg32(self, cam, register, bank):
        if register == ed._REG_CH0_EXP_TIME:
            return self.reg_exp
        if register == ed._REG_CH0_FRAME_TIME:
            return self.reg_frame
        if register == ed._REG_T_STAMP_EXP_STOP:
            return self.hw_exp
        if register == ed._REG_T_STAMP_EXP_START:
            return 0
        return 0

    def e9u_LSMD_diff32(self, a, b):
        return a - b


def make_driver(monkeypatch, registers=True, flush=None):
    monkeypatch.setenv(ed._FLUSH_ENV, flush) if flush is not None else \
        monkeypatch.delenv(ed._FLUSH_ENV, raising=False)
    drv = EurecaDriver()
    lib = FakeLib(registers=registers)
    drv._lib = lib
    drv._ptr = ctypes.cast(ctypes.pointer((ctypes.c_uint16 * EurecaDriver.PIXELS)()),
                           ctypes.POINTER(ctypes.c_uint16))
    drv._read_limits()
    drv._exposure_us = lib.reg_exp
    drv._frame_us = lib.reg_frame
    return drv, lib


class TestFrameTime:
    """A frame time equal to the exposure is the exposure clamped by a readout."""

    def test_frame_time_leaves_room_for_the_readout(self, monkeypatch):
        drv, lib = make_driver(monkeypatch)
        drv.set_times_us(20_000)
        _exp, frame = lib.asked[-1]
        assert frame >= 20_000 + MIN_FRAME

    @pytest.mark.parametrize("us", [1_000, 3_750, 10_000, 100_000, 1_000_000])
    def test_the_exposure_register_keeps_what_was_asked_for(self, monkeypatch, us):
        drv, lib = make_driver(monkeypatch)
        drv.set_times_us(us)
        assert lib.reg_exp == us
        assert drv.exposure_us == us

    def test_frame_time_is_never_floored_below_the_exposure(self, monkeypatch):
        # a frame time that is not a step multiple used to survive as the vendor's
        # floor of it, which can land under the exposure and clamp it down
        drv, lib = make_driver(monkeypatch)
        drv.set_times_us(20_005)
        assert lib.reg_frame >= lib.reg_exp

    def test_short_exposure_still_gets_the_minimum_frame(self, monkeypatch):
        drv, lib = make_driver(monkeypatch)
        drv.set_times_us(500)                       # under minimum_frame
        assert lib.reg_exp == 500
        assert lib.reg_frame >= MIN_FRAME

    def test_an_explicit_frame_time_is_honoured(self, monkeypatch):
        drv, lib = make_driver(monkeypatch)
        drv.set_times_us(10_000, 50_000)
        assert lib.asked[-1] == (10_000, 50_000)

    def test_below_the_minimum_exposure_is_raised_not_silently_zeroed(self, monkeypatch):
        drv, lib = make_driver(monkeypatch)
        drv.set_times_us(1)
        assert lib.reg_exp == MIN_EXP               # 0 would mean "exposure = frame"

    def test_exposure_is_rounded_up_to_a_step_multiple(self, monkeypatch):
        drv, lib = make_driver(monkeypatch)
        drv.set_times_us(1_005)
        assert lib.reg_exp == 1_010                 # the vendor would have floored to 1000


class TestSettle:
    def test_a_new_exposure_is_live_before_set_times_returns(self, monkeypatch):
        drv, lib = make_driver(monkeypatch)
        drv.set_times_us(50_000)
        assert drv.measured_exposure_us() == 50_000

    def test_settling_costs_frames_not_an_infinite_wait(self, monkeypatch):
        drv, lib = make_driver(monkeypatch)
        before = lib.frames
        drv.set_times_us(50_000)
        assert 0 < lib.frames - before <= ed._SETTLE_MAX_FRAMES

    def test_no_register_access_means_no_wait(self, monkeypatch):
        drv, lib = make_driver(monkeypatch, registers=False)
        drv.set_times_us(50_000)
        assert lib.frames == 0                      # nothing to wait on, so nothing spent
        assert drv.measured_exposure_us() is None


class TestIdleFlush:
    """Async mode does not clock the line between triggers, so an idle gap is
    integrated. The frame that holds it must not be the frame we keep."""

    def test_first_grab_after_connect_flushes(self, monkeypatch):
        drv, lib = make_driver(monkeypatch)
        drv.grab()
        assert lib.frames == 2                      # one thrown away, one kept

    def test_back_to_back_grabs_do_not_flush(self, monkeypatch):
        drv, lib = make_driver(monkeypatch)
        drv.set_times_us(100_000)
        drv.grab()
        before = lib.frames
        drv.grab()
        assert lib.frames - before == 1

    def test_an_idle_gap_flushes(self, monkeypatch):
        drv, lib = make_driver(monkeypatch)
        drv.set_times_us(100_000)                   # 100 ms -> 10 ms of idle is enough
        drv.grab()
        before = lib.frames
        drv._last_read -= 0.5                       # a 1 Hz live loop's pause
        drv.grab()
        assert lib.frames - before == 2

    def test_explicit_discard_still_applies(self, monkeypatch):
        drv, lib = make_driver(monkeypatch)
        drv.set_times_us(100_000)
        drv.grab()
        before = lib.frames
        drv.grab(discard=2)
        assert lib.frames - before == 3

    def test_flush_can_be_switched_off(self, monkeypatch):
        drv, lib = make_driver(monkeypatch, flush="0")
        drv.set_times_us(100_000)
        before = lib.frames
        drv.grab()
        assert lib.frames - before == 1

    def test_flush_can_be_forced_on_every_grab(self, monkeypatch):
        drv, lib = make_driver(monkeypatch, flush="always")
        drv.set_times_us(100_000)
        drv.grab()
        before = lib.frames
        drv.grab()
        assert lib.frames - before == 2

    def test_a_reconnect_inherits_no_frame_history(self, monkeypatch):
        drv, lib = make_driver(monkeypatch)
        drv.grab()
        drv.close()
        assert drv._last_read is None
