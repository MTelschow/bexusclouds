/* Hardware layer: implements the sequencer's seq_ops_t against the Pico
 * SDK, plus sensor acquisition, redundant SD logging, and persistence.
 * Everything above this file is portable and unit-tested natively. */
#ifndef CLOUDS_HW_H
#define CLOUDS_HW_H

#include <stdbool.h>
#include <stdint.h>

#include "../core/frame.h"
#include "../core/sequencer.h"

void hw_init(void);

/* seq_ops_t implementation (pass to seq_init) */
extern const seq_ops_t hw_seq_ops;

/* Starts and ends the scheduled actuator drives. Must be called every pass
 * of the main loop: the 5 s valve pulse is timed here precisely so that no
 * actuation ever blocks past the 2 s watchdog (S.9). Never waits. */
void hw_actuators_service(uint64_t now_ms);

/* Persistence (S.3): mirrored raw sectors on both SD cards, whichever has
 * the newer valid CRC wins. Returns false on cold start. */
bool hw_restore_persist(seq_persist_t *out);

/* 1 Hz sensor sweep into the HK struct (fills everything but state/flags). */
void hw_read_sensors(hk_t *hk);

/* Redundant HK + event logging to both SD cards (S.6), CRC per record. */
void hw_log_hk(const hk_t *hk, uint32_t wall_s);
void hw_log_event(uint8_t code, const char *msg, uint32_t wall_s);

/* Wall clock: seconds from the Pi's TIMESYNC (S.4), monotonic fallback. */
void hw_timesync(uint32_t t_s, uint16_t t_ms);
uint32_t hw_wall_s(void);
uint64_t hw_monotonic_ms(void);

void hw_watchdog_enable(void);
void hw_watchdog_kick(void);

#endif
