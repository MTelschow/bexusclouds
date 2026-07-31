"""FSW-PI spectrometer source: 1 Hz cadence, flags, reconnect (P.3, P-10)."""
import threading
import time

import numpy as np
import pytest

from spectro.calibration import Calibration
from spectro.driver import DeviceInfo, DriverError, SpectrometerDriver
from clouds_fsw.spectro_source import SpectroSource
from clouds_fsw.storage import FLAG_MOCK, FLAG_SATURATED


class ScriptedDriver(SpectrometerDriver):
    """Driver whose behaviour is scripted per call - failure injection."""

    def __init__(self, fail_connects=0, fail_after=None, saturate=False):
        self.fail_connects = fail_connects
        self.fail_after = fail_after
        self.saturate = saturate
        self.grabs = 0
        self.exposure_history = []

    def connect(self):
        if self.fail_connects > 0:
            self.fail_connects -= 1
            raise DriverError("no camera")
        return DeviceInfo(model="scripted", mock=True)

    def set_times_us(self, exposure_us, frame_us=None):
        self.exposure_history.append(exposure_us)

    def grab(self, discard=0):
        self.grabs += 1
        if self.fail_after is not None and self.grabs > self.fail_after:
            raise DriverError("usb dropped")
        level = 65520 if self.saturate else 5000
        return np.full(2048, level, dtype=np.uint16)

    def close(self):
        pass


def _collect(source, n, timeout=5.0):
    got = []
    done = threading.Event()

    def on_frame(t, counts, exp, flags):
        got.append((t, counts, exp, flags))
        if len(got) >= n:
            done.set()
    source._on_frame = on_frame
    source.start()
    done.wait(timeout)
    source.stop()
    return got


def _source(driver, **kw):
    kw.setdefault("interval_s", 0.02)
    kw.setdefault("reconnect_s", 0.02)
    return SpectroSource(driver_factory=lambda: driver,
                         calibration=Calibration.load(),
                         on_frame=lambda *a: None, **kw)


class TestSpectroSource:
    def test_frames_delivered_with_mock_flag(self):
        got = _collect(_source(ScriptedDriver()), 3)
        assert len(got) >= 3
        _, counts, exp, flags = got[0]
        assert counts.shape == (2048,) and exp == 100_000
        assert flags & FLAG_MOCK

    def test_saturation_flagged(self):
        got = _collect(_source(ScriptedDriver(saturate=True)), 2)
        assert all(f & FLAG_SATURATED for *_, f in got)

    def test_reconnect_after_connect_failures(self):
        driver = ScriptedDriver(fail_connects=2)
        got = _collect(_source(driver), 2)
        assert len(got) >= 2   # survived two failed connects (P-10)

    def test_reconnect_after_grab_failure(self):
        statuses = []
        driver = ScriptedDriver(fail_after=2)
        src = _source(ScriptedDriver())   # placeholder, replaced below
        src = SpectroSource(driver_factory=lambda: driver,
                            calibration=Calibration.load(),
                            on_frame=lambda *a: None,
                            interval_s=0.02, reconnect_s=0.02,
                            on_status=statuses.append)
        src.start()
        deadline = time.time() + 5.0
        while time.time() < deadline and statuses.count(True) < 2:
            time.sleep(0.02)
        src.stop()
        # connected -> lost (grab fail) -> reconnected
        assert statuses[:3] == [True, False, True]
        assert src.errors >= 1

    def test_auto_exposure_reduces_on_saturation(self):
        driver = ScriptedDriver(saturate=True)
        src = _source(driver, auto_exposure=True)
        _collect(src, 3)
        assert min(driver.exposure_history) < 100_000

    def test_fixed_exposure_by_default(self):
        driver = ScriptedDriver(saturate=True)
        _collect(_source(driver), 3)
        assert driver.exposure_history == [100_000]   # only the initial set
