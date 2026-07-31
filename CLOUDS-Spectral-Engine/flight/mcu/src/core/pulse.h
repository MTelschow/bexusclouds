/* Timed actuator pulses without blocking the main loop.
 *
 * The valves want a 5 s drive (VALVE_PULSE_MS) and the hardware watchdog
 * bites at 2 s (WATCHDOG_TIMEOUT_MS): a `sleep_ms(VALVE_PULSE_MS)` inside
 * the sequencer's fire path therefore resets the MCU *mid-actuation*, and
 * with the fired bits persisted the resume path would fire again. So the
 * drive is scheduled here instead - the loop starts a pulse, keeps kicking
 * the watchdog, and ends the pulse when its deadline passes (S.9 vs F.4).
 *
 * Portable logic, no hardware includes: the pin edges go out through a
 * caller-supplied sink, so this is unit-tested natively (test/test_core).
 *
 * One pulse drives at a time. Requests queue and run in order, which keeps
 * the peak actuator current at one solenoid and preserves the sequential
 * behaviour the blocking version had.
 */
#ifndef CLOUDS_PULSE_H
#define CLOUDS_PULSE_H

#include <stdbool.h>
#include <stdint.h>

#define PULSE_PIN_NONE 0xFFu

/* One slot per drivable output on the board (2 pinch + 4 valve lines).
 * Requests coalesce per pin, so the queue cannot exceed that. */
#define PULSE_SLOTS 6

/* Sink for a single pin edge (gpio_put on the Pico, a recorder in tests). */
typedef void (*pulse_drive_fn)(void *ctx, uint8_t pin, bool level);

typedef struct {
    uint8_t pin;
    uint8_t interlock; /* forced low before pin goes high; NONE = no pair */
} pulse_req_t;

typedef struct {
    pulse_req_t q[PULSE_SLOTS];
    uint8_t head;
    uint8_t count;
    uint8_t active_pin; /* PULSE_PIN_NONE while nothing is driving */
    uint64_t active_until_ms;
    uint16_t dropped; /* requests refused for want of a slot - stays 0 */
} pulse_sched_t;

void pulse_init(pulse_sched_t *s);

/* Queue a timed drive of `pin`. A pin already driving or already queued is
 * left alone (coalesced) and true is returned - repeated requests, e.g. the
 * 1 Hz seal retry, cannot pile up. false = no slot free (never expected;
 * counted in `dropped`). */
bool pulse_request(pulse_sched_t *s, uint8_t pin, uint8_t interlock);

/* End an expired pulse and start the next one. Emits at most two edges and
 * never waits, so it is safe anywhere in the loop; call it as often as
 * convenient - a pulse overruns by at most one call interval. */
void pulse_service(pulse_sched_t *s, uint64_t now_ms, uint32_t pulse_ms,
                   pulse_drive_fn drive, void *ctx);

/* True while a pulse is driving or waiting its turn: the actuators have not
 * finished moving, so nothing downstream should judge their effect yet. */
bool pulse_busy(const pulse_sched_t *s);

#endif
