"""calibration_edu.json: the single-channel 3648-px file --edu loads by default.

Guards the two ways this file can silently go wrong: drifting out of step with
the EDU board's real pixel count, or growing a reference channel it has no
fibre for (which would make the transmission view compute against noise).
"""
import os

import numpy as np
import pytest

from spectro.calibration import Calibration
from spectro.eureca_edu_driver import EurecaEduDriver

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDU_JSON = os.path.join(ROOT, "calibration_edu.json")


@pytest.fixture(scope="module")
def cal():
    return Calibration.load(EDU_JSON)


class TestEduCalibration:
    def test_file_is_shipped(self):
        assert os.path.isfile(EDU_JSON)

    def test_pixel_count_matches_the_driver(self, cal):
        assert cal.n_pixels == EurecaEduDriver.PIXELS == 3648

    def test_single_channel_no_reference(self, cal):
        assert len(cal.channels) == 1
        assert cal.by_role("measurement") is not None
        assert cal.by_role_optional("reference") is None

    def test_window_covers_the_whole_detector(self, cal):
        assert cal.channels[0].pixel_window == (0, cal.n_pixels - 1)

    def test_wavelengths_monotonic_and_in_range(self, cal):
        wl = cal.channels[0].wavelengths
        assert len(wl) == cal.n_pixels
        assert np.all(np.diff(wl) > 0)
        lo, hi = cal.channels[0].range_nm
        assert wl[0] == pytest.approx(lo, abs=1.0)
        assert wl[-1] == pytest.approx(hi, abs=1.0)

    def test_slicing_a_full_edu_frame_keeps_every_pixel(self, cal):
        frame = np.arange(EurecaEduDriver.PIXELS, dtype=np.uint16)
        assert np.array_equal(cal.channels[0].slice(frame), frame)

    def test_declares_itself_a_placeholder(self, cal):
        # the geometry is a hardware fact, the polynomial is not - keep it labelled
        assert "PLACEHOLDER" in cal.source.upper()


class TestDuoCalibrationUnchanged:
    def test_duo_default_still_dual_channel_2048(self):
        duo = Calibration.load(os.path.join(ROOT, "calibration.json"))
        assert duo.n_pixels == 2048
        assert duo.by_role_optional("reference") is not None
