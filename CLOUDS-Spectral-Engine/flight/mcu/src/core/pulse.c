#include "pulse.h"

void pulse_init(pulse_sched_t *s)
{
    *s = (pulse_sched_t){0};
    s->active_pin = PULSE_PIN_NONE;
}

static bool queued(const pulse_sched_t *s, uint8_t pin)
{
    for (uint8_t i = 0; i < s->count; i++)
        if (s->q[(uint8_t)((s->head + i) % PULSE_SLOTS)].pin == pin)
            return true;
    return false;
}

bool pulse_request(pulse_sched_t *s, uint8_t pin, uint8_t interlock)
{
    if (pin == PULSE_PIN_NONE)
        return false;
    if (s->active_pin == pin || queued(s, pin))
        return true; /* already scheduled */
    if (s->count >= PULSE_SLOTS) {
        s->dropped++;
        return false;
    }
    s->q[(uint8_t)((s->head + s->count) % PULSE_SLOTS)] =
        (pulse_req_t){.pin = pin, .interlock = interlock};
    s->count++;
    return true;
}

bool pulse_busy(const pulse_sched_t *s)
{
    return s->active_pin != PULSE_PIN_NONE || s->count > 0;
}

void pulse_service(pulse_sched_t *s, uint64_t now_ms, uint32_t pulse_ms,
                   pulse_drive_fn drive, void *ctx)
{
    pulse_req_t next;

    if (s->active_pin != PULSE_PIN_NONE) {
        if (now_ms < s->active_until_ms)
            return; /* still driving - one at a time */
        drive(ctx, s->active_pin, false);
        s->active_pin = PULSE_PIN_NONE;
    }
    if (s->count == 0)
        return;

    next = s->q[s->head];
    s->head = (uint8_t)((s->head + 1) % PULSE_SLOTS);
    s->count--;
    /* firmware interlock: never drive an open/close pair together (S.8) */
    if (next.interlock != PULSE_PIN_NONE)
        drive(ctx, next.interlock, false);
    drive(ctx, next.pin, true);
    s->active_pin = next.pin;
    s->active_until_ms = now_ms + pulse_ms;
}
