"""Command set (spec S.2).

Uplink is TCP; every command frame is answered by an ACK frame.

**Nothing gates a command any more (2026-09-18).** The ground interlock
(S.10) and the arm/execute rule (S.8) are both gone: while ground is
connected, every command the chain can parse is executed, and the operator's
START is what begins the experiment. `Command.ARM` stays in the enum so an
older ground station is still understood - it is forwarded, answered OK, and
does nothing.

**Three commands carry the mission (2026-09-28).** `PING`, `START`, `STOP`.
The pressure profile stopped driving the sequence on 2026-09-18, so there was
no longer a sequence to pause, and `HOLD`/`RESUME` had shrunk to one job
between them: deciding whether automatic mode may take over when the link
drops. That is a mode, not a pause, and a mode wants two commands, not three:

  START  autonomy armed   - RUNNING; if ground goes silent for
                            PARAM_LINKLOSS_S, the MCU runs the cycle alone
  STOP   manual, and stay manual - actuators de-energized, TERMINATION ->
                            SAFE, and automatic mode inhibited until the next
                            START, link loss included

`STOP` keeps `ABORT`'s opcode (0x04) because it keeps `ABORT`'s effect and
adds to it: an older ground station's `ABORT` still de-energizes, and now
also latches the inhibit that the old `ABORT` cleared. That clearing was a
hole - abort, then lose the link, and automatic mode restarted the motor the
operator had just shut down.

`HOLD` (0x02) and `RESUME` (0x03) are retired and answered `ACK_INVALID`;
the numbers are not reused. They are not silently mapped onto `STOP`: an old
`HOLD` asked for the actuators to keep running, and `STOP` shuts them off, so
honouring it would execute something other than what was sent. A refusal the
operator can see beats a command that did something else.
"""

from __future__ import annotations

from enum import IntEnum

HEARTBEAT_INTERVAL_S = 5.0      # GSE sends PING at this rate
LINK_LOSS_LATCH_S = 600.0       # MCU runs automatic mode after this much
                                # ground silence (O.2, PARAM_LINKLOSS_S)


class Command(IntEnum):
    PING = 0x00        # heartbeat; also refreshes link-ok on the MCU
    START = 0x01       # autonomy armed: -> RUNNING, inhibit lifted
    # 0x02 (HOLD) and 0x03 (RESUME) are RETIRED (2026-09-28). The MCU
    # answers both ACK_INVALID and the numbers are not reused.
    STOP = 0x04        # manual, and stay manual: -> TERMINATION -> SAFE,
                       # automatic mode inhibited. Was ABORT, same opcode.
    RELEASE = 0x05     # key = 1 | 2
    SET_PARAM = 0x06   # key = Param, value = i32
    STATUS_REQ = 0x07
    ARM = 0x08         # retired: answered OK, does nothing
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


#: Direct actuator drives for the dispersion hardware (M-07) - the motor and
#: the membrane solenoid. Kept as a named set because the panel groups them,
#: not because anything gates them: neither is irreversible, and driving them
#: on the bench is the whole point of having them on the panel.
MANUAL_ACTUATORS = frozenset({Command.MEMBRANE, Command.DISPERSE})

#: Commands whose ACK to ground carries the *MCU's* own verdict: the Pi waits
#: for the MCU's ACK over UART and relays its result. PING is deliberately
#: absent - it is the heartbeat addressed to the Pi (S.8), which must answer
#: it even while the RP2350 is silent; PISTATUS.uart_ok reports that instead.
MCU_CONFIRMED = frozenset({Command.START, Command.STOP, Command.RELEASE,
                           Command.SET_PARAM, Command.MEMBRANE,
                           Command.DISPERSE})


class Param(IntEnum):
    """SET_PARAM keys - mirror of config.h on the MCU. Values are i32."""
    LAUNCH_DP_PA = 1          # pressure drop vs ground ref (default 5000)
    LAUNCH_DEBOUNCE_S = 2     # sustained for this long (default 60)
    FLOAT_P_PA = 3            # float if below (default 5500 Pa ~ 20 km)
    FLOAT_DPDT_CPA_S = 4      # |dp/dt| below, centi-Pa/s (default 500)
    FLOAT_HOLD_S = 5          # for this long (default 300)
    T_FLOAT_S = 6             # timer fallback after launch (default 7200)
    LINKLOSS_S = 7            # automatic mode after this much ground
                              # silence, seconds (default 600 = 10 min)
    # 8 (T_MEASURE_S) and 11 (SEAL_RETRY) are RETIRED with the old
    # ascent/seal/release sequence (2026-09-18). The MCU answers both with
    # ACK_INVALID; the numbers are not reused.
    MEMBRANE_MHZ = 9          # solenoid drive frequency, MILLIhertz (default
                              # 2000 = 2 Hz; 100..400000). Was MEMBRANE_HZ in
                              # whole Hz - the operator needs 0.1..0.9 Hz
    MEMBRANE_DUTY = 10        # percent (default 20)
    PI_SILENT_S = 12          # MCU declares the Pi lost after this (default 60)
    DISPERSE_DUTY = 13        # CaCO3 motor speed, percent (default 50)
    # Automatic mode's cycle, seconds per phase, in this order.
    AUTO_DISPERSE_S = 14      # motor only     (default 120)
    AUTO_MEMBRANE_S = 15      # solenoid only  (default 180)
    AUTO_WAIT_S = 16          # neither        (default 300)
