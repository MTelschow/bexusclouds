"""Housekeeping payload (PacketType.HK) - 64 bytes, little-endian.

Produced by the RP2350 at 1 Hz (C mirror flight/mcu/src/core/frame.c),
relayed unchanged by the Pi, decoded by the GSE.

**Chamber temperature, humidity and pressure are the last eight bytes**, from
a second BME280 on the carrier's SPI_1 bus behind the chip select on GP9,
with an error bit of their own.

The chamber part is **instrumentation, not a control input**: the MCU's
launch and float detection reads ``p_amb_pa``, the ambient part on i2c0, and
nothing in the sequencer touches ``chm_*``. That is why a chamber failure is
``HkErrors.BME280_CHM_FAIL`` and not folded into ``BME280_FAIL`` - two parts
on two buses fail independently, and only one of them can fire a valve.

There is still no second humidity channel on i2c0.

Four rails are carried, but only three monitors are fitted: the 24 V rail's
INA226 is not on the carrier yet, so its slot is reserved here and reported
as ``RAIL_MV_INVALID`` until the part is populated. A reserved slot is the
cheaper mistake: the alternative is a wire format that changes on the day
the part arrives, on an instrument that is already flying its protocol.

Two bytes before those, after ``mission_t_s``, are the CaCO3 dispersion
motor's current sense, the ``ACT_HB_SENS`` net on GP46 read by the RP2350B's ADC: raw 12-bit counts,
scaled to volts and amps here (``hb_sense_v()`` / ``hb_sense_a()``), for the
same reason the INA226 shunts come down raw. It is the IPROPI output of the
motor's DRV8251A H-bridge, not the membrane solenoid - ``ACT_HB`` is the
driver channel that carries GP17/GP18 (drive) and GP46 (sense) together.
Appended after ``mission_t_s`` so every older field keeps the offset a logged
session was written with.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field, asdict
from enum import IntEnum

_HK = struct.Struct("<BBBBBBhhhHIhhhhhhHHHHhhhhIIHhHI")
SIZE = _HK.size  # 64

#: The layout before the chamber BME280's eight bytes were appended
#: (2026-09-17), and the size an MCU flashed before that date still sends.
#:
#: This packet has only ever grown by appending, so a shorter payload is not a
#: corrupt one - it is an older one, and every field it does carry is at the
#: offset this decoder expects. ``unpack`` therefore accepts it rather than
#: raising, because the alternative is what actually happened on the bench:
#: the ground software was updated, the MCU was not, every HK packet failed to
#: decode, and the operator panel went blank in both its sections with no
#: message saying why. A wire-format change must degrade to "these fields have
#: no source", never to "there is no telemetry".
#:
#: The fields the older packet does not carry are filled the way the MCU
#: itself fills them when the part does not answer - zeros behind
#: ``HkErrors.BME280_CHM_FAIL`` - so nothing on screen is a number that no
#: hardware produced.
_HK_PRE_CHAMBER = struct.Struct("<BBBBBBhhhHIhhhhhhHHHHhhhhIIH")
SIZE_PRE_CHAMBER = _HK_PRE_CHAMBER.size  # 56

#: Payload sizes this decoder understands, smallest first.
KNOWN_SIZES = (SIZE_PRE_CHAMBER, SIZE)


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
#: an idle motor reads, and the two must stay distinguishable.
HB_SENSE_INVALID = 0xFFFF

#: Full scale of the RP2350 ADC and the reference it is measured against, in
#: volts. 3.3 V is the SDK's nominal ADC_VREF; the carrier's actual reference
#: has not been measured, so an amp value carries that assumption too.
HB_SENSE_ADC_COUNTS = 4096
HB_SENSE_VREF_V = 3.3

#: The DRV8251A current-sense chain on the dispersion motor's H-bridge.
#:
#: The part has no external power shunt: an internal current mirror on the
#: low-side FETs drives the IPROPI pin with a current proportional to the
#: motor current, ``I_IPROPI = I_motor x AIPROPI``, and the carrier turns that
#: back into a voltage across ``R_IPROPI`` to ground, which is what GP46
#: measures. ``AIPROPI`` is the datasheet's 1500 uA/A typical (the AERR spec
#: covers offset and gain error together); ``R_IPROPI`` is the 1.5 kOhm fitted
#: on the carrier.
IPROPI_GAIN_A_PER_A = 1.5e-3
IPROPI_R_OHM = 1500.0

#: Amps of motor current per volt at the ACT_HB_SENS pin, from the chain
#: above: ``1 / (R_IPROPI * AIPROPI)`` = 0.444 A/V, i.e. a 3.3 V full-scale
#: ADC reading is 1.47 A.
#:
#: The counts still go down the link raw and are scaled here, as the INA226
#: shunts are: if the resistor turns out to be a different value, or the
#: measured AIPROPI of this part differs, every logged session can be
#: re-derived, which an amp value the firmware had already computed could not.
#:
#: **A reading of 0 is not proof of no current.** IPROPI only sees current
#: flowing drain-to-source in a low-side FET, so it is valid while the bridge
#: drives or brakes and reads zero in coast, where the winding current
#: freewheels through the body diodes. The dispersion motor is driven forward
#: (GP17 high, GP18 low) in bounded 5 s pulses and coasts the rest of the
#: time, so a run shows a few in-pulse samples at 1 Hz and 0 between them.
HB_SENSE_A_PER_V: float | None = 1.0 / (IPROPI_R_OHM * IPROPI_GAIN_A_PER_A)


class ValveStatus(IntEnum):
    """Mirror of the HKV_* bits in flight/mcu/src/core/frame.h.

    A set bit means that actuator line is energized *now*. The drives are
    bounded pulses (5 s) that can finish between two 1 Hz packets, so this is
    where ground sees a commanded valve or motor drive actually happen. Only
    one *drive* bit is ever set at a time: the MCU drives one line at a time
    to cap peak actuator current. The membrane drive is not here - it is a
    repeating waveform, reported as ``membrane_duty``.

    ``MEMBRANE_PULLED`` is the exception in kind: it is an **input**, the
    position switch on GP30 on the solenoid plunger - released while the
    solenoid rests, pressed (bit set) while it is actuated. It reports what
    the plunger is doing, not what the MCU is
    driving, so it can be set alongside a drive bit. When the MCU build
    cannot reach GP30 it raises ``HkErrors.NO_MEMBRANE_SENSE`` and the bit
    means nothing; ``Housekeeping.membrane_pulled`` folds that in.

    ``MEMBRANE_CYCLING`` is the switch's history: set when it changed state
    at least once since the previous HK packet. It is the evidence that a
    commanded drive moves anything, because ``MEMBRANE_PULLED`` alone cannot
    be: HK is sent every 1000 ms and the membrane's 500 ms cycle is timed by
    the same MCU loop, so the 1 Hz sample sits at a fixed phase and reads the
    same value packet after packet whether the plunger moves or not. The MCU
    samples the switch every 10 ms pass and latches any edge into this bit.
    """
    PINCH_1 = 1 << 0
    PINCH_2 = 1 << 1
    EQ1_CLOSE = 1 << 2
    EQ2_CLOSE = 1 << 3
    DISPERSE = 1 << 4        # CaCO3 dispersion motor, forward line (pulse or run)
    MEMBRANE_PULLED = 1 << 5  # sensed, not driven: GP30 switch pressed (LOW) now
    MEMBRANE_CYCLING = 1 << 6  # sensed: GP30 switch changed since the last HK


#: The ``ValveStatus`` bits that are drives - what ``actuator_text`` lists.
#: The two membrane sense bits are positions, and belong with the membrane row.
SENSE_BITS = (ValveStatus.MEMBRANE_PULLED, ValveStatus.MEMBRANE_CYCLING)
DRIVE_BITS = tuple(v for v in ValveStatus if v not in SENSE_BITS)


class HkErrors(IntEnum):
    """Mirror of the HKE_* bits in flight/mcu/src/core/frame.h.

    A set bit means the matching field is not a live measurement, so ground
    can distinguish a held or absent reading from a real one.

    Bits 2 and 3 carried two retired sensor flags before 2026-09-11 and
    have been reused since - bit 2 for the membrane switch, bit 3 for the
    chamber BME280. Every other bit has kept the position it had, so an
    older session log still decodes on those; these two do not, which is why
    a log has to be read against the ``SIZE`` its frames carry.
    """
    BME280_FAIL = 1 << 0    # BME280 absent or read failed
    P_AMB_STALE = 1 << 1    # p_amb_pa is a held last-good value
    NO_MEMBRANE_SENSE = 1 << 2  # GP30 unreachable in this MCU build (pico2):
                                # ValveStatus.MEMBRANE_PULLED has no source
    BME280_CHM_FAIL = 1 << 3    # chamber BME280 (SPI_1 / GP9) absent or read
                                # failed: the chm_* fields are zeros. Separate
                                # from BME280_FAIL - different bus, different
                                # part, and only the ambient one feeds the
                                # MCU's launch detection
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
    #: Dispersion motor current sense (ACT_HB_SENS, GP46 / ADC6): raw
    #: 12-bit ADC counts, 0..4095. ``HB_SENSE_INVALID`` means this MCU build
    #: cannot reach the pin. Defaults to "no reading" like ``rail_mv``.
    hb_sense_raw: int = HB_SENSE_INVALID
    #: Chamber BME280 (SPI_1, chip select GP9): the test chamber's own
    #: temperature, humidity and pressure, same units as the ambient part's
    #: ``bme_temp_cc`` / ``rh1_cpct`` / ``p_amb_pa``. Zeros behind
    #: ``HkErrors.BME280_CHM_FAIL`` when the part did not answer - the MCU
    #: does not hold the last good value here, as it does for ``p_amb_pa``,
    #: because nothing reads these and a held value would look current.
    #:
    #: The pressure default is sea level like ``p_amb_pa``, so a
    #: ``Housekeeping()`` built in a test does not start out asserting a
    #: vacuum in the chamber.
    chm_temp_cc: int = 0
    chm_rh_cpct: int = 0
    chm_p_pa: int = 101325

    def pack(self) -> bytes:
        return _HK.pack(self.state, self.flags, self.fired, self.valve_status,
                        self.membrane_duty, self.error_flags,
                        self.temp1_cc, self.temp2_cc, self.bme_temp_cc,
                        self.rh1_cpct, self.p_amb_pa,
                        *self.accel_mg, *self.gyro_ddps,
                        *self.rail_mv, *self.shunt_raw,
                        self.uptime_s, self.mission_t_s,
                        self.hb_sense_raw,
                        self.chm_temp_cc, self.chm_rh_cpct, self.chm_p_pa)

    @classmethod
    def unpack(cls, payload: bytes) -> "Housekeeping":
        """Decode an HK payload, of this version or of an older, shorter one.

        A payload at least ``SIZE`` bytes long is decoded in full. One that is
        ``SIZE_PRE_CHAMBER`` long comes from an MCU flashed before the chamber
        BME280 was added: its fields are all at the offsets this decoder
        expects, because the packet has only ever grown by appending, so it is
        decoded and the chamber fields are reported as having no source rather
        than the whole packet being thrown away. See ``_HK_PRE_CHAMBER``.

        Anything shorter than that is genuinely undecodable and raises, as
        before - a truncated frame is not an old one.
        """
        n = len(payload)
        if n < SIZE:
            if n < SIZE_PRE_CHAMBER:
                raise struct.error(
                    f"HK payload is {n} B, shorter than any known layout "
                    f"{KNOWN_SIZES}")
            v = _HK_PRE_CHAMBER.unpack_from(payload)
            # Zeros behind the flag, exactly as the MCU sends when the chamber
            # part does not answer: the dataclass defaults include a sea-level
            # chm_p_pa, and defaulting to that here would put a pressure on
            # screen that no sensor produced.
            chm = dict(chm_temp_cc=0, chm_rh_cpct=0, chm_p_pa=0)
            err = v[5] | HkErrors.BME280_CHM_FAIL
        else:
            v = _HK.unpack_from(payload)
            chm = dict(chm_temp_cc=v[28], chm_rh_cpct=v[29], chm_p_pa=v[30])
            err = v[5]
        return cls(state=v[0], flags=v[1], fired=v[2], valve_status=v[3],
                   membrane_duty=v[4], error_flags=err,
                   temp1_cc=v[6], temp2_cc=v[7], bme_temp_cc=v[8],
                   rh1_cpct=v[9], p_amb_pa=v[10],
                   accel_mg=(v[11], v[12], v[13]),
                   gyro_ddps=(v[14], v[15], v[16]),
                   rail_mv=(v[17], v[18], v[19], v[20]),
                   shunt_raw=(v[21], v[22], v[23], v[24]),
                   uptime_s=v[25], mission_t_s=v[26],
                   hb_sense_raw=v[27], **chm)

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
        """Voltage across R_IPROPI at the motor current-sense pin, or None if
        this MCU build has no reading for it. Assumes ``HB_SENSE_VREF_V``."""
        if self.hb_sense_raw == HB_SENSE_INVALID:
            return None
        return self.hb_sense_raw * HB_SENSE_VREF_V / HB_SENSE_ADC_COUNTS

    def hb_sense_a(self) -> float | None:
        """CaCO3 dispersion motor current in amps, or None when there is no
        reading **or no calibration**: with ``HB_SENSE_A_PER_V`` unset a
        current cannot be derived, and 0.0 would claim an idle motor.

        0.0 A is a real reading, but it means "no current through a low-side
        FET", which is also what coast looks like - see ``HB_SENSE_A_PER_V``.
        """
        v = self.hb_sense_v()
        if v is None or HB_SENSE_A_PER_V is None:
            return None
        return v * HB_SENSE_A_PER_V

    @property
    def hb_sense_text(self) -> str:
        """The motor current row for HK displays: amps from the DRV8251A
        IPROPI chain, or the bare pin voltage if ``HB_SENSE_A_PER_V`` is ever
        cleared, ``-`` for no reading. A voltage rather than nothing in that
        case, because it still answers the question the sensor exists for -
        does the current rise with the drive and fall without it."""
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
        displays. A commanded drive is a 5 s pulse (or, for the dispersion
        motor, a run held until DISPERSE STOP), so this is what tells an
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
    def membrane_cycling(self) -> bool | None:
        """Whether the GP30 switch changed state since the previous HK packet,
        or ``None`` when the switch is unsourced in this MCU build."""
        if self.error_flags & HkErrors.NO_MEMBRANE_SENSE:
            return None
        return bool(self.valve_status & ValveStatus.MEMBRANE_CYCLING)

    @property
    def membrane_text(self) -> str:
        """The membrane row for HK displays: the commanded duty, the sensed
        plunger position at the sample, and whether it moved during the last
        second. The row is the check: ``60 %  pulled, cycling`` is a working
        drive; ``60 %  pushed, not cycling`` is a solenoid, a driver or a
        switch to look at; ``0 %  pushed`` is rest. The position alone is
        one fixed-phase sample of a 2 Hz cycle and says nothing about
        motion, which is why ``cycling`` is printed with it whenever the
        drive is on."""
        pulled = self.membrane_pulled
        if pulled is None:
            return f"{self.membrane_duty} %"
        text = f"{self.membrane_duty} %  {'pulled' if pulled else 'pushed'}"
        if self.membrane_cycling:
            text += ", cycling"
        elif self.membrane_duty:
            text += ", not cycling"
        return text

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
        An unknown bit is kept visible as its mask rather than dropped, so
        a log written by a newer MCU stays readable here.
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
        d["membrane_cycling"] = self.membrane_cycling
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
        # Same rule for the motor sense: the raw counts are in the row via
        # asdict(); the derived volts and amps sit beside them, blank where
        # there is no reading or (amps) no gain to apply yet.
        v, a = self.hb_sense_v(), self.hb_sense_a()
        d["hb_sense_v"] = "" if v is None else round(v, 4)
        d["hb_sense_a"] = "" if a is None else round(a, 4)
        return d
