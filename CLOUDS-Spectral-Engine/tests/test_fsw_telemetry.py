"""FSW-PI telemetry: relay passthrough, quick-look binning, budget (O.4)."""
import socket

import numpy as np
import pytest

from clouds_link import frames, hk
from clouds_fsw.telemetry import (BudgetMeter, Downlink, QuicklookSender,
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
        h = hk.Housekeeping(state=hk.SeqState.ASCENT, p_amb_pa=42_000)
        raw = frames.Frame(type=frames.PacketType.HK, payload=h.pack(),
                           seq=77).stamp().encode()
        down.relay(raw)
        got, _ = rx.recvfrom(65536)
        assert got == raw                       # CRC survives end-to-end
        f = frames.decode(got)
        assert f.seq == 77                      # MCU's own seq preserved
        assert hk.Housekeeping.unpack(f.payload).p_amb_pa == 42_000


class TestDownlinkBudget:
    """The configured cadences must fit the 2 kbit/s continuous E-Link limit.

    Sizes come from real encoded frames, not assumptions, so a payload or
    cadence change that busts the budget fails here instead of in flight.
    """

    def _rate_kbit_s(self, cfg, hk_hz=1.0):
        cal = Calibration.load(None)
        counts = np.zeros(2048, dtype=np.uint16)
        ql_bytes = sum(
            len(frames.Frame(
                type=frames.PacketType.QUICKLOOK,
                payload=frames.pack_quicklook(
                    i, cfg.quicklook_bin, 100,
                    bin_channel(counts, ch.pixel_window[0], ch.pixel_window[1],
                                cfg.quicklook_bin)),
                seq=0).stamp().encode())
            for i, ch in enumerate(cal.channels))
        pistatus_bytes = len(frames.Frame(
            type=frames.PacketType.PISTATUS,
            payload=frames.pack_pistatus(1, 2, True, True, 3000),
            seq=0).stamp().encode())
        hk_bytes = len(frames.Frame(
            type=frames.PacketType.HK, payload=hk.Housekeeping().pack(),
            seq=0).stamp().encode())
        per_s = (ql_bytes / cfg.quicklook_interval_s
                 + pistatus_bytes / cfg.pistatus_interval_s
                 + hk_bytes * hk_hz)
        return per_s * 8 / 1000.0

    def test_defaults_fit_the_continuous_budget(self):
        from clouds_fsw.config import FswConfig
        cfg = FswConfig()
        rate = self._rate_kbit_s(cfg)
        assert rate <= cfg.budget_kbit_s, f"{rate:.3f} kbit/s over budget"

    def test_twice_as_fast_would_bust_it(self):
        """Guards the claim that the default cadence IS the maximum."""
        from clouds_fsw.config import FswConfig
        half = FswConfig().quicklook_interval_s / 2
        cfg = FswConfig(quicklook_interval_s=half)
        assert self._rate_kbit_s(cfg) > cfg.budget_kbit_s

    def test_hk_payload_stays_within_its_ceiling(self):
        """1 Hz quick-look only fits because HK is lean (SOFTWARE_SPEC.md).

        The spec originally allowed HK ~180 B, at which size 1 Hz quick-look
        totals ~2.9 kbit/s and busts the 2 kbit/s continuous limit. Growing
        Housekeeping past the ceiling must fail here, not in flight.
        """
        from clouds_fsw.config import FswConfig
        cfg = FswConfig()
        overhead = len(frames.Frame(type=frames.PacketType.HK,
                                    payload=b"").stamp().encode())
        budget_bytes_s = cfg.budget_kbit_s * 1000 / 8
        ql_and_pistatus = self._rate_kbit_s(cfg, hk_hz=0.0) * 1000 / 8
        ceiling = budget_bytes_s - ql_and_pistatus - overhead   # payload bytes
        assert hk.SIZE <= ceiling, (
            f"HK payload {hk.SIZE} B exceeds the {ceiling:.0f} B that "
            f"{cfg.quicklook_interval_s}s quick-look leaves: bin harder or "
            f"slow the quick-look cadence")


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


class TestBudget:
    def test_meter_window(self):
        m = BudgetMeter(window_s=10.0)
        for i in range(10):
            m.add(250, now=100.0 + i)          # 250 B/s = 2 kbit/s
        assert m.kbit_s(now=109.0) == pytest.approx(2.0, rel=0.01)
        assert m.kbit_s(now=200.0) == 0.0      # window drained

    def test_hk_stream_fits_continuous_budget(self, udp_pair):
        """Spec section 4: 1 Hz HK relay must stay under 2 kbit/s."""
        down, _ = udp_pair
        raw = frames.Frame(type=frames.PacketType.HK,
                           payload=hk.Housekeeping().pack()).stamp().encode()
        assert len(raw) * 8 / 1000.0 < 2.0     # one HK frame per second
        for i in range(10):
            down.meter.add(len(raw), now=100.0 + i)
        assert down.meter.kbit_s(now=109.0) < 2.0
