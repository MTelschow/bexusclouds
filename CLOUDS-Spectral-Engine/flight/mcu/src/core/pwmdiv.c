#include "pwmdiv.h"

uint32_t pwmdiv_min_hz(uint32_t sys_hz)
{
    /* f = sys * 16 / (div16 * period); slowest is max divider, max period.
     * Rounded up, so a request at exactly this value is achievable. */
    uint64_t d = (uint64_t)PWMDIV_MAX_DIV16 * PWMDIV_MAX_WRAP;

    return (uint32_t)(((uint64_t)sys_hz * 16u + d - 1u) / d);
}

void pwmdiv_solve(uint32_t sys_hz, uint32_t target_hz, uint32_t *div16,
                  uint32_t *wrap_period)
{
    uint64_t d, w;

    if (target_hz == 0)
        target_hz = 1;

    /* Smallest divider that still keeps the period inside 16 bits. */
    d = ((uint64_t)sys_hz * 16u + (uint64_t)PWMDIV_MAX_WRAP * target_hz - 1u) /
        ((uint64_t)PWMDIV_MAX_WRAP * target_hz);
    if (d < PWMDIV_MIN_DIV16)
        d = PWMDIV_MIN_DIV16;
    if (d > PWMDIV_MAX_DIV16)
        d = PWMDIV_MAX_DIV16;

    /* Round the period rather than truncating: at high divider values a
     * truncated period is a visibly wrong frequency. */
    w = ((uint64_t)sys_hz * 16u + (d * target_hz) / 2u) / (d * target_hz);
    if (w < 1u)
        w = 1u;
    if (w > PWMDIV_MAX_WRAP)
        w = PWMDIV_MAX_WRAP;

    *div16 = (uint32_t)d;
    *wrap_period = (uint32_t)w;
}

uint32_t pwmdiv_actual_hz(uint32_t sys_hz, uint32_t div16, uint32_t wrap_period)
{
    if (div16 == 0 || wrap_period == 0)
        return 0;
    return (uint32_t)(((uint64_t)sys_hz * 16u) /
                      ((uint64_t)div16 * wrap_period));
}
