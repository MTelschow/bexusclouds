"""The E-Link limits and the one meter that measures against them.

Fake time throughout: the meter takes ``now`` on every call, so the window
arithmetic is checked exactly, not against a sleeping clock.
"""
import threading

import pytest

from clouds_link import linkrate as L
from clouds_link.linkrate import LinkMeter


class TestConstants:
    def test_the_operator_limits(self):
        """The numbers of 2026-09-29, in bit/s, on the wire."""
        assert L.UPLINK_MAX_BIT_S == 1_000
        assert L.DOWNLINK_AVG_BIT_S == 100_000
        assert L.DOWNLINK_PEAK_BIT_S == 400_000
        assert L.AVG_WINDOW_S == 60.0 and L.PEAK_WINDOW_S == 1.0
        assert L.UPLINK_WINDOW_S == 60.0
        assert dict(L.DOWNLINK_LIMITS) == {1.0: 400_000, 60.0: 100_000}
        assert dict(L.UPLINK_LIMITS) == {60.0: 1_000}

    def test_wire_overhead(self):
        assert L.UDP_WIRE_OVERHEAD == 42 and L.TCP_WIRE_OVERHEAD == 54
        assert L.udp_wire_bytes(96) == 138        # a framed 80 B HK packet
        assert L.tcp_wire_bytes(22) == 76         # a framed CMD
        # CMD segment + the ground's bare TCP ack of the Pi's reply
        assert L.uplink_transaction_bytes(22) == 130

    def test_one_command_does_not_fit_a_one_second_uplink_window(self):
        """Why the uplink limit is a 60 s average and not a 1 s one."""
        assert L.uplink_transaction_bytes(22) * 8 > L.UPLINK_MAX_BIT_S * 1.0


class TestWindow:
    def test_rate_is_bytes_over_the_full_window(self):
        m = LinkMeter(windows=(1.0, 60.0))
        for i in range(60):
            m.add(250, now=100.0 + i)           # 250 B/s = 2 kbit/s
        assert m.bit_s(60.0, now=159.5) == pytest.approx(2000.0)
        assert m.bytes_in(1.0, now=159.5) == 250   # only the newest entry
        assert m.bit_s(1.0, now=159.5) == pytest.approx(2000.0)

    def test_window_drains(self):
        m = LinkMeter(windows=(1.0, 60.0))
        m.add(1000, now=100.0)
        assert m.bytes_in(60.0, now=100.0) == 1000
        assert m.bytes_in(60.0, now=159.9) == 1000
        assert m.bytes_in(60.0, now=160.0) == 0    # (t - W, t]
        assert m.bytes_in(1.0, now=101.0) == 0

    def test_first_packet_is_not_divided_by_elapsed_time(self):
        """One 96 B HK frame at t = 1 ms must read as 96 B in a minute, not
        as 768 kbit/s - the latter would trip the shaper on packet one."""
        m = LinkMeter()
        m.add(96, now=0.001)
        assert m.bit_s(60.0, now=0.002) == pytest.approx(96 * 8 / 60)
        assert m.bit_s(1.0, now=0.002) == pytest.approx(96 * 8)

    def test_short_window_needs_no_second_deque(self):
        m = LinkMeter(windows=(1.0, 60.0))
        for i in range(10):
            m.add(100, now=100.0 + i * 0.25)     # 2.5 s of traffic
        # last second: entries at 101.5, 101.75, 102.0, 102.25 -> 4 x 100
        assert m.bytes_in(1.0, now=102.25) == 400
        assert m.bytes_in(60.0, now=102.25) == 1000

    def test_reset(self):
        m = LinkMeter()
        m.add(500, now=1.0)
        m.reset()
        assert m.bytes_in(60.0, now=1.0) == 0

    def test_needs_a_window(self):
        with pytest.raises(ValueError):
            LinkMeter(windows=())


class TestAdmit:
    LIMITS = ((1.0, 8_000),)                    # 1000 B per second

    def test_refuses_exactly_at_the_limit(self):
        m = LinkMeter(windows=(1.0,))
        assert m.admit(600, self.LIMITS, now=10.0)
        assert m.admit(400, self.LIMITS, now=10.1)      # fills it exactly
        assert not m.admit(1, self.LIMITS, now=10.2)
        assert m.bytes_in(1.0, now=10.2) == 1000        # refusal recorded nothing
        assert m.admit(1, self.LIMITS, now=11.0)        # first entry aged out

    def test_headroom_stops_short(self):
        m = LinkMeter(windows=(1.0,))
        assert m.admit(900, self.LIMITS, now=10.0, headroom=0.1)
        assert not m.admit(1, self.LIMITS, now=10.0, headroom=0.1)
        assert m.admit(100, self.LIMITS, now=10.0)      # no headroom: room left

    def test_reserve_is_kept_free(self):
        m = LinkMeter(windows=(1.0,))
        assert not m.admit(900, self.LIMITS, now=10.0, reserve_bytes=200)
        assert m.admit(800, self.LIMITS, now=10.0, reserve_bytes=200)
        assert m.admit(200, self.LIMITS, now=10.0)      # the reserved part

    def test_every_limit_must_hold(self):
        limits = ((1.0, 8_000), (10.0, 2_000))          # 1000 B/s, 2500 B/10 s
        m = LinkMeter(windows=(1.0, 10.0))
        assert m.admit(1000, limits, now=0.0)
        assert m.admit(1000, limits, now=1.0)
        assert not m.admit(1000, limits, now=2.0)       # 1 s fine, 10 s not
        assert m.admit(500, limits, now=2.0)

    def test_time_until_admit(self):
        m = LinkMeter(windows=(1.0,))
        m.add(600, now=10.0)
        m.add(400, now=10.5)
        assert m.time_until_admit(1, self.LIMITS, now=10.6) == pytest.approx(0.4)
        assert m.time_until_admit(700, self.LIMITS, now=10.6) == pytest.approx(0.9)
        assert m.time_until_admit(1, self.LIMITS, now=11.0) == 0.0
        assert m.time_until_admit(1001, self.LIMITS, now=11.0) == float("inf")

    def test_thread_safe_totals(self):
        m = LinkMeter(windows=(60.0,))

        def feed():
            for _ in range(2000):
                m.add(1, now=1.0)

        ts = [threading.Thread(target=feed) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert m.bytes_in(60.0, now=1.0) == 8000
