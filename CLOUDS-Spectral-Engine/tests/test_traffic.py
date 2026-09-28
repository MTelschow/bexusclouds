"""The Ethernet traffic indicator's lane maths, without a display.

`_Lane` is plain Python on purpose - the rules that matter (a link with no
source is not a dead link, a silent link is not an idle one, the budget lane
knows its limit) are testable by driving a fake counter forwards in fake
time. The widget that draws them is exercised by verify_qt.py.
"""
import pytest

from clouds_link import linkrate
from clouds_ui import traffic as T


class _Src:
    """A byte counter and its last-activity stamp, driven by hand."""

    def __init__(self):
        self.total = 0
        self.last = 0.0
        self.present = True

    def add(self, n, now):
        self.total += n
        self.last = now

    def read(self):
        return (self.total, self.last) if self.present else None


def _lane(limits=None, windows=(1.0, 60.0)):
    src = _Src()
    return src, T._Lane("Down", src.read, limits=limits, windows=windows)


def test_no_source_reads_as_no_link_not_a_dead_one():
    src, lane = _lane()
    src.present = False
    lane.poll(1000.0)
    assert lane.state == "none"
    assert lane.rate_text == "-"


def test_rate_converges_on_the_offered_load():
    """A steady 250 B/s is 2 kbit/s. The window average ramps for its first
    minute by construction, so what is asserted is where it settles."""
    src, lane = _lane()
    t = 1000.0
    for _ in range(200):
        t += 0.5
        src.add(125, t)                 # 250 B/s = 2000 bit/s
        lane.poll(t)
    assert lane.avg == pytest.approx(2000, rel=0.02)
    assert lane.bit_s == lane.avg
    assert lane.peak == pytest.approx(2000, rel=0.02)
    assert lane.total == 200 * 125


def test_average_ramps_and_peak_does_not():
    """After ten seconds of a 1 kB/s link the 1 s peak is 8 kbit/s and the
    60 s average is a sixth of it - true, and what the tooltip says."""
    src, lane = _lane()
    t = 1000.0
    for _ in range(20):
        t += 0.5
        src.add(500, t)
        lane.poll(t)
    assert lane.peak == pytest.approx(8000)
    # 19 deltas: the first poll has no previous count to difference against
    assert lane.avg == pytest.approx(19 * 500 * 8 / 60)


def test_first_poll_does_not_invent_a_rate():
    """The counter is already at whatever the session has sent; charging that
    to the first half-second would read as a huge burst that never happened."""
    src, lane = _lane()
    src.add(1_000_000, 1000.0)
    lane.poll(1000.0)
    assert lane.bit_s == 0.0
    assert lane.total == 1_000_000


def test_activity_blinks_between_packets():
    """HK is 1 Hz and the poll is 500 ms, so half the windows are empty. That
    is the blink - the light says 'a packet arrived', not 'the link is up'."""
    src, lane = _lane()
    t = 1000.0
    for i in range(6):
        t += 0.5
        if i % 2 == 0:
            src.add(72, t)
        lane.poll(t)
        assert lane.state == ("active" if i % 2 == 0 else "idle")


def test_silence_is_not_idleness():
    src, lane = _lane()
    t = 1000.0
    src.add(72, t)
    lane.poll(t)
    lane.poll(t + T.SILENT_S + 0.1)
    assert lane.state == "silent"
    # A link that never delivered anything says so rather than showing 0 bit/s
    # next to a green light.
    _s2, lane2 = _lane()
    lane2.poll(1000.0)
    assert lane2.state == "silent" and lane2.rate_text == "no data"


def test_over_the_peak_with_the_average_fine_is_over():
    """One second at 500 kbit/s is over the 400 kbit/s peak even though the
    minute's average is nowhere near 100 kbit/s."""
    src, lane = _lane(limits=linkrate.DOWNLINK_LIMITS)
    t = 1000.0
    src.add(100, t)
    lane.poll(t)
    t += 0.5
    src.add(62_500, t)                  # 500 kbit in one poll
    lane.poll(t)
    assert lane.state == "over"
    assert lane.peak > linkrate.DOWNLINK_PEAK_BIT_S
    assert lane.avg < linkrate.DOWNLINK_AVG_BIT_S
    t += 1.5
    lane.poll(t)
    assert lane.state == "idle"         # the burst left the 1 s window


def test_over_the_average_is_over():
    """A steady 150 kbit/s never trips the 400 kbit/s peak, and is over the
    100 kbit/s average once a minute of it has been seen."""
    src, lane = _lane(limits=linkrate.DOWNLINK_LIMITS)
    t = 1000.0
    for _ in range(130):
        t += 0.5
        src.add(9_375, t)               # 18 750 B/s = 150 kbit/s
        lane.poll(t)
    assert lane.state == "over"
    assert lane.peak < linkrate.DOWNLINK_PEAK_BIT_S
    assert lane.avg > linkrate.DOWNLINK_AVG_BIT_S


def test_up_lane_has_the_uplink_limit():
    src, lane = _lane(limits=linkrate.UPLINK_LIMITS,
                      windows=(linkrate.UPLINK_WINDOW_S,))
    t = 1000.0
    for _ in range(12):
        t += 5.0
        src.add(130, t)                 # one PING transaction per beat
        lane.poll(t)
    assert lane.state == "active"       # 1560 B/min = 208 bit/s
    assert lane.rate_text.endswith("bit/s")
    src.add(7000, t)
    lane.poll(t)
    assert lane.state == "over"


def test_lanes_use_the_shared_limits():
    """The indicator's amber lines and the Pi's shaper are the same
    numbers, from one module; two copies would let one drift."""
    from clouds_fsw.config import FswConfig
    widget_src = open(T.__file__, encoding="utf-8").read()
    assert "DOWNLINK_LIMITS" in widget_src and "UPLINK_LIMITS" in widget_src
    assert FswConfig().downlink_avg_kbit_s * 1000 == linkrate.DOWNLINK_AVG_BIT_S
    assert FswConfig().downlink_peak_kbit_s * 1000 == linkrate.DOWNLINK_PEAK_BIT_S


def test_two_window_lane_shows_avg_and_peak():
    src, lane = _lane()
    t = 1000.0
    for _ in range(4):
        t += 0.5
        src.add(500, t)
        lane.poll(t)
    assert lane.rate_text == (f"{T.fmt_rate_short(lane.avg)} / "
                              f"{T.fmt_rate_short(lane.peak)}")
    assert "/" in lane.rate_text


@pytest.mark.parametrize("bit_s,text", [
    (0, "0"), (480, "480"), (3_210, "3.2k"), (98_400, "98k"),
    (402_000, "402k"), (1_250_000, "1.2M"),
])
def test_short_rate_units(bit_s, text):
    assert T.fmt_rate_short(bit_s) == text


@pytest.mark.parametrize("bit_s,text", [
    (0, "0 bit/s"), (480, "480 bit/s"), (1894, "1.89 kbit/s"),
    (402_000, "402.00 kbit/s"), (12_500_000, "12.50 Mbit/s"),
])
def test_rate_units(bit_s, text):
    assert T.fmt_rate(bit_s) == text


@pytest.mark.parametrize("n,text", [
    (0, "0 B"), (72, "72 B"), (2048, "2.0 kB"), (5 * 1024 ** 2, "5.0 MB"),
])
def test_byte_units(n, text):
    assert T.fmt_bytes(n) == text
