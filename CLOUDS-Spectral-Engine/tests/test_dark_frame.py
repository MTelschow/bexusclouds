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

    def test_a_different_serial_is_a_conflict(self):
        d = darkstore.DarkFrame(_frame(), 10_000, serial="20260312-004")
        why = d.serial_conflict("MOCK-0001")
        assert "20260312-004" in why and "MOCK-0001" in why

    def test_same_serial_is_no_conflict(self):
        d = darkstore.DarkFrame(_frame(), 10_000, serial="20260312-004")
        assert d.serial_conflict("20260312-004") == ""
        assert d.serial_conflict(" 20260312-004 ") == ""

    def test_unknown_serial_on_either_side_is_no_conflict(self):
        # darks captured before the serial travelled with them, and drivers
        # that report none, must not start refusing themselves
        assert darkstore.DarkFrame(_frame(), 10_000).serial_conflict("20260312-004") == ""
        d = darkstore.DarkFrame(_frame(), 10_000, serial="20260312-004")
        assert d.serial_conflict("") == ""

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


class TestRepoDefault:
    """The committed baseline dark.

    `dark_frame.npz` is tracked (2026-09-17) so a fresh checkout is not a
    machine with no dark: capturing one needs the Duo and a darkened bench,
    which a second laptop does not have. If this suite fails, the file was
    lost or re-ignored - not a reason to delete the test.
    """

    def test_it_is_there_and_loads_against_this_detector(self, monkeypatch):
        monkeypatch.delenv("CLOUDS_DARK", raising=False)
        path = darkstore.default_path()
        assert os.path.isfile(path), f"{path} is missing - is it .gitignore'd again?"
        d = darkstore.load(path, pixels=2048)
        assert d is not None
        assert d.pixels == 2048
        assert d.exposure_us > 0
        assert d.counts.min() >= 0.0

    def test_it_names_the_flight_detector(self, monkeypatch):
        import json
        monkeypatch.delenv("CLOUDS_DARK", raising=False)
        d = darkstore.load(darkstore.default_path(), pixels=2048)
        root = os.path.dirname(os.path.dirname(os.path.abspath(darkstore.__file__)))
        with open(os.path.join(root, "calibration.json")) as f:
            want = json.load(f)["instrument"]["serials"]["eureca"]
        # a baseline from another instrument would be dropped on connect
        assert d.serial == want
        assert d.serial_conflict(want) == ""


class TestLightLeak:
    """A dark taken with a fibre unblocked, caught against the covered gap.

    Worse than no dark: it subtracts real signal out of the baseline and
    nothing downstream can tell, so it is named rather than refused - the
    pedestal is still right everywhere nothing leaked.
    """

    WINDOWS = [("Ch1", 0, 235), ("Ch2", 1516, 1766)]

    def _lit(self, gap=24000.0, ch2_peak=None):
        c = np.full(2048, gap, dtype=float)
        rng = np.random.default_rng(7)
        c += rng.normal(0.0, 60.0, 2048)          # read noise
        c[236:1516:97] += 6000.0                  # hot pixels in the gap too
        if ch2_peak:
            c[1700:1740] += ch2_peak              # a leak is lines, not a level
        return c

    def test_a_blocked_dark_is_clean(self):
        d = darkstore.DarkFrame(self._lit(), 10_000)
        assert d.light_leak(self.WINDOWS) == {}
        assert d.leak_note(self.WINDOWS) == ""

    def test_a_lit_channel_is_named_with_its_excess(self):
        d = darkstore.DarkFrame(self._lit(ch2_peak=12_000.0), 10_000)
        lit = d.light_leak(self.WINDOWS)
        assert set(lit) == {"Ch2"}
        assert lit["Ch2"] > 2000.0
        note = d.leak_note(self.WINDOWS)
        assert "Ch2" in note and "blocked" in note
        assert "Ch1" not in note

    def test_the_mean_would_have_missed_it(self):
        # 40 lit pixels of 251: the window mean moves ~1.9 k, the check is on
        # the 99th percentile for exactly this reason
        c = self._lit(ch2_peak=12_000.0)
        w = c[1516:1767]
        assert w.mean() - np.median(c[236:1516]) < 2500.0
        assert darkstore.DarkFrame(c, 10_000).light_leak(self.WINDOWS)

    def test_no_windows_means_no_reference_and_no_claim(self):
        d = darkstore.DarkFrame(self._lit(ch2_peak=12_000.0), 10_000)
        assert d.light_leak([]) == {}
        # a window covering the whole detector leaves no gap to compare to
        assert d.light_leak([("all", 0, 2047)]) == {}
