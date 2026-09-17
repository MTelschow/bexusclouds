"""The simulated RP2350 behind ``clouds_ui --mock``.

What is worth testing here is not the physics - the pressure profile is a
demo, not an atmosphere - but the answers ground gets, because those are what
an operator learns the interface on. A mock that accepts a RELEASE nobody
armed, or that re-fires a valve, teaches the wrong reflexes.
"""
import time

import pytest

from clouds_fsw.sim_mcu import SimMcu
from clouds_fsw.uart_link import PipeTransport
from clouds_link import cobs, frames, hk
from clouds_link.commands import Command, DisperseKey, Param
from clouds_link.frames import AckResult, Frame, PacketType, SeqCounter


class Pi:
    """The Pi's end of the pipe: sends commands, collects frames."""

    def __init__(self, transport):
        self._t = transport
        self._seq = SeqCounter()
        self._buf = bytearray()

    def _pump(self, timeout=0.3):
        chunk = self._t.read(timeout=timeout)
        if chunk:
            self._buf.extend(chunk)
        out = []
        while b"\x00" in self._buf:
            raw, _, rest = self._buf.partition(b"\x00")
            self._buf = bytearray(rest)
            if raw:
                out.append(frames.decode(cobs.decode(bytes(raw))))
        return out

    def collect(self, ptype, seconds=1.5):
        got, t0 = [], time.time()
        while time.time() - t0 < seconds:
            got += [f for f in self._pump() if f.type == ptype]
        return got

    def command(self, cmd, key=0, value=0, timeout=2.0):
        seq = self._seq.next()
        frame = Frame(type=PacketType.CMD, seq=seq,
                      payload=frames.pack_cmd(cmd, key, value)).stamp()
        self._t.write(cobs.encode(frame.encode()) + b"\x00")
        t0 = time.time()
        while time.time() - t0 < timeout:
            for f in self._pump():
                if f.type == PacketType.ACK:
                    ack_seq, ack_cmd, result = frames.unpack_ack(f.payload)
                    if ack_seq == seq and ack_cmd == cmd:
                        return result
        raise AssertionError(f"no ACK for {cmd}")


@pytest.fixture
def sim():
    near, far = PipeTransport.pair()
    # 5 s valve drives are flight numbers and would idle the suite.
    mcu = SimMcu(far, hk_interval_s=0.1, ascent_s=1.0, t_measure_s=0.5,
                 valve_pulse_s=0.3)
    mcu.start()
    try:
        yield mcu, Pi(near)
    finally:
        mcu.stop()


def _wait(predicate, timeout=6.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_housekeeping_is_emitted_and_decodes(sim):
    mcu, pi = sim
    packets = pi.collect(PacketType.HK, seconds=0.6)
    assert packets, "no housekeeping from the sim MCU"
    h = hk.Housekeeping.unpack(packets[-1].payload)
    assert h.state == hk.SeqState.STANDBY
    assert h.p_amb_pa == pytest.approx(101_325, abs=50)
    # Seq numbers are per packet type and must advance.
    assert packets[-1].seq > packets[0].seq


def test_sensor_picture_matches_the_carrier(sim):
    """Absent parts report absent, not zero (DEVLOG 2026-09-11)."""
    mcu, pi = sim
    h = mcu.housekeeping()
    assert h.error_flags & hk.HkErrors.NO_TEMP      # STLM20 pair not fitted
    assert h.error_flags & hk.HkErrors.IMU_FAIL     # BNO055 absent
    assert h.accel_mg == (0, 0, 0) and h.gyro_ddps == (0, 0, 0)
    # The 24 V monitor is not populated: sentinel, and no current derived.
    assert h.rail_mv[1] == hk.RAIL_MV_INVALID
    assert h.rail_a(1) is None
    for i in (0, 2, 3):
        assert h.rail_mv[i] != hk.RAIL_MV_INVALID
        assert h.rail_a(i) is not None


def test_release_without_arm_is_refused(sim):
    mcu, pi = sim
    assert pi.command(Command.RELEASE, key=1) == AckResult.NOT_ARMED
    assert mcu.fired == 0


def test_release_on_the_pad_is_rejected_even_when_armed(sim):
    """The state check that keeps a stray RELEASE harmless before flight."""
    mcu, pi = sim
    assert pi.command(Command.ARM, key=int(Command.RELEASE)) == AckResult.OK
    assert pi.command(Command.RELEASE, key=1) == AckResult.REJECTED
    assert mcu.fired == 0


def test_arm_release_fires_once(sim):
    mcu, pi = sim
    assert pi.command(Command.START) == AckResult.OK
    assert pi.command(Command.ARM, key=int(Command.RELEASE)) == AckResult.OK
    assert pi.command(Command.RELEASE, key=1) == AckResult.OK
    # The command enters RELEASE_1; the drive itself happens in the next step,
    # as on the MCU - so the fired bit lags the ACK by one loop.
    assert _wait(lambda: mcu.fired & 1)
    # One ARM authorises one execute, and a fired valve never fires again.
    assert pi.command(Command.RELEASE, key=1) == AckResult.NOT_ARMED
    assert pi.command(Command.ARM, key=int(Command.RELEASE)) == AckResult.OK
    assert pi.command(Command.RELEASE, key=1) == AckResult.REJECTED
    assert mcu.fired == 1


def test_arm_only_accepts_an_armable_command(sim):
    mcu, pi = sim
    assert pi.command(Command.ARM, key=int(Command.MEMBRANE)) \
        == AckResult.INVALID


def test_start_is_rejected_outside_standby(sim):
    mcu, pi = sim
    assert pi.command(Command.START) == AckResult.OK
    assert pi.command(Command.START) == AckResult.REJECTED


def test_manual_drives_show_up_in_valve_status(sim):
    mcu, pi = sim
    assert pi.command(Command.MEMBRANE, key=60) == AckResult.OK
    assert pi.command(Command.DISPERSE, key=1) == AckResult.OK
    assert mcu.housekeeping().membrane_duty == 60
    assert _wait(lambda: mcu.housekeeping().valve_status
                 & hk.ValveStatus.DISPERSE), "dispersion drive never energized"
    assert pi.command(Command.MEMBRANE, key=101) == AckResult.INVALID
    assert pi.command(Command.DISPERSE, key=3) == AckResult.INVALID


def test_motor_speed_is_a_parameter_not_the_disperse_key(sim):
    """What the panel's Speed slider does: SET_PARAM first, then the pulse.
    The key stays the request (1), so a speed sent as the key is a bad
    command rather than a 2 % drive nobody asked for."""
    mcu, pi = sim
    assert mcu.disperse_duty == 100                # full-on by default
    assert pi.command(Command.SET_PARAM, key=Param.DISPERSE_DUTY,
                      value=40) == AckResult.OK
    assert mcu.disperse_duty == 40
    assert pi.command(Command.DISPERSE, key=1) == AckResult.OK
    assert pi.command(Command.DISPERSE, key=40) == AckResult.INVALID



def test_motor_run_holds_until_stop(sim):
    """DISPERSE RUN / STOP: the motor stays on across HK packets (not a 5 s
    pulse), a pulse asked for meanwhile is refused, a new speed re-latches
    at once, Stop ends it, and Stop also cuts a plain pulse short."""
    mcu, pi = sim
    assert pi.command(Command.DISPERSE, key=DisperseKey.RUN) == AckResult.OK
    assert mcu.motor_running
    assert mcu.housekeeping().valve_status & hk.ValveStatus.DISPERSE
    assert mcu.housekeeping().actuator_text == "DISPERSE"
    assert mcu.housekeeping().hb_sense_a() > 0.2
    assert pi.command(Command.DISPERSE, key=DisperseKey.PULSE) \
        == AckResult.REJECTED
    assert pi.command(Command.SET_PARAM, key=Param.DISPERSE_DUTY,
                      value=30) == AckResult.OK
    assert mcu.disperse_duty == 30 and mcu.motor_running
    assert pi.command(Command.DISPERSE, key=DisperseKey.RUN) == AckResult.OK
    assert pi.command(Command.DISPERSE, key=DisperseKey.STOP) == AckResult.OK
    assert not mcu.motor_running
    assert not mcu.housekeeping().valve_status & hk.ValveStatus.DISPERSE
    assert pi.command(Command.DISPERSE, key=DisperseKey.STOP) == AckResult.OK

    assert pi.command(Command.DISPERSE, key=DisperseKey.PULSE) == AckResult.OK
    assert _wait(lambda: mcu.housekeeping().valve_status
                 & hk.ValveStatus.DISPERSE)
    assert pi.command(Command.DISPERSE, key=DisperseKey.STOP) == AckResult.OK
    assert not mcu.housekeeping().valve_status & hk.ValveStatus.DISPERSE, \
        "Stop must cut a running pulse short, not wait 5 s for it"


def test_membrane_switch_follows_the_drive(sim):
    """The simulated GP30 switch: never pulled and never cycling with the
    membrane off; cycling on every packet with it on, and (polled here much
    faster than 1 Hz) pulled for some samples and pushed for others; kept out
    of the Driving text like the real bits."""
    mcu, pi = sim
    for _ in range(5):
        assert not mcu.housekeeping().valve_status & hk.ValveStatus.MEMBRANE_PULLED
        assert mcu.housekeeping().membrane_pulled is False
        assert mcu.housekeeping().membrane_cycling is False
    assert pi.command(Command.MEMBRANE, key=60) == AckResult.OK
    assert mcu.housekeeping().membrane_duty == 60
    assert mcu.housekeeping().membrane_cycling is True
    seen = set()
    t_end = time.monotonic() + 1.5
    while time.monotonic() < t_end and len(seen) < 2:
        seen.add(mcu.housekeeping().membrane_pulled)
        time.sleep(0.02)
    assert seen == {True, False}, "the switch should alternate under a 2 Hz drive"
    assert "MEMBRANE_PULLED" not in mcu.housekeeping().actuator_text
    assert pi.command(Command.MEMBRANE, key=0) == AckResult.OK
    assert mcu.housekeeping().membrane_pulled is False
    assert mcu.housekeeping().membrane_cycling is False


def test_motor_current_sense_follows_the_dispersion_drive(sim):
    """The simulated ACT_HB_SENS ADC: near zero with the motor idle, amps
    while the DISPERSE drive is up, never the sentinel (the sim is the
    RP2350B carrier, which has GP46). It follows the motor, not the
    membrane - they are different actuators on different pins."""
    mcu, pi = sim
    for _ in range(5):
        h = mcu.housekeeping()
        assert h.hb_sense_raw != hk.HB_SENSE_INVALID
        assert h.hb_sense_a() is not None and h.hb_sense_a() < 0.05
    assert pi.command(Command.MEMBRANE, key=60) == AckResult.OK
    assert mcu.housekeeping().hb_sense_a() < 0.05, \
        "the membrane must not move the motor's current sense"
    assert pi.command(Command.DISPERSE, key=1) == AckResult.OK
    highs = 0
    t_end = time.monotonic() + 1.5
    while time.monotonic() < t_end:
        h = mcu.housekeeping()
        assert 0 <= h.hb_sense_raw <= 4095
        highs += h.hb_sense_a() > 0.2
        time.sleep(0.02)
    assert highs, "the sense should rise while the motor drive is up"


def test_abort_locks_the_actuators_out(sim):
    """TERMINATION/SAFE mean off and stay off - an abort is not reversible
    from the panel."""
    mcu, pi = sim
    assert pi.command(Command.MEMBRANE, key=40) == AckResult.OK
    assert pi.command(Command.ABORT) == AckResult.OK
    assert _wait(lambda: mcu.state == hk.SeqState.SAFE)
    assert mcu.housekeeping().membrane_duty == 0
    assert pi.command(Command.MEMBRANE, key=40) == AckResult.REJECTED
    assert pi.command(Command.DISPERSE, key=1) == AckResult.REJECTED
    assert pi.command(Command.DISPERSE, key=DisperseKey.RUN) \
        == AckResult.REJECTED
    # Stop can only de-energize, so it is the one drive command SAFE takes
    assert pi.command(Command.DISPERSE, key=DisperseKey.STOP) == AckResult.OK


def test_abort_stops_a_running_motor(sim):
    mcu, pi = sim
    assert pi.command(Command.DISPERSE, key=DisperseKey.RUN) == AckResult.OK
    assert pi.command(Command.ABORT) == AckResult.OK
    assert _wait(lambda: mcu.state == hk.SeqState.SAFE)
    assert not mcu.motor_running
    assert not mcu.housekeeping().valve_status & hk.ValveStatus.DISPERSE


def test_hold_stops_the_sequence_and_resume_restarts_it(sim):
    mcu, pi = sim
    assert pi.command(Command.HOLD) == AckResult.OK
    assert pi.command(Command.START) == AckResult.OK   # START clears hold
    assert mcu.state == hk.SeqState.ASCENT
    assert pi.command(Command.HOLD) == AckResult.OK
    assert mcu.housekeeping().flags & hk.McuFlags.HOLD
    time.sleep(1.5)                                    # ascent_s is 1.0 s here
    assert mcu.state == hk.SeqState.ASCENT, "HOLD did not hold the sequence"
    assert pi.command(Command.RESUME) == AckResult.OK
    assert _wait(lambda: mcu.state >= hk.SeqState.SEAL)


def test_the_whole_sequence_runs_to_safe(sim):
    """START -> ... -> SAFE, both valves fired, on the compressed timeline."""
    mcu, pi = sim
    assert pi.command(Command.START) == AckResult.OK
    assert _wait(lambda: mcu.state == hk.SeqState.SAFE, timeout=30.0), \
        f"stuck in {hk.SeqState(mcu.state).name}"
    assert mcu.fired == 0b11
    assert mcu.housekeeping().membrane_duty == 0


def test_link_flags_follow_the_traffic(sim):
    mcu, pi = sim
    assert not mcu.housekeeping().flags & hk.McuFlags.LINK_OK
    assert pi.command(Command.PING) == AckResult.OK
    flags = mcu.housekeeping().flags
    assert flags & hk.McuFlags.LINK_OK      # ground is talking
    assert flags & hk.McuFlags.PI_OK        # so is the Pi (M-13)


def test_unknown_command_is_invalid(sim):
    mcu, pi = sim
    assert pi.command(0x7E) == AckResult.INVALID
