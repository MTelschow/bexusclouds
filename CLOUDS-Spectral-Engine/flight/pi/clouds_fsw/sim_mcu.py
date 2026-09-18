"""A simulated RP2350 on the far end of the UART pipe (bench / demo only).

``--mock`` runs the real flight app against a synthetic spectrometer, but the
MCU end of the UART was a bare ``PipeTransport`` that nothing ever wrote to:
no housekeeping, no ACKs, so every command timed out and every HK panel on
the ground stayed empty. That is not "no hardware", it is "broken hardware",
and it is the wrong thing to show an operator who is learning the interface.

``SimMcu`` fills that end. It speaks the same framing as the real MCU
(COBS + `clouds_link.frames`), emits `Housekeeping` at 1 Hz, answers every
`CMD` with its own verdict, and runs the sequencer state graph of
``flight/mcu/src/core/sequencer.c`` - including the arm/execute gate of
``core/link.c``, the "never re-fire" bit (S.3) and the refusal of actuator
drives in TERMINATION/SAFE.

**What it is not**: flight timing, and not a second source of truth. The
phase durations are compressed to demo length (``ascent_s``, ``t_measure_s``
below) because a mock that sits in ASCENT for two hours teaches nobody
anything, and the ascent pressure profile is a decaying exponential, not an
atmosphere model. Nothing here is evidence about the real firmware: when the
two disagree, the C is right. The mirror tests
(``tests/test_link.py``) police the wire format; this file is
policed by ``tests/test_sim_mcu.py`` only for the behaviour ground sees.

The sensor picture it reports is the carrier as measured (DEVLOG 2026-09-11):
both BME280s answering - the ambient one on i2c0 and the chamber one on
SPI_1 - three INA226 rails live, the 24 V slot unfitted
(``RAIL_MV_INVALID``), no STLM20 pair (``NO_TEMP``) and no IMU
(``IMU_FAIL``, zeroed vectors). Pass ``imu=True`` for a board that has one.

The chamber part answering here is an assumption, not a measurement: it has
never been run against the fitted hardware. ``--mock`` therefore exercises
the success path of a chain whose transport is untested, which is what it is
for - but it is not evidence the part works.
"""
from __future__ import annotations

import math
import random
import threading
import time

from clouds_link import cobs, frames, hk
from clouds_link.commands import Command, DisperseKey, Param
from clouds_link.frames import (AckResult, EventCode, EventSeverity, Frame,
                                PacketType, SeqCounter)

#: Valve/motor drive length on the real MCU (VALVE_PULSE_MS in core/pulse.h).
VALVE_PULSE_S = 5.0

#: Ground-level ambient pressure the sim starts from, in pascals.
P_GROUND_PA = 101_325

#: Float threshold (PARAM_FLOAT_P_PA) and the pressure the profile decays to.
P_FLOAT_PA = 5_500
P_CEILING_PA = 4_000


class SimMcu:
    """Far end of a ``PipeTransport`` pair, behaving like the RP2350.

    ``ascent_s`` is how long the compressed ascent takes to reach float, and
    ``t_measure_s`` stands in for PARAM_T_MEASURE_S (480 s in flight). Both
    are demo numbers - see the module docstring. ``valve_pulse_s`` is the
    real 5 s drive; only the tests shorten it.
    """

    def __init__(self, transport, *, hk_interval_s: float = 1.0,
                 ascent_s: float = 45.0, t_measure_s: float = 60.0,
                 valve_pulse_s: float = VALVE_PULSE_S,
                 imu: bool = False, log=None):
        self._t = transport
        self._hk_interval = hk_interval_s
        self._ascent_s = ascent_s
        self._t_measure_s = t_measure_s
        self._valve_pulse_s = valve_pulse_s
        self._imu = imu
        self._log = log or (lambda *_: None)

        self._hk_seq = SeqCounter()
        self._ev_seq = SeqCounter()
        self._ack_seq = SeqCounter()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._buf = bytearray()
        self._threads: list[threading.Thread] = []

        # -- sequencer state (mirror of sequencer_t) -------------------------
        self.state = hk.SeqState.STANDBY   # self-test passes instantly here
        self.fired = 0
        self.hold = False
        self.membrane_duty = 0
        self.membrane_mhz = 2000            # PARAM_MEMBRANE_MHZ default
        self.disperse_duty = 50          # PARAM_DISPERSE_DUTY, motor speed
        self.motor_running = False       # DISPERSE RUN .. STOP, like the MCU
        self.seal_verified = False
        self._t0 = time.monotonic()
        self._state_entered = self._t0
        self._mission_start: float | None = None
        self._launch_detected = False
        self._float_detected = False

        # -- link state (mirror of link_t) -----------------------------------
        self._armed_cmd: int | None = None
        self._armed_until = 0.0
        self._last_ground_cmd = 0.0
        self._last_pi_rx = 0.0

        # -- actuator lines --------------------------------------------------
        # The MCU drives one line at a time to cap peak current, so a queued
        # drive waits for the one in flight rather than overlapping it.
        self._drive_queue: list[tuple[int, float]] = []
        self._drive: tuple[int, float] | None = None   # (bit, ends_at)

        self._p_amb = float(P_GROUND_PA)

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self._threads = [
            threading.Thread(target=self._run, daemon=True, name="sim-mcu"),
            threading.Thread(target=self._listen, daemon=True,
                             name="sim-mcu-rx"),
        ]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads = []

    # -- wire ----------------------------------------------------------------

    def _send(self, frame: Frame) -> None:
        self._t.write(cobs.encode(frame.encode()) + b"\x00")

    def _event(self, code: int, text: str,
               severity: int = EventSeverity.INFO) -> None:
        self._send(Frame(type=PacketType.EVENT,
                         payload=frames.pack_event(code, severity, text),
                         seq=self._ev_seq.next()).stamp())
        self._log("sim-mcu", f"event {frames.event_name(code)}: {text}")

    def _listen(self) -> None:
        while not self._stop.is_set():
            chunk = self._t.read(timeout=0.2)
            if not chunk:
                continue
            self._buf.extend(chunk)
            while b"\x00" in self._buf:
                raw, _, rest = self._buf.partition(b"\x00")
                self._buf = bytearray(rest)
                if not raw:
                    continue
                try:
                    frame = frames.decode(cobs.decode(bytes(raw)))
                except (cobs.CobsError, frames.FrameError):
                    continue
                self._on_frame(frame)

    def _on_frame(self, frame: Frame) -> None:
        with self._lock:
            self._last_pi_rx = time.monotonic()      # anything = the Pi lives
            if frame.type == PacketType.CMD:
                cmd, key, value = frames.unpack_cmd(frame.payload)
                result = self._command(cmd, key, value)
                self._send(Frame(type=PacketType.ACK,
                                 payload=frames.pack_ack(frame.seq, cmd,
                                                         result),
                                 seq=self._ack_seq.next()).stamp())

    # -- command handling (mirror of link_gate + seq_command) ----------------

    def _command(self, cmd: int, key: int, value: int) -> int:
        now = time.monotonic()
        self._last_ground_cmd = now

        if cmd == Command.ARM:
            # Only actuator commands are armable, exactly as on the Pi.
            if key != Command.RELEASE:
                return AckResult.INVALID
            self._armed_cmd = int(Command.RELEASE)
            self._armed_until = now + 10.0          # LINK_ARM_WINDOW_MS
            return AckResult.OK

        if cmd == Command.RELEASE:
            armed = (self._armed_cmd == int(Command.RELEASE)
                     and now <= self._armed_until)
            self._armed_cmd = None      # one ARM authorises one execute
            if not armed:
                return AckResult.NOT_ARMED

        if cmd == Command.PING or cmd == Command.STATUS_REQ:
            return AckResult.OK
        if cmd == Command.HOLD:
            self.hold = True
            return AckResult.OK
        if cmd == Command.RESUME:
            self.hold = False
            return AckResult.OK
        if cmd == Command.ABORT:
            self._event(EventCode.ABORTED, "ground abort",
                        EventSeverity.CRITICAL)
            self.hold = False
            if self.state != hk.SeqState.SAFE:
                self._enter(hk.SeqState.TERMINATION)
            return AckResult.OK
        if cmd == Command.START:
            if self.state != hk.SeqState.STANDBY:
                return AckResult.REJECTED
            self.hold = False
            if self._mission_start is None:
                self._mission_start = now
            self._enter(hk.SeqState.ASCENT)
            return AckResult.OK
        if cmd == Command.RELEASE:
            if key == 1 and (hk.SeqState.ASCENT <= self.state
                             < hk.SeqState.RELEASE_1) and not self.fired & 1:
                self.hold = False
                self._enter(hk.SeqState.RELEASE_1)
                return AckResult.OK
            if key == 2 and (hk.SeqState.ASCENT <= self.state
                             < hk.SeqState.RELEASE_2) and not self.fired & 2:
                self.hold = False
                self._enter(hk.SeqState.RELEASE_2)
                return AckResult.OK
            # Wrong valve, already fired, or not flying yet: ground has to
            # hear that the command did nothing.
            return AckResult.REJECTED if key in (1, 2) else AckResult.INVALID
        if cmd == Command.MEMBRANE:
            if key > 100:
                return AckResult.INVALID
            if not self._actuators_commandable():
                return AckResult.REJECTED
            self.membrane_duty = key
            self._event(EventCode.MANUAL_DRIVE,
                        "membrane on" if key else "membrane off")
            return AckResult.OK
        if cmd == Command.DISPERSE:
            if key > DisperseKey.RUN:
                return AckResult.INVALID
            if key == DisperseKey.STOP:
                # Always honoured, TERMINATION/SAFE included - it can only
                # de-energize. Ends a run and cuts a pulse short alike.
                self._stop_motor()
                self._event(EventCode.MANUAL_DRIVE, "disperse stop")
                return AckResult.OK
            if not self._actuators_commandable():
                return AckResult.REJECTED
            if key == DisperseKey.RUN:
                self.motor_running = True
                self._event(EventCode.MANUAL_DRIVE, "disperse run")
                return AckResult.OK
            if self.motor_running:
                return AckResult.REJECTED    # the bounded pulse cannot happen
            self._queue_drive(hk.ValveStatus.DISPERSE)
            self._event(EventCode.MANUAL_DRIVE, "disperse")
            return AckResult.OK
        if cmd == Command.SET_PARAM:
            # The real MCU range-checks each key against config.c; the sim
            # only knows the key space, and honours the three knobs it models.
            if key not in {int(p) for p in Param}:
                return AckResult.INVALID
            if key == Param.T_MEASURE_S:
                self._t_measure_s = float(value)
            elif key == Param.MEMBRANE_MHZ:
                # config.c limits, so the sim refuses what the MCU refuses -
                # in particular a stale sender's whole-hertz "2".
                if not 100 <= int(value) <= 400000:
                    return AckResult.INVALID
                self.membrane_mhz = int(value)
            elif key == Param.MEMBRANE_DUTY and self.membrane_duty:
                self.membrane_duty = int(value)
            elif key == Param.DISPERSE_DUTY:
                # Latched for the *next* pulse, like the MCU: a running 5 s
                # drive keeps the speed it started at.
                self.disperse_duty = int(value)
            return AckResult.OK
        return AckResult.INVALID

    def _actuators_commandable(self) -> bool:
        """TERMINATION and SAFE mean the actuators stay off - an abort is not
        reversible from the panel."""
        return self.state not in (hk.SeqState.TERMINATION, hk.SeqState.SAFE)

    # -- sequencer -----------------------------------------------------------

    def _enter(self, state: int) -> None:
        self.state = state
        self._state_entered = time.monotonic()
        self._event(EventCode.STATE_CHANGE, f"state={int(state)}")

    def _fire(self, n: int) -> None:
        bit = 1 << (n - 1)
        if self.fired & bit:
            return                       # never re-fire (S.3)
        self.fired |= bit
        self._queue_drive(hk.ValveStatus.PINCH_1 if n == 1
                          else hk.ValveStatus.PINCH_2)
        self._queue_drive(hk.ValveStatus.DISPERSE)
        self.membrane_duty = 20          # PARAM_MEMBRANE_DUTY
        self._event(EventCode.RELEASE_FIRED, f"valve {n}")

    def _step(self, now: float) -> None:
        self._step_pressure(now)
        self._step_drives(now)

        st = hk.SeqState
        if self.state == st.STANDBY:
            if not self.hold and self._launch_detected:
                self._enter(st.ASCENT)
        elif self.state == st.ASCENT:
            if not self.hold and self._float_detected:
                self._enter(st.SEAL)
        elif self.state == st.SEAL:
            if self.hold:
                return
            if not self.seal_verified:
                self._queue_drive(hk.ValveStatus.EQ1_CLOSE)
                self._queue_drive(hk.ValveStatus.EQ2_CLOSE)
                self.seal_verified = True
                return
            if self._drive is None and not self._drive_queue:
                self._enter(st.RELEASE_1)   # seal_ok() is `true` today (M-15)
        elif self.state == st.RELEASE_1:
            self._fire(1)
            self._enter(st.MEASURE_1)
        elif self.state == st.MEASURE_1:
            if not self.hold and self._phase_done(now):
                self._enter(st.RELEASE_2)
        elif self.state == st.RELEASE_2:
            self._fire(2)
            self._enter(st.MEASURE_2)
        elif self.state == st.MEASURE_2:
            if not self.hold and self._phase_done(now):
                self._enter(st.TERMINATION)
        elif self.state == st.TERMINATION:
            self.membrane_duty = 0
            self.motor_running = False
            self._drive_queue.clear()
            self._drive = None
            self._enter(st.SAFE)

    def _phase_done(self, now: float) -> bool:
        """Has this measurement phase run its length (PARAM_T_MEASURE_S)?"""
        return now - self._state_entered >= self._t_measure_s

    def _queue_drive(self, bit: int) -> None:
        """Ask for one actuator line. It waits its turn: the MCU drives one
        at a time to cap peak current, so queued drives never overlap. A
        motor pulse while the operator holds the motor on is redundant and
        not queued, as in hw.c's ops_disperse()."""
        if bit == hk.ValveStatus.DISPERSE and self.motor_running:
            return
        self._drive_queue.append((bit, self._valve_pulse_s))

    def _stop_motor(self) -> None:
        """DISPERSE STOP: release the hold and cancel any motor pulse that
        is driving or queued, leaving the valve pulses alone (pulse_cancel)."""
        self.motor_running = False
        self._drive_queue = [d for d in self._drive_queue
                             if d[0] != hk.ValveStatus.DISPERSE]
        if self._drive is not None and \
                self._drive[0] == hk.ValveStatus.DISPERSE:
            self._drive = None

    def _step_drives(self, now: float) -> None:
        if self._drive is not None and now >= self._drive[1]:
            self._drive = None
        if self._drive is None and self._drive_queue:
            bit, dur = self._drive_queue.pop(0)
            self._drive = (bit, now + dur)

    def _step_pressure(self, now: float) -> None:
        """Ground level until ASCENT, then a decaying exponential to ceiling.

        A profile, not an atmosphere: what it has to get right is the shape
        ground reads - a fall that trips launch detection, then a float that
        stops falling - on a timescale someone can sit through.
        """
        st = hk.SeqState
        if st.ASCENT <= self.state < st.TERMINATION:
            # tau chosen so the profile reaches P_FLOAT_PA at ascent_s; past
            # ASCENT it holds there, which is what float means.
            tau = self._ascent_s / math.log(P_GROUND_PA / P_FLOAT_PA)
            dt = (now - self._state_entered if self.state == st.ASCENT
                  else self._ascent_s)
            self._p_amb = max(P_CEILING_PA,
                              P_GROUND_PA * math.exp(-dt / tau))
        else:
            self._p_amb = float(P_GROUND_PA)

        if not self._launch_detected and \
                self._p_amb < P_GROUND_PA - 5000:       # PARAM_LAUNCH_DP_PA
            self._launch_detected = True
            if self._mission_start is None:
                self._mission_start = now
            self._event(EventCode.LAUNCH_DETECTED, "launch")
        if not self._float_detected and self._p_amb <= P_FLOAT_PA:
            self._float_detected = True
            self._event(EventCode.FLOAT_DETECTED, "float")

    # -- housekeeping --------------------------------------------------------

    def _flags(self, now: float) -> int:
        f = 0
        if now - self._last_ground_cmd <= 600.0:        # PARAM_LINKLOSS_S
            f |= hk.McuFlags.LINK_OK
        elif self._last_ground_cmd:
            f |= hk.McuFlags.AUTONOMOUS_LATCHED
        if self._last_pi_rx and now - self._last_pi_rx <= 60.0:
            f |= hk.McuFlags.PI_OK                      # PARAM_PI_SILENT_S
        if self.seal_verified:
            f |= hk.McuFlags.SEAL_VERIFIED
        if self.hold:
            f |= hk.McuFlags.HOLD
        return f

    def housekeeping(self) -> hk.Housekeeping:
        """The packet as the ground would receive it, built from sim state."""
        with self._lock:
            now = time.monotonic()
            err = hk.HkErrors.NO_TEMP          # STLM20 pair not populated
            accel = gyro = (0, 0, 0)
            if self._imu:
                accel = (int(random.gauss(0, 30)), int(random.gauss(0, 30)),
                         int(random.gauss(1000, 30)))
                gyro = tuple(int(random.gauss(0, 50)) for _ in range(3))
            else:
                err |= hk.HkErrors.IMU_FAIL    # absent on the carrier

            # Three monitors fitted; the 24 V slot has no part (RAIL_I2C_ADDR),
            # so it carries the sentinel and no current is derived from it.
            rail_mv = (int(random.gauss(24_060, 15)), hk.RAIL_MV_INVALID,
                       int(random.gauss(5_090, 5)),
                       int(random.gauss(3_300, 3)))
            # Amps are computed on the ground from shunt_raw, so the sim has
            # to go the other way: pick a draw and emit the register.
            draw = 0.9 if (self._drive or self.membrane_duty
                           or self.motor_running) else 0.35
            shunt = tuple(self._shunt_counts(a, i) for i, a in
                          enumerate((draw, 0.0, 0.4, 0.2)))

            mission = 0 if self._mission_start is None \
                else int(now - self._mission_start)
            # The position switch on GP30 follows the solenoid: with the
            # drive on it reads pulled during the on-phase of each 2 Hz
            # cycle. HK is sampled at 1 Hz, i.e. at a fixed phase of that
            # cycle, so PULLED reads one constant value across packets - as
            # on the carrier - and CYCLING is what says the plunger moved
            # during the last second. With the drive off the plunger is
            # released: the switch never closes and nothing cycles.
            valves = self._drive[0] if self._drive else 0
            if self.motor_running:      # a held motor, beside any pulse
                valves |= hk.ValveStatus.DISPERSE
            on_phase = bool(self.membrane_duty and
                            (now * self.membrane_mhz / 1000.0) % 1.0 < self.membrane_duty / 100.0)
            if on_phase:
                valves |= hk.ValveStatus.MEMBRANE_PULLED
            # ...but only when an edge is actually due inside this 1 Hz
            # packet. A 0.2 Hz drive holds each level for seconds, so most
            # packets legitimately see no edge, and a sim that set CYCLING
            # anyway would show the panel a green light the carrier cannot
            # give it.
            if self.membrane_duty and self._membrane_phase_ms() < 1000.0:
                valves |= hk.ValveStatus.MEMBRANE_CYCLING
            # The current sense on GP46 is the dispersion motor's, not the
            # membrane's: it reads while the DISPERSE drive is up and ~0
            # otherwise, including every second between releases. ~980 counts
            # is 0.79 V over the 1.5 kOhm IPROPI resistor, i.e. ~0.35 A of
            # motor current through hk.HB_SENSE_A_PER_V - a plausible draw,
            # not a measured one.
            hb_sense = int(random.gauss(
                980 if valves & hk.ValveStatus.DISPERSE else 3, 8))
            return hk.Housekeeping(
                state=int(self.state), flags=self._flags(now),
                fired=self.fired,
                valve_status=valves,
                membrane_duty=self.membrane_duty, error_flags=int(err),
                bme_temp_cc=int(random.gauss(2200, 20)),
                rh1_cpct=int(random.gauss(4500, 50)),
                p_amb_pa=int(self._p_amb),
                accel_mg=accel, gyro_ddps=gyro,
                rail_mv=rail_mv, shunt_raw=shunt,
                uptime_s=int(now - self._t0) & 0xFFFF,
                mission_t_s=mission,
                hb_sense_raw=max(0, min(4095, hb_sense)),
                # The chamber BME280 on SPI_1. Warmer and drier than ambient
                # by a fixed offset, and its pressure held at ground level
                # while the ambient one falls with the model altitude: the
                # chamber is sealed, so the two pressures diverging during
                # ascent is the thing the pair exists to show, and a sim
                # that moved them together would hide it.
                chm_temp_cc=int(random.gauss(2450, 20)),
                chm_rh_cpct=int(random.gauss(3800, 50)),
                chm_p_pa=int(random.gauss(P_GROUND_PA, 30)))

    def _membrane_phase_ms(self) -> float:
        """How long the simulated drive holds one level, in ms - the longer
        of the two phases, the same quantity `sqwave_start()` produces on the
        MCU. It decides whether a 1 Hz housekeeping packet is entitled to see
        an edge at all."""
        period = 1000000.0 / max(1, self.membrane_mhz)
        on = period * self.membrane_duty / 100.0
        on = min(max(on, 1.0), period - 1.0)
        return max(on, period - on)

    @staticmethod
    def _shunt_counts(amps: float, rail: int) -> int:
        """Amps -> the INA226 shunt register ground will read them back from
        (I[mA] = U[uV] / R[mOhm], SHUNT_LSB_UV per count)."""
        return int(amps * hk.RAIL_SHUNT_MOHM[rail] * 1000 / hk.SHUNT_LSB_UV)

    def _run(self) -> None:
        next_hk = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            with self._lock:
                self._step(now)
            if now >= next_hk:
                self._send(Frame(type=PacketType.HK,
                                 payload=self.housekeeping().pack(),
                                 seq=self._hk_seq.next()).stamp())
                next_hk = now + self._hk_interval
            self._stop.wait(0.05)
