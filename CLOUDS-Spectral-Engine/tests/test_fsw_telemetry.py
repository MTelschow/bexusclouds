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
