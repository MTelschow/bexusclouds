/* BNO055 accel/gyro driver - see bno055.h for why the boot wait is the whole
 * point of this file. */
#include "bno055.h"

#include <string.h>

#include "hardware/i2c.h"

#include "board.h"

#define BNO_ADDR 0x28 /* COM3 low. Measured here, not assumed (DEVLOG). */

/* Page-0 registers. Nothing in this file addresses above 0x3F, well inside
 * the 0x6A end of the page-0 map. */
#define REG_CHIP_ID 0x00
#define REG_ACC_ID 0x01
#define REG_MAG_ID 0x02
#define REG_GYR_ID 0x03
#define REG_PAGE_ID 0x07
#define REG_ACC_DATA 0x08 /* 6 bytes, X/Y/Z LSB-first */
#define REG_GYR_DATA 0x14 /* 6 bytes, same layout */
#define REG_UNIT_SEL 0x3B
#define REG_OPR_MODE 0x3D
#define REG_PWR_MODE 0x3E
#define REG_SYS_TRIGGER 0x3F

#define CHIP_ID 0xA0
#define ACC_ID 0xFB
#define MAG_ID 0x32
#define GYR_ID 0x0F

#define OPR_CONFIG 0x00
#define OPR_ACCGYRO 0x05 /* accel + gyro, no mag, no fusion */
#define PWR_NORMAL 0x00

/* UNIT_SEL: bit0 = 1 -> accel in mg (1 LSB = 1 mg), bit1 = 0 -> gyro in dps
 * (16 LSB = 1 dps), bit7 = 0 -> Windows orientation. Everything else default.
 * Choosing mg is what makes accel_mg a copy rather than a conversion; the
 * gyro has no deci-dps unit, so that one is converted below. */
#define UNIT_SEL_VALUE 0x01

/* SYS_TRIGGER: bit5 RST_SYS resets the system, bit7 CLK_SEL selects an
 * external crystal. Writing 0x00 after the reset is deliberate - a missing or
 * non-oscillating 32.768 kHz crystal with CLK_SEL asserted is the classic
 * cause of exactly the signature this board showed, and the carrier's crystal
 * is unconfirmed. The internal oscillator is always present. */
#define SYS_TRIGGER_RESET 0x20
#define SYS_TRIGGER_INTERNAL_CLK 0x00

/* Datasheet 3.3: 650 ms from power-on reset to config mode. 750 ms gives the
 * slowest part margin and still costs one 1 Hz sweep. */
#define BOOT_MS 750u
/* Datasheet 3.3.1: 7 ms CONFIG -> operation mode. 30 ms is margin; it is
 * waited out between two calls, not slept through. */
#define MODE_SWITCH_MS 30u
/* How long a part that failed bring-up is left alone before the next attempt.
 * Slow on purpose: an IMU is not on the release path (S.7, MS002), and
 * hammering a wedged device every second buys nothing and costs bus time. */
#define RETRY_MS 30000u
/* Consecutive read failures that force a full re-reset. Three 1 Hz sweeps is
 * long enough that a single bus glitch does not tear down a working part. */
#define MAX_READ_FAILS 3u

/* One transfer's patience. A 6-byte burst at 100 kHz is ~0.7 ms; 4 ms covers
 * it with margin and bounds a dead bus tightly, as in ina226.c. */
#define BNO_TIMEOUT_US 4000

enum state {
    ST_BOOT_WAIT,   /* reset issued, waiting out the 650 ms boot */
    ST_MODE_WAIT,   /* configured, waiting out the mode switch */
    ST_RUN,         /* identified, configured, delivering samples */
    ST_DOWN,        /* unusable; waiting to retry */
};

static enum state state;
static uint64_t due_ms;
static unsigned read_fails;

static bool read_regs(uint8_t reg, uint8_t *buf, size_t n)
{
    if (i2c_write_timeout_us(i2c0, BNO_ADDR, &reg, 1, true, BNO_TIMEOUT_US) < 0)
        return false;
    return i2c_read_timeout_us(i2c0, BNO_ADDR, buf, n, false,
                               BNO_TIMEOUT_US) >= 0;
}

static bool write_reg(uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = {reg, val};

    return i2c_write_timeout_us(i2c0, BNO_ADDR, buf, 2, false,
                                BNO_TIMEOUT_US) >= 0;
}

static void stand_down(uint64_t now_ms)
{
    state = ST_DOWN;
    due_ms = now_ms + RETRY_MS;
    read_fails = 0;
}

static void start_boot(uint64_t now_ms)
{
    /* The part stops acknowledging partway through its own reset, so this
     * write is expected to fail as often as it succeeds. Its return value
     * says nothing about the hardware and is deliberately ignored. */
    (void)write_reg(REG_SYS_TRIGGER, SYS_TRIGGER_RESET);
    state = ST_BOOT_WAIT;
    due_ms = now_ms + BOOT_MS;
    read_fails = 0;
}

/* The ID block, read as one burst once the boot has had its full time. This
 * is the measurement the 2026-08-31 survey took too early.
 *
 * MAG_ID is deliberately not required: this driver never uses the
 * magnetometer, and refusing to deliver acceleration because a sensor nobody
 * reads is unhappy would be its own kind of invented failure. */
static bool identify(void)
{
    uint8_t id[4];

    if (!read_regs(REG_CHIP_ID, id, sizeof id))
        return false;
    return id[0] == CHIP_ID && id[1] == ACC_ID && id[3] == GYR_ID;
}

static bool configure(void)
{
    /* Order matters: the part is in CONFIGMODE after a reset, and PWR_MODE,
     * UNIT_SEL and SYS_TRIGGER are only writable there. OPR_MODE goes last. */
    return write_reg(REG_PAGE_ID, 0x00) &&
           write_reg(REG_OPR_MODE, OPR_CONFIG) &&
           write_reg(REG_PWR_MODE, PWR_NORMAL) &&
           write_reg(REG_SYS_TRIGGER, SYS_TRIGGER_INTERNAL_CLK) &&
           write_reg(REG_UNIT_SEL, UNIT_SEL_VALUE) &&
           write_reg(REG_OPR_MODE, OPR_ACCGYRO);
}

static int16_t le16(const uint8_t *p)
{
    return (int16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static bool read_vectors(int16_t accel_mg[3], int16_t gyro_ddps[3])
{
    uint8_t acc[6], gyr[6];

    if (!read_regs(REG_ACC_DATA, acc, sizeof acc))
        return false;
    if (!read_regs(REG_GYR_DATA, gyr, sizeof gyr))
        return false;

    for (unsigned i = 0; i < 3; i++) {
        /* Accel is already mg per LSB from UNIT_SEL. Gyro is 16 LSB/dps and
         * the wire field is deci-dps, so x10/16 = x5/8, in 32-bit: at the
         * +-2000 dps full scale the numerator reaches 160000. */
        accel_mg[i] = le16(&acc[2 * i]);
        gyro_ddps[i] = (int16_t)(((int32_t)le16(&gyr[2 * i]) * 5) / 8);
    }
    return true;
}

bool bno055_init(uint64_t now_ms)
{
    bool acked = write_reg(REG_SYS_TRIGGER, SYS_TRIGGER_RESET);

    state = ST_BOOT_WAIT;
    due_ms = now_ms + BOOT_MS;
    read_fails = 0;
    return acked;
}

bool bno055_read(uint64_t now_ms, int16_t accel_mg[3], int16_t gyro_ddps[3])
{
    switch (state) {
    case ST_BOOT_WAIT:
        if (now_ms < due_ms)
            return false;
        /* The one place the fitted-but-faulted verdict may be pronounced:
         * after a reset this driver issued and a boot it timed. */
        if (!identify() || !configure()) {
            stand_down(now_ms);
            return false;
        }
        state = ST_MODE_WAIT;
        due_ms = now_ms + MODE_SWITCH_MS;
        return false;

    case ST_MODE_WAIT: {
        uint8_t mode = 0;

        if (now_ms < due_ms)
            return false;
        /* Read the mode back rather than assume the write took: a part whose
         * dies never came up can accept the write and sit in CONFIGMODE,
         * where the data registers are all zero - which is precisely the
         * reading this driver must never pass off as a measurement. */
        if (!read_regs(REG_OPR_MODE, &mode, 1) || mode != OPR_ACCGYRO) {
            stand_down(now_ms);
            return false;
        }
        state = ST_RUN;
        return false;
    }

    case ST_RUN:
        if (read_vectors(accel_mg, gyro_ddps)) {
            read_fails = 0;
            return true;
        }
        /* A single failed transfer is a bus glitch, not a dead IMU. Only a
         * run of them is worth a re-reset, which costs another boot. */
        if (++read_fails >= MAX_READ_FAILS)
            start_boot(now_ms);
        return false;

    case ST_DOWN:
    default:
        if (now_ms >= due_ms)
            start_boot(now_ms);
        return false;
    }
}
