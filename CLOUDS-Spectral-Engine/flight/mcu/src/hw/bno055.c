/* BNO055 accel/gyro driver - see bno055.h for why the boot wait is the whole
 * point of this file. Register numbers, timings and the address table are from
 * BST-BNO055-DS000-18 rev 1.8 (October 2021); section numbers below are its. */
#include "bno055.h"

#include <string.h>

#include "hardware/i2c.h"

#include "board.h"

/* Two parts share i2c0 and the address is what tells them apart.
 *
 * Datasheet Table 4-7: the default address is 0x29 (COM3 high) and 0x28 is the
 * *alternative*, selected by pulling COM3 low. Table 4-6 gives COM3 a 20-60
 * kOhm internal pull-up, so a COM3 left open reads high and answers at 0x29.
 * The ambient part sits at 0x29 and the chamber part at 0x28 (bno055.h
 * BNO055_ADDR_*). Each instance talks only to its own address: with both
 * fitted, an instance that went looking at the other address would identify
 * the other part and downlink its readings under the wrong name. */

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
#define OPR_ACCGYRO 0x05 /* accel + gyro, no mag, no fusion (3.3.2.4) */
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

/* Table 0-2, TSup: 400 ms from Off to CONFIGMODE. This is a SEPARATE number
 * from TPOR below and it is the one this driver used to ignore. The IMU and
 * the MCU come up on the same 3V3 rail, so hw_init() runs while the BNO055 is
 * still inside its own start-up: the RST_SYS write issued there was addressed
 * to a part that could not acknowledge it, no reset ever happened, and the
 * boot timer was then measured from the wrong instant. Nothing is written to
 * the bus until this has elapsed. 500 ms carries the margin. */
#define POWER_UP_MS 500u
/* Table 0-2, TPOR: 650 ms from reset to CONFIGMODE. 750 ms gives the slowest
 * part margin and still costs one 1 Hz sweep. */
#define BOOT_MS 750u
/* Table 3-6: 19 ms from any operation mode to CONFIGMODE. Only OPR_MODE and
 * the interrupt registers are writable outside CONFIGMODE (3.3.1), so the
 * PWR_MODE / SYS_TRIGGER / UNIT_SEL writes must not be issued inside this
 * window - they would be accepted on the wire and dropped by the part. 25 ms
 * is margin; it is waited out between two calls, not slept through. */
#define CONFIG_SWITCH_MS 25u
/* Table 3-6: 7 ms CONFIGMODE -> operation mode. 30 ms is margin. */
#define MODE_SWITCH_MS 30u
/* How long a part that failed bring-up is left alone before the next attempt.
 * Slow on purpose: an IMU is not on the release path (S.7, MS002), and
 * hammering a wedged device every second buys nothing and costs bus time. */
#define RETRY_MS 30000u
/* Consecutive read failures that force a full re-reset. Three 1 Hz sweeps is
 * long enough that a single bus glitch does not tear down a working part. */
#define MAX_READ_FAILS 3u

/* One transfer's patience. Section 4.6: "The BNO055 I2C interface uses clock
 * stretching" - it is the only part on this bus that does, and a stretched
 * byte is not a failed one. A 6-byte burst at 100 kHz is ~0.7 ms unstretched;
 * 10 ms leaves the part room to hold SCL and still bounds a dead bus tightly.
 * Worst case is six transfers a sweep per part, 120 ms for both, against the
 * 2 s watchdog. */
#define BNO_TIMEOUT_US 10000

bno055_t bno055_ambient = {.addr = BNO055_ADDR_AMBIENT};
bno055_t bno055_chamber = {.addr = BNO055_ADDR_CHAMBER};

static bool read_regs(uint8_t addr, uint8_t reg, uint8_t *buf, size_t n)
{
    if (i2c_write_timeout_us(i2c0, addr, &reg, 1, true, BNO_TIMEOUT_US) < 0)
        return false;
    return i2c_read_timeout_us(i2c0, addr, buf, n, false, BNO_TIMEOUT_US) >= 0;
}

static bool write_reg(uint8_t addr, uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = {reg, val};

    return i2c_write_timeout_us(i2c0, addr, buf, 2, false, BNO_TIMEOUT_US) >= 0;
}

static void stand_down(bno055_t *dev, uint64_t now_ms)
{
    dev->state = ST_DOWN;
    dev->due_ms = now_ms + RETRY_MS;
    dev->read_fails = 0;
    dev->identified = false;
}

/* RST_SYS. The part stops acknowledging partway through its own reset, so
 * this write is expected to fail as often as it succeeds; its return value
 * says nothing about the hardware and is deliberately ignored. */
static void start_boot(bno055_t *dev, uint64_t now_ms)
{
    (void)write_reg(dev->addr, REG_SYS_TRIGGER, SYS_TRIGGER_RESET);
    dev->identified = false;
    dev->state = ST_BOOT_WAIT;
    dev->due_ms = now_ms + BOOT_MS;
    dev->read_fails = 0;
}

/* The ID block, read as one burst once the boot has had its full time. This
 * is the measurement the 2026-08-31 survey took too early.
 *
 * An ACK alone would not do - 0x28 and 0x29 are ordinary addresses another
 * part could hold - so the identity is what decides, as it does in ina226.c.
 *
 * MAG_ID is deliberately not required: this driver never uses the
 * magnetometer, and refusing to deliver acceleration because a sensor nobody
 * reads is unhappy would be its own kind of invented failure. */
static bool identify(bno055_t *dev)
{
    uint8_t id[4];

    dev->identified = read_regs(dev->addr, REG_CHIP_ID, id, sizeof id) &&
                      id[0] == CHIP_ID && id[1] == ACC_ID &&
                      id[3] == GYR_ID;
    return dev->identified;
}

/* Ask for CONFIGMODE. Writable in any mode (3.3.1), which is what makes this
 * the one write that may be issued before the 19 ms wait rather than after. */
static bool enter_config(uint8_t addr)
{
    return write_reg(addr, REG_PAGE_ID, 0x00) &&
           write_reg(addr, REG_OPR_MODE, OPR_CONFIG);
}

/* The CONFIGMODE-only writes, issued once the switch has had its 19 ms.
 * Order matters: OPR_MODE goes last, because it is what leaves CONFIGMODE. */
static bool configure(uint8_t addr)
{
    return write_reg(addr, REG_PWR_MODE, PWR_NORMAL) &&
           write_reg(addr, REG_SYS_TRIGGER, SYS_TRIGGER_INTERNAL_CLK) &&
           write_reg(addr, REG_UNIT_SEL, UNIT_SEL_VALUE) &&
           write_reg(addr, REG_OPR_MODE, OPR_ACCGYRO);
}

static int16_t le16(const uint8_t *p)
{
    return (int16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static bool read_vectors(uint8_t addr, int16_t accel_mg[3], int16_t gyro_ddps[3])
{
    uint8_t acc[6], gyr[6];

    if (!read_regs(addr, REG_ACC_DATA, acc, sizeof acc))
        return false;
    if (!read_regs(addr, REG_GYR_DATA, gyr, sizeof gyr))
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

void bno055_init(bno055_t *dev, uint64_t now_ms)
{
    dev->state = ST_POWER_WAIT;
    dev->due_ms = now_ms + POWER_UP_MS;
    dev->read_fails = 0;
    dev->identified = false;
}

bool bno055_identified(const bno055_t *dev)
{
    return dev->identified;
}

bool bno055_read(bno055_t *dev, uint64_t now_ms, int16_t accel_mg[3],
                 int16_t gyro_ddps[3])
{
    switch (dev->state) {
    case ST_POWER_WAIT:
        /* Nothing is on the bus yet on purpose: TSup has to elapse before the
         * part can acknowledge anything, and a reset it cannot hear is worse
         * than no reset - it starts the boot timer against a boot that never
         * happened. */
        if (now_ms < dev->due_ms)
            return false;
        start_boot(dev, now_ms);
        return false;

    case ST_BOOT_WAIT:
        if (now_ms < dev->due_ms)
            return false;
        /* The one place the fitted-but-faulted verdict may be pronounced:
         * after a reset this driver issued and a boot it timed. */
        if (!identify(dev) || !enter_config(dev->addr)) {
            stand_down(dev, now_ms);
            return false;
        }
        dev->state = ST_CONFIG_WAIT;
        dev->due_ms = now_ms + CONFIG_SWITCH_MS;
        return false;

    case ST_CONFIG_WAIT:
        if (now_ms < dev->due_ms)
            return false;
        if (!configure(dev->addr)) {
            stand_down(dev, now_ms);
            return false;
        }
        dev->state = ST_MODE_WAIT;
        dev->due_ms = now_ms + MODE_SWITCH_MS;
        return false;

    case ST_MODE_WAIT: {
        uint8_t mode = 0;

        if (now_ms < dev->due_ms)
            return false;
        /* Read the mode back rather than assume the write took: a part whose
         * dies never came up can accept the write and sit in CONFIGMODE,
         * where the data registers are all zero - which is precisely the
         * reading this driver must never pass off as a measurement. */
        if (!read_regs(dev->addr, REG_OPR_MODE, &mode, 1) ||
            mode != OPR_ACCGYRO) {
            stand_down(dev, now_ms);
            return false;
        }
        dev->state = ST_RUN;
        return false;
    }

    case ST_RUN:
        if (read_vectors(dev->addr, accel_mg, gyro_ddps)) {
            dev->read_fails = 0;
            return true;
        }
        /* A single failed transfer is a bus glitch, not a dead IMU. Only a
         * run of them is worth a re-reset, which costs another boot. */
        if (++dev->read_fails >= MAX_READ_FAILS)
            start_boot(dev, now_ms);
        return false;

    case ST_DOWN:
    default:
        if (now_ms >= dev->due_ms)
            start_boot(dev, now_ms);
        return false;
    }
}
