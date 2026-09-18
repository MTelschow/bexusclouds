/* Pi link supervision (M-13, S.7).
 *
 * Pure logic, injected time - the whole thing runs in the native test suite.
 * One job: **liveness**. Any valid frame from the Pi refreshes the link.
 * After PARAM_PI_SILENT_S without one the MCU declares the Pi lost, reports
 * it (MCUF_PI_OK clears, one event) and carries on: S.7 forbids the Pi from
 * delaying any state transition, so this is observation, never control.
 *
 * The arm/execute gate that used to live here is gone (2026-09-18): while
 * ground is connected every command executes, so there is nothing left for
 * this layer to refuse. `link_gate()` went with it - main.c hands every
 * command straight to the sequencer.
 */
#ifndef CLOUDS_LINK_H
#define CLOUDS_LINK_H

#include <stdbool.h>
#include <stdint.h>

#include "config.h"

typedef struct {
    uint64_t last_rx_ms;
    bool has_seen_pi;
    bool pi_ok;
} link_t;

void link_init(link_t *l, uint64_t t_ms);
/* Any valid frame decoded from the Pi - CMD, TIMESYNC, anything. */
void link_rx(link_t *l, uint64_t t_ms);
/* Call at the HK cadence. Returns true when pi_ok changed, so the caller can
 * emit exactly one event per transition. */
bool link_step(link_t *l, const cfg_t *cfg, uint64_t t_ms);

#endif
