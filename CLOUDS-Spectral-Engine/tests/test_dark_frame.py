"""The stored dark frame: roundtrip, and the two ways it must refuse itself.

A dark that comes back from disk is trusted by everything downstream, so the
guards are the point of this suite - a wrong-length frame belongs to another
detector, and a frame whose exposure does not match the one in use removes the
wrong pedestal while still looking like a spectrum.
"""
import os
import time

import numpy as np
import pytest

from spectro import dark as darkstore


def _frame(n=2048, level=1200.0):
    return np.full(n, level, dtype=float)


class TestRoundtrip:
    def test_save_then_load(self, tmp_path):
        path = str(tmp_path / "d.npz")
        d = darkstore.DarkFrame(counts=_frame(), exposure_us=10_000, navg=16,
                                clean=True, captured_t=1_789_000_000.0,
                                model="e9u_LSMD-TCD1304-PRO",
                                serial="20260312-004", source="net 192.168.100.10")
        assert darkstore.save(d, path) == path
        back = darkstore.load(path)
        assert back is not None
        np.testing.assert_allclose(back.counts, d.counts)
        assert back.exposure_us == 10_000 and back.navg == 16
        assert back.clean is True
        assert back.serial == "20260312-004"
        assert back.source == "net 192.168.100.10"
        assert back.captured_t == pytest.approx(1_789_000_000.0)

    def test_missing_file_is_not_an_error(self, tmp_path):
        assert darkstore.load(str(tmp_path / "nothing.npz")) is None

    def test_clear_reports_whether_there_was_one(self, tmp_path):
        path = str(tmp_path / "d.npz")
        darkstore.save(darkstore.DarkFrame(_frame(), 10_000), path)
        assert darkstore.clear(path) is True
        assert darkstore.clear(path) is False
        assert darkstore.load(path) is None

    def test_derived_fields(self):
        d = darkstore.DarkFrame(_frame(level=2000.0), 200_000, navg=8)
        assert d.pixels == 2048
        assert d.exposure_ms == pytest.approx(200.0)
        assert d.mean == pytest.approx(2000.0)
        assert "200 ms" in d.summary() and "x8" in d.summary()


class TestGuards:
    def test_another_detector_is_refused(self, tmp_path):
        path = str(tmp_path / "d.npz")
        darkstore.save(darkstore.DarkFrame(_frame(3648), 10_000), path)
        with pytest.raises(darkstore.DarkError, match="3648 px"):
            darkstore.load(path, pixels=2048)

    def test_matching_detector_is_accepted(self, tmp_path):
        path = str(tmp_path / "d.npz")
        darkstore.save(darkstore.DarkFrame(_frame(2048), 10_000), path)
        assert darkstore.load(path, pixels=2048) is not None

    def test_garbage_file_raises_rather_than_returning_nothing(self, tmp_path):
        path = tmp_path / "d.npz"
        path.write_bytes(b"not an npz")
        with pytest.raises(darkstore.DarkError, match="unreadable"):
            darkstore.load(str(path))

    def test_exposure_match_is_exact_within_a_microsecond(self):
        d = darkstore.DarkFrame(_frame(), 10_000)
        assert d.matches_exposure(10_000)
        assert d.matches_exposure(10_001)          # rounding of 10.0 ms
        assert not d.matches_exposure(10_100)
        assert not d.matches_exposure(200_000)


class TestDefaultPath:
    def test_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLOUDS_DARK", str(tmp_path / "mine.npz"))
        assert darkstore.default_path() == str(tmp_path / "mine.npz")

    def test_sits_beside_the_calibration(self, monkeypatch):
        monkeypatch.delenv("CLOUDS_DARK", raising=False)
        path = darkstore.default_path()
        assert os.path.basename(path) == darkstore.DEFAULT_NAME
        # the same directory calibration.json resolves from (spectro/..)
        assert os.path.dirname(path) == os.path.dirname(
            os.path.dirname(os.path.abspath(darkstore.__file__)))

    def test_captured_t_defaults_to_now(self):
        d = darkstore.DarkFrame(_frame(), 10_000)
        assert abs(d.captured_t - time.time()) < 5.0
