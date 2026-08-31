#include "sqwave.h"

void sqwave_init(sqwave_t *w)
{
    w->active = false;
    w->level = false;
    w->on_ms = 0;
    w->off_ms = 0;
    w->next_edge_ms = 0;
}

void sqwave_start(sqwave_t *w, uint32_t hz, uint8_t duty_pct, uint64_t now_ms)
{
    uint32_t period_ms;

    if (hz == 0)
        hz = 1;
    period_ms = 1000u / hz;
    if (period_ms < 2u)
        period_ms = 2u; /* both phases need a millisecond to live in */

    w->on_ms = period_ms * duty_pct / 100u;
    if (w->on_ms < 1u)
        w->on_ms = 1u;
    if (w->on_ms > period_ms - 1u)
        w->on_ms = period_ms - 1u;
    w->off_ms = period_ms - w->on_ms;

    w->active = true;
    w->level = true; /* start energized: the caller asked for a drive */
    w->next_edge_ms = now_ms + w->on_ms;
}

void sqwave_stop(sqwave_t *w)
{
    w->active = false;
    w->level = false;
}

bool sqwave_active(const sqwave_t *w)
{
    return w->active;
}

bool sqwave_level(const sqwave_t *w)
{
    return w->active && w->level;
}

bool sqwave_service(sqwave_t *w, uint64_t now_ms)
{
    if (!w->active || now_ms < w->next_edge_ms)
        return false;

    w->level = !w->level;
    /* Scheduled from `now`, not from the previous edge: a late service pass
     * stretches this cycle instead of firing a burst of catch-up edges, which
     * matters because the pass that was late is usually the one where the
     * loop had real work to do. */
    w->next_edge_ms = now_ms + (w->level ? w->on_ms : w->off_ms);
    return true;
}
