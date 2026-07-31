/* Autonomy / flight detection (S.1, O.2) - pure logic, injected samples.
 *
 * Launch:  ambient pressure below (ground reference - LAUNCH_DP_PA),
 *          sustained LAUNCH_DEBOUNCE_S.
 * Float:   p < FLOAT_P_PA and |dp/dt| < FLOAT_DPDT for FLOAT_HOLD_S,
 *          OR T_FLOAT_S after launch (timer fallback).
 * Link:    latched autonomous when no ground command for LINKLOSS_S -
 *          informational (the sequence is autonomous by default, S.2).
 */
#ifndef CLOUDS_AUTONOMY_H
#define CLOUDS_AUTONOMY_H

#include <stdbool.h>
#include <stdint.h>

#include "config.h"

#define AUT_RING 16 /* dp/dt window: 16 samples ~ 16 s at 1 Hz */

typedef struct {
    const cfg_t *cfg;
    /* launch */
    uint32_t p_ground_pa; /* reference: max pressure seen before launch */
    uint64_t launch_cand_ms;
    bool launch_detected;
    uint64_t launch_ms;
    /* float */
    uint64_t float_cand_ms;
    bool float_detected;
    /* dp/dt ring */
    uint32_t ring_p[AUT_RING];
    uint64_t ring_t[AUT_RING];
    uint8_t ring_n, ring_head;
    /* link */
    uint64_t last_cmd_ms;
    bool has_seen_cmd;
    bool autonomous_latched;
} autonomy_t;

void autonomy_init(autonomy_t *a, const cfg_t *cfg, uint64_t t_ms);
/* Restore across a reset (S.3 resume path). */
void autonomy_restore(autonomy_t *a, bool launch_detected, uint64_t launch_ms);
void autonomy_step(autonomy_t *a, uint64_t t_ms, uint32_t p_amb_pa);
void autonomy_cmd_seen(autonomy_t *a, uint64_t t_ms);
/* |dp/dt| in centi-Pa/s over the ring window; INT32_MAX until enough data. */
int32_t autonomy_dpdt_cpa_s(const autonomy_t *a);

#endif
