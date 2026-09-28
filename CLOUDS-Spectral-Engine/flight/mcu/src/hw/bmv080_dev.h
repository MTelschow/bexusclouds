/* BMV080 particulate matter sensor, on SPI_1 behind GP12 (board.h).
 *
 * Unlike every other part on this board there is no register map to drive:
 * the datasheet publishes only the transaction format, and the measurement
 * algorithm ships as two prebuilt Bosch archives (api/lib/arm_cortex_m33 for
 * the RP2350 - see the flight CMakeLists). This file is the thin layer
 * between that library and the conventions the rest of hw/ follows; the
 * transport it drives is hw/bmv080_port.c. The "_dev" suffix is not
 * decoration: the vendor API's header is itself bmv080.h, so a header named
 * after the part would shadow it inside src/hw/.
 *
 * INSTRUMENTATION ONLY. Nothing in core/ reads particulate mass, for the same
 * reason nothing reads the chamber BME280: only the ambient pressure is in
 * the sequencer's path, and a second sensor able to influence actuation is a
 * second sensor able to fire one by failing.
 *
 * WHAT IS DIFFERENT ABOUT THIS PART, and worth knowing before changing
 * anything here:
 *
 *   - It produces one sample about every 1.03 s (max ODR 0.97 Hz), against a
 *     1 Hz housekeeping sweep. So some sweeps repeat the previous sample.
 *     That is what PM_STALE says; it is not an error.
 *   - The first sample arrives ~1.9 s after the measurement starts. Before
 *     that there is nothing to report and PM_FAIL stands.
 *   - bmv080_serve_interrupt() must be called at least once a second in every
 *     mode, or events are missed. bmv080_dev_service() is driven from the
 *     10 ms pass in main.c and rate-limits itself.
 *   - One service call can deliver SEVERAL readings if it was late: the
 *     library replays one per elapsed second. The data-ready callback
 *     therefore just overwrites the latest sample rather than queueing.
 *   - Continuous mode, HIGH_PRECISION, 10 s integration time (the default).
 *     Duty cycling is deliberately not used: it voids the precision spec and
 *     forces the fast-response algorithm.
 *
 * The vendor library delays internally during bring-up, so bmv080_dev_init()
 * is called from hw_init() - before hw_watchdog_enable() in main() - and the
 * delay callback kicks the watchdog and refuses an unreasonable wait
 * (bmv080_port.c). Nothing here spins.
 */
#ifndef CLOUDS_BMV080_DEV_H
#define CLOUDS_BMV080_DEV_H

#include <stdbool.h>
#include <stdint.h>

/* Opens the part, resets it, sets the measurement algorithm and starts a
 * continuous measurement. Returns false if any of that fails, in which case
 * every later bmv080_dev_read() also fails and the caller must fall back.
 *
 * On SPI there is no chip-id register to check - the vendor API's own
 * bmv080_open() reports E_BMV080_ERROR_MISMATCH_CHIP_ID (107) when it cannot
 * talk to the part, so a wrong chip select or a crossed harness fails here
 * rather than downlinking a number from nothing. The failing status is kept
 * for bmv080_dev_status(). */
bool bmv080_dev_init(void);

/* Serves the library. Must be reached at least once a second; calling it more
 * often is free, since it rate-limits itself to BMV080_SERVICE_INTERVAL_MS.
 * Never sleeps except through the vendor library's delay callback. */
void bmv080_dev_service(uint64_t now_ms);

/* Latest PM2.5 mass concentration, ug/m3, saturated at the part's specified
 * 1000 ug/m3 range ceiling. Returns false when there is no sample to give -
 * init failed, or the first sample has not arrived yet - and leaves the
 * outputs untouched so the caller can decide what to downlink.
 *
 * `*fresh` is false when this is the same sample the previous call returned,
 * which is the normal case for roughly one sweep in thirty-three. */
bool bmv080_dev_read(uint16_t *pm2_5_ugm3, bool *fresh, bool *obstructed,
                     bool *out_of_range);

/* The last non-OK vendor status code, or 0. Bench tools print it; the flight
 * path reduces it to one bit (PM_FAIL) because there is no room on the wire
 * for a status byte per sensor. */
int bmv080_dev_status(void);

/* The part's 13-character sensor id, or "" if it never answered. There is no
 * numeric chip id on this part. */
const char *bmv080_dev_sensor_id(void);

/* Stops the measurement and closes the handle. For the bench probe, which
 * wants to re-open the part itself after hw_init() has already done so.
 * Nothing in the flight path calls this. */
void bmv080_dev_close(void);

#endif
