/* BME280 (M-09): temperature, humidity and pressure. Two parts, two buses.
 *
 * AMBIENT, on i2c0 at 0x76, chip_id 0x60 - confirmed on the CLOUDS carrier
 * (DEVLOG 2026-08-31). This is the part the sequencer depends on: its
 * pressure is hk_t.p_amb_pa, which autonomy_step() reads for launch and
 * float detection.
 *
 * CHAMBER, on SPI_1 with its chip select on GP9 - the test chamber part.
 * Instrumentation only: it fills hk_t.chm_* and nothing in the sequencer
 * reads it. That separation is deliberate and is the reason a chamber read
 * failure is its own flag (HKE_BME280_CHM_FAIL) rather than folded into the
 * ambient one - the two parts fail independently and only one of them can
 * fire a valve.
 *
 * Both are driven in normal (continuous) mode so a sample is always waiting:
 * reading one costs a register burst and no delay, which is what lets the
 * 1 Hz sweep stay inside the 2 s watchdog without ever sleeping in the
 * hardware layer (S.9).
 */
#ifndef CLOUDS_BME280_H
#define CLOUDS_BME280_H

#include <stdbool.h>
#include <stdint.h>

/* Which bus a bme280_t sits on. The register map, the compensation and the
 * sample cadence are identical either way; only the transport differs. */
typedef enum {
    BME280_BUS_I2C, /* i2c0, address in bme280_t.addr */
    BME280_BUS_SPI, /* spi1, chip select in bme280_t.cs_pin */
} bme280_bus_t;

/* One part. The calibration block is per-part - two BME280s do not share
 * trim values - and so is t_fine, which carries temperature into the same
 * part's pressure and humidity compensation. A single shared t_fine would
 * silently compensate the chamber's pressure with the ambient part's
 * temperature, which reads as a plausible number and is wrong. */
typedef struct {
    bme280_bus_t bus;
    uint8_t addr;   /* I2C only */
    uint8_t cs_pin; /* SPI only */

    uint16_t dig_T1, dig_P1;
    int16_t dig_T2, dig_T3;
    int16_t dig_P2, dig_P3, dig_P4, dig_P5, dig_P6, dig_P7, dig_P8, dig_P9;
    uint8_t dig_H1, dig_H3;
    int16_t dig_H2, dig_H4, dig_H5;
    int8_t dig_H6;

    bool ready;
    int32_t t_fine;
} bme280_t;

/* The two parts on this board. Defined in bme280.c with their bus, address
 * and chip select already set; hw_init() calls bme280_init() on each. */
extern bme280_t bme280_ambient;
extern bme280_t bme280_chamber;

/* Reads the calibration block and starts continuous conversion. Returns
 * false if the chip id does not read back 0x60, in which case every later
 * bme280_read() on that part also fails and the caller must fall back.
 * Never sleeps.
 *
 * On SPI the id check is also the presence test: an absent part leaves MISO
 * undriven and the burst reads all-0x00 or all-0xff, neither of which is
 * 0x60. A wrong chip select fails here rather than downlinking numbers
 * compensated from a garbage trim block. */
bool bme280_init(bme280_t *dev);

/* Latest compensated sample. Returns false on any bus error or if init
 * failed; outputs are untouched in that case, so the caller keeps its own
 * last-good values. Never sleeps.
 *   temp_cc   centi-degC
 *   rh_cpct   centi-%RH
 *   p_pa      Pa
 */
bool bme280_read(bme280_t *dev, int16_t *temp_cc, uint16_t *rh_cpct,
                 uint32_t *p_pa);

#endif
