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

/* Which actuator line is energized right now, as HKV_* bits (core/frame.h),
 * for hk_t.valve_status. The drives are bounded pulses that finish between
 * two 1 Hz housekeeping packets, so this is the only way ground sees a
 * commanded valve or motor drive actually happen. Also carries
 * HKV_MEMBRANE_PULLED, the one sensed bit: the membrane position switch on
 * GP30, read at the moment of the call. */
uint8_t hw_actuator_status(void);

/* The membrane position switch (board.h PIN_MEMBRANE_SENSE), decoded: true
 * while the switch says the solenoid is energized (pulled) - the button is
 * pressed then, so the pull-up's LOW is inverted into this true. False when the
 * pin is not reachable in this build - hw_read_sensors() raises
 * HKE_NO_MEMBRANE_SENSE in that case so ground does not read the false as
 * "pushed". */
bool hw_membrane_pulled(void);

/* The CaCO3 dispersion motor's current sense (board.h PIN_HB_SENSE,
 * ACT_HB_SENS on GP46 / ADC6): the raw 12-bit ADC sample, or
 * HB_SENSE_INVALID when the pin is not reachable in this build. Not
 * converted here - the DRV8251A IPROPI gain and its sense resistor are
 * ground-side constants (clouds_link/hk.py HB_SENSE_A_PER_V). */
uint16_t hw_hb_sense_raw(void);

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
