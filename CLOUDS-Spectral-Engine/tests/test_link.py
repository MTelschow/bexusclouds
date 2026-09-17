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
    def test_size_is_56(self):
        assert hk.SIZE == 56

    def test_roundtrip(self):
        h = hk.Housekeeping(state=hk.SeqState.MEASURE_1, fired=0b01,
                            temp1_cc=-5512, p_amb_pa=5300,
                            accel_mg=(12, -34, 980),
                            rail_mv=(24012, hk.RAIL_MV_INVALID, 5003, 3298),
                            mission_t_s=4210)
        g = hk.Housekeeping.unpack(h.pack())
        assert g == h
        assert g.state_name == "MEASURE_1"
        row = g.to_row()
        assert row["accel_z_mg"] == 980 and row["state_name"] == "MEASURE_1"
        assert g.rail_mv == (24012, hk.RAIL_MV_INVALID, 5003, 3298)

    def test_link_flags_are_rendered_for_displays(self):
        """The whole link story is in `flags`, so it must be readable: an
        operator has to be able to tell a quiet flight from a dead link."""
        h = hk.Housekeeping(flags=hk.McuFlags.LINK_OK | hk.McuFlags.PI_OK)
        assert h.link_text == "GND PI"
        assert hk.Housekeeping(flags=0).link_text == "-"
        latched = hk.Housekeeping(flags=hk.McuFlags.AUTONOMOUS_LATCHED)
        assert latched.link_text == "AUTONOMOUS"
        assert latched.to_row()["link_text"] == "AUTONOMOUS"


    def test_actuator_bits_are_rendered_for_displays(self):
        """A commanded drive is a 5 s pulse: `valve_status` is where an
        operator sees it happen at all, so it must be readable."""
        h = hk.Housekeeping(valve_status=hk.ValveStatus.DISPERSE)
        assert h.actuator_text == "DISPERSE"
        assert hk.Housekeeping(valve_status=0).actuator_text == "-"
        assert h.to_row()["actuator_text"] == "DISPERSE"

    def test_membrane_switch_is_shown_with_the_duty_not_as_a_drive(self):
        """The GP30 position switch shares `valve_status` but is an input:
        it belongs next to the commanded duty, where duty-vs-position is the
        check, and must not appear in the Driving row as a held line."""
        both = hk.ValveStatus.DISPERSE | hk.ValveStatus.MEMBRANE_PULLED
        h = hk.Housekeeping(membrane_duty=60, valve_status=both)
        assert h.actuator_text == "DISPERSE"
        assert h.membrane_pulled is True
        assert h.membrane_text == "60 %  pulled"
        off = hk.Housekeeping(membrane_duty=0, valve_status=0)
        assert off.membrane_pulled is False
        assert off.membrane_text == "0 %  pushed"
        assert h.to_row()["membrane_pulled"] is True

    def test_unreadable_membrane_switch_is_not_reported_as_pushed(self):
        """A pico2 build has no GP30 and says so with NO_MEMBRANE_SENSE; a
        clear bit is then no reading at all, not a released plunger."""
        h = hk.Housekeeping(membrane_duty=60,
                            error_flags=hk.HkErrors.NO_MEMBRANE_SENSE)
        assert h.membrane_pulled is None
        assert h.membrane_text == "60 %"
        assert "NO_MEMBRANE_SENSE" in h.error_text

    def test_rail_voltages_are_rendered_for_displays(self):
        """The rails are the health of the power tree; an operator has to be
        able to read them without converting mV in their head."""
        h = hk.Housekeeping(rail_mv=(24012, hk.RAIL_MV_INVALID, 5003, 3298),
                            shunt_raw=(514, 0, 0, 6667))
        assert h.rail_text == ("V_in 24.01V 0.129A  24 V -  "
                               "5 V 5.00V 0.000A  3.3 V 3.30V 0.333A")
        assert h.to_row()["rail_text"] == h.rail_text

    def test_an_unreadable_rail_is_never_shown_as_a_voltage(self):
        """0 mV is a real reading for a rail whose supply is absent - V_in on
        a USB-powered bench - so a failed read must not render as 0.00 V, or
        ground cannot tell a dead monitor from a dead rail."""
        h = hk.Housekeeping(rail_mv=(hk.RAIL_MV_INVALID, hk.RAIL_MV_INVALID,
                                     0, 3298))
        assert h.rail_text == ("V_in -  24 V -  5 V 0.00V 0.000A  "
                               "3.3 V 3.30V 0.000A")

    def test_rail_current_is_ohms_law_on_the_measured_shunt_voltage(self):
        """The MCU downlinks the raw shunt register; the amps are computed
        here, so the arithmetic and the units have to be pinned. 514 counts
        x 2.5 uV = 1.285 mV, and over 10 mOhm that is 128.5 mA."""
        h = hk.Housekeeping(rail_mv=(24012, 24010, 5003, 3298),
                            shunt_raw=(514, 514, 514, 514))
        assert h.rail_uv(0) == 1285.0
        assert h.rail_a(0) == pytest.approx(0.1285)
        # same shunt voltage, different resistor: the 3.3 V rail is 50 mOhm
        assert h.rail_a(3) == pytest.approx(1285.0 / 50_000)
        assert hk.RAIL_SHUNT_MOHM == (10.0, 15.0, 50.0, 50.0)

    def test_a_negative_rail_current_survives_the_wire(self):
        """The shunt register is signed because current can flow either way.
        A rail pushing back into its supply is real data, so the sign has to
        make it through the packet rather than being clamped away."""
        h = hk.Housekeeping(rail_mv=(24012, hk.RAIL_MV_INVALID, 5003, 3298),
                            shunt_raw=(-514, 0, 0, 0))
        g = hk.Housekeeping.unpack(h.pack())
        assert g.shunt_raw == (-514, 0, 0, 0)
        assert g.rail_a(0) == pytest.approx(-0.1285)

    def test_an_unmonitored_rail_reports_no_current_not_zero_amps(self):
        """0.000 A is what an idle rail reads, so a monitor that did not
        answer must not produce one - the same trap RAIL_MV_INVALID exists
        for on the voltage side."""
        h = hk.Housekeeping(rail_mv=(hk.RAIL_MV_INVALID, hk.RAIL_MV_INVALID,
                                     5003, 3298),
                            shunt_raw=(9999, 0, 0, 0))
        assert h.rail_a(0) is None and h.rail_uv(0) is None
        assert h.rail_a(2) == 0.0
        assert h.to_row()["rail_vin_a"] == ""
        assert h.to_row()["rail_24v_a"] == ""

    def test_the_keller_fields_are_gone_from_the_packet(self):
        """The two Keller 23SY parts are off the design, and their HK fields
        went with them: a field no part can fill is read as data by anything
        that displays it. Their bytes carry the shunt voltages instead."""
        h = hk.Housekeeping()
        assert not hasattr(h, "p_ch_pa") and not hasattr(h, "rh2_cpct")
        assert not any(e.name in ("NO_CHAMBER_P", "NO_RH2")
                       for e in hk.HkErrors)

    def test_an_older_logs_retired_error_bits_stay_readable(self):
        """The surviving HKE_* bits kept their positions, and a bit with no
        name (bit 3, the retired NO_RH2) renders as a mask rather than
        vanishing, so a session logged before the change still decodes. Bit 2
        was the retired NO_CHAMBER_P and has since been reused for the
        membrane switch, so a pre-Keller-removal log now decodes that bit as
        NO_MEMBRANE_SENSE - a known cost of reusing a slot, recorded here."""
        h = hk.Housekeeping(error_flags=0b0000_1000 | hk.HkErrors.NO_TEMP)
        assert h.error_text == "NO_TEMP 0x0008"
        old = hk.Housekeeping(error_flags=0b0000_1100)
        assert old.error_text == "NO_MEMBRANE_SENSE 0x0008"

    def test_solenoid_sense_rides_the_wire_raw_and_scales_on_the_ground(self):
        """The ACT_HB_SENS ADC counts go down raw; volts come from the ADC
        reference and amps only once the sense gain is known. With the gain
        unset there is no current - 0.0 would claim an idle solenoid."""
        h = hk.Housekeeping(hb_sense_raw=2048)
        g = hk.Housekeeping.unpack(h.pack())
        assert g.hb_sense_raw == 2048
        assert g.hb_sense_v() == pytest.approx(1.65)
        assert hk.HB_SENSE_A_PER_V is None
        assert g.hb_sense_a() is None
        assert g.hb_sense_text == "1.650V"
        row = g.to_row()
        assert row["hb_sense_raw"] == 2048
        assert row["hb_sense_v"] == pytest.approx(1.65) and row["hb_sense_a"] == ""
        assert row["hb_sense_text"] == "1.650V"

    def test_solenoid_sense_amps_appear_once_the_gain_is_set(self, monkeypatch):
        monkeypatch.setattr(hk, "HB_SENSE_A_PER_V", 2.0)
        h = hk.Housekeeping(hb_sense_raw=2048)
        assert h.hb_sense_a() == pytest.approx(3.3)
        assert h.hb_sense_text == "3.300A"
        assert h.to_row()["hb_sense_a"] == pytest.approx(3.3)

    def test_solenoid_sense_sentinel_is_no_reading_not_zero(self):
        """A pico2 build cannot reach GP46 and sends the sentinel; 0 counts
        is what a de-energized solenoid reads, so the two must differ."""
        assert hk.HB_SENSE_INVALID == 0xFFFF and hk.HB_SENSE_INVALID > 4095
        none = hk.Housekeeping()                       # default: no reading
        assert none.hb_sense_v() is None and none.hb_sense_text == "-"
        idle = hk.Housekeeping(hb_sense_raw=0)
        assert idle.hb_sense_v() == 0.0 and idle.hb_sense_text == "0.000V"
        g = hk.Housekeeping.unpack(none.pack())
        assert g.hb_sense_raw == hk.HB_SENSE_INVALID

    def test_the_rail_sentinel_cannot_be_a_real_measurement(self):
        """0xFFFF is 65.535 V; the INA226's input rating is 36 V, so no real
        bus voltage can collide with the sentinel."""
        assert hk.RAIL_MV_INVALID == 0xFFFF
        assert hk.RAIL_MV_INVALID / 1000 > 36

    def test_rails_survive_the_wire_including_the_sentinel(self):
        h = hk.Housekeeping(rail_mv=(hk.RAIL_MV_INVALID, hk.RAIL_MV_INVALID,
                                     5003, 0),
                            shunt_raw=(0, 0, 514, -1))
        g = hk.Housekeeping.unpack(h.pack())
        assert g.rail_mv == (hk.RAIL_MV_INVALID, hk.RAIL_MV_INVALID, 5003, 0)
        assert g.shunt_raw == (0, 0, 514, -1)

    def test_actuator_bits_fit_the_valve_status_byte(self):
        """valve_status is one byte in the 54-byte payload - a sixth or
        seventh line would need a wider field, not a wider enum."""
        for v in hk.ValveStatus:
            assert 0 < int(v) <= 0xFF


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
