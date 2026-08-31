/* Pi link supervision + uplink command gate (M-13, S.7, S.8).
 *
 * Pure logic, injected time - the whole thing runs in the native test suite.
 * Two jobs, both about the peer on UART0:
 *
 *  - **Liveness.** Any valid frame from the Pi refreshes the link. After
 *    PARAM_PI_SILENT_S without one the MCU declares the Pi lost, reports it
 *    (MCUF_PI_OK clears, one event) and carries on: S.7 forbids the Pi from
 *    delaying any state transition, so this is observation, never control.
 *
 *  - **Arm/execute gate.** The Pi command server is authoritative for S.8,
 *    but a corrupted or spurious CMD_RELEASE that survives CRC would fire a
 *    pinch valve if the MCU trusted the wire. So the MCU keeps its own arm
 *    latch: RELEASE is refused unless an ARM naming it arrived within
 *    LINK_ARM_WINDOW_MS, and one ARM authorises exactly one execute.
 */
#ifndef CLOUDS_LINK_H
#define CLOUDS_LINK_H

#include <stdbool.h>
#include <stdint.h>

#include "config.h"

/* Mirror of ARM_WINDOW_S in clouds_link/commands.py. */
#define LINK_ARM_WINDOW_MS 10000u

/* link_gate() verdict meaning "not decided here - hand it to the sequencer".
 * Distinct from every enum ack_result value. */
#define LINK_PASS 0xFFu

typedef struct {
    uint64_t last_rx_ms;
    bool has_seen_pi;
    bool pi_ok;
    uint8_t armed_cmd; /* CMD_NONE when nothing is armed */
    uint64_t armed_until_ms;
} link_t;

void link_init(link_t *l, uint64_t t_ms);
/* Any valid frame decoded from the Pi - CMD, TIMESYNC, anything. */
void link_rx(link_t *l, uint64_t t_ms);
/* Call at the HK cadence. Returns true when pi_ok changed, so the caller can
 * emit exactly one event per transition. */
bool link_step(link_t *l, const cfg_t *cfg, uint64_t t_ms);
/* Command safety gate: returns an enum ack_result value to answer with, or
 * LINK_PASS when the sequencer should decide. Consumes the arm latch. */
uint8_t link_gate(link_t *l, uint64_t t_ms, uint8_t cmd, uint8_t key);

#endif
