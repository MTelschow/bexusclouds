/* BME280 driver (M-09), for both parts on this board: the ambient one on
 * i2c0 at 0x76 and the chamber one on SPI_1 behind GP9. Compensation is the
 * datasheet fixed-point reference (section 4.2.3); it was validated against
 * this board before being committed: 29.17 degC / 99396 Pa / 41.15 %RH on
 * the bench, calibration dig_T1=28323, dig_P1=37257, dig_H1=75. See DEVLOG
 * 2026-08-31. The compensation is bus-independent - only the transport
 * below it differs - so the chamber part inherits that validation, but its
 * transport has NOT been run against a fitted part.
 *
 * Nothing here sleeps or spins. Every I2C transfer carries a timeout, so a
 * wedged bus costs a bounded number of microseconds and reports failure
 * rather than stalling the 1 Hz loop into the 2 s watchdog (S.9). SPI needs
 * no timeout to make that guarantee: the controller clocks out a fixed
 * number of bytes at SPI1_BAUD_HZ and there is no bus party that can hold
 * the transfer open, so an absent part costs the same microseconds as a
 * present one and returns whatever an undriven MISO reads as.
 */
#include "bme280.h"

#include "hardware/gpio.h"
#include "hardware/i2c.h"
#include "hardware/spi.h"

#include "board.h"

#define BME_ADDR 0x76
#define BME_CHIP_ID 0x60

#define REG_CHIP_ID 0xD0
#define REG_CALIB_1 0x88 /* 26 bytes: dig_T1..T3, dig_P1..P9, dig_H1 */
#define REG_CALIB_2 0xE1 /* 7 bytes: dig_H2..H6 */
#define REG_CTRL_HUM 0xF2
#define REG_CTRL_MEAS 0xF4
#define REG_CONFIG 0xF5
#define REG_DATA 0xF7 /* 8 bytes: press[3], temp[3], hum[2] */

/* SPI register access bit 7 (datasheet 6.3): the address byte carries 0 to
 * write and 1 to read. The register numbers above are the I2C ones, which
 * are the SPI read addresses with this bit already clear, so a write must
 * mask it and a read must set it. */
#define SPI_READ 0x80u
#define SPI_WRITE_MASK 0x7Fu

/* One I2C transfer's patience. At 100 kHz a 26-byte burst needs ~2.6 ms, so
 * 8 ms covers the longest read with margin and still bounds a dead bus
 * tightly. */
#define BME_TIMEOUT_US 8000

bme280_t bme280_ambient = {
    .bus = BME280_BUS_I2C,
    .addr = BME_ADDR,
};

bme280_t bme280_chamber = {
    .bus = BME280_BUS_SPI,
    .cs_pin = PIN_BME_CHAMBER_CS,
};

/* ---- transport ----------------------------------------------------------- */

/* Chip select is driven manually, not by spi1's hardware CSn, and it is held
 * LOW across the whole address-then-data transaction. Hardware CSn on the
 * RP2350 deasserts between bytes, which the BME280 reads as the end of the
 * transaction: the burst would restart from the address register every byte
 * and return the same register over and over. */
static void cs_select(const bme280_t *dev)
{
    gpio_put(dev->cs_pin, 0);
}

static void cs_deselect(const bme280_t *dev)
{
    gpio_put(dev->cs_pin, 1);
}

static bool read_regs(bme280_t *dev, uint8_t reg, uint8_t *buf, size_t n)
{
    if (dev->bus == BME280_BUS_SPI) {
        uint8_t a = (uint8_t)(reg | SPI_READ);

        cs_select(dev);
        spi_write_blocking(spi1, &a, 1);
        spi_read_blocking(spi1, 0, buf, n);
        cs_deselect(dev);
        return true;
    }

    if (i2c_write_timeout_us(i2c0, dev->addr, &reg, 1, true,
                             BME_TIMEOUT_US) < 0)
        return false;
    return i2c_read_timeout_us(i2c0, dev->addr, buf, n, false,
                               BME_TIMEOUT_US) >= 0;
}

static bool write_reg(bme280_t *dev, uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = {reg, val};

    if (dev->bus == BME280_BUS_SPI) {
        buf[0] = (uint8_t)(reg & SPI_WRITE_MASK);
        cs_select(dev);
        spi_write_blocking(spi1, buf, 2);
        cs_deselect(dev);
        return true;
    }

    return i2c_write_timeout_us(i2c0, dev->addr, buf, 2, false,
                                BME_TIMEOUT_US) >= 0;
}

/* ---- compensation (datasheet 4.2.3) -------------------------------------- */

static int32_t compensate_t(bme280_t *dev, int32_t adc)
{
    int32_t v1 = ((((adc >> 3) - ((int32_t)dev->dig_T1 << 1))) *
                  (int32_t)dev->dig_T2) >>
                 11;
    int32_t v2 = (((((adc >> 4) - (int32_t)dev->dig_T1) *
                    ((adc >> 4) - (int32_t)dev->dig_T1)) >>
                   12) *
                  (int32_t)dev->dig_T3) >>
                 14;

    dev->t_fine = v1 + v2;
    return (dev->t_fine * 5 + 128) >> 8; /* centi-degC */
}

static uint32_t compensate_p(const bme280_t *dev, int32_t adc)
{
    int64_t v1, v2, p;

    v1 = (int64_t)dev->t_fine - 128000;
    v2 = v1 * v1 * (int64_t)dev->dig_P6;
    v2 = v2 + ((v1 * (int64_t)dev->dig_P5) << 17);
    v2 = v2 + (((int64_t)dev->dig_P4) << 35);
    v1 = ((v1 * v1 * (int64_t)dev->dig_P3) >> 8) +
         ((v1 * (int64_t)dev->dig_P2) << 12);
    v1 = ((((int64_t)1 << 47) + v1)) * ((int64_t)dev->dig_P1) >> 33;
    if (v1 == 0)
        return 0; /* datasheet: avoid the division by zero */
    p = 1048576 - adc;
    p = (((p << 31) - v2) * 3125) / v1;
    v1 = (((int64_t)dev->dig_P9) * (p >> 13) * (p >> 13)) >> 25;
    v2 = (((int64_t)dev->dig_P8) * p) >> 19;
    p = ((p + v1 + v2) >> 8) + (((int64_t)dev->dig_P7) << 4);
    return (uint32_t)(p / 256); /* Pa */
}

static uint32_t compensate_h(const bme280_t *dev, int32_t adc)
{
    int32_t v = dev->t_fine - 76800;

    v = (((((adc << 14) - (((int32_t)dev->dig_H4) << 20) -
            (((int32_t)dev->dig_H5) * v)) +
           16384) >>
          15) *
         (((((((v * (int32_t)dev->dig_H6) >> 10) *
              (((v * (int32_t)dev->dig_H3) >> 11) + 32768)) >>
             10) +
            2097152) *
               (int32_t)dev->dig_H2 +
           8192) >>
          14));
    v = v - (((((v >> 15) * (v >> 15)) >> 7) * (int32_t)dev->dig_H1) >> 4);
    if (v < 0)
        v = 0;
    if (v > 419430400)
        v = 419430400;
    return (uint32_t)(v >> 12); /* Q22.10 %RH */
}

/* ---- public -------------------------------------------------------------- */

bool bme280_init(bme280_t *dev)
{
    uint8_t id = 0, c1[26], c2[7];

    dev->ready = false;
    if (!read_regs(dev, REG_CHIP_ID, &id, 1) || id != BME_CHIP_ID)
        return false;
    if (!read_regs(dev, REG_CALIB_1, c1, sizeof c1) ||
        !read_regs(dev, REG_CALIB_2, c2, sizeof c2))
        return false;

    dev->dig_T1 = (uint16_t)(c1[0] | c1[1] << 8);
    dev->dig_T2 = (int16_t)(c1[2] | c1[3] << 8);
    dev->dig_T3 = (int16_t)(c1[4] | c1[5] << 8);
    dev->dig_P1 = (uint16_t)(c1[6] | c1[7] << 8);
    dev->dig_P2 = (int16_t)(c1[8] | c1[9] << 8);
    dev->dig_P3 = (int16_t)(c1[10] | c1[11] << 8);
    dev->dig_P4 = (int16_t)(c1[12] | c1[13] << 8);
    dev->dig_P5 = (int16_t)(c1[14] | c1[15] << 8);
    dev->dig_P6 = (int16_t)(c1[16] | c1[17] << 8);
    dev->dig_P7 = (int16_t)(c1[18] | c1[19] << 8);
    dev->dig_P8 = (int16_t)(c1[20] | c1[21] << 8);
    dev->dig_P9 = (int16_t)(c1[22] | c1[23] << 8);
    dev->dig_H1 = c1[25];
    dev->dig_H2 = (int16_t)(c2[0] | c2[1] << 8);
    dev->dig_H3 = c2[2];
    dev->dig_H4 = (int16_t)((c2[3] << 4) | (c2[4] & 0x0F));
    dev->dig_H5 = (int16_t)((c2[5] << 4) | (c2[4] >> 4));
    dev->dig_H6 = (int8_t)c2[6];

    /* humidity oversampling x1; temp/press oversampling x1 + normal mode;
     * 125 ms standby, which keeps a fresh sample waiting for a 1 Hz reader
     * without ever needing a delay here.
     *
     * CTRL_HUM must be written before CTRL_MEAS: the part latches the
     * humidity oversampling only on a CTRL_MEAS write (datasheet 5.4.3),
     * and the order below is that requirement, not a preference. */
    if (!write_reg(dev, REG_CTRL_HUM, 0x01) ||
        !write_reg(dev, REG_CTRL_MEAS, 0x27) ||
        !write_reg(dev, REG_CONFIG, 0x40))
        return false;

    dev->ready = true;
    return true;
}

bool bme280_read(bme280_t *dev, int16_t *temp_cc, uint16_t *rh_cpct,
                 uint32_t *p_pa)
{
    uint8_t raw[8];
    int32_t adc_p, adc_t, adc_h, tc;
    uint32_t pa, rh;

    if (!dev->ready || !read_regs(dev, REG_DATA, raw, sizeof raw))
        return false;

    adc_p = (int32_t)((raw[0] << 12) | (raw[1] << 4) | (raw[2] >> 4));
    adc_t = (int32_t)((raw[3] << 12) | (raw[4] << 4) | (raw[5] >> 4));
    adc_h = (int32_t)((raw[6] << 8) | raw[7]);

    /* 0x80000 in both slots is the reset value: conversion has never run. */
    if (adc_t == 0x80000 || adc_p == 0x80000)
        return false;

    tc = compensate_t(dev, adc_t); /* must run first: it sets t_fine */
    pa = compensate_p(dev, adc_p);
    rh = compensate_h(dev, adc_h);

    *temp_cc = (int16_t)tc;
    *p_pa = pa;
    *rh_cpct = (uint16_t)((rh * 100) >> 10); /* Q22.10 %RH -> centi-%RH */
    return true;
}
