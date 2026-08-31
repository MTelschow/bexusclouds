/* Low-frequency square wave for the membrane solenoid (M-07).
 *
 * Why this exists rather than a PWM slice: the RP2xxx PWM divider caps at
 * 255+15/16 and its counter at 16 bits, so the slowest frequency it can
 * produce is clk_sys / (256 * 65536), about 9 Hz at 150 MHz. The membrane runs
 * at 2 Hz, well under that floor.
 *
 * Edges are released by the main loop, exactly as core/pulse releases the
 * valve drives, so a hung loop cannot leave the solenoid energized - the
 * watchdog resets the part and hw_init() drives the pin low. An interrupt- or
 * PWM-driven output would keep toggling through a hang, which is why neither
 * is used for an actuator here (S.8, S.9).
 *
 * Timing therefore quantises to the loop period (~10 ms), which at 2 Hz is a
 * 2 % edge granularity on a 500 ms cycle.
 */
#ifndef CLOUDS_SQWAVE_H
#define CLOUDS_SQWAVE_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    bool active;
    bool level;
    uint32_t on_ms;
    uint32_t off_ms;
    uint64_t next_edge_ms;
} sqwave_t;

void sqwave_init(sqwave_t *w);

/* Begin oscillating at `hz` with `duty_pct` high time, starting high.
 * Both phases are forced to at least 1 ms, so a duty of 0 or 100 still
 * produces a real square wave rather than a stuck level - callers that mean
 * "off" must use sqwave_stop(), which is unambiguous. */
void sqwave_start(sqwave_t *w, uint32_t hz, uint8_t duty_pct,
                  uint64_t now_ms);

/* Stop and return to the low level. Idempotent. */
void sqwave_stop(sqwave_t *w);

bool sqwave_active(const sqwave_t *w);
bool sqwave_level(const sqwave_t *w);

/* Advance the waveform. Returns true when the output level changed, so the
 * caller only touches the pin on an edge. Never waits. */
bool sqwave_service(sqwave_t *w, uint64_t now_ms);

#endif
