"""Housekeeping payload (PacketType.HK) - 44 bytes, little-endian.

Produced by the RP2350 at 1 Hz (C mirror flight/mcu/src/core/frame.c),
relayed unchanged by the Pi, decoded by the GSE. Two RH channels are
reserved per spec section 7 (F.6 needs humidity in two locations).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field, asdict
from enum import IntEnum

_HK = struct.Struct("<BBBBBBhhhHHIIhhhhhhII")
SIZE = _HK.size  # 44


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


class HkErrors(IntEnum):
    """Mirror of the HKE_* bits in flight/mcu/src/core/frame.h.

    A set bit means the matching field is not a live measurement, so ground
    can distinguish a held or absent reading from a real one.
    """
    BME280_FAIL = 1 << 0    # BME280 absent or read failed
    P_AMB_STALE = 1 << 1    # p_amb_pa is a held last-good value
    NO_CHAMBER_P = 1 << 2   # no chamber pressure sensor fitted
    NO_RH2 = 1 << 3         # no second humidity channel fitted
    IMU_FAIL = 1 << 4       # IMU absent or reporting a fault


@dataclass
class Housekeeping:
    state: int = 0
    flags: int = 0
    fired: int = 0            # bit0 pinch valve 1, bit1 pinch valve 2 (S.3)
    valve_status: int = 0     # bitfield: 4 valves currently driven open
    membrane_duty: int = 0    # percent
    error_flags: int = 0
    temp1_cc: int = 0         # STLM20 #1, centi-degC
    temp2_cc: int = 0         # STLM20 #2
    bme_temp_cc: int = 0
    rh1_cpct: int = 0         # centi-%RH, ambient
    rh2_cpct: int = 0         # centi-%RH, chamber (reserved, spec sec. 7)
    p_amb_pa: int = 101325
    p_ch_pa: int = 101325
    accel_mg: tuple = field(default=(0, 0, 0))
    gyro_ddps: tuple = field(default=(0, 0, 0))
    uptime_s: int = 0
    mission_t_s: int = 0      # 0 until launch detection

    def pack(self) -> bytes:
        return _HK.pack(self.state, self.flags, self.fired, self.valve_status,
                        self.membrane_duty, self.error_flags,
                        self.temp1_cc, self.temp2_cc, self.bme_temp_cc,
                        self.rh1_cpct, self.rh2_cpct,
                        self.p_amb_pa, self.p_ch_pa,
                        *self.accel_mg, *self.gyro_ddps,
                        self.uptime_s, self.mission_t_s)

    @classmethod
    def unpack(cls, payload: bytes) -> "Housekeeping":
        v = _HK.unpack_from(payload)
        return cls(state=v[0], flags=v[1], fired=v[2], valve_status=v[3],
                   membrane_duty=v[4], error_flags=v[5],
                   temp1_cc=v[6], temp2_cc=v[7], bme_temp_cc=v[8],
                   rh1_cpct=v[9], rh2_cpct=v[10],
                   p_amb_pa=v[11], p_ch_pa=v[12],
                   accel_mg=(v[13], v[14], v[15]),
                   gyro_ddps=(v[16], v[17], v[18]),
                   uptime_s=v[19], mission_t_s=v[20])

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
        ax, ay, az = d.pop("accel_mg")
        gx, gy, gz = d.pop("gyro_ddps")
        d.update(accel_x_mg=ax, accel_y_mg=ay, accel_z_mg=az,
                 gyro_x_ddps=gx, gyro_y_ddps=gy, gyro_z_ddps=gz)
        return d
