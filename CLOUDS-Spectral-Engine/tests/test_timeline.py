"""The housekeeping timeline's buffer: what it records and what it refuses to.

No Qt here - `TimelineBuffer` and the `Series` table are plain Python on
purpose, so the rules that matter (a missing reading is a gap, a dropout is a
gap, an unsourced field is a gap) are testable without a display. The widget
that draws them is exercised by verify_qt.py.
"""
import numpy as np
import pytest

from clouds_link.hk import RAIL_I2C_ADDR, RAIL_MV_INVALID, HkErrors, Housekeeping
from clouds_ui import timeline as T


def _hk(**kw):
    base = dict(p_amb_pa=101325, bme_temp_cc=2100, rh1_cpct=4500,
                rail_mv=(24060, RAIL_MV_INVALID, 5090, 3300),
                shunt_raw=(400, 0, 200, 100))
    base.update(kw)
    return Housekeeping(**base)


def test_series_table_is_consistent():
    keys = [s.key for s in T.SERIES]
    assert len(keys) == len(set(keys)), "duplicate series key"
    assert set(T.DEFAULT_KEYS) <= set(keys)
    # Every series the table offers must have a column in the buffer.
    buf = T.TimelineBuffer()
    assert set(buf.v) == set(keys)
    # Grouping covers the table exactly once.
    assert sum(len(m) for _g, m in T.GROUPS) == len(T.SERIES)


def test_records_one_sample_per_packet():
    buf = T.TimelineBuffer()
    for i in range(5):
        buf.append(1000.0 + i, _hk())
    assert len(buf) == 5
    x, cols = buf.window(["p_amb", "bme_t"], None)
    assert x.size == 5
    assert x[-1] == 0.0 and x[0] == -4.0          # relative to the newest sample
    assert np.allclose(cols["p_amb"], 1013.25)
    assert np.allclose(cols["bme_t"], 21.0)


def test_unsourced_field_is_a_gap_not_a_zero():
    """The whole point of the flag column: the MCU sends 0 for a part that is
    not fitted, and 0 degC is a plausible temperature."""
    buf = T.TimelineBuffer()
    buf.append(1000.0, _hk(temp1_cc=0, temp2_cc=0,
                           error_flags=int(HkErrors.NO_TEMP)))
    _x, cols = buf.window(["t1", "t2"], None)
    assert np.isnan(cols["t1"]).all()
    assert np.isnan(cols["t2"]).all()
    assert buf.last_flags & HkErrors.NO_TEMP


def test_unreadable_rail_is_a_gap_but_a_dead_rail_is_a_number():
    """0.00 V is a real reading for a rail with no supply; RAIL_MV_INVALID is
    a monitor that did not answer. They must not look alike."""
    buf = T.TimelineBuffer()
    buf.append(1000.0, _hk(rail_mv=(0, RAIL_MV_INVALID, 5090, 3300)))
    _x, cols = buf.window(["rail_v0", "rail_v1", "rail_v2"], None)
    assert cols["rail_v0"][0] == 0.0              # rail down, monitor fine
    assert np.isnan(cols["rail_v1"][0])           # no monitor fitted
    assert cols["rail_v2"][0] == pytest.approx(5.09)


def test_not_fitted_rail_is_flagged_in_the_table():
    for i, addr in enumerate(RAIL_I2C_ADDR):
        assert T.SERIES_BY_KEY[f"rail_v{i}"].fitted is (addr is not None)
        assert T.SERIES_BY_KEY[f"rail_i{i}"].fitted is (addr is not None)


def test_a_dropout_breaks_the_trace():
    """A line drawn straight across a link outage claims ground knows what
    happened during it."""
    buf = T.TimelineBuffer(gap_s=5.0)
    buf.append(1000.0, _hk())
    buf.append(1001.0, _hk())
    buf.append(1060.0, _hk())                     # 59 s hole
    x, cols = buf.window(["p_amb"], None)
    assert x.size == 4                            # three packets + one break
    y = cols["p_amb"]
    assert np.isnan(y[2]) and not np.isnan(y[1]) and not np.isnan(y[3])
    # ...and a normal 1 Hz cadence inserts nothing.
    buf2 = T.TimelineBuffer(gap_s=5.0)
    for i in range(10):
        buf2.append(2000.0 + i, _hk())
    assert len(buf2) == 10


def test_window_trims_to_the_span():
    buf = T.TimelineBuffer()
    for i in range(600):
        buf.append(1000.0 + i, _hk())
    x, cols = buf.window(["p_amb"], 60.0)
    assert x[0] >= -60.0 and x[-1] == 0.0
    assert cols["p_amb"].size == x.size
    x_all, _ = buf.window(["p_amb"], None)
    assert x_all.size == 600


def test_buffer_is_bounded():
    buf = T.TimelineBuffer(maxlen=10)
    for i in range(50):
        buf.append(1000.0 + i, _hk())
    assert len(buf) == 10
    assert all(len(d) == 10 for d in buf.v.values())


def test_empty_buffer_reads_back_empty():
    buf = T.TimelineBuffer()
    x, cols = buf.window(["p_amb"], 60.0)
    assert x.size == 0 and cols == {}


def test_clear_drops_everything():
    buf = T.TimelineBuffer()
    buf.append(1000.0, _hk(error_flags=int(HkErrors.IMU_FAIL)))
    buf.clear()
    assert len(buf) == 0 and buf.last_flags == 0
    assert all(len(d) == 0 for d in buf.v.values())


def test_a_raising_series_costs_only_itself():
    """A decode surprise in one field must not lose the whole sample."""
    buf = T.TimelineBuffer()
    bad = _hk()
    object.__setattr__(bad, "accel_mg", ())        # too short for the x/y/z getters
    buf.append(1000.0, bad)
    _x, cols = buf.window(["acc_x", "p_amb"], None)
    assert np.isnan(cols["acc_x"][0])
    assert cols["p_amb"][0] == pytest.approx(1013.25)
