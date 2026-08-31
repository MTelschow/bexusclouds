/* BME280 driver (M-09). Compensation is the datasheet fixed-point reference
 * (section 4.2.3); it was validated against this board before being committed:
 * 29.17 degC / 99396 Pa / 41.15 %RH on the bench, calibration dig_T1=28323,
 * dig_P1=37257, dig_H1=75. See DEVLOG 2026-08-31.
 *
 * Nothing here sleeps or spins: every transfer carries a timeout, so a wedged
 * bus costs a bounded number of microseconds and reports failure rather than
 * stalling the 1 Hz loop into the 2 s watchdog (S.9).
 */
#include "bme280.h"

#include "hardware/i2c.h"

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

/* One transfer's patience. At 100 kHz a 26-byte burst needs ~2.6 ms, so 8 ms
 * covers the longest read with margin and still bounds a dead bus tightly. */
#define BME_TIMEOUT_US 8000

static uint16_t dig_T1, dig_P1;
static int16_t dig_T2, dig_T3;
static int16_t dig_P2, dig_P3, dig_P4, dig_P5, dig_P6, dig_P7, dig_P8, dig_P9;
static uint8_t dig_H1, dig_H3;
static int16_t dig_H2, dig_H4, dig_H5;
static int8_t dig_H6;

static bool ready;
static int32_t t_fine; /* carries temperature into the P and H compensation */

static bool read_regs(uint8_t reg, uint8_t *buf, size_t n)
{
    if (i2c_write_timeout_us(i2c0, BME_ADDR, &reg, 1, true, BME_TIMEOUT_US) < 0)
        return false;
    return i2c_read_timeout_us(i2c0, BME_ADDR, buf, n, false,
                               BME_TIMEOUT_US) >= 0;
}

static bool write_reg(uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = {reg, val};

    return i2c_write_timeout_us(i2c0, BME_ADDR, buf, 2, false,
                                BME_TIMEOUT_US) >= 0;
}

static int32_t compensate_t(int32_t adc)
{
    int32_t v1 = ((((adc >> 3) - ((int32_t)dig_T1 << 1))) * (int32_t)dig_T2) >>
                 11;
    int32_t v2 = (((((adc >> 4) - (int32_t)dig_T1) *
                    ((adc >> 4) - (int32_t)dig_T1)) >>
                   12) *
                  (int32_t)dig_T3) >>
                 14;

    t_fine = v1 + v2;
    return (t_fine * 5 + 128) >> 8; /* centi-degC */
}

static uint32_t compensate_p(int32_t adc)
{
    int64_t v1, v2, p;

    v1 = (int64_t)t_fine - 128000;
    v2 = v1 * v1 * (int64_t)dig_P6;
    v2 = v2 + ((v1 * (int64_t)dig_P5) << 17);
    v2 = v2 + (((int64_t)dig_P4) << 35);
    v1 = ((v1 * v1 * (int64_t)dig_P3) >> 8) + ((v1 * (int64_t)dig_P2) << 12);
    v1 = ((((int64_t)1 << 47) + v1)) * ((int64_t)dig_P1) >> 33;
    if (v1 == 0)
        return 0; /* datasheet: avoid the division by zero */
    p = 1048576 - adc;
    p = (((p << 31) - v2) * 3125) / v1;
    v1 = (((int64_t)dig_P9) * (p >> 13) * (p >> 13)) >> 25;
    v2 = (((int64_t)dig_P8) * p) >> 19;
    p = ((p + v1 + v2) >> 8) + (((int64_t)dig_P7) << 4);
    return (uint32_t)(p / 256); /* Pa */
}

static uint32_t compensate_h(int32_t adc)
{
    int32_t v = t_fine - 76800;

    v = (((((adc << 14) - (((int32_t)dig_H4) << 20) -
            (((int32_t)dig_H5) * v)) +
           16384) >>
          15) *
         (((((((v * (int32_t)dig_H6) >> 10) *
              (((v * (int32_t)dig_H3) >> 11) + 32768)) >>
             10) +
            2097152) *
               (int32_t)dig_H2 +
           8192) >>
          14));
    v = v - (((((v >> 15) * (v >> 15)) >> 7) * (int32_t)dig_H1) >> 4);
    if (v < 0)
        v = 0;
    if (v > 419430400)
        v = 419430400;
    return (uint32_t)(v >> 12); /* Q22.10 %RH */
}

bool bme280_init(void)
{
    uint8_t id = 0, c1[26], c2[7];

    ready = false;
    if (!read_regs(REG_CHIP_ID, &id, 1) || id != BME_CHIP_ID)
        return false;
    if (!read_regs(REG_CALIB_1, c1, sizeof c1) ||
        !read_regs(REG_CALIB_2, c2, sizeof c2))
        return false;

    dig_T1 = (uint16_t)(c1[0] | c1[1] << 8);
    dig_T2 = (int16_t)(c1[2] | c1[3] << 8);
    dig_T3 = (int16_t)(c1[4] | c1[5] << 8);
    dig_P1 = (uint16_t)(c1[6] | c1[7] << 8);
    dig_P2 = (int16_t)(c1[8] | c1[9] << 8);
    dig_P3 = (int16_t)(c1[10] | c1[11] << 8);
    dig_P4 = (int16_t)(c1[12] | c1[13] << 8);
    dig_P5 = (int16_t)(c1[14] | c1[15] << 8);
    dig_P6 = (int16_t)(c1[16] | c1[17] << 8);
    dig_P7 = (int16_t)(c1[18] | c1[19] << 8);
    dig_P8 = (int16_t)(c1[20] | c1[21] << 8);
    dig_P9 = (int16_t)(c1[22] | c1[23] << 8);
    dig_H1 = c1[25];
    dig_H2 = (int16_t)(c2[0] | c2[1] << 8);
    dig_H3 = c2[2];
    dig_H4 = (int16_t)((c2[3] << 4) | (c2[4] & 0x0F));
    dig_H5 = (int16_t)((c2[5] << 4) | (c2[4] >> 4));
    dig_H6 = (int8_t)c2[6];

    /* humidity oversampling x1; temp/press oversampling x1 + normal mode;
     * 125 ms standby, which keeps a fresh sample waiting for a 1 Hz reader
     * without ever needing a delay here. */
    if (!write_reg(REG_CTRL_HUM, 0x01) || !write_reg(REG_CTRL_MEAS, 0x27) ||
        !write_reg(REG_CONFIG, 0x40))
        return false;

    ready = true;
    return true;
}

bool bme280_read(int16_t *temp_cc, uint16_t *rh_cpct, uint32_t *p_pa)
{
    uint8_t raw[8];
    int32_t adc_p, adc_t, adc_h, tc;
    uint32_t pa, rh;

    if (!ready || !read_regs(REG_DATA, raw, sizeof raw))
        return false;

    adc_p = (int32_t)((raw[0] << 12) | (raw[1] << 4) | (raw[2] >> 4));
    adc_t = (int32_t)((raw[3] << 12) | (raw[4] << 4) | (raw[5] >> 4));
    adc_h = (int32_t)((raw[6] << 8) | raw[7]);

    /* 0x80000 in both slots is the reset value: conversion has never run. */
    if (adc_t == 0x80000 || adc_p == 0x80000)
        return false;

    tc = compensate_t(adc_t); /* must run first: it sets t_fine */
    pa = compensate_p(adc_p);
    rh = compensate_h(adc_h);

    *temp_cc = (int16_t)tc;
    *p_pa = pa;
    *rh_cpct = (uint16_t)((rh * 100) >> 10); /* Q22.10 %RH -> centi-%RH */
    return true;
}
