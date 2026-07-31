/* Runtime-settable parameters (SET_PARAM) - mirror of commands.py Param.
 * Feature M-16: loaded from SD at boot, defaults below (spec section 5). */
#ifndef CLOUDS_CONFIG_H
#define CLOUDS_CONFIG_H

#include <stdbool.h>
#include <stdint.h>

enum param {
    PARAM_LAUNCH_DP_PA = 1,      /* drop vs ground reference (Pa)         */
    PARAM_LAUNCH_DEBOUNCE_S = 2, /* sustained for this long               */
    PARAM_FLOAT_P_PA = 3,        /* float candidate below this pressure   */
    PARAM_FLOAT_DPDT_CPA_S = 4,  /* |dp/dt| below this (centi-Pa/s)       */
    PARAM_FLOAT_HOLD_S = 5,      /* for this long                         */
    PARAM_T_FLOAT_S = 6,         /* timer fallback after launch           */
    PARAM_LINKLOSS_S = 7,        /* autonomous latch (O.2)                */
    PARAM_T_MEASURE_S = 8,       /* per measurement phase (P.6 + P.7)     */
    PARAM_MEMBRANE_HZ = 9,
    PARAM_MEMBRANE_DUTY = 10,    /* percent                               */
    PARAM_SEAL_RETRY = 11,
    PARAM_COUNT_ /* keep last */
};

typedef struct {
    int32_t v[PARAM_COUNT_];
} cfg_t;

void cfg_defaults(cfg_t *cfg);
bool cfg_set(cfg_t *cfg, uint8_t key, int32_t value); /* range-checked */
int32_t cfg_get(const cfg_t *cfg, uint8_t key);

#endif
