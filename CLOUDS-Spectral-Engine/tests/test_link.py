"""Shared link protocol (clouds_link) - CRC, COBS, frames, HK, payloads."""
import pytest

from clouds_link import cobs, frames, hk
from clouds_link.crc16 import crc16
from clouds_link.frames import (AckResult, Frame, FrameError, GapStats,
                                PacketType, SeqCounter, decode)


class TestCrc16:
    def test_check_vector(self):
        # CRC-16/CCITT-FALSE canonical check value (mirrored in the C tests)
        assert crc16(b"123456789") == 0x29B1

    def test_empty(self):
        assert crc16(b"") == 0xFFFF

    def test_incremental_equals_whole(self):
        data = bytes(range(200))
        assert crc16(data[100:], crc16(data[:100])) == crc16(data)


class TestCobs:
    @pytest.mark.parametrize("data", [
        b"", b"\x00", b"\x00\x00", b"\x11\x22\x00\x33", b"\x11\x00",
        b"\x00\x11", bytes(range(1, 255)), bytes(range(1, 256)),
        bytes(300), bytes(range(256)) * 3,
    ])
    def test_roundtrip(self, data):
        enc = cobs.encode(data)
        assert 0 not in enc, "encoded frame must not contain the delimiter"
        assert cobs.decode(enc) == data

    def test_known_vectors(self):
        # canonical examples from the COBS paper
        assert cobs.encode(b"\x00") == b"\x01\x01"
        assert cobs.encode(b"\x11\x22\x00\x33") == b"\x03\x11\x22\x02\x33"
        assert cobs.encode(bytes(range(1, 255))) == b"\xff" + bytes(range(1, 255)) + b"\x01"

    def test_decode_rejects_garbage(self):
        with pytest.raises(cobs.CobsError):
            cobs.decode(b"")
        with pytest.raises(cobs.CobsError):
            cobs.decode(b"\x05\x11")  # group overruns
        with pytest.raises(cobs.CobsError):
            cobs.decode(b"\x02\x00\x02\x11")  # embedded zero


class TestFrame:
    def test_roundtrip(self):
        f = Frame(type=PacketType.EVENT, payload=b"\x01\x00hello", seq=42)
        f.stamp(1750000000.25)
        g = decode(f.encode())
        assert (g.type, g.payload, g.seq) == (f.type, f.payload, 42)
        assert g.timestamp == pytest.approx(1750000000.25, abs=0.001)

    def test_corrupt_crc_rejected(self):
        raw = bytearray(Frame(type=PacketType.HK, payload=b"x" * 44).encode())
        raw[20] ^= 0xFF
        with pytest.raises(FrameError):
            decode(bytes(raw))

    def test_bad_magic_rejected(self):
        raw = bytearray(Frame(type=PacketType.HK).encode())
        raw[0] = 0
        with pytest.raises(FrameError):
            decode(bytes(raw))

    def test_truncated_rejected(self):
        raw = Frame(type=PacketType.HK, payload=b"abcdef").encode()
        with pytest.raises(FrameError):
            decode(raw[:-3])

    def test_seq_counter_wraps(self):
        c = SeqCounter(0xFFFE)
        assert [c.next() for _ in range(3)] == [0xFFFE, 0xFFFF, 0]

    def test_gap_stats(self):
        g = GapStats()
        for seq in (0, 1, 2, 5, 6):
            g.update(PacketType.HK, seq)
        assert g.received == 5 and g.lost == 2
        # independent per type; restart (big backwards jump) is not loss
        g.update(PacketType.EVENT, 100)
        g.update(PacketType.HK, 0)
        assert g.lost == 2

    def test_interleaved_types_are_not_loss(self):
        """Each type carries its own counter, so interleaving charges nothing."""
        g = GapStats()
        for seq in range(3):
            g.update(PacketType.PISTATUS, seq)
            g.update(PacketType.QUICKLOOK, seq)
        assert g.received == 6 and g.lost == 0

    def test_events_are_recorded_but_never_charged(self):
        """EVENT has two independent emitters (the MCU's ev_seq_no and the Pi's
        own), so its numbers are not one space and gaps there are meaningless."""
        g = GapStats()
        for seq in (0, 40, 1, 41):        # two interleaved counters
            g.update(PacketType.EVENT, seq)
        assert g.received == 4 and g.unsequenced == 4 and g.lost == 0

    def test_real_loss_is_still_charged(self):
        g = GapStats()
        for seq in (0, 1, 5):             # 2, 3, 4 dropped
            g.update(PacketType.QUICKLOOK, seq)
        assert g.lost == 3


class TestHousekeeping:
    def test_size_is_44(self):
        assert hk.SIZE == 44

    def test_roundtrip(self):
        h = hk.Housekeeping(state=hk.SeqState.MEASURE_1, fired=0b01,
                            temp1_cc=-5512, p_amb_pa=5300,
                            accel_mg=(12, -34, 980), mission_t_s=4210)
        g = hk.Housekeeping.unpack(h.pack())
        assert g == h
        assert g.state_name == "MEASURE_1"
        row = g.to_row()
        assert row["accel_z_mg"] == 980 and row["state_name"] == "MEASURE_1"

    def test_link_flags_are_rendered_for_displays(self):
        """The whole link story is in `flags`, so it must be readable: an
        operator has to be able to tell a quiet flight from a dead link."""
        h = hk.Housekeeping(flags=hk.McuFlags.LINK_OK | hk.McuFlags.PI_OK)
        assert h.link_text == "GND PI"
        assert hk.Housekeeping(flags=0).link_text == "-"
        latched = hk.Housekeeping(flags=hk.McuFlags.AUTONOMOUS_LATCHED)
        assert latched.link_text == "AUTONOMOUS"
        assert latched.to_row()["link_text"] == "AUTONOMOUS"


class TestPayloads:
    def test_quicklook_roundtrip(self):
        counts = list(range(0, 2560, 10))
        p = frames.pack_quicklook(1, 8, 120, counts)
        d = frames.unpack_quicklook(p)
        assert d == {"channel": 1, "bin": 8, "exposure_ms": 120,
                     "counts": counts}

    def test_cmd_ack_roundtrip(self):
        assert frames.unpack_cmd(frames.pack_cmd(0x05, 2, -7)) == (0x05, 2, -7)
        assert frames.unpack_ack(frames.pack_ack(9, 5, AckResult.NOT_ARMED)) \
            == (9, 5, AckResult.NOT_ARMED)

    def test_timesync_roundtrip(self):
        t = 1750000123.456
        assert frames.unpack_timesync(frames.pack_timesync(t)) \
            == pytest.approx(t, abs=0.001)

    def test_event_roundtrip(self):
        d = frames.unpack_event(frames.pack_event(7, 2, "seal failed"))
        assert d == {"code": 7, "severity": 2, "text": "seal failed"}

    def test_pistatus_roundtrip(self):
        p = frames.pack_pistatus(12000, 345, True, False, 4150)
        assert frames.unpack_pistatus(p) == {
            "disk_free_mb": 12000, "spectra_count": 345,
            "uart_ok": True, "spectro_ok": False, "cpu_temp_cc": 4150}
