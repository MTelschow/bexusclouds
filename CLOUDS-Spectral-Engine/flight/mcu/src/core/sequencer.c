#include "sequencer.h"

#include <stdio.h>

#include "frame.h" /* enum command */

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
     * the Pi went quiet. EV_AUTO_ENTERED is deliberately not here - it
     * always follows EV_AUTONOMOUS_LATCHED, which carries the warning, and
     * two warnings for one event teach nothing. */
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

static void enter(sequencer_t *s, seq_state_t st, uint64_t t_ms)
{
    char msg[24];

    s->state = st;
    s->state_entered_ms = t_ms;
    persist_now(s); /* every transition is durable (S.3 resume path) */
    snprintf(msg, sizeof msg, "state=%d", (int)st);
    s->ops->event(s->ops->ctx, EV_STATE_CHANGE, msg);
}

/* One phase of the automatic cycle. Both actuators are set on every phase
 * entry, not only the one this phase drives: the phase says what the whole
 * hardware is doing, so "motor only" is a statement about the solenoid too.
 * Speeds come from the running config - the defaults unless the operator
 * changed them before the link went away. */
static void enter_auto_phase(sequencer_t *s, seq_state_t st, uint64_t t_ms)
{
    set_motor(s, st == ST_AUTO_DISPERSE);
    set_membrane(s, st == ST_AUTO_MEMBRANE
                        ? (uint8_t)cfg_get(s->cfg, PARAM_MEMBRANE_DUTY)
                        : 0);
    enter(s, st, t_ms);
}

static void enter_auto(sequencer_t *s, uint64_t t_ms)
{
    s->ops->event(s->ops->ctx, EV_AUTO_ENTERED, "link silent");
    enter_auto_phase(s, ST_AUTO_DISPERSE, t_ms);
}

/* The link is back. Everything the cycle energized stops now, in the same
 * pass that saw the command - not at the end of the current phase. */
static void leave_auto(sequencer_t *s, uint64_t t_ms)
{
    set_motor(s, false);
    set_membrane(s, 0);
    s->ops->event(s->ops->ctx, EV_AUTO_LEFT, "link back");
    enter(s, ST_RUNNING, t_ms);
}

/* How long the current automatic phase lasts. */
static uint64_t auto_phase_ms(const sequencer_t *s)
{
    uint8_t key;

    switch (s->state) {
    case ST_AUTO_DISPERSE:
        key = PARAM_AUTO_DISPERSE_S;
        break;
    case ST_AUTO_MEMBRANE:
        key = PARAM_AUTO_MEMBRANE_S;
        break;
    default:
        key = PARAM_AUTO_WAIT_S;
        break;
    }
    return (uint64_t)cfg_get(s->cfg, key) * 1000u;
}

static seq_state_t auto_next(seq_state_t st)
{
    switch (st) {
    case ST_AUTO_DISPERSE:
        return ST_AUTO_MEMBRANE;
    case ST_AUTO_MEMBRANE:
        return ST_AUTO_WAIT;
    default:
        return ST_AUTO_DISPERSE; /* the cycle repeats while the link is out */
    }
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
     * the CaCO3 the pinch valve just let out. A bounded pulse, so this
     * returns at once. The membrane is NOT started here - it is the
     * operator's to drive (CMD_MEMBRANE) and automatic mode's to cycle;
     * latching it on behind a release left it oscillating with nothing
     * saying why. */
    if (s->ops->disperse != NULL && !s->motor_running)
        s->ops->disperse(s->ops->ctx);
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
        /* A reset drops out of automatic mode into RUNNING with both
         * actuators off (they are off anyway after a reset). If the link is
         * still gone, the link-loss timer runs again from here and the
         * cycle restarts at its first phase - the same thing it does after
         * any other entry, which is the point of restarting it. The old
         * RELEASE_1/RELEASE_2 state numbers land here too: they are the
         * AUTO_* numbers now, and resuming them as RUNNING is the safe
         * reading of a persist record written by an older image. */
        if (ST_IS_AUTO((seq_state_t)restored->state))
            s->state = ST_RUNNING;
        else
            s->state = (seq_state_t)restored->state;
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

    (void)wall_s;
    autonomy_step(&s->autonomy, t_ms, p_amb_pa);
    if (!was_latched && s->autonomy.autonomous_latched)
        s->ops->event(s->ops->ctx, EV_AUTONOMOUS_LATCHED, "link lost");
    /* Launch and float are reported, and nothing more: since 2026-09-18 the
     * experiment is started by the operator and driven by the link state,
     * so a pressure profile can no longer move the sequence on its own. */
    if (!was_launched && s->autonomy.launch_detected) {
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
        /* Nothing on its own, ever: the experiment begins with the
         * operator's START and with nothing else. A link that was never up
         * is not a link that was lost, so automatic mode does not start
         * here either. */
        break;

    case ST_RUNNING:
        /* HOLD is what says "stay passive": it is the only way to sit out a
         * link loss, and it survives one - see docs/TRAPS.md. */
        if (s->hold)
            break;
        if (s->autonomy.autonomous_latched)
            enter_auto(s, t_ms);
        break;

    case ST_AUTO_DISPERSE:
    case ST_AUTO_MEMBRANE:
    case ST_AUTO_WAIT:
        /* seq_note_ground_cmd() normally gets here first; this covers the
         * latch being cleared by anything else. */
        if (!s->autonomy.autonomous_latched) {
            leave_auto(s, t_ms);
            break;
        }
        if (elapsed(s, t_ms) >= auto_phase_ms(s))
            enter_auto_phase(s, auto_next(s->state), t_ms);
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
    /* The link is back and the operator is at the panel: the cycle stops
     * before their command is even acted on, so nothing they send lands on
     * a motor that is already turning for its own reasons. */
    if (ST_IS_AUTO(s->state))
        leave_auto(s, t_ms);
}

/* A drive commanded after an abort takes the experiment out of SAFE rather
 * than being refused (2026-09-18: while ground is connected, every command
 * executes). The state has to follow the hardware - SAFE means "nothing is
 * energized", so it cannot be what HK reports while the operator is running
 * the motor. ABORT remains the way back to SAFE, and START the other way. */
static void wake_from_safe(sequencer_t *s, uint64_t t_ms)
{
    if (s->state == ST_TERMINATION || s->state == ST_SAFE)
        enter(s, ST_RUNNING, t_ms);
}

uint8_t seq_command(sequencer_t *s, uint64_t t_ms, uint32_t wall_s,
                    uint8_t cmd, uint8_t key, int32_t value, cfg_t *cfg)
{
    seq_note_ground_cmd(s, t_ms); /* any traffic = link alive, cycle off */

    switch (cmd) {
    case CMD_PING:
        return ACK_OK;
    case CMD_ARM:
        /* Retired with the arm/execute gate (2026-09-18). A ground station
         * that still sends one gets an OK for a command that now does
         * nothing, rather than a refusal it cannot act on. */
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
    case CMD_START: /* the start button, from any state */
        s->hold = false;
        if (s->mission_start_s == 0)
            s->mission_start_s = wall_s;
        if (s->state != ST_RUNNING)
            enter(s, ST_RUNNING, t_ms);
        return ACK_OK;
    case CMD_RELEASE:
        if (key != 1 && key != 2)
            return ACK_INVALID;
        wake_from_safe(s, t_ms);
        /* The fired bit still cannot be set twice - that is the hardware's
         * own limit, not a state rule - but a second command is answered OK
         * like every other. */
        fire(s, key, t_ms);
        return ACK_OK;
    case CMD_MEMBRANE: /* operator drive of the push-pull solenoid */
        if (key > 100)
            return ACK_INVALID;
        wake_from_safe(s, t_ms);
        set_membrane(s, key);
        s->ops->event(s->ops->ctx, EV_MANUAL_DRIVE,
                      key ? "membrane on" : "membrane off");
        return ACK_OK;
    case CMD_DISPERSE: /* the CaCO3 motor: stop, one bounded pulse, or run */
        if (key > DISPERSE_RUN)
            return ACK_INVALID;
        if (key == DISPERSE_STOP) {
            set_motor(s, false);
            s->ops->event(s->ops->ctx, EV_MANUAL_DRIVE, "disperse stop");
            return ACK_OK;
        }
        wake_from_safe(s, t_ms);
        if (key == DISPERSE_RUN) {
            /* Idempotent: a second RUN re-latches the speed, nothing else. */
            set_motor(s, true);
            s->ops->event(s->ops->ctx, EV_MANUAL_DRIVE, "disperse run");
            return ACK_OK;
        }
        /* PULSE while the motor is already held on: the bounded drive it
         * asks for cannot be scheduled on top of a running motor, so the
         * hold stands and the command is answered OK - the motor is turning,
         * which is what was asked for. */
        if (!s->motor_running && s->ops->disperse != NULL)
            s->ops->disperse(s->ops->ctx);
        s->ops->event(s->ops->ctx, EV_MANUAL_DRIVE, "disperse");
        return ACK_OK;
    case CMD_SET_PARAM:
        if (!cfg_set(cfg, key, value))
            return ACK_INVALID; /* unknown key or out-of-envelope value */
        /* A running motor takes a new speed at once, or the panel would show
         * a speed the motor is not turning at until the next STOP/RUN. */
        if (key == PARAM_DISPERSE_DUTY && s->motor_running)
            set_motor(s, true);
        return ACK_OK;
    case CMD_STATUS_REQ:
        return ACK_OK; /* answered by the Pi's PISTATUS, nothing to do here */
    default:
        return ACK_INVALID; /* a command this build does not know */
    }
}
