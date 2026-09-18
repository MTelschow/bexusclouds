"""`plot_session.py`: what it finds, what it masks, what it draws.

The plot itself is checked only for "a figure came out with the axes it
should have" - the value here is in the loading rules, because those are
where a log can be made to say something it does not: a zero drawn as a
reading, a dropout drawn as a straight line, a 10 s stream measured against
a 1 Hz threshold until nothing is left of it.
"""
import csv
import os

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")

import plot_session as PS                                   # noqa: E402
from clouds_link.hk import HkErrors, RAIL_MV_INVALID        # noqa: E402
from clouds_gse.session_log import SessionLog                # noqa: E402

HK_FIELDS = ["recv_t", "frame_t", "seq", "state", "state_name", "error_flags",
             "p_amb_pa", "chm_p_pa", "bme_temp_cc", "chm_temp_cc", "rh1_cpct",
             "chm_rh_cpct", "rail_mv", "rail_vin_a", "rail_24v_a",
             "hb_sense_raw", "hb_sense_a", "membrane_duty", "accel_x_mg",
             "accel_y_mg", "accel_z_mg", "gyro_x_ddps", "gyro_y_ddps",
             "gyro_z_ddps", "valve_pinch_1", "membrane_pulled",
             "membrane_cycling"]


def _hk_row(t, seq, err=0, state=1, **kw):
    row = {"recv_t": t, "frame_t": t, "seq": seq, "state": state,
           "state_name": "STANDBY", "error_flags": err,
           "p_amb_pa": 101325, "chm_p_pa": 101300, "bme_temp_cc": 2200,
           "chm_temp_cc": 2400, "rh1_cpct": 4500, "chm_rh_cpct": 3800,
           "rail_mv": (24000, RAIL_MV_INVALID, 5000, 3300),
           "rail_vin_a": 0.35, "rail_24v_a": "", "hb_sense_raw": 16,
           "hb_sense_a": 0.0057, "membrane_duty": 0,
           "accel_x_mg": 0, "accel_y_mg": 0, "accel_z_mg": 0,
           "gyro_x_ddps": 0, "gyro_y_ddps": 0, "gyro_z_ddps": 0,
           "valve_pinch_1": 0, "membrane_pulled": "False",
           "membrane_cycling": "False"}
    row.update(kw)
    return row


def _write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return str(path)


@pytest.fixture
def session(tmp_path):
    """A small but complete session: HK, Pi status, events, commands."""
    t0 = 1_000_000.0
    rows = [_hk_row(t0 + i, i, err=int(HkErrors.IMU_FAIL)) for i in range(4)]
    # A hole: the next packet is 30 s later, which is a dropout, not a ramp.
    rows += [_hk_row(t0 + 30 + i, 4 + i, err=int(HkErrors.IMU_FAIL))
             for i in range(3)]
    _write(tmp_path / "session_test_hk.csv", HK_FIELDS, rows)
    _write(tmp_path / "session_test_pistatus.csv",
           ["recv_t", "frame_t", "seq", "disk_free_mb", "spectra_count",
            "uart_ok", "spectro_ok", "cpu_temp_cc"],
           [{"recv_t": t0 + 10 * i, "frame_t": t0 + 10 * i, "seq": i,
             "disk_free_mb": 42704 - i, "spectra_count": 10 * i,
             "uart_ok": "True", "spectro_ok": "True" if i else "False",
             "cpu_temp_cc": 4150} for i in range(4)])
    _write(tmp_path / "session_test_events.csv",
           ["recv_t", "frame_t", "seq", "code", "code_name", "severity",
            "severity_name", "text"],
           [{"recv_t": t0 + 2, "frame_t": t0 + 2, "seq": 0, "code": 1,
             "code_name": "STATE_CHANGE", "severity": 0,
             "severity_name": "INFO", "text": "state=2"}])
    _write(tmp_path / "session_test_commands.csv",
           # The writer's own column list, so a column renamed there fails
           # here rather than silently becoming an empty series on the plot.
           list(SessionLog.COMMAND_FIELDS),
           [{"send_t": t0 + 1, "origin": "operator", "cmd": 1,
             "cmd_name": "START", "key": 0, "value": 0, "seq": "",
             "result": "", "result_name": "INTERLOCK_GROUND", "rtt_ms": "",
             "note": "refused on the ground"},
            {"send_t": t0 + 3, "origin": "heartbeat", "cmd": 0,
             "cmd_name": "PING", "key": 0, "value": 0, "seq": 1, "result": 0,
             "result_name": "OK", "rtt_ms": 1.2, "note": ""}])
    return tmp_path


class TestFindingLogs:
    def test_any_member_finds_the_whole_session(self, session):
        for member in ("hk", "events", "pistatus", "commands"):
            files = PS.session_files(
                str(session / f"session_test_{member}.csv"))
            assert set(files) == {"hk", "events", "pistatus", "commands"}

    def test_default_is_the_newest_session_in_the_directory(self, session,
                                                            tmp_path):
        older = tmp_path / "old"
        older.mkdir()
        _write(older / "session_aaa_hk.csv", HK_FIELDS, [_hk_row(1.0, 0)])
        _write(older / "session_zzz_hk.csv", HK_FIELDS, [_hk_row(2.0, 0)])
        os.utime(older / "session_aaa_hk.csv", (1, 1))
        kind, files = PS.resolve(None, str(older))
        assert kind == "session"
        assert files["hk"].endswith("session_zzz_hk.csv")

    def test_the_instrument_log_is_recognised_by_its_own_shape(self, tmp_path):
        p = _write(tmp_path / "session_20260918_1_.csv",
                   ["iso_time", "exposure_ms", "navg", "meas_peak",
                    "meas_peak_nm", "ref_peak", "ref_peak_nm", "sat_frac"],
                   [{"iso_time": "2026-09-18T20:59:40.680", "exposure_ms": 40,
                     "navg": 8, "meas_peak": 37055, "meas_peak_nm": 609.39,
                     "ref_peak": 30262, "ref_peak_nm": 643.23,
                     "sat_frac": 0.0042}])
        assert PS.is_instrument_csv(p)
        assert PS.resolve(p, None)[0] == "instrument"

    def test_an_unknown_csv_is_refused_rather_than_half_plotted(self, tmp_path):
        p = _write(tmp_path / "notes.csv", ["a", "b"], [{"a": 1, "b": 2}])
        with pytest.raises(SystemExit):
            PS.resolve(p, None)


class TestMasking:
    """The plot must not turn "no sensor" into a reading."""

    def test_imu_fail_is_a_gap_not_zero_g(self, session):
        d = PS.load_hk(str(session / "session_test_hk.csv"))
        assert np.all(np.isnan(d["accel_x"])) and np.all(np.isnan(d["gyro_z"]))

    def test_an_unreadable_rail_is_a_gap_not_zero_volts(self, session):
        d = PS.load_hk(str(session / "session_test_hk.csv"))
        assert np.allclose(d["rail_v_0"], 24.0)
        assert np.all(np.isnan(d["rail_v_1"]))      # RAIL_MV_INVALID
        assert np.all(np.isnan(d["rail_a_1"]))      # blank derived column

    def test_a_held_pressure_is_drawn_and_flagged(self, tmp_path):
        rows = [_hk_row(1.0, 0), _hk_row(2.0, 1, err=int(HkErrors.P_AMB_STALE))]
        d = PS.load_hk(_write(tmp_path / "session_s_hk.csv", HK_FIELDS, rows))
        assert np.allclose(d["p_amb_hpa"], 1013.25)   # still plotted
        assert list(d["p_stale"]) == [False, True]    # and marked

    def test_a_dead_sensor_bit_does_not_mask_the_other_part(self, tmp_path):
        """Ambient and chamber are two BME280s on two buses - one failing
        must not blank the other, which is what one shared flag would do."""
        rows = [_hk_row(1.0, 0, err=int(HkErrors.BME280_FAIL))]
        d = PS.load_hk(_write(tmp_path / "session_b_hk.csv", HK_FIELDS, rows))
        assert np.all(np.isnan(d["p_amb_hpa"]))
        assert np.allclose(d["p_chm_hpa"], 1013.0)


class TestGaps:
    def test_a_dropout_breaks_the_trace(self):
        t = np.array([0.0, 1.0, 2.0, 40.0, 41.0])
        y = PS._split_gaps(t, np.ones(5), 5.0)
        assert np.isnan(y[2])                   # the sample before the hole
        assert np.count_nonzero(np.isnan(y)) == 1

    def test_a_slow_stream_is_not_all_gaps(self):
        """Pi status is 10 s. Measured against the 1 Hz threshold every
        sample is its own island and the row draws empty."""
        t = np.arange(0.0, 100.0, 10.0)
        assert PS._stream_gap(t, 5.0) == pytest.approx(25.0)
        assert not np.any(np.isnan(PS._split_gaps(t, np.ones(len(t)),
                                                  PS._stream_gap(t, 5.0))))

    def test_the_threshold_is_never_narrowed_below_what_was_asked(self):
        t = np.arange(0.0, 10.0, 0.1)           # 10 Hz
        assert PS._stream_gap(t, 5.0) == 5.0


class TestFigures:
    def test_a_session_plots_every_unit_it_carries(self, session):
        files = PS.session_files(str(session / "session_test_hk.csv"))
        fig = PS.plot_session(files)
        labels = [ax.get_ylabel() for ax in fig.axes]
        assert "hPa" in labels and "C" in labels and "V" in labels
        assert "MB free" in labels and "frames stored" in labels
        # The IMU never reported, so its two axes are not drawn at all: an
        # empty axis reads as "recorded and flat", which is the opposite.
        assert "mg" not in labels and "dps" not in labels

    def test_it_writes_the_file_it_was_asked_for(self, session, tmp_path):
        out = tmp_path / "plot.png"
        assert PS.main([str(session / "session_test_hk.csv"),
                        "--save", str(out)]) == 0
        assert out.exists() and out.stat().st_size > 10_000

    def test_the_instrument_log_plots_on_its_own_terms(self, tmp_path):
        p = _write(tmp_path / "session_inst.csv",
                   ["iso_time", "exposure_ms", "navg", "meas_peak",
                    "meas_peak_nm", "ref_peak", "ref_peak_nm", "sat_frac"],
                   [{"iso_time": f"2026-09-18T20:59:4{i}.000",
                     "exposure_ms": 40, "navg": 8, "meas_peak": 37000 + i,
                     "meas_peak_nm": 609.39, "ref_peak": 30000,
                     "ref_peak_nm": 643.23, "sat_frac": 0.004}
                    for i in range(5)])
        fig = PS.plot_instrument(p)
        assert [ax.get_ylabel() for ax in fig.axes] == \
            ["counts", "peak nm", "ms / n", "fraction"]

    def test_a_session_with_nothing_over_time_is_refused(self, tmp_path):
        _write(tmp_path / "session_empty_events.csv",
               ["recv_t", "frame_t", "seq", "code", "code_name", "severity",
                "severity_name", "text"],
               [{"recv_t": 1.0, "frame_t": 1.0, "seq": 0, "code": 1,
                 "code_name": "STATE_CHANGE", "severity": 0,
                 "severity_name": "INFO", "text": "state=2"}])
        files = PS.session_files(str(tmp_path / "session_empty_events.csv"))
        with pytest.raises(SystemExit):
            PS.plot_session(files)
