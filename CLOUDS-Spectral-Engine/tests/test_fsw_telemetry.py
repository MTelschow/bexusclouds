"""FSW-PI telemetry: relay passthrough, quick-look binning, the E-Link
budget and the shaper that holds it (O.4)."""
import json
import socket

import numpy as np
import pytest

from clouds_link import frames, hk
from clouds_link.frames import PacketType
from clouds_link.linkrate import (AVG_WINDOW_S, DOWNLINK_AVG_BIT_S,
                                  DOWNLINK_PEAK_BIT_S, PEAK_WINDOW_S,
                                  UDP_WIRE_OVERHEAD, udp_wire_bytes)
from clouds_fsw.telemetry import (Downlink, DropReporter, QuicklookSender,
                                  bin_channel)
from spectro.calibration import Calibration


@pytest.fixture
def udp_pair():
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2.0)
    down = Downlink("127.0.0.1", rx.getsockname()[1])
    yield down, rx
    down.close()
    rx.close()


class TestRelay:
    def test_mcu_frame_relayed_byte_identical(self, udp_pair):
        down, rx = udp_pair
        h = hk.Housekeeping(state=hk.SeqState.RUNNING, p_amb_pa=42_000)
        raw = frames.Frame(type=frames.PacketType.HK, payload=h.pack(),
                           seq=77).stamp().encode()
        down.relay(raw)
        got, _ = rx.recvfrom(65536)
        assert got == raw                       # CRC survives end-to-end
        f = frames.decode(got)
        assert f.seq == 77                      # MCU's own seq preserved
        assert hk.Housekeeping.unpack(f.payload).p_amb_pa == 42_000


def _ql_frames(cfg):
    cal = Calibration.load(None)
    counts = np.zeros(2048, dtype=np.uint16)
    return [frames.Frame(
        type=PacketType.QUICKLOOK,
        payload=frames.pack_quicklook(
            i, cfg.quicklook_bin, 100,
            bin_channel(counts, ch.pixel_window[0], ch.pixel_window[1],
                        cfg.quicklook_bin)),
        seq=0).stamp().encode() for i, ch in enumerate(cal.channels)]


def _hk_frame():
    return frames.Frame(type=PacketType.HK, payload=hk.Housekeeping().pack(),
                        seq=0).stamp().encode()


def _pistatus_frame():
    return frames.Frame(type=PacketType.PISTATUS,
                        payload=frames.pack_pistatus(1, 2, True, True, 3000),
                        seq=0).stamp().encode()


def _event_frame():
    return frames.Frame(type=PacketType.EVENT,
                        payload=frames.pack_event(0x13, 1, "x" * 40),
                        seq=0).stamp().encode()


class TestDownlinkBudget:
    """The configured cadences must fit the E-Link (linkrate.py): 100 kbit/s
    on average and 400 kbit/s at any time, counted on the wire.

    Sizes come from real encoded frames plus the per-datagram header cost,
    not assumptions, so a payload or cadence change that busts the link
    fails here instead of in flight. The 2 kbit/s "continuous" figure and
    the 67 B HK ceiling derived from it were retired 2026-09-29.
    """

    def _wire_bit_s(self, cfg, hk_hz=1.0, overhead=UDP_WIRE_OVERHEAD):
        ql = sum(len(f) + overhead for f in _ql_frames(cfg))
        ps = len(_pistatus_frame()) + overhead
        hkb = len(_hk_frame()) + overhead
        per_s = (ql / cfg.quicklook_interval_s
                 + ps / cfg.pistatus_interval_s
                 + hkb * hk_hz)
        return per_s * 8

    def test_defaults_fit_the_average_with_margin(self):
        """The flight mix is ~3.2 kbit/s: a few percent of the average."""
        from clouds_fsw.config import FswConfig
        rate = self._wire_bit_s(FswConfig())
        assert rate <= 0.10 * DOWNLINK_AVG_BIT_S, f"{rate:.0f} bit/s"
        assert rate > 2_000, "arithmetic dropped a stream"

    def test_worst_second_fits_the_peak(self):
        """Everything that can land in one second - both quick-look
        packets, HK, a PISTATUS and an event - against 400 kbit/s."""
        from clouds_fsw.config import FswConfig
        cfg = FswConfig()
        burst = (sum(udp_wire_bytes(len(f)) for f in _ql_frames(cfg))
                 + udp_wire_bytes(len(_hk_frame()))
                 + udp_wire_bytes(len(_pistatus_frame()))
                 + udp_wire_bytes(len(_event_frame())))
        assert burst * 8 / PEAK_WINDOW_S <= DOWNLINK_PEAK_BIT_S

    def test_arithmetic_counts_wire_overhead(self):
        """Headers are the network's bytes but the link's bits: the budget
        differs from a payload-only sum by exactly 42 B per datagram."""
        from clouds_fsw.config import FswConfig
        cfg = FswConfig()
        packets_per_s = (2 / cfg.quicklook_interval_s
                         + 1 / cfg.pistatus_interval_s + 1.0)
        with_hdr = self._wire_bit_s(cfg)
        without = self._wire_bit_s(cfg, overhead=0)
        assert with_hdr - without == pytest.approx(
            UDP_WIRE_OVERHEAD * 8 * packets_per_s)

    def test_config_defaults_are_the_link_limits(self):
        """One source for the numbers: the config's defaults are the
        constants the ground and the panel use too."""
        from clouds_fsw.config import FswConfig
        cfg = FswConfig()
        assert cfg.downlink_avg_kbit_s * 1000 == DOWNLINK_AVG_BIT_S
        assert cfg.downlink_peak_kbit_s * 1000 == DOWNLINK_PEAK_BIT_S
        down = Downlink("127.0.0.1", 1,
                        avg_bit_s=cfg.downlink_avg_kbit_s * 1000,
                        peak_bit_s=cfg.downlink_peak_kbit_s * 1000)
        try:
            assert dict(down.limits) == {PEAK_WINDOW_S: DOWNLINK_PEAK_BIT_S,
                                         AVG_WINDOW_S: DOWNLINK_AVG_BIT_S}
        finally:
            down.close()


class TestConfigKeys:
    def test_retired_budget_key_still_loads(self, tmp_path, capsys):
        """The deployed /etc/clouds/fsw.json carries `budget_kbit_s`; a Pi
        that refused it would crash-loop at the next deploy."""
        from clouds_fsw.config import FswConfig
        path = tmp_path / "fsw.json"
        path.write_text(json.dumps({"budget_kbit_s": 2.0,
                                    "quicklook_bin": 4}))
        cfg = FswConfig.load(str(path))
        assert cfg.quicklook_bin == 4
        assert not hasattr(cfg, "budget_kbit_s")
        assert "budget_kbit_s" in capsys.readouterr().err

    def test_unknown_key_is_still_refused(self, tmp_path):
        from clouds_fsw.config import FswConfig
        path = tmp_path / "fsw.json"
        path.write_text(json.dumps({"downlink_kbit_s": 2.0}))
        with pytest.raises(ValueError):
            FswConfig.load(str(path))

    def test_example_config_loads(self):
        import os
        from clouds_fsw.config import FswConfig
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "flight", "pi", "config",
                            "fsw.example.json")
        cfg = FswConfig.load(path)
        assert cfg.downlink_avg_kbit_s == 100.0
        assert cfg.downlink_peak_kbit_s == 400.0


class TestSequenceNumbering:
    """One counter per packet type, as the MCU does and GapStats assumes."""

    def _recv_type_seq(self, rx):
        f = frames.decode(rx.recvfrom(65536)[0])
        return f.type, f.seq

    def test_each_type_numbered_independently(self, udp_pair):
        down, rx = udp_pair
        for _ in range(2):
            down.send(frames.PacketType.PISTATUS,
                      frames.pack_pistatus(1, 2, True, True, 3000))
            down.send(frames.PacketType.QUICKLOOK,
                      frames.pack_quicklook(0, 8, 100, [1, 2, 3]))
        got = [self._recv_type_seq(rx) for _ in range(4)]
        pistatus = [s for t, s in got if t == frames.PacketType.PISTATUS]
        quicklook = [s for t, s in got if t == frames.PacketType.QUICKLOOK]
        assert pistatus == [0, 1] and quicklook == [0, 1]

    def test_interleaved_types_charge_no_phantom_loss(self, udp_pair):
        """Regression: a shared counter made every other type look lost."""
        down, rx = udp_pair
        gaps = frames.GapStats()
        for _ in range(3):
            down.send(frames.PacketType.PISTATUS,
                      frames.pack_pistatus(1, 2, True, True, 3000))
            for ch in (0, 1):
                down.send(frames.PacketType.QUICKLOOK,
                          frames.pack_quicklook(ch, 8, 100, [1, 2, 3]))
        for _ in range(9):
            t, s = self._recv_type_seq(rx)
            gaps.update(t, s)
        assert gaps.received == 9
        assert gaps.lost == 0            # nothing was dropped, so charge nothing


class TestBinning:
    def test_bin_channel_means(self):
        counts = np.arange(2048, dtype=np.uint16)
        # window [0, 15], factor 4 -> means of [0..3],[4..7],[8..11],[12..15]
        assert bin_channel(counts, 0, 15, 4) == [1, 5, 9, 13]

    def test_bin_channel_is_bin_mean(self):
        """The ground bins the stored dark with `spectro.processing.bin_mean`
        to take it off the quick-look; the Pi must bin the frame the same
        way or the two grids drift apart."""
        from spectro.processing import bin_mean
        rng = np.random.default_rng(3)
        counts = rng.integers(0, 60000, 2048).astype(np.uint16)
        cal = Calibration.load()
        for ch in cal.channels:
            lo, hi = ch.pixel_window
            ground = bin_mean(counts[lo:hi + 1].astype(float), 8)
            assert bin_channel(counts, lo, hi, 8) == [int(v) for v in ground]

    def test_partial_bin_dropped(self):
        counts = np.ones(2048, dtype=np.uint16)
        assert len(bin_channel(counts, 0, 9, 4)) == 2   # 10 px -> 2 full bins

    def test_quicklook_sizes_match_calibration(self, udp_pair):
        down, rx = udp_pair
        cal = Calibration.load()
        ql = QuicklookSender(down, cal, bin_factor=8, interval_s=30)
        counts = np.full(2048, 1234, dtype=np.uint16)
        assert ql.maybe_send((1e9, counts, 100_000), now=1000.0)
        seen = {}
        for _ in range(2):
            f = frames.decode(rx.recvfrom(65536)[0])
            assert f.type == frames.PacketType.QUICKLOOK
            d = frames.unpack_quicklook(f.payload)
            seen[d["channel"]] = d
        for idx, role in enumerate(("measurement", "reference")):
            lo, hi = cal.by_role(role).pixel_window
            assert len(seen[idx]["counts"]) == (hi - lo + 1) // 8
            assert all(c == 1234 for c in seen[idx]["counts"])

    def test_quicklook_rejects_usb_glitches(self, udp_pair):
        """The transfer pins ~9 % of pixels per frame to ~33514 and they move
        frame to frame; a plain 8-px mean lifts about half the bins by +4 k.
        The quick-look must despike first, as the bench view does."""
        down, rx = udp_pair
        cal = Calibration.load()
        ql = QuicklookSender(down, cal, bin_factor=8, interval_s=30)
        rng = np.random.default_rng(7)
        counts = np.full(2048, 1500, dtype=np.uint16)
        hit = rng.random(2048) < 0.09
        counts[hit] = 33514
        assert ql.maybe_send((1e9, counts, 100_000), now=1000.0)
        for _ in range(2):
            f = frames.decode(rx.recvfrom(65536)[0])
            d = frames.unpack_quicklook(f.payload)
            assert d["counts"], "empty channel"
            assert max(d["counts"]) <= 1500 + 50, d["counts"]
            assert min(d["counts"]) >= 1500 - 50, d["counts"]

    def test_quicklook_rate_limited(self, udp_pair):
        down, rx = udp_pair
        ql = QuicklookSender(down, Calibration.load(), 8, interval_s=30)
        latest = (1e9, np.zeros(2048, dtype=np.uint16), 100_000)
        assert ql.maybe_send(latest, now=1000.0)
        assert not ql.maybe_send(latest, now=1010.0)   # inside interval
        assert ql.maybe_send(latest, now=1030.1)

    def test_no_frame_no_send(self, udp_pair):
        down, _ = udp_pair
        ql = QuicklookSender(down, Calibration.load(), 8, interval_s=30)
        assert not ql.maybe_send(None, now=1000.0)


class TestShaper:
    """The Pi drops rather than exceeds (linkrate.py, telemetry.py). Fake
    time throughout, tiny limits so a handful of packets fill them."""

    HK = _hk_frame()

    def _down(self, rx, avg_bit_s, peak_bit_s):
        return Downlink("127.0.0.1", rx.getsockname()[1],
                        avg_bit_s=avg_bit_s, peak_bit_s=peak_bit_s)

    def _drain(self, rx):
        rx.settimeout(0.2)
        got = []
        try:
            while True:
                got.append(frames.decode(rx.recvfrom(65536)[0]))
        except (TimeoutError, socket.timeout):
            return got

    def test_quicklook_stops_at_ninety_percent_hk_goes_to_the_limit(self, udp_pair):
        _, rx = udp_pair
        # 1 s peak window sized for exactly 1000 wire bytes; average is not
        # the binding limit here.
        down = self._down(rx, avg_bit_s=1e9, peak_bit_s=8_000)
        try:
            ql = b"\x00" * (udp_wire_bytes(16 + 700) - UDP_WIRE_OVERHEAD - 16)
            # a 758 B wire quick-look fits under 900 B ...
            assert down.send(PacketType.QUICKLOOK, ql, now=10.0)
            # ... a second one would take the window past 90 % -> dropped
            assert not down.send(PacketType.QUICKLOOK, b"\x00" * 100, now=10.1)
            # HK at the same instant is admitted up to the limit itself
            assert down.relay(self.HK, now=10.1)
            assert down.dropped[PacketType.QUICKLOOK] == 1
            assert down.dropped_total == 1 and down.dropped_priority == 0
            assert down.sent == 2
            got = self._drain(rx)
            assert [f.type for f in got] == [PacketType.QUICKLOOK, PacketType.HK]
        finally:
            down.close()

    def test_burst_is_refused_then_admitted_a_second_later(self, udp_pair):
        _, rx = udp_pair
        down = self._down(rx, avg_bit_s=1e9, peak_bit_s=8_000)   # 1000 B/s
        try:
            hk_wire = udp_wire_bytes(len(self.HK))                 # 138 B
            n_fit = 1000 // hk_wire                                # 7
            for i in range(n_fit):
                assert down.relay(self.HK, now=20.0 + i * 0.01)
            assert not down.relay(self.HK, now=20.5)
            assert down.dropped_priority == 1
            assert down.relay(self.HK, now=21.01)     # first entries aged out
        finally:
            down.close()

    def test_average_window_binds_too(self, udp_pair):
        _, rx = udp_pair
        # 60 s window sized for 500 wire bytes total; peak window generous.
        down = self._down(rx, avg_bit_s=500 * 8 / AVG_WINDOW_S, peak_bit_s=1e9)
        try:
            assert down.relay(self.HK, now=0.0)          # 138 B
            assert down.relay(self.HK, now=5.0)          # 276 B
            assert down.relay(self.HK, now=10.0)         # 414 B
            assert not down.relay(self.HK, now=15.0)     # 552 > 500
            assert down.relay(self.HK, now=60.5)         # the first aged out
        finally:
            down.close()

    def test_dropped_send_consumes_no_sequence_number(self, udp_pair):
        """`GapStats.lost` on the ground must keep meaning the link lost it."""
        _, rx = udp_pair
        down = self._down(rx, avg_bit_s=1e9, peak_bit_s=8_000)
        try:
            ps = frames.pack_pistatus(1, 2, True, True, 3000)
            assert down.send(PacketType.PISTATUS, ps, now=30.0)
            down.send(PacketType.QUICKLOOK, b"\x00" * 2000, now=30.0)  # dropped
            assert not down.send(PacketType.PISTATUS, b"\x00" * 2000, now=30.0)
            assert down.send(PacketType.PISTATUS, ps, now=30.0)
            got = self._drain(rx)
            assert [(f.type, f.seq) for f in got] == [(PacketType.PISTATUS, 0),
                                                       (PacketType.PISTATUS, 1)]
            gaps = frames.GapStats()
            for f in got:
                gaps.update(f.type, f.seq)
            assert gaps.lost == 0
            assert down.dropped_priority == 1      # the oversize PISTATUS
        finally:
            down.close()

    def test_rates_are_wire_bytes(self, udp_pair):
        _, rx = udp_pair
        down = self._down(rx, avg_bit_s=1e9, peak_bit_s=1e9)
        try:
            down.relay(self.HK, now=100.0)
            assert down.sent_wire_bytes == len(self.HK) + UDP_WIRE_OVERHEAD
            assert down.peak_bit_s(now=100.5) == pytest.approx(
                (len(self.HK) + UDP_WIRE_OVERHEAD) * 8)
            assert down.avg_bit_s(now=100.5) == pytest.approx(
                (len(self.HK) + UDP_WIRE_OVERHEAD) * 8 / AVG_WINDOW_S)
        finally:
            down.close()

    def test_drop_reporter_sends_one_event_per_interval(self, udp_pair):
        _, rx = udp_pair
        down = self._down(rx, avg_bit_s=1e9, peak_bit_s=8_000)
        events = []
        rep = DropReporter(down, lambda c, s, t: events.append((c, s, t)),
                           interval_s=60.0)
        try:
            assert not rep.poll(now=0.0)                 # nothing dropped
            for _ in range(3):
                down.send(PacketType.QUICKLOOK, b"\x00" * 2000, now=1.0)
            down.send(PacketType.PISTATUS, b"\x00" * 2000, now=1.0)
            assert rep.poll(now=1.0)
            assert events[-1][0] == frames.EventCode.DOWNLINK_SHAPED
            assert events[-1][1] == frames.EventSeverity.WARNING
            assert "4 dropped (3 quick-look)" in events[-1][2]
            down.send(PacketType.QUICKLOOK, b"\x00" * 2000, now=2.0)
            assert not rep.poll(now=30.0)                # inside the interval
            assert rep.poll(now=61.0)
            assert "1 dropped (1 quick-look) in 60 s" in events[-1][2]
            assert not rep.poll(now=200.0)               # nothing new
            assert len(events) == 2
        finally:
            down.close()
