#include "sequencer.h"

#include <stdio.h>

#include "frame.h" /* enum command */

#define SEAL_RETRY_SPACING_MS 1000u

static void persist_now(sequencer_t *s)
{
    seq_persist_t p = {
        .state = (uint8_t)s->state,
        .fired = s->fired,
        .mission_start_s = s->mission_start_s,
        .launch_detected = s->autonomy.launch_detected,
    };
    s->ops->persist(s->ops->ctx, &p);
}

/* Actuator drives are scheduled, not blocking (core/pulse): the sequencer
 * must let them finish before judging what they did. */
uint8_t event_severity(uint8_t code)
{
    switch (code) {
    case EV_ABORTED:
        return EVS_CRITICAL;
    case EV_SELF_TEST_FAIL:
    case EV_SEAL_FAILED:
        return EVS_ERROR;
    /* Something is wrong with the flight the operator should chase, but the
     * experiment carries on: a reset happened, ground was given up on, or
     * the Pi went quiet. */
    case EV_RESUMED_AFTER_RESET:
    case EV_AUTONOMOUS_LATCHED:
    case EV_PI_LINK_LOST:
        return EVS_WARNING;
    /* Nominal progress, including the release itself and an operator's own
     * actuator drive - important, but not a fault. */
    default:
        return EVS_INFO;
    }
}

static bool actuators_busy(const sequencer_t *s)
{
    return s->ops->busy != NULL && s->ops->busy(s->ops->ctx);
}

/* TERMINATION and SAFE mean the actuators are off and stay off, so no ground
 * command may start one there - an abort must not be reversible from the
 * panel. Every other state is fair game: the operator drives are how the
 * dispersion hardware is exercised on the bench, and how a release whose
 * automatic drive failed can still be helped along in flight. */
static bool actuators_commandable(const sequencer_t *s)
{
    return s->state != ST_TERMINATION && s->state != ST_SAFE;
}

/* The one path to the membrane: every caller goes through here so
 * s->membrane_duty is what the solenoid is actually doing, and HK cannot
 * drift away from the hardware. */
static void set_membrane(sequencer_t *s, uint8_t duty_pct)
{
    s->membrane_duty = duty_pct;
    s->ops->membrane(s->ops->ctx, duty_pct);
}

/* Same idea for the held motor drive: s->motor_running is what HK and the
 * PULSE refusal key off, so it changes only here, together with the line. */
static void set_motor(sequencer_t *s, bool on)
{
    s->motor_running = on;
    if (s->ops->disperse_run != NULL)
        s->ops->disperse_run(s->ops->ctx, on);
}

static void close_eq_valves(sequencer_t *s, uint64_t t_ms)
{
    s->ops->close_eq_valves(s->ops->ctx);
    s->last_seal_try_ms = t_ms;
    s->seal_attempts++;
}

static void enter(sequencer_t *s, seq_state_t st, uint64_t t_ms)
{
    char msg[24];

    s->state = st;
    s->state_entered_ms = t_ms;
    persist_now(s); /* every transition is durable (S.3 resume path) */
    snprintf(msg, sizeof msg, "state=%d", (int)st);
    s->ops->event(s->ops->ctx, EV_STATE_CHANGE, msg);
}

static void fire(sequencer_t *s, uint8_t n, uint64_t t_ms)
{
    uint8_t bit = (uint8_t)(1u << (n - 1));

    (void)t_ms;
    if (s->fired & bit)
        return; /* never re-fire (S.3) */
    s->fired |= bit;
    persist_now(s); /* durable BEFORE the irreversible action */
    s->ops->fire_pinch(s->ops->ctx, n);
    /* Dispersion runs with the release, not instead of it: the motor moves
     * the CaCO3 the pinch valve just let out, and the membrane keeps
     * oscillating alongside. Both are scheduled drives, so this returns at
     * once. */
    if (s->ops->disperse != NULL)
        s->ops->disperse(s->ops->ctx);
    set_membrane(s, (uint8_t)cfg_get(s->cfg, PARAM_MEMBRANE_DUTY));
    s->ops->event(s->ops->ctx, EV_RELEASE_FIRED, n == 1 ? "valve 1"
                                                        : "valve 2");
}

void seq_init(sequencer_t *s, const cfg_t *cfg, const seq_ops_t *ops,
              const seq_persist_t *restored, uint64_t t_ms, uint32_t wall_s)
{
    (void)wall_s;
    *s = (sequencer_t){0};
    s->cfg = cfg;
    s->ops = ops;
    autonomy_init(&s->autonomy, cfg, t_ms);
    s->state = ST_INIT;
    s->state_entered_ms = t_ms;

    if (restored != NULL && restored->state != (uint8_t)ST_INIT) {
        s->fired = restored->fired;
        s->mission_start_s = restored->mission_start_s;
        autonomy_restore(&s->autonomy, restored->launch_detected, t_ms);
        switch ((seq_state_t)restored->state) {
        /* mid-release: the fired bit tells the truth; measure, don't
         * re-fire */
        case ST_RELEASE_1:
            s->state = ST_MEASURE_1;
            break;
        case ST_RELEASE_2:
            s->state = ST_MEASURE_2;
            break;
        default:
            s->state = (seq_state_t)restored->state;
            break;
        }
        s->state_entered_ms = t_ms; /* phase timers restart, conservative */
        s->ops->event(s->ops->ctx, EV_RESUMED_AFTER_RESET, "resume");
        persist_now(s);
    }
}

uint32_t seq_mission_t_s(const sequencer_t *s, uint32_t wall_s)
{
    if (s->mission_start_s == 0 || wall_s < s->mission_start_s)
        return 0;
    return wall_s - s->mission_start_s;
}

static uint64_t elapsed(const sequencer_t *s, uint64_t t_ms)
{
    return t_ms - s->state_entered_ms;
}

void seq_step(sequencer_t *s, uint64_t t_ms, uint32_t wall_s,
              uint32_t p_amb_pa)
{
    bool was_latched = s->autonomy.autonomous_latched;
    bool was_launched = s->autonomy.launch_detected;
    bool was_float = s->autonomy.float_detected;

    autonomy_step(&s->autonomy, t_ms, p_amb_pa);
    if (!was_latched && s->autonomy.autonomous_latched)
        s->ops->event(s->ops->ctx, EV_AUTONOMOUS_LATCHED, "link lost");
    if (!was_launched && s->autonomy.launch_detected) {
        s->mission_start_s = wall_s;
        persist_now(s);
        s->ops->event(s->ops->ctx, EV_LAUNCH_DETECTED, "launch");
    }
    if (!was_float && s->autonomy.float_detected)
        s->ops->event(s->ops->ctx, EV_FLOAT_DETECTED, "float");

    switch (s->state) {
    case ST_INIT:
        if (s->ops->self_test(s->ops->ctx)) {
            enter(s, ST_STANDBY, t_ms);
        } else {
            s->ops->event(s->ops->ctx, EV_SELF_TEST_FAIL, "self-test");
            enter(s, ST_SAFE, t_ms);
        }
        break;

    case ST_STANDBY:
        if (s->hold)
            break;
        if (s->autonomy.launch_detected)
            enter(s, ST_ASCENT, t_ms);
        break;

    case ST_ASCENT:
        if (s->hold)
            break;
        if (s->autonomy.float_detected)
            enter(s, ST_SEAL, t_ms);
        break;

    case ST_SEAL:
        if (s->hold)
            break;
        if (s->seal_attempts == 0) {
            close_eq_valves(s, t_ms); /* command it, then let it drive */
            break;
        }
        if (actuators_busy(s))
            break; /* lines still moving: nothing to judge yet (M-15) */
        if (s->ops->seal_ok(s->ops->ctx)) {
            s->seal_verified = true;
            enter(s, ST_RELEASE_1, t_ms);
        } else if (s->seal_attempts >
                   (uint8_t)cfg_get(s->cfg, PARAM_SEAL_RETRY)) {
            /* proceed flagged: the measurement is still valid (spec) */
            s->ops->event(s->ops->ctx, EV_SEAL_FAILED, "unverified");
            enter(s, ST_RELEASE_1, t_ms);
        } else if (t_ms - s->last_seal_try_ms >= SEAL_RETRY_SPACING_MS) {
            close_eq_valves(s, t_ms);
        }
        break;

    case ST_RELEASE_1:
        fire(s, 1, t_ms);
        enter(s, ST_MEASURE_1, t_ms);
        break;

    case ST_MEASURE_1:
        if (s->hold)
            break;
        if (elapsed(s, t_ms) >=
            (uint64_t)cfg_get(s->cfg, PARAM_T_MEASURE_S) * 1000u)
            enter(s, ST_RELEASE_2, t_ms);
        break;

    case ST_RELEASE_2:
        fire(s, 2, t_ms);
        enter(s, ST_MEASURE_2, t_ms);
        break;

    case ST_MEASURE_2:
        if (s->hold)
            break;
        if (elapsed(s, t_ms) >=
            (uint64_t)cfg_get(s->cfg, PARAM_T_MEASURE_S) * 1000u)
            enter(s, ST_TERMINATION, t_ms);
        break;

    case ST_TERMINATION:
        set_membrane(s, 0);
        set_motor(s, false);
        s->ops->close_eq_valves(s->ops->ctx);
        enter(s, ST_SAFE, t_ms);
        break;

    case ST_SAFE:
        break; /* actuators off, logging + HK continue outside */
    }
}

void seq_note_ground_cmd(sequencer_t *s, uint64_t t_ms)
{
    autonomy_cmd_seen(&s->autonomy, t_ms);
}

uint8_t seq_command(sequencer_t *s, uint64_t t_ms, uint32_t wall_s,
                    uint8_t cmd, uint8_t key, int32_t value, cfg_t *cfg)
{
    autonomy_cmd_seen(&s->autonomy, t_ms); /* any traffic = link alive */

    switch (cmd) {
    case CMD_PING:
        return ACK_OK;
    case CMD_HOLD:
        s->hold = true;
        return ACK_OK;
    case CMD_RESUME:
        s->hold = false;
        return ACK_OK;
    case CMD_ABORT:
        s->ops->event(s->ops->ctx, EV_ABORTED, "ground abort");
        s->hold = false;
        if (s->state != ST_SAFE)
            enter(s, ST_TERMINATION, t_ms);
        return ACK_OK;
    case CMD_START: /* accelerator only: skip waiting for launch detect */
        if (s->state != ST_STANDBY)
            return ACK_REJECTED;
        s->hold = false;
        if (s->mission_start_s == 0)
            s->mission_start_s = wall_s;
        enter(s, ST_ASCENT, t_ms);
        return ACK_OK;
    case CMD_RELEASE: /* accelerator: jump the sequence forward */
        if (key == 1 && s->state >= ST_ASCENT && s->state < ST_RELEASE_1 &&
            !(s->fired & 1u)) {
            s->hold = false;
            enter(s, ST_RELEASE_1, t_ms);
            return ACK_OK;
        }
        if (key == 2 && s->state >= ST_ASCENT && s->state < ST_RELEASE_2 &&
            !(s->fired & 2u)) {
            s->hold = false;
            enter(s, ST_RELEASE_2, t_ms);
            return ACK_OK;
        }
        /* Wrong valve number, already fired, or not in flight yet - on the
         * pad this is the state check that keeps a stray RELEASE harmless.
         * Ground needs to hear that it did nothing. */
        return key == 1 || key == 2 ? ACK_REJECTED : ACK_INVALID;
    case CMD_MEMBRANE: /* operator drive of the push-pull solenoid */
        if (key > 100)
            return ACK_INVALID;
        if (!actuators_commandable(s))
            return ACK_REJECTED;
        set_membrane(s, key);
        s->ops->event(s->ops->ctx, EV_MANUAL_DRIVE,
                      key ? "membrane on" : "membrane off");
        return ACK_OK;
    case CMD_DISPERSE: /* the CaCO3 motor: stop, one bounded pulse, or run */
        if (key > DISPERSE_RUN)
            return ACK_INVALID;
        /* A board without the motor must say so rather than answer OK for a
         * drive that no line can make. */
        if (s->ops->disperse == NULL || s->ops->disperse_run == NULL)
            return ACK_REJECTED;
        if (key == DISPERSE_STOP) {
            /* Always honoured, TERMINATION and SAFE included: it can only
             * de-energize. Ends a run and cuts a pulse short alike. */
            set_motor(s, false);
            s->ops->event(s->ops->ctx, EV_MANUAL_DRIVE, "disperse stop");
            return ACK_OK;
        }
        if (!actuators_commandable(s))
            return ACK_REJECTED;
        if (key == DISPERSE_RUN) {
            /* Idempotent: a second RUN re-latches the speed, nothing else. */
            set_motor(s, true);
            s->ops->event(s->ops->ctx, EV_MANUAL_DRIVE, "disperse run");
            return ACK_OK;
        }
        /* PULSE while the operator holds the motor on: the bounded drive it
         * asks for cannot happen, so ground hears that it did nothing. */
        if (s->motor_running)
            return ACK_REJECTED;
        s->ops->disperse(s->ops->ctx);
        s->ops->event(s->ops->ctx, EV_MANUAL_DRIVE, "disperse");
        return ACK_OK;
    case CMD_SET_PARAM:
        if (!cfg_set(cfg, key, value))
            return ACK_INVALID;
        /* A running motor takes a new speed at once, or the panel would show
         * a speed the motor is not turning at until the next STOP/RUN. */
        if (key == PARAM_DISPERSE_DUTY && s->motor_running)
            set_motor(s, true);
        return ACK_OK;
    case CMD_STATUS_REQ:
        return ACK_OK; /* answered by the Pi's PISTATUS, nothing to do here */
    default:
        return ACK_INVALID;
    }
}
