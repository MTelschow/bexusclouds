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
    """The whole point of the flag column: the MCU sends 0 for a part it
    cannot read, and 0 mg is a plausible acceleration."""
    buf = T.TimelineBuffer()
    buf.append(1000.0, _hk(accel_mg=(0, 0, 0), gyro_ddps=(0, 0, 0),
                           error_flags=int(HkErrors.IMU_FAIL)))
    _x, cols = buf.window(["acc_x", "acc_z", "gyr_y"], None)
    assert all(np.isnan(v).all() for v in cols.values())
    assert buf.last_flags & HkErrors.IMU_FAIL


def test_the_stlm20_pair_has_no_rows():
    """Not populated and not coming, so it is not offered. The two wire
    fields survive in the packet and are declared by HKE_NO_TEMP."""
    assert not any(s.key in ("t1", "t2") or "STLM20" in s.group
                   for s in T.SERIES)
    assert not any("STLM20" in g for g, _m in T.GROUPS)


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


# -- the actuator lines -----------------------------------------------------
# The panel's `Driving` row is a snapshot and a pulse is 5 s, so "did pinch 1
# fire, and when" is a question only the history can answer.

def test_actuator_lines_plot_as_one_and_zero():
    from clouds_link.hk import ValveStatus
    buf = T.TimelineBuffer()
    buf.append(1000.0, _hk(valve_status=int(ValveStatus.PINCH_1)))
    buf.append(1001.0, _hk(valve_status=int(ValveStatus.DISPERSE)))
    _x, cols = buf.window(["valve_pinch_1", "valve_disperse"], None)
    assert list(cols["valve_pinch_1"]) == [1.0, 0.0]
    assert list(cols["valve_disperse"]) == [0.0, 1.0]


def test_a_clear_drive_bit_is_a_reading_not_a_gap():
    """Unlike a sensor field, `valve_status` is in every packet: a clear bit
    means the line is not energized, which is the thing being plotted."""
    buf = T.TimelineBuffer()
    buf.append(1000.0, _hk(valve_status=0))
    _x, cols = buf.window(["valve_pinch_1"], None)
    assert cols["valve_pinch_1"][0] == 0.0


def test_the_membrane_switch_is_a_gap_where_it_has_no_source():
    """GP30 is unreachable in a pico2 build; a clear bit then means nothing,
    and "not pulled" would be an invented reading."""
    from clouds_link.hk import ValveStatus
    buf = T.TimelineBuffer()
    buf.append(1000.0, _hk(valve_status=int(ValveStatus.MEMBRANE_PULLED
                                            | ValveStatus.MEMBRANE_CYCLING)))
    buf.append(1001.0, _hk(valve_status=0,
                           error_flags=int(HkErrors.NO_MEMBRANE_SENSE)))
    _x, cols = buf.window(["membrane_pulled", "membrane_cycling"], None)
    for k in ("membrane_pulled", "membrane_cycling"):
        assert cols[k][0] == 1.0
        assert np.isnan(cols[k][1])


def test_the_lines_share_one_axis_of_their_own():
    """All on the digital unit, so they stack as lanes instead of landing on
    a hPa or A axis."""
    lines = [s for s in T.SERIES if s.unit == T.DIGITAL_UNIT]
    assert {s.key for s in lines} >= {"valve_pinch_1", "valve_pinch_2",
                                      "valve_eq1_close", "valve_eq2_close",
                                      "valve_disperse", "membrane_pulled",
                                      "membrane_cycling"}
    assert {s.group for s in lines} == {"Actuator lines"}
    # ...and no measured series was dragged onto it.
    assert all(s.unit != T.DIGITAL_UNIT
               for s in T.SERIES if s.key in ("p_amb", "hb_sense", "membrane"))


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


# -- the span an operator types ---------------------------------------------
# The presets do not cover the question a given event asks ("the 90 s around
# that valve firing"), so the span box is editable. The parser is what keeps
# a typed span from becoming a silently different one.

@pytest.mark.parametrize("text,secs", [
    ("90", 90.0), ("90 s", 90.0), ("90s", 90.0), ("90 sec", 90.0),
    ("90 seconds", 90.0), ("2 min", 120.0), ("2m", 120.0), ("1.5 h", 5400.0),
    ("  300  SECONDS ", 300.0), (".5 min", 30.0),
])
def test_parse_window_accepts_a_span_in_any_of_its_units(text, secs):
    assert T.parse_window(text) == pytest.approx(secs)


@pytest.mark.parametrize("text", ["all", "All", " FULL "])
def test_parse_window_whole_buffer(text):
    assert T.parse_window(text) is None


@pytest.mark.parametrize("text", ["", "abc", "0", "-60", "5 furlong", "1e3",
                                  "1 min 30 s", "min"])
def test_parse_window_refuses_rather_than_guesses(text):
    """A typo must not select a span nobody asked for: the caller keeps the
    span that is drawn instead."""
    with pytest.raises(ValueError):
        T.parse_window(text)


def test_parse_window_clamps_to_what_the_buffer_can_show():
    assert T.parse_window("1") == T.MIN_WINDOW_S
    assert T.parse_window("99 h") == T.MAX_WINDOW_S
    assert T.MAX_WINDOW_S == float(T.MAXLEN)        # 1 Hz, one sample per second


def test_format_window_matches_the_preset_spelling():
    """A typed 300 s and the picked 5 min are one setting, so they must not
    read as two."""
    for name, secs in T.WINDOWS:
        assert T.format_window(secs) == name
    assert T.format_window(T.parse_window("300 s")) == "5 min"
    assert T.format_window(90.0) == "90 s"
    assert T.format_window(5400.0) == "90 min"
    assert T.format_window(7200.0) == "2 h"


def test_a_typed_span_round_trips():
    for text in ("45 s", "7 min", "2 h", "All"):
        secs = T.parse_window(text)
        assert T.parse_window(T.format_window(secs)) == secs
