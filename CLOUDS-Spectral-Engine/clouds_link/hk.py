"""Housekeeping payload (PacketType.HK) - 56 bytes, little-endian.

Produced by the RP2350 at 1 Hz (C mirror flight/mcu/src/core/frame.c),
relayed unchanged by the Pi, decoded by the GSE.

The chamber pressure and second humidity channel that spec section 7 asks
for are **not** in this packet: the two Keller 23SY parts that were to
provide them are off the design (they answered at no address on the carrier,
DEVLOG 2026-08-31), and a wire field no part can ever fill is worse than an
absent one - it reads as data. The six bytes they held now carry the shunt
voltage of the INA226 monitors, which is a measurement that exists.

Four rails are carried, but only three monitors are fitted: the 24 V rail's
INA226 is not on the carrier yet, so its slot is reserved here and reported
as ``RAIL_MV_INVALID`` until the part is populated. A reserved slot is the
cheaper mistake: the alternative is a wire format that changes on the day
the part arrives, on an instrument that is already flying its protocol.

The last two bytes are the push-pull solenoid's current sense, the
``ACT_HB_SENS`` net on GP46 read by the RP2350B's ADC: raw 12-bit counts,
scaled to volts and amps here (``hb_sense_v()`` / ``hb_sense_a()``), for the
same reason the INA226 shunts come down raw. Appended after ``mission_t_s``
so every older field keeps the offset a logged session was written with.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field, asdict
from enum import IntEnum

_HK = struct.Struct("<BBBBBBhhhHIhhhhhhHHHHhhhhIIH")
SIZE = _HK.size  # 56


class SeqState(IntEnum):
    """Mirror of seq_state_t in flight/mcu/src/core/sequencer.h."""
    INIT = 0
    STANDBY = 1
    ASCENT = 2
    SEAL = 3
    RELEASE_1 = 4
    MEASURE_1 = 5
    RELEASE_2 = 6
    MEASURE_2 = 7
    TERMINATION = 8
    SAFE = 9


class McuFlags(IntEnum):
    AUTONOMOUS_LATCHED = 1 << 0   # link lost > threshold (O.2)
    LINK_OK = 1 << 1
    PI_OK = 1 << 2
    SEAL_VERIFIED = 1 << 3
    HOLD = 1 << 4


#: "No reading" for a ``rail_mv`` entry - mirror of RAIL_MV_INVALID in
#: flight/mcu/src/hw/ina226.h. Not 0, because a rail can legitimately be at
#: 0 mV: the 24 V bus reads 0 on a USB-powered bench with no supply attached,
#: and collapsing that into the same value as a failed I2C transfer throws
#: away the distinction ground most needs. 0xFFFF is 65.535 V, above the
#: part's 36 V input rating, so it cannot be a real measurement.
#:
#: It covers the matching ``shunt_raw`` entry too: both registers are read
#: from the same part in the same sweep, and the MCU invalidates the pair
#: together rather than inventing a second sentinel for a distinction
#: (bus read fine, shunt read failed) that nobody would chase separately.
RAIL_MV_INVALID = 0xFFFF

#: Rail names, in ``rail_mv`` order, with the nominal each should sit near.
#:
#: ``V_in`` is the incoming gondola bus, the rail the 0x40 monitor actually
#: sits on - it was labelled "24 V" until the two were found to be different
#: nets. The **24 V rail proper has no monitor fitted yet**; its slot exists
#: so that adding the part is a firmware change and not a wire-format change.
RAIL_NAMES = ("V_in", "24 V", "5 V", "3.3 V")
RAIL_NOMINAL_MV = (24000, 24000, 5000, 3300)

#: I2C address of each rail's INA226, or ``None`` where no part is fitted.
#: Mirrors addr_of[] in flight/mcu/src/hw/ina226.c.
RAIL_I2C_ADDR = (0x40, None, 0x44, 0x45)

#: LSB of the INA226 shunt-voltage register, in microvolts. Absolute, from
#: the datasheet: unlike the part's current and power registers it does not
#: depend on the calibration register being programmed, so the raw i16 is a
#: real voltage measurement whatever the MCU knows about the shunts.
SHUNT_LSB_UV = 2.5

#: Shunt resistance per rail, in milliohms, in ``rail_mv`` order.
#:
#: The conversion from shunt voltage to current happens **here**, on the
#: ground, and not on the MCU: if one of these numbers turns out to be wrong,
#: a logged session can be re-derived from ``shunt_raw``, whereas an amp value
#: the firmware had already computed could not. Ohm's law in these units is
#: exactly ``I[mA] = U[uV] / R[mOhm]``; ``rail_a()`` scales that to amps.
RAIL_SHUNT_MOHM = (10.0, 15.0, 50.0, 50.0)

#: "No reading" for ``hb_sense_raw`` - mirror of HB_SENSE_INVALID in
#: flight/mcu/src/core/frame.h. The ADC is 12-bit, so a real sample is
#: 0..4095 and 0xFFFF cannot be one. It is what a build that cannot reach
#: GP46 (pico2 / RP2350A) downlinks: not 0, because 0 counts is exactly what
#: a de-energized solenoid reads, and the two must stay distinguishable.
HB_SENSE_INVALID = 0xFFFF

#: Full scale of the RP2350 ADC and the reference it is measured against, in
#: volts. 3.3 V is the SDK's nominal ADC_VREF; the carrier's actual reference
#: has not been measured, so a sense *voltage* shown on the panel carries
#: that assumption.
HB_SENSE_ADC_COUNTS = 4096
HB_SENSE_VREF_V = 3.3

#: Amps per volt at the ACT_HB_SENS pin - the solenoid current-sense gain.
#:
#: ``None`` until measured: the schematic page we have names the net and
#: nothing else (no sense resistor, no amplifier gain, no proportional-output
#: resistor), and a guessed number here would put a confident wrong current
#: on the panel and in every session log. While it is ``None`` the ground
#: shows the sense **voltage** only; set it and ``hb_sense_a()`` starts
#: returning amps, for live packets and for every logged ``hb_sense_raw``
#: alike - which is why the counts go down raw rather than an amp value the
#: firmware computed.
HB_SENSE_A_PER_V: float | None = None


class ValveStatus(IntEnum):
    """Mirror of the HKV_* bits in flight/mcu/src/core/frame.h.

    A set bit means that actuator line is energized *now*. The drives are
    bounded pulses (5 s) that can finish between two 1 Hz packets, so this is
    where ground sees a commanded valve or motor drive actually happen. Only
    one *drive* bit is ever set at a time: the MCU drives one line at a time
    to cap peak actuator current. The membrane drive is not here - it is a
    repeating waveform, reported as ``membrane_duty``.

    ``MEMBRANE_PULLED`` is the exception in kind: it is an **input**, the
    position switch on GP30 that the solenoid plunger presses while it is
    energized. It reports what the plunger is doing, not what the MCU is
    driving, so it can be set alongside a drive bit, and it is the only
    evidence ground has that a commanded membrane drive moves anything. When
    the MCU build cannot reach GP30 it raises ``HkErrors.NO_MEMBRANE_SENSE``
    and the bit means nothing; ``Housekeeping.membrane_pulled`` folds that in.
    """
    PINCH_1 = 1 << 0
    PINCH_2 = 1 << 1
    EQ1_CLOSE = 1 << 2
    EQ2_CLOSE = 1 << 3
    DISPERSE = 1 << 4        # CaCO3 dispersion motor, forward line
    MEMBRANE_PULLED = 1 << 5  # sensed, not driven: GP30 switch reads LOW


#: The ``ValveStatus`` bits that are drives - what ``actuator_text`` lists.
#: ``MEMBRANE_PULLED`` is a sensed position and belongs with the membrane row.
DRIVE_BITS = tuple(v for v in ValveStatus if v is not ValveStatus.MEMBRANE_PULLED)


class HkErrors(IntEnum):
    """Mirror of the HKE_* bits in flight/mcu/src/core/frame.h.

    A set bit means the matching field is not a live measurement, so ground
    can distinguish a held or absent reading from a real one.

    Bit 2 was NO_CHAMBER_P and bit 3 NO_RH2; both went out with the Keller
    pair and the fields those flagged. Bit 2 has since been reused for the
    membrane switch; bit 3 is free. The surviving bits keep the positions
    they had, so an older session log still decodes.
    """
    BME280_FAIL = 1 << 0    # BME280 absent or read failed
    P_AMB_STALE = 1 << 1    # p_amb_pa is a held last-good value
    NO_MEMBRANE_SENSE = 1 << 2  # GP30 unreachable in this MCU build (pico2):
                                # ValveStatus.MEMBRANE_PULLED has no source
    IMU_FAIL = 1 << 4       # IMU absent or reporting a fault
    NO_TEMP = 1 << 5        # STLM20 pair not fitted, temps unsourced
    RAIL_FAIL = 1 << 6      # an INA226 rail is unreadable (see RAIL_MV_INVALID)


@dataclass
class Housekeeping:
    state: int = 0
    flags: int = 0
    fired: int = 0            # bit0 pinch valve 1, bit1 pinch valve 2 (S.3)
    valve_status: int = 0     # ValveStatus bits: line energized right now
    membrane_duty: int = 0    # percent
    error_flags: int = 0
    temp1_cc: int = 0         # STLM20 #1, centi-degC
    temp2_cc: int = 0         # STLM20 #2
    bme_temp_cc: int = 0
    rh1_cpct: int = 0         # centi-%RH, ambient
    p_amb_pa: int = 101325
    accel_mg: tuple = field(default=(0, 0, 0))
    gyro_ddps: tuple = field(default=(0, 0, 0))
    #: Bus voltage of the V_in, 24 V, 5 V and 3.3 V rails in mV, in
    #: ``RAIL_NAMES`` order (INA226 at 0x40 / not fitted / 0x44 / 0x45).
    #: ``RAIL_MV_INVALID`` means no reading, which is what the 24 V slot
    #: carries until its monitor is populated. Defaults to "no reading"
    #: rather than 0, so a Housekeeping() built in a test never asserts that
    #: every rail is dead.
    rail_mv: tuple = field(default=(RAIL_MV_INVALID,) * 4)
    #: Raw INA226 shunt-voltage register per rail, same order: signed,
    #: ``SHUNT_LSB_UV`` per count. Meaningful only where ``rail_mv`` is not
    #: ``RAIL_MV_INVALID``; use ``rail_a()``, which enforces that.
    shunt_raw: tuple = field(default=(0, 0, 0, 0))
    uptime_s: int = 0
    mission_t_s: int = 0      # 0 until launch detection
    #: Push-pull solenoid current sense (ACT_HB_SENS, GP46 / ADC6): raw
    #: 12-bit ADC counts, 0..4095. ``HB_SENSE_INVALID`` means this MCU build
    #: cannot reach the pin. Defaults to "no reading" like ``rail_mv``.
    hb_sense_raw: int = HB_SENSE_INVALID

    def pack(self) -> bytes:
        return _HK.pack(self.state, self.flags, self.fired, self.valve_status,
                        self.membrane_duty, self.error_flags,
                        self.temp1_cc, self.temp2_cc, self.bme_temp_cc,
                        self.rh1_cpct, self.p_amb_pa,
                        *self.accel_mg, *self.gyro_ddps,
                        *self.rail_mv, *self.shunt_raw,
                        self.uptime_s, self.mission_t_s,
                        self.hb_sense_raw)

    @classmethod
    def unpack(cls, payload: bytes) -> "Housekeeping":
        v = _HK.unpack_from(payload)
        return cls(state=v[0], flags=v[1], fired=v[2], valve_status=v[3],
                   membrane_duty=v[4], error_flags=v[5],
                   temp1_cc=v[6], temp2_cc=v[7], bme_temp_cc=v[8],
                   rh1_cpct=v[9], p_amb_pa=v[10],
                   accel_mg=(v[11], v[12], v[13]),
                   gyro_ddps=(v[14], v[15], v[16]),
                   rail_mv=(v[17], v[18], v[19], v[20]),
                   shunt_raw=(v[21], v[22], v[23], v[24]),
                   uptime_s=v[25], mission_t_s=v[26],
                   hb_sense_raw=v[27])

    def rail_uv(self, i: int) -> float | None:
        """Shunt voltage of rail ``i`` in microvolts, or None if that monitor
        gave no reading."""
        if self.rail_mv[i] == RAIL_MV_INVALID:
            return None
        return self.shunt_raw[i] * SHUNT_LSB_UV

    def rail_a(self, i: int) -> float | None:
        """Current through rail ``i`` in amps, or None if that monitor gave no
        reading.

        A rail whose monitor did not answer has no current, and returning 0.0
        would claim an idle rail - the same mistake ``RAIL_MV_INVALID`` exists
        to prevent on the voltage side.
        """
        uv = self.rail_uv(i)
        if uv is None:
            return None
        return uv / (RAIL_SHUNT_MOHM[i] * 1000.0)

    def hb_sense_v(self) -> float | None:
        """Voltage at the solenoid current-sense pin, or None if this MCU
        build has no reading for it. Assumes ``HB_SENSE_VREF_V``."""
        if self.hb_sense_raw == HB_SENSE_INVALID:
            return None
        return self.hb_sense_raw * HB_SENSE_VREF_V / HB_SENSE_ADC_COUNTS

    def hb_sense_a(self) -> float | None:
        """Push-pull solenoid current in amps, or None when there is no
        reading **or no calibration**: with ``HB_SENSE_A_PER_V`` unset a
        current cannot be derived, and 0.0 would claim an idle solenoid."""
        v = self.hb_sense_v()
        if v is None or HB_SENSE_A_PER_V is None:
            return None
        return v * HB_SENSE_A_PER_V

    @property
    def hb_sense_text(self) -> str:
        """The solenoid current row for HK displays: amps once the sense gain
        is known, the pin voltage until then, ``-`` for no reading. The
        voltage is shown rather than nothing because it already answers the
        question the sensor exists for - does the current rise with the
        drive and fall without it - and the scale can be applied later."""
        v = self.hb_sense_v()
        if v is None:
            return "-"
        a = self.hb_sense_a()
        return f"{v:.3f}V" if a is None else f"{a:.3f}A"

    @property
    def link_text(self) -> str:
        """Compact rendering of ``flags`` for HK displays.

        The link and interlock story lives entirely in these bits - whether
        ground commands are getting through (``LINK_OK``), whether the MCU
        has given up on them (``AUTONOMOUS``), and whether the Pi is talking
        to the MCU at all (``PI_OK``, M-13). An operator who cannot see them
        cannot tell a quiet flight from a broken link.
        """
        short = {McuFlags.AUTONOMOUS_LATCHED: "AUTONOMOUS",
                 McuFlags.LINK_OK: "GND", McuFlags.PI_OK: "PI",
                 McuFlags.SEAL_VERIFIED: "SEALED", McuFlags.HOLD: "HOLD"}
        set_bits = [name for flag, name in short.items() if self.flags & flag]
        return " ".join(set_bits) if set_bits else "-"

    @property
    def actuator_text(self) -> str:
        """Which actuator lines ``valve_status`` says are driven, for HK
        displays. A commanded drive is a 5 s pulse, so this is what tells an
        operator the command reached the hardware. The sensed
        ``MEMBRANE_PULLED`` bit is left out: it is not a drive, and it is
        shown with the membrane duty (``membrane_text``) instead."""
        names = [v.name for v in DRIVE_BITS if self.valve_status & v]
        return " ".join(names) if names else "-"

    @property
    def membrane_pulled(self) -> bool | None:
        """What the position switch on GP30 says the solenoid plunger is
        doing: ``True`` pulled (energized), ``False`` pushed (released), or
        ``None`` when this MCU build cannot read the switch
        (``HkErrors.NO_MEMBRANE_SENSE``) - a clear bit then means nothing,
        and reporting it as "pushed" would be an invented reading."""
        if self.error_flags & HkErrors.NO_MEMBRANE_SENSE:
            return None
        return bool(self.valve_status & ValveStatus.MEMBRANE_PULLED)

    @property
    def membrane_text(self) -> str:
        """The membrane row for HK displays: the commanded duty and, next to
        it, the sensed plunger position. The two together are the check - a
        duty above zero with a switch that never reads pulled, or a duty of
        zero with one that does, is a solenoid or a switch to look at. At the
        membrane's 2 Hz the 1 Hz HK sample lands at a random phase, so with
        the drive on the position is expected to alternate between packets."""
        pulled = self.membrane_pulled
        if pulled is None:
            return f"{self.membrane_duty} %"
        return f"{self.membrane_duty} %  {'pulled' if pulled else 'pushed'}"

    @property
    def rail_text(self) -> str:
        """The rails for HK displays: volts and amps per rail.

        An unreadable rail reads ``-``, never a number: an INA226 that did not
        answer and a rail that is genuinely down are different faults, and
        0.000 V would report the first as the second. A rail with no monitor
        fitted - the 24 V rail today - reads the same way; the panel is where
        the two are told apart, from ``RAIL_I2C_ADDR``.
        """
        parts = []
        for i, name in enumerate(RAIL_NAMES):
            mv, a = self.rail_mv[i], self.rail_a(i)
            parts.append(f"{name} -" if a is None
                         else f"{name} {mv / 1000:.2f}V {a:.3f}A")
        return "  ".join(parts)

    @property
    def error_text(self) -> str:
        """Which ``error_flags`` bits are set, by name.

        Some of these bits are permanently set on this hardware (the STLM20
        pair is not populated), so the field is the operator's list of what
        has no source - and ``0x0030`` is not a list.
        An unknown bit is kept visible as its mask rather than dropped: a
        newer MCU, or an older log written when the Keller bits still
        existed, must stay readable here.
        """
        names = [e.name for e in HkErrors if self.error_flags & e]
        known = 0
        for e in HkErrors:
            known |= e
        rest = self.error_flags & ~known
        if rest:
            names.append(f"{rest:#06x}")
        return " ".join(names) if names else "-"

    @property
    def state_name(self) -> str:
        try:
            return SeqState(self.state).name
        except ValueError:
            return f"UNKNOWN({self.state})"

    def to_row(self) -> dict:
        """Flat dict for CSV/JSON session logging (GSE feature G-05)."""
        d = asdict(self)
        d["state_name"] = self.state_name
        d["link_text"] = self.link_text
        d["actuator_text"] = self.actuator_text
        d["membrane_pulled"] = self.membrane_pulled
        d["error_text"] = self.error_text
        d["rail_text"] = self.rail_text
        d["hb_sense_text"] = self.hb_sense_text
        ax, ay, az = d.pop("accel_mg")
        gx, gy, gz = d.pop("gyro_ddps")
        d.update(accel_x_mg=ax, accel_y_mg=ay, accel_z_mg=az,
                 gyro_x_ddps=gx, gyro_y_ddps=gy, gyro_z_ddps=gz)
        # Derived current per rail, alongside the raw register it came from:
        # a session log has to stay re-derivable if a shunt value turns out
        # to be wrong, and it has to be readable without doing the arithmetic.
        for i, name in enumerate(("vin", "24v", "5v", "3v3")):
            a = self.rail_a(i)
            d[f"rail_{name}_a"] = "" if a is None else round(a, 4)
        # Same rule for the solenoid sense: the raw counts are in the row via
        # asdict(); the derived volts and amps sit beside them, blank where
        # there is no reading or (amps) no gain to apply yet.
        v, a = self.hb_sense_v(), self.hb_sense_a()
        d["hb_sense_v"] = "" if v is None else round(v, 4)
        d["hb_sense_a"] = "" if a is None else round(a, 4)
        return d
