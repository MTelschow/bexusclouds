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
    # 5 s valve drives are flight numbers and would idle the suite. The
    # link-loss threshold stays long here on purpose: these tests poke at
    # commands and actuators, and a cycle taking over mid-test would be
    # noise. The cycle itself has its own fixture below.
    mcu = SimMcu(far, hk_interval_s=0.1, ascent_s=1.0, linkloss_s=30.0,
                 valve_pulse_s=0.3)
    mcu.start()
    try:
        yield mcu, Pi(near)
    finally:
        mcu.stop()


@pytest.fixture
def sim_auto():
    """A sim whose automatic mode is reachable inside a test: silence for
    0.5 s, then phases of 0.3 / 0.4 / 0.5 s standing in for 2 / 3 / 5 min."""
    near, far = PipeTransport.pair()
    mcu = SimMcu(far, hk_interval_s=0.1, ascent_s=1.0, linkloss_s=0.5,
                 auto_s=(0.3, 0.4, 0.5), valve_pulse_s=0.1)
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


def test_the_mock_exercises_the_particulate_row(sim):
    """`--mock` has to put a real number on the PM2.5 row, and the absent and
    stale cases too - they are the ones the panel gets wrong if untested.

    The BMV080 has never answered on any board, so this simulator is the only
    thing that exercises the success path at all. That makes it worth checking
    it produces each state rather than a constant.
    """
    mcu, pi = sim
    # Before the part's ~1.9 s warm-up there is no sample, and that must not
    # render as clean air - 0 ug/m3 is a real reading.
    h = mcu.housekeeping()
    assert h.pm_status & hk.PmStatus.FAIL
    assert not h.pm_measured and h.pm_text == "-"

    mcu._pm_next_s = time.monotonic()           # jump the warm-up
    fresh = mcu.housekeeping()
    assert fresh.pm_measured and fresh.pm2_5_ugm3 > 0
    assert not fresh.pm_status & hk.PmStatus.STALE

    # The next packet inside the same 1.03 s sample is a repeat, and says so
    # without becoming a fault: the part makes 0.97 samples/s against a 1 Hz
    # sweep, so ground sees this regularly.
    again = mcu.housekeeping()
    assert again.pm_status & hk.PmStatus.STALE
    assert again.pm_measured and again.pm2_5_ugm3 == fresh.pm2_5_ugm3


def test_the_mock_can_have_no_particulate_sensor(sim):
    """The part is not fitted on every board, and `pm=False` is how a panel
    with a dead BMV080 gets exercised."""
    near, far = PipeTransport.pair()
    mcu = SimMcu(far, pm=False)
    h = mcu.housekeeping()
    assert h.pm_status & hk.PmStatus.FAIL
    assert h.pm2_5_ugm3 == 0 and not h.pm_measured


def test_dispersing_moves_the_particulate_reading(sim):
    """The experiment exists to put CaCO3 in the chamber, so the motor is the
    one thing that should move this number. A mock where PM ignored the
    actuators would make the row look like decoration."""
    mcu, pi = sim
    mcu._pm_next_s = time.monotonic()
    idle = mcu.housekeeping().pm2_5_ugm3
    mcu.motor_running = True
    mcu._pm_next_s = time.monotonic()
    running = mcu.housekeeping().pm2_5_ugm3
    assert running > idle * 2, (idle, running)


def test_release_is_a_command_the_build_cannot_act_on(sim):
    """The pinch valves are off the experiment (2026-09-18): no line to
    drive, so RELEASE is INVALID like any other unimplemented command."""
    mcu, pi = sim
    assert pi.command(Command.RELEASE, key=1) == AckResult.INVALID
    assert pi.command(Command.RELEASE, key=7) == AckResult.INVALID






def test_a_stale_arm_is_answered_and_does_nothing(sim):
    mcu, pi = sim
    assert pi.command(Command.ARM, key=int(Command.RELEASE)) == AckResult.OK
    assert pi.command(Command.ARM, key=int(Command.MEMBRANE)) == AckResult.OK


def test_start_is_accepted_in_every_state(sim):
    mcu, pi = sim
    assert pi.command(Command.START) == AckResult.OK
    assert pi.command(Command.START) == AckResult.OK
    assert mcu.state == hk.SeqState.RUNNING
    assert pi.command(Command.STOP) == AckResult.OK
    assert _wait(lambda: mcu.state == hk.SeqState.SAFE)
    # and it is the way back out of SAFE
    assert pi.command(Command.START) == AckResult.OK
    assert mcu.state == hk.SeqState.RUNNING


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
    assert mcu.disperse_duty == 50                 # PARAM_DISPERSE_DUTY default
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
    # a pulse on top of a held motor schedules nothing and is answered OK
    assert pi.command(Command.DISPERSE, key=DisperseKey.PULSE) == AckResult.OK
    assert mcu.motor_running
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


def test_motor_encoder_speed_follows_the_drive_and_duty(sim):
    """The simulated encoder: 0 rpm at rest (a real speed, not the
    sentinel), a speed that tracks DISPERSE_DUTY while running, and a jammed
    shaft reads 0 rpm with the stall bit up - which never comes up with the
    drive off."""
    mcu, pi = sim
    h = mcu.housekeeping()
    assert h.motor_rpm == 0 and h.motor_rpm_valid and h.motor_stalled is False
    assert pi.command(Command.SET_PARAM, key=Param.DISPERSE_DUTY,
                      value=30) == AckResult.OK
    assert pi.command(Command.DISPERSE, key=DisperseKey.RUN) == AckResult.OK
    slow = mcu.housekeeping().motor_rpm
    assert pi.command(Command.SET_PARAM, key=Param.DISPERSE_DUTY,
                      value=90) == AckResult.OK
    fast = mcu.housekeeping().motor_rpm
    assert 0 < slow < fast
    assert mcu.housekeeping().motor_stalled is False
    mcu.motor_jammed = True
    h = mcu.housekeeping()
    assert h.motor_rpm == 0 and h.motor_stalled is True
    assert h.actuator_text == "DISPERSE"
    assert pi.command(Command.DISPERSE, key=DisperseKey.STOP) == AckResult.OK
    assert mcu.housekeeping().motor_stalled is False


def test_a_stop_de_energizes_but_does_not_lock_out(sim):
    """The STOP itself leaves nothing running; a drive commanded afterwards
    is honoured and takes the state with it, so HK never reports SAFE over a
    turning motor."""
    mcu, pi = sim
    assert pi.command(Command.MEMBRANE, key=40) == AckResult.OK
    assert pi.command(Command.STOP) == AckResult.OK
    assert _wait(lambda: mcu.state == hk.SeqState.SAFE)
    assert mcu.housekeeping().membrane_duty == 0
    assert not mcu.motor_running

    assert pi.command(Command.MEMBRANE, key=40) == AckResult.OK
    assert mcu.housekeeping().membrane_duty == 40
    assert mcu.state == hk.SeqState.RUNNING
    assert pi.command(Command.DISPERSE, key=DisperseKey.RUN) == AckResult.OK
    assert mcu.motor_running
    # Stop can only de-energize, and leaves the state where it is.
    assert pi.command(Command.DISPERSE, key=DisperseKey.STOP) == AckResult.OK
    assert not mcu.motor_running


def test_stop_stops_a_running_motor(sim):
    mcu, pi = sim
    assert pi.command(Command.DISPERSE, key=DisperseKey.RUN) == AckResult.OK
    assert pi.command(Command.STOP) == AckResult.OK
    assert _wait(lambda: mcu.state == hk.SeqState.SAFE)
    assert not mcu.motor_running
    assert not mcu.housekeeping().valve_status & hk.ValveStatus.DISPERSE


def test_stop_keeps_the_cycle_off(sim_auto):
    """STOP is how an operator says "do nothing without me", and it outlives
    the link: silence alone does not start the cycle while it is set."""
    mcu, pi = sim_auto
    assert pi.command(Command.START) == AckResult.OK
    assert mcu.state == hk.SeqState.RUNNING
    assert pi.command(Command.STOP) == AckResult.OK
    assert _wait(lambda: mcu.state == hk.SeqState.SAFE)
    assert mcu.housekeeping().flags & hk.McuFlags.STOPPED
    time.sleep(1.2)                                  # linkloss_s is 0.5 s
    assert mcu.state == hk.SeqState.SAFE, "STOP did not hold the cycle off"
    assert not mcu.motor_running
    # START is itself a command, so the link is up again; the next silence
    # runs the cycle as usual.
    assert pi.command(Command.START) == AckResult.OK
    assert not mcu.housekeeping().flags & hk.McuFlags.STOPPED
    assert _wait(lambda: mcu.state == hk.SeqState.AUTO_DISPERSE)


def test_a_manual_drive_after_stop_does_not_re_arm_the_cycle(sim_auto):
    """A drive sent after a STOP wakes the state out of SAFE, because the
    hardware really is energized. It must not also lift the inhibit: the
    operator asked for that one actuator, not for automatic mode back."""
    mcu, pi = sim_auto
    assert pi.command(Command.START) == AckResult.OK
    assert pi.command(Command.STOP) == AckResult.OK
    assert _wait(lambda: mcu.state == hk.SeqState.SAFE)
    assert pi.command(Command.MEMBRANE, key=40) == AckResult.OK
    assert mcu.state == hk.SeqState.RUNNING
    assert mcu.housekeeping().flags & hk.McuFlags.STOPPED
    time.sleep(1.2)                                  # linkloss_s is 0.5 s
    assert mcu.state == hk.SeqState.RUNNING, "the drive re-armed the cycle"
    assert not mcu.motor_running


def test_the_retired_hold_and_resume_opcodes_are_refused(sim_auto):
    """0x02 and 0x03. Not mapped onto STOP: an old HOLD asked for the
    actuators to keep running, which STOP does not do."""
    mcu, pi = sim_auto
    assert pi.command(Command.START) == AckResult.OK
    assert pi.command(0x02) == AckResult.INVALID
    assert pi.command(0x03) == AckResult.INVALID
    assert not mcu.housekeeping().flags & hk.McuFlags.STOPPED
    assert mcu.state == hk.SeqState.RUNNING


def test_the_cycle_runs_while_the_link_is_down(sim_auto):
    """Ten minutes of ground silence (0.5 s here) and the electronics run
    themselves: motor, then solenoid, then neither, then round again."""
    mcu, pi = sim_auto
    assert pi.command(Command.START) == AckResult.OK

    assert _wait(lambda: mcu.state == hk.SeqState.AUTO_DISPERSE)
    assert mcu.motor_running and mcu.membrane_duty == 0

    assert _wait(lambda: mcu.state == hk.SeqState.AUTO_MEMBRANE)
    assert not mcu.motor_running and mcu.membrane_duty == 20

    assert _wait(lambda: mcu.state == hk.SeqState.AUTO_WAIT)
    assert not mcu.motor_running and mcu.membrane_duty == 0

    # ...and it repeats, from the motor phase.
    assert _wait(lambda: mcu.state == hk.SeqState.AUTO_DISPERSE)
    assert mcu.housekeeping().flags & hk.McuFlags.AUTONOMOUS_LATCHED


def test_a_command_ends_the_cycle_at_once(sim_auto):
    mcu, pi = sim_auto
    assert pi.command(Command.START) == AckResult.OK
    assert _wait(lambda: mcu.state == hk.SeqState.AUTO_DISPERSE)
    assert mcu.motor_running

    # A bare heartbeat is enough: it is the link that matters, not what the
    # operator sent. The drives stop in the same call.
    assert pi.command(Command.PING) == AckResult.OK
    assert mcu.state == hk.SeqState.RUNNING
    assert not mcu.motor_running
    assert mcu.membrane_duty == 0
    assert not mcu.housekeeping().valve_status & hk.ValveStatus.DISPERSE


def test_standby_never_starts_the_cycle(sim_auto):
    """A link that was never up is not a link that was lost: without the
    start button the experiment does nothing at all."""
    mcu, _pi = sim_auto
    time.sleep(1.2)
    assert mcu.state == hk.SeqState.STANDBY
    assert not mcu.motor_running and mcu.membrane_duty == 0


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
