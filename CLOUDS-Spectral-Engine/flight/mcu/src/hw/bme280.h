/* BME280 over I2C0 (M-09): ambient temperature, humidity and pressure.
 *
 * Confirmed on the CLOUDS carrier at address 0x76, chip_id 0x60 (DEVLOG
 * 2026-08-31). The part is driven in normal (continuous) mode so a sample is
 * always waiting: reading it costs one register burst and no delay, which is
 * what lets the 1 Hz sweep stay inside the 2 s watchdog without ever
 * sleeping in the hardware layer (S.9).
 */
#ifndef CLOUDS_BME280_H
#define CLOUDS_BME280_H

#include <stdbool.h>
#include <stdint.h>

/* Reads the calibration block and starts continuous conversion. Returns
 * false if the chip id does not read back 0x60, in which case every later
 * bme280_read() also fails and the caller must fall back. Never sleeps. */
bool bme280_init(void);

/* Latest compensated sample. Returns false on any I2C error or if init
 * failed; outputs are untouched in that case, so the caller keeps its own
 * last-good values. Never sleeps.
 *   temp_cc   centi-degC
 *   rh_cpct   centi-%RH
 *   p_pa      Pa
 */
bool bme280_read(int16_t *temp_cc, uint16_t *rh_cpct, uint32_t *p_pa);

#endif
