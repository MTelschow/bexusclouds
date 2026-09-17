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
    MEMBRANE = 0x09    # key = duty percent, 0 = off (M-07 manual drive)
    DISPERSE = 0x0A    # key = DisperseKey: stop / one pulse / run


class DisperseKey(IntEnum):
    """DISPERSE keys - mirror of DISPERSE_* in frame.h. The key is the
    request, never the speed (that is Param.DISPERSE_DUTY): PULSE is the
    bounded 5 s drive a release also schedules, RUN holds the motor on until
    STOP, and STOP ends either - it can only de-energize, so the MCU honours
    it in every state, TERMINATION and SAFE included."""
    STOP = 0
    PULSE = 1
    RUN = 2


#: Commands that require a prior ARM within ARM_WINDOW_S.
ARMED_COMMANDS = frozenset({Command.RELEASE})

#: Direct actuator drives for the dispersion hardware (M-07). Deliberately
#: outside ARMED_COMMANDS and GROUND_INTERLOCKED: unlike RELEASE, neither is
#: irreversible - the membrane solenoid oscillates while it is told to and
#: stops on MEMBRANE key=0, and the motor runs one bounded pulse or runs until
#: DISPERSE STOP - and driving them on the bench is the whole point of having
#: them on the panel. The MCU still refuses both in TERMINATION and SAFE, so
#: an abort cannot be undone from the panel (DISPERSE STOP excepted: it only
#: de-energizes).
MANUAL_ACTUATORS = frozenset({Command.MEMBRANE, Command.DISPERSE})

#: Commands the GSE refuses to send while on ground (S.10) unless the
#: operator has explicitly enabled flight mode.
GROUND_INTERLOCKED = frozenset({Command.RELEASE, Command.START})

#: Commands the *Pi* refuses unless the MCU's housekeeping says the
#: experiment is flying - the ground interlock as defence in depth, since the
#: GSE's own check (G-04) lives on a laptop and anything can open TCP 4001.
#: START is deliberately absent: it is the on-pad accelerator that creates the
#: in-flight state in the first place, so interlocking it would be circular.
FLIGHT_ONLY = frozenset({Command.RELEASE})

#: Commands whose ACK to ground carries the *MCU's* own verdict: the Pi waits
#: for the MCU's ACK over UART and relays its result. PING is deliberately
#: absent - it is the heartbeat addressed to the Pi (S.8), which must answer
#: it even while the RP2350 is silent; PISTATUS.uart_ok reports that instead.
MCU_CONFIRMED = frozenset({Command.START, Command.HOLD, Command.RESUME,
                           Command.ABORT, Command.RELEASE, Command.SET_PARAM,
                           Command.ARM, Command.MEMBRANE, Command.DISPERSE})


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
    MEMBRANE_MHZ = 9          # solenoid drive frequency, MILLIhertz (default
                              # 2000 = 2 Hz; 100..400000). Was MEMBRANE_HZ in
                              # whole Hz - the operator needs 0.1..0.9 Hz
    MEMBRANE_DUTY = 10        # percent (default 60)
    SEAL_RETRY = 11           # seal verification retries (default 3)
    PI_SILENT_S = 12          # MCU declares the Pi lost after this (default 60)
    DISPERSE_DUTY = 13        # CaCO3 motor speed, percent (default 100)
