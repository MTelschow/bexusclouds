"""The Ethernet traffic indicator's lane maths, without a display.

`_Lane` is plain Python on purpose - the rules that matter (a link with no
source is not a dead link, a silent link is not an idle one, the budget lane
knows its limit) are testable by driving a fake counter forwards in fake
time. The widget that draws them is exercised by verify_qt.py.
"""
import pytest

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


def _lane(budget=None):
    src = _Src()
    return src, T._Lane("Down", src.read, budget=budget)


def test_no_source_reads_as_no_link_not_a_dead_one():
    src, lane = _lane()
    src.present = False
    lane.poll(1000.0)
    assert lane.state == "none"
    assert lane.rate_text == "-"


def test_rate_converges_on_the_offered_load():
    """A steady 250 B/s is 2 kbit/s. The EMA starts low by construction, so
    what is asserted is where it settles, not the first sample."""
    src, lane = _lane()
    t = 1000.0
    for _ in range(200):
        t += 0.5
        src.add(125, t)                 # 250 B/s = 2000 bit/s
        lane.poll(t)
    assert lane.bit_s == pytest.approx(2000, rel=0.02)
    assert lane.total == 200 * 125


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


def test_over_budget_is_its_own_state():
    src, lane = _lane(budget=T.BUDGET_BIT_S)
    t = 1000.0
    for _ in range(200):
        t += 0.5
        src.add(500, t)                 # 1000 B/s = 8 kbit/s, 4x the budget
        lane.poll(t)
    assert lane.state == "over"
    assert lane.bit_s > T.BUDGET_BIT_S


def test_budget_matches_the_flight_side_allowance():
    """The indicator's amber line and the Pi's own watch level are the same
    2 kbit/s; two numbers here would let one drift."""
    from clouds_fsw.config import FswConfig
    assert T.BUDGET_BIT_S == FswConfig().budget_kbit_s * 1000


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
