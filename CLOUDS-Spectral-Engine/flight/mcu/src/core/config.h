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
    PARAM_LINKLOSS_S = 7,        /* automatic mode after this much
                                    ground silence (O.2)                  */
    /* 8 = PARAM_T_MEASURE_S and 11 = PARAM_SEAL_RETRY are RETIRED: the
       measurement phases and the seal state they configured went with the
       old ascent/release sequence on 2026-09-18. The numbers are not
       reused, and cfg_set() refuses them, so a stale sender is told its
       parameter no longer exists instead of quietly setting something
       else.                                                              */
    PARAM_MEMBRANE_MHZ = 9,      /* solenoid drive frequency, MILLIhertz:
                                    2000 = 2 Hz. Was PARAM_MEMBRANE_HZ in
                                    whole hertz until 2026-09-17; the key
                                    number is unchanged, the unit is not, so
                                    a stale sender's "2" is now 2 mHz and
                                    is refused by the 100 mHz floor.       */
    PARAM_MEMBRANE_DUTY = 10,    /* percent                               */
    PARAM_PI_SILENT_S = 12,      /* Pi declared lost after this (M-13)     */
    PARAM_DISPERSE_DUTY = 13,    /* CaCO3 motor speed, percent             */
    /* Automatic mode's cycle (sequencer.h). One phase each, in this
       order, repeating for as long as the link stays down.               */
    PARAM_AUTO_DISPERSE_S = 14,  /* motor only      (default 120)          */
    PARAM_AUTO_MEMBRANE_S = 15,  /* solenoid only   (default 180)          */
    PARAM_AUTO_WAIT_S = 16,      /* neither         (default 300)          */
    PARAM_COUNT_ /* keep last */
};

typedef struct {
    int32_t v[PARAM_COUNT_];
} cfg_t;

void cfg_defaults(cfg_t *cfg);
bool cfg_set(cfg_t *cfg, uint8_t key, int32_t value); /* range-checked */
int32_t cfg_get(const cfg_t *cfg, uint8_t key);
/* Compiled-in default for a key, without needing a cfg_t. Lets a fallback
 * path use the same number as cfg_defaults() instead of duplicating it.
 * Returns 0 for an unknown key. */
int32_t cfg_default(uint8_t key);

#endif
