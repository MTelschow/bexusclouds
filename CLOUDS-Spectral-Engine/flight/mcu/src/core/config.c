#include "config.h"

/* {default, min, max} - a corrupted or malicious SET_PARAM can never push
 * a value outside the physically sane envelope. */
static const int32_t limits[PARAM_COUNT_][3] = {
    [PARAM_LAUNCH_DP_PA] = {5000, 500, 50000},
    [PARAM_LAUNCH_DEBOUNCE_S] = {60, 5, 600},
    [PARAM_FLOAT_P_PA] = {5500, 1000, 30000},
    [PARAM_FLOAT_DPDT_CPA_S] = {500, 50, 10000},
    [PARAM_FLOAT_HOLD_S] = {300, 10, 3600},
    [PARAM_T_FLOAT_S] = {7200, 600, 21600},
    [PARAM_LINKLOSS_S] = {600, 60, 3600},
    [PARAM_T_MEASURE_S] = {480, 60, 3600},
    [PARAM_MEMBRANE_MHZ] = {2000, 100, 400000}, /* millihertz. 2 Hz default:
                                          below the ~9 Hz PWM floor, so the
                                          drive is loop-toggled (core/sqwave).
                                          Floor 0.1 Hz = a 10 s cycle; the
                                          operator asked for tenths of a hertz,
                                          and an int32 in whole Hz cannot say
                                          0.5. Ceiling 400 Hz as before. */
    [PARAM_MEMBRANE_DUTY] = {60, 5, 100},
    [PARAM_SEAL_RETRY] = {3, 0, 10},
    /* M-13: the Pi's own beat is TIMESYNC every 10 s, so 60 s is six missed
     * beats before it is called lost. Losing it changes nothing the sequence
     * does (S.7) - it only clears MCUF_PI_OK and raises one event. */
    [PARAM_PI_SILENT_S] = {60, 5, 600},
    /* M-07 motor speed. Default 100 % = the full-on drive this pin had
     * before it was a PWM, so no configured system changes behaviour. The
     * 20 % floor is not a safety limit but a usefulness one: a brushed motor
     * below that draws current and does not turn, which reads on the panel
     * as a drive that ran and dispersed nothing. */
    [PARAM_DISPERSE_DUTY] = {100, 20, 100},
};

void cfg_defaults(cfg_t *cfg)
{
    for (int i = 1; i < PARAM_COUNT_; i++)
        cfg->v[i] = limits[i][0];
    cfg->v[0] = 0;
}

int32_t cfg_default(uint8_t key)
{
    if (key == 0 || key >= PARAM_COUNT_)
        return 0;
    return limits[key][0];
}

bool cfg_set(cfg_t *cfg, uint8_t key, int32_t value)
{
    if (key == 0 || key >= PARAM_COUNT_)
        return false;
    if (value < limits[key][1] || value > limits[key][2])
        return false;
    cfg->v[key] = value;
    return true;
}

int32_t cfg_get(const cfg_t *cfg, uint8_t key)
{
    if (key == 0 || key >= PARAM_COUNT_)
        return 0;
    return cfg->v[key];
}
