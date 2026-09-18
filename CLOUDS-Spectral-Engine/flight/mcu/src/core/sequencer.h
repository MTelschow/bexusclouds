/* Experiment sequencer: the authoritative state machine.
 *
 * Pure logic - all hardware effects go through seq_ops_t callbacks, all
 * inputs (time, pressure, commands) are injected, so the full sequence runs
 * on a desk (test harness X-03 = test/test_core).
 *
 * The sequence (changed 2026-09-18, DEVLOG):
 *
 *   INIT      self-test, once -> STANDBY, or SAFE if it fails.
 *   STANDBY   nothing happens on its own. The experiment is started by the
 *             operator's START button and by nothing else: no pressure
 *             profile, no timer and no link state moves out of here.
 *   RUNNING   started. Sensors are swept, housekeeping is logged to both SD
 *             cards and the Pi stores spectra - as in every state - and the
 *             actuators do only what ground commands.
 *   AUTO_*    automatic mode: entered from RUNNING when no ground command
 *             has arrived for PARAM_LINKLOSS_S (10 min by default), left on
 *             the first command that does. It cycles
 *                 AUTO_DISPERSE  PARAM_AUTO_DISPERSE_S  motor only
 *                 AUTO_MEMBRANE  PARAM_AUTO_MEMBRANE_S  solenoid only
 *                 AUTO_WAIT      PARAM_AUTO_WAIT_S      neither
 *             at PARAM_DISPERSE_DUTY / PARAM_MEMBRANE_DUTY+MHZ, and starts
 *             again at AUTO_DISPERSE. Measurement and storage never stop.
 *   TERMINATION/SAFE  abort: actuators off and they stay off.
 *
 * Invariants (spec S.1..S.3):
 *  - No state waits indefinitely for ground input; commands only start,
 *    hold, or abort - and automatic mode needs no command at all.
 *  - While ground is connected nothing is refused: every command executes
 *    in every state (see seq_command).
 *  - The cycle always restarts at AUTO_DISPERSE. Nothing about it is
 *    carried across a link-up period or a reset, so what the electronics do
 *    after a given drop-out is the same every time.
 *  - The pinch valves are NOT part of the automatic path. They fire only on
 *    a ground RELEASE: irreversible, and not something to do while nobody
 *    is watching.
 *  - persist() is called with the fired bit set BEFORE fire_pinch(): a
 *    brownout between the two loses one release but can never double-fire.
 *  - Any restore path never re-fires a valve whose bit is persisted.
 */
#ifndef CLOUDS_SEQUENCER_H
#define CLOUDS_SEQUENCER_H

#include <stdbool.h>
#include <stdint.h>

#include "autonomy.h"
#include "config.h"

/* Mirror of clouds_link/hk.py SeqState.
 *
 * 6 and 7 are retired, not reused: they were RELEASE_2 and MEASURE_2 of the
 * old ascent/seal/release sequence, and a stale ground decoder reading a 6
 * as "release" would be worse than reading it as nothing. TERMINATION and
 * SAFE keep their numbers so a persisted SAFE from an older image still
 * restores as SAFE. */
typedef enum {
    ST_INIT = 0,
    ST_STANDBY = 1,       /* on the pad, waiting for the START button */
    ST_RUNNING = 2,       /* started; ground has the actuators */
    ST_AUTO_DISPERSE = 3, /* automatic mode: dispersion motor only */
    ST_AUTO_MEMBRANE = 4, /* automatic mode: push-pull solenoid only */
    ST_AUTO_WAIT = 5,     /* automatic mode: measure only */
    ST_TERMINATION = 8,
    ST_SAFE = 9,
} seq_state_t;

/* True for the three phases of automatic mode. */
#define ST_IS_AUTO(st) \
    ((st) == ST_AUTO_DISPERSE || (st) == ST_AUTO_MEMBRANE || \
     (st) == ST_AUTO_WAIT)

/* Event codes (PKT_EVENT payloads + log). */
enum seq_event {
    EV_STATE_CHANGE = 0x01,
    EV_SELF_TEST_FAIL = 0x02,
    EV_LAUNCH_DETECTED = 0x03,
    EV_FLOAT_DETECTED = 0x04,
    EV_SEAL_FAILED = 0x05, /* retired with the seal state; kept so an old
                              log record still decodes to its own name */
    EV_RELEASE_FIRED = 0x06,
    EV_ABORTED = 0x07,
    EV_RESUMED_AFTER_RESET = 0x08,
    EV_AUTONOMOUS_LATCHED = 0x09,
    EV_PI_LINK_LOST = 0x0A,
    EV_PI_LINK_OK = 0x0B,
    EV_MANUAL_DRIVE = 0x0C,  /* operator drove an actuator from the panel */
    EV_AUTO_ENTERED = 0x0D,  /* link silent: the cycle took over */
    EV_AUTO_LEFT = 0x0E,     /* a command arrived: actuators off, cycle ended */
};

/* Severity (EVS_* in frame.h) to downlink one event code at. Every MCU event
 * used to go out at a hardcoded EVS_WARNING, which made the field carry no
 * information: an abort and a routine state change reached ground at the same
 * level, so an operator could not sort a log by what matters. Lives here
 * because the event codes do - frame.c is the layer below and must not need
 * to know them. */
uint8_t event_severity(uint8_t code);

/* What survives a reset (persisted to SD/flash before it matters, S.3). */
typedef struct {
    uint8_t state;
    uint8_t fired; /* bit0 = pinch valve 1, bit1 = pinch valve 2 */
    uint32_t mission_start_s; /* wall-clock s of START, 0 = none */
    bool launch_detected;
} seq_persist_t;

typedef struct {
    void *ctx;
    /* MUST be durable before returning - called before every fire. */
    void (*persist)(void *ctx, const seq_persist_t *p);
    /* The actuator calls only *schedule* the drive (core/pulse): they
     * return immediately, so nothing here can outrun the watchdog. */
    void (*fire_pinch)(void *ctx, uint8_t n); /* n = 1 | 2 */
    void (*close_eq_valves)(void *ctx);
    /* CaCO3 dispersion motor, one bounded drive. Optional (may be NULL):
     * the carrier grew it after the SED was written, so a board without it
     * still sequences. */
    void (*disperse)(void *ctx);
    /* The same motor held on (true) or released (false) for as long as it
     * is wanted - DISPERSE_RUN / DISPERSE_STOP, and automatic mode's motor
     * phase. Not a pulse: it sits beside core/pulse rather than in its
     * one-at-a-time queue, so a run can neither delay a release's pinch
     * valve nor keep busy() true. STOP also cuts a running pulse short.
     * Optional, like disperse. */
    void (*disperse_run)(void *ctx, bool on);
    void (*membrane)(void *ctx, uint8_t duty_pct); /* 0 = off */
    /* Optional (may be NULL): true while a scheduled drive is still
     * running. */
    bool (*busy)(void *ctx);
    bool (*self_test)(void *ctx); /* sensors + SD + actuator continuity */
    void (*event)(void *ctx, uint8_t code, const char *msg);
} seq_ops_t;

typedef struct {
    seq_state_t state;
    uint8_t fired;
    /* Last duty handed to ops->membrane, i.e. what the solenoid is doing
     * now. Kept here so HK reports the drive rather than a constant 0 - the
     * membrane is the one actuator whose state is not a short pulse. */
    uint8_t membrane_duty;
    /* True while the motor is held on - by DISPERSE_RUN or by automatic
     * mode's motor phase. */
    bool motor_running;
    bool hold;
    uint64_t state_entered_ms;
    uint32_t mission_start_s;
    autonomy_t autonomy;
    const cfg_t *cfg;
    const seq_ops_t *ops;
} sequencer_t;

/* restored = NULL for a cold start; non-NULL resumes after a reset. */
void seq_init(sequencer_t *s, const cfg_t *cfg, const seq_ops_t *ops,
              const seq_persist_t *restored, uint64_t t_ms, uint32_t wall_s);
/* Call at ~1 Hz with fresh sensor data. Ambient pressure feeds launch and
 * float detection (core/autonomy), which since 2026-09-18 only reports -
 * no state depends on it. Deliberately nothing else: a parameter no caller
 * reads invites one to pass something plausible instead. */
void seq_step(sequencer_t *s, uint64_t t_ms, uint32_t wall_s,
              uint32_t p_amb_pa);
/* Ground command. Returns the enum ack_result to answer with.
 *
 * **Nothing is refused for state (2026-09-18).** While ground is connected
 * every command executes: START works from any state, a drive commanded
 * after an abort takes the experiment back out of SAFE rather than being
 * turned away, and the arm/execute gate is gone. What is left is ACK_INVALID
 * for input this build cannot act on at all - an unknown command, a duty
 * above 100, a parameter outside its envelope - because a corrupted frame
 * must not come back as an OK. ACK_REJECTED is no longer produced.
 *
 * ANY command also ends automatic mode before it is acted on: the link is
 * back, so the cycle stops at once and both actuators are de-energized. The
 * command then runs from RUNNING, where ground owns the hardware.
 *
 * CMD_MEMBRANE (key = duty percent, 0 = off) and CMD_DISPERSE (key =
 * DISPERSE_PULSE for the bounded drive, DISPERSE_RUN to hold the motor on,
 * DISPERSE_STOP to end either) are the operator's drives of the dispersion
 * hardware. The motor's speed is not in its key - it is PARAM_DISPERSE_DUTY,
 * so a commanded drive runs at the same speed automatic mode uses; a
 * SET_PARAM of it while the motor is running re-latches the speed at once.
 */
uint8_t seq_command(sequencer_t *s, uint64_t t_ms, uint32_t wall_s,
                    uint8_t cmd, uint8_t key, int32_t value, cfg_t *cfg);
/* Any valid ground command refreshes the link-loss latch (O.2) and ends
 * automatic mode, including the ones core/link answers itself and never
 * passes on. */
void seq_note_ground_cmd(sequencer_t *s, uint64_t t_ms);
/* Mission-elapsed seconds for HK (0 before START). */
uint32_t seq_mission_t_s(const sequencer_t *s, uint32_t wall_s);

#endif
