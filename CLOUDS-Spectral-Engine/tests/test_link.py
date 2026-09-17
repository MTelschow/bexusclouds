"""Shared link protocol (clouds_link) - CRC, COBS, frames, HK, payloads."""
import struct

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
    def test_size_is_64(self):
        assert hk.SIZE == 64

    def test_roundtrip(self):
        h = hk.Housekeeping(state=hk.SeqState.MEASURE_1, fired=0b01,
                            temp1_cc=-5512, p_amb_pa=5300,
                            accel_mg=(12, -34, 980),
                            rail_mv=(24012, hk.RAIL_MV_INVALID, 5003, 3298),
                            mission_t_s=4210,
                            chm_temp_cc=2450, chm_rh_cpct=3812,
                            chm_p_pa=98_765)
        g = hk.Housekeeping.unpack(h.pack())
        assert g == h
        assert g.state_name == "MEASURE_1"
        row = g.to_row()
        assert row["accel_z_mg"] == 980 and row["state_name"] == "MEASURE_1"
        assert g.rail_mv == (24012, hk.RAIL_MV_INVALID, 5003, 3298)
        # The chamber triple must survive the round trip distinct from the
        # ambient one: both are BME280 readings in the same units, and a
        # packing slip that crossed them would still decode to plausible
        # numbers.
        assert (g.chm_temp_cc, g.chm_rh_cpct, g.chm_p_pa) == (2450, 3812, 98_765)
        assert g.p_amb_pa == 5300 and g.chm_p_pa == 98_765

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
        assert h.membrane_cycling is False
        # position without motion under a drive is the fault, and says so
        assert h.membrane_text == "60 %  pulled, not cycling"
        moving = hk.Housekeeping(membrane_duty=60, valve_status=(
            hk.ValveStatus.MEMBRANE_PULLED | hk.ValveStatus.MEMBRANE_CYCLING))
        assert moving.actuator_text == "-"
        assert moving.membrane_text == "60 %  pulled, cycling"
        off = hk.Housekeeping(membrane_duty=0, valve_status=0)
        assert off.membrane_pulled is False
        assert off.membrane_text == "0 %  pushed"
        assert h.to_row()["membrane_pulled"] is True
        assert moving.to_row()["membrane_cycling"] is True

    def test_unreadable_membrane_switch_is_not_reported_as_pushed(self):
        """A pico2 build has no GP30 and says so with NO_MEMBRANE_SENSE; a
        clear bit is then no reading at all, not a released plunger."""
        h = hk.Housekeeping(membrane_duty=60,
                            error_flags=hk.HkErrors.NO_MEMBRANE_SENSE)
        assert h.membrane_pulled is None
        assert h.membrane_cycling is None
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

    def test_an_older_logs_retired_error_bits_stay_readable(self):
        """The surviving HKE_* bits kept their positions, and a bit with no
        name still renders as a mask rather than vanishing, so a session
        logged before a change still decodes.

        Bits 2 and 3 are the exception: both carried retired sensor flags
        before 2026-09-11 and both have been reused since, bit 2 by the
        membrane switch and bit 3 by the chamber BME280. A log from before
        that date therefore decodes those two under their current names,
        which is wrong about the past and right about every packet written
        since. That is the cost of reusing a slot, recorded here rather than
        discovered while reading an old session.
        """
        old = hk.Housekeeping(error_flags=0b0000_1100)
        assert old.error_text == "NO_MEMBRANE_SENSE BME280_CHM_FAIL"
        # Bit 7 is the free one now, and an unnamed bit must still survive as
        # a mask - that is what keeps a log written by a NEWER MCU readable
        # by this decoder.
        assert not any(e == 1 << 7 for e in hk.HkErrors)
        h = hk.Housekeeping(error_flags=0b1000_0000 | hk.HkErrors.NO_TEMP)
        assert h.error_text == "NO_TEMP 0x0080"

    def test_an_older_mcus_shorter_hk_still_decodes(self):
        """An MCU flashed before the chamber BME280 sends 56 B, and the ground
        must read it rather than throw the packet away.

        This is the bench failure the tolerance exists for: the ground
        software was updated, the MCU was not, `unpack` raised on every
        packet, both panel sections sat at their startup dashes and nothing
        said why. A wire-format change has to degrade to "these fields have
        no source", never to "there is no telemetry".
        """
        legacy = struct.Struct("<BBBBBBhhhHIhhhhhhHHHHhhhhIIH")
        assert legacy.size == hk.SIZE_PRE_CHAMBER == 56
        payload = legacy.pack(hk.SeqState.ASCENT, 0, 0, 0, 60, 0,
                              0, 0, 2140, 3050, 99_248,
                              1, -2, 981, 0, 1, -1,
                              24_060, hk.RAIL_MV_INVALID, 5090, 3300,
                              129, 0, -1, 333, 1234, 0, 1500)
        g = hk.Housekeeping.unpack(payload)
        # Everything the older packet does carry survives at its own offset.
        assert g.state_name == "ASCENT" and g.p_amb_pa == 99_248
        assert g.bme_temp_cc == 2140 and g.hb_sense_raw == 1500
        assert g.rail_mv == (24_060, hk.RAIL_MV_INVALID, 5090, 3300)
        # ...and what it does not carry is declared unsourced, not defaulted.
        # The dataclass default for chm_p_pa is sea level, and letting that
        # reach a display would be a pressure no sensor produced.
        assert g.error_flags & hk.HkErrors.BME280_CHM_FAIL
        assert (g.chm_p_pa, g.chm_temp_cc, g.chm_rh_cpct) == (0, 0, 0)

    def test_a_truncated_hk_is_still_an_error(self):
        """Tolerating a shorter *known* layout must not become tolerating any
        payload: a truncated frame is not an older one, and decoding one would
        put whatever bytes arrived on screen as readings."""
        with pytest.raises(struct.error):
            hk.Housekeeping.unpack(b"\x00" * (hk.SIZE_PRE_CHAMBER - 1))

    def test_the_two_bme280s_fail_independently(self):
        """Ambient and chamber are two parts on two buses, and only the
        ambient one feeds the MCU's launch detection. A single flag would
        make a chamber sensor that never got fitted look like the ambient
        part failing, which is the one sensor fault that matters in flight.
        """
        chm = hk.Housekeeping(error_flags=hk.HkErrors.BME280_CHM_FAIL)
        assert chm.error_text == "BME280_CHM_FAIL"
        amb = hk.Housekeeping(error_flags=hk.HkErrors.BME280_FAIL)
        assert amb.error_text == "BME280_FAIL"
        assert hk.HkErrors.BME280_FAIL != hk.HkErrors.BME280_CHM_FAIL

    def test_motor_sense_rides_the_wire_raw_and_scales_on_the_ground(self):
        """The ACT_HB_SENS ADC counts go down raw; the DRV8251A IPROPI chain
        turns them into the dispersion motor's amps here, on the ground, so a
        wrong resistor or gain is correctable against a logged session."""
        h = hk.Housekeeping(hb_sense_raw=2048)
        g = hk.Housekeeping.unpack(h.pack())
        assert g.hb_sense_raw == 2048
        assert g.hb_sense_v() == pytest.approx(1.65)
        assert g.hb_sense_a() == pytest.approx(1.65 * hk.HB_SENSE_A_PER_V)
        assert g.hb_sense_text == "0.733A"
        row = g.to_row()
        assert row["hb_sense_raw"] == 2048
        assert row["hb_sense_v"] == pytest.approx(1.65)
        assert row["hb_sense_a"] == pytest.approx(0.7333, abs=1e-4)
        assert row["hb_sense_text"] == "0.733A"

    def test_the_ipropi_gain_is_the_datasheet_chain_not_a_guess(self):
        """1 / (R_IPROPI * AIPROPI): 1.5 kOhm on the carrier against the
        DRV8251A's 1500 uA/A, so full scale (3.3 V) is 1.47 A."""
        assert hk.IPROPI_R_OHM == 1500.0
        assert hk.IPROPI_GAIN_A_PER_A == pytest.approx(1.5e-3)
        assert hk.HB_SENSE_A_PER_V == pytest.approx(0.4444, abs=1e-4)
        full = hk.Housekeeping(hb_sense_raw=4095)
        assert full.hb_sense_a() == pytest.approx(1.466, abs=1e-3)

    def test_motor_sense_falls_back_to_volts_without_a_gain(self, monkeypatch):
        """Clear the gain and the panel shows the pin voltage rather than a
        current it cannot derive - 0.0 A would claim an idle motor."""
        monkeypatch.setattr(hk, "HB_SENSE_A_PER_V", None)
        h = hk.Housekeeping(hb_sense_raw=2048)
        assert h.hb_sense_a() is None
        assert h.hb_sense_text == "1.650V"
        assert h.to_row()["hb_sense_a"] == ""

    def test_motor_sense_sentinel_is_no_reading_not_zero(self):
        """A pico2 build cannot reach GP46 and sends the sentinel; 0 counts
        is what an idle motor reads - and what a coasting one reads, since
        IPROPI only mirrors low-side current - so the two must differ."""
        assert hk.HB_SENSE_INVALID == 0xFFFF and hk.HB_SENSE_INVALID > 4095
        none = hk.Housekeeping()                       # default: no reading
        assert none.hb_sense_v() is None and none.hb_sense_text == "-"
        idle = hk.Housekeeping(hb_sense_raw=0)
        assert idle.hb_sense_v() == 0.0 and idle.hb_sense_text == "0.000A"
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
