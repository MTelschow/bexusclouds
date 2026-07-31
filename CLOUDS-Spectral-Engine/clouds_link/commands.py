"""Command set + arm/execute rules (spec S.2, S.8, S.10).

Uplink is TCP; every command frame is answered by an ACK frame. Actuator
commands (RELEASE) additionally require a preceding ARM naming the command,
within ARM_WINDOW_S - enforced by the Pi command server (authoritative)
and pre-checked by the GSE for operator feedback.
"""
from __future__ import annotations

from enum import IntEnum

ARM_WINDOW_S = 10.0
HEARTBEAT_INTERVAL_S = 5.0      # GSE sends PING at this rate
LINK_LOSS_LATCH_S = 600.0       # MCU latches autonomous after this (O.2)


class Command(IntEnum):
    PING = 0x00        # heartbeat; also refreshes link-ok on the MCU
    START = 0x01       # accelerate STANDBY -> ASCENT (S.2: override only)
    HOLD = 0x02
    RESUME = 0x03
    ABORT = 0x04       # -> TERMINATION -> SAFE
    RELEASE = 0x05     # key = 1 | 2; requires ARM (S.8)
    SET_PARAM = 0x06   # key = Param, value = i32
    STATUS_REQ = 0x07
    ARM = 0x08         # key = command code being armed


#: Commands that require a prior ARM within ARM_WINDOW_S.
ARMED_COMMANDS = frozenset({Command.RELEASE})

#: Commands the GSE refuses to send while on ground (S.10) unless the
#: operator has explicitly enabled flight mode.
GROUND_INTERLOCKED = frozenset({Command.RELEASE, Command.START})


class Param(IntEnum):
    """SET_PARAM keys - mirror of config.h on the MCU. Values are i32."""
    LAUNCH_DP_PA = 1          # pressure drop vs ground ref (default 5000)
    LAUNCH_DEBOUNCE_S = 2     # sustained for this long (default 60)
    FLOAT_P_PA = 3            # float if below (default 5500 Pa ~ 20 km)
    FLOAT_DPDT_CPA_S = 4      # |dp/dt| below, centi-Pa/s (default 500)
    FLOAT_HOLD_S = 5          # for this long (default 300)
    T_FLOAT_S = 6             # timer fallback after launch (default 7200)
    LINKLOSS_S = 7            # autonomous latch (default 600)
    T_MEASURE_S = 8           # per measurement phase (default 480, P.6+P.7)
    MEMBRANE_HZ = 9           # solenoid PWM frequency (default 50)
    MEMBRANE_DUTY = 10        # percent (default 60)
    SEAL_RETRY = 11           # seal verification retries (default 3)
