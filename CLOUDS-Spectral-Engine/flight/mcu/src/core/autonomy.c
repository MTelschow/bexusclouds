#include "autonomy.h"

#include <limits.h>
#include <stdlib.h>

void autonomy_init(autonomy_t *a, const cfg_t *cfg, uint64_t t_ms)
{
    *a = (autonomy_t){0};
    a->cfg = cfg;
    a->last_cmd_ms = t_ms;
}

void autonomy_restore(autonomy_t *a, bool launch_detected, uint64_t launch_ms)
{
    a->launch_detected = launch_detected;
    a->launch_ms = launch_ms;
}

void autonomy_cmd_seen(autonomy_t *a, uint64_t t_ms)
{
    a->last_cmd_ms = t_ms;
    a->has_seen_cmd = true;
    a->autonomous_latched = false; /* link is back */
}

int32_t autonomy_dpdt_cpa_s(const autonomy_t *a)
{
    uint8_t oldest;
    uint64_t dt_ms;
    int64_t dp_pa;

    if (a->ring_n < AUT_RING)
        return INT32_MAX;
    oldest = a->ring_head; /* head points at the slot to overwrite = oldest */
    dt_ms = a->ring_t[(uint8_t)((a->ring_head + AUT_RING - 1) % AUT_RING)] -
            a->ring_t[oldest];
    if (dt_ms == 0)
        return INT32_MAX;
    dp_pa = (int64_t)a->ring_p[(uint8_t)((a->ring_head + AUT_RING - 1) %
                                         AUT_RING)] -
            (int64_t)a->ring_p[oldest];
    return (int32_t)(llabs(dp_pa) * 100000 / (int64_t)dt_ms);
}

static void ring_push(autonomy_t *a, uint64_t t_ms, uint32_t p)
{
    a->ring_p[a->ring_head] = p;
    a->ring_t[a->ring_head] = t_ms;
    a->ring_head = (uint8_t)((a->ring_head + 1) % AUT_RING);
    if (a->ring_n < AUT_RING)
        a->ring_n++;
}

void autonomy_step(autonomy_t *a, uint64_t t_ms, uint32_t p_amb_pa)
{
    const cfg_t *c = a->cfg;

    ring_push(a, t_ms, p_amb_pa);

    /* link-loss latch (O.2): informational, sequence continues either way */
    if (!a->autonomous_latched &&
        t_ms - a->last_cmd_ms >
            (uint64_t)cfg_get(c, PARAM_LINKLOSS_S) * 1000u)
        a->autonomous_latched = true;

    if (!a->launch_detected) {
        if (p_amb_pa > a->p_ground_pa)
            a->p_ground_pa = p_amb_pa; /* track ground reference */
        if (a->p_ground_pa > 0 &&
            p_amb_pa + (uint32_t)cfg_get(c, PARAM_LAUNCH_DP_PA) <=
                a->p_ground_pa) {
            if (a->launch_cand_ms == 0)
                a->launch_cand_ms = t_ms;
            if (t_ms - a->launch_cand_ms >=
                (uint64_t)cfg_get(c, PARAM_LAUNCH_DEBOUNCE_S) * 1000u) {
                a->launch_detected = true;
                a->launch_ms = t_ms;
            }
        } else {
            a->launch_cand_ms = 0; /* debounce reset */
        }
        return;
    }

    if (a->float_detected)
        return;

    /* timer fallback */
    if (t_ms - a->launch_ms >=
        (uint64_t)cfg_get(c, PARAM_T_FLOAT_S) * 1000u) {
        a->float_detected = true;
        return;
    }

    /* pressure criterion */
    if (p_amb_pa < (uint32_t)cfg_get(c, PARAM_FLOAT_P_PA) &&
        autonomy_dpdt_cpa_s(a) < cfg_get(c, PARAM_FLOAT_DPDT_CPA_S)) {
        if (a->float_cand_ms == 0)
            a->float_cand_ms = t_ms;
        if (t_ms - a->float_cand_ms >=
            (uint64_t)cfg_get(c, PARAM_FLOAT_HOLD_S) * 1000u)
            a->float_detected = true;
    } else {
        a->float_cand_ms = 0;
    }
}
