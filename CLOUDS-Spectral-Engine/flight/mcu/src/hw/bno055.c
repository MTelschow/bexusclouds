/* BNO055 accel/gyro driver - see bno055.h for why the boot wait is the whole
 * point of this file. Register numbers, timings and the address table are from
 * BST-BNO055-DS000-18 rev 1.8 (October 2021); section numbers below are its. */
#include "bno055.h"

#include <string.h>

#include "hardware/i2c.h"

#include "board.h"

/* The address is DISCOVERED, not assumed.
 *
 * Datasheet Table 4-7: the default address is 0x29 (COM3 high) and 0x28 is the
 * *alternative*, selected only by pulling COM3 low. Table 4-6 gives COM3 a
 * 20-60 kOhm internal pull-up to VDDIO, so a COM3 left open reads high and the
 * part answers at 0x29.
 *
 * This file used to hardcode 0x28, on the strength of the 2026-08-31 survey
 * having found a part there. That is one board's strap written up as the
 * part's address: a BNO055 fitted with COM3 open or tied high would answer a
 * bus scan at 0x29 all day and be invisible to the flight build, which is
 * indistinguishable at the HK bit from the part being absent. Both addresses
 * are tried until one identifies, and the winner is latched. */
static const uint8_t BNO_ADDRS[2] = {0x29, 0x28};
static uint8_t bno_addr; /* 0 = not yet identified */

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
 * Worst case is six transfers a sweep, 60 ms, against the 2 s watchdog. */
#define BNO_TIMEOUT_US 10000

enum state {
    ST_POWER_WAIT,  /* waiting out the part's own start-up; bus untouched */
    ST_BOOT_WAIT,   /* reset issued, waiting out the 650 ms boot */
    ST_CONFIG_WAIT, /* CONFIGMODE requested, waiting out the 19 ms switch */
    ST_MODE_WAIT,   /* configured, waiting out the mode switch */
    ST_RUN,         /* identified, configured, delivering samples */
    ST_DOWN,        /* unusable; waiting to retry */
};

static enum state state;
static uint64_t due_ms;
static unsigned read_fails;

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

static void stand_down(uint64_t now_ms)
{
    state = ST_DOWN;
    due_ms = now_ms + RETRY_MS;
    read_fails = 0;
    /* Forget the address too. A part that stopped identifying may come back
     * on the other strap - a reseated module, a fitted part where there was
     * none - and a latched address would keep the retry looking in the one
     * place that has already failed. */
    bno_addr = 0;
}

/* RST_SYS, to the latched address if there is one and to both candidates if
 * there is not. The part stops acknowledging partway through its own reset,
 * so these writes are expected to fail as often as they succeed; their return
 * values say nothing about the hardware and are deliberately ignored. */
static void start_boot(uint64_t now_ms)
{
    if (bno_addr) {
        (void)write_reg(bno_addr, REG_SYS_TRIGGER, SYS_TRIGGER_RESET);
    } else {
        for (unsigned i = 0; i < 2; i++)
            (void)write_reg(BNO_ADDRS[i], REG_SYS_TRIGGER, SYS_TRIGGER_RESET);
    }
    state = ST_BOOT_WAIT;
    due_ms = now_ms + BOOT_MS;
    read_fails = 0;
}

/* The ID block, read as one burst once the boot has had its full time. This
 * is the measurement the 2026-08-31 survey took too early.
 *
 * Doubles as the address probe: whichever candidate returns a whole ID block
 * is the part, and it is latched for every transfer afterwards. An ACK alone
 * would not do - 0x28 and 0x29 are ordinary addresses another part could hold
 * - so the identity is what decides, as it does in ina226.c.
 *
 * MAG_ID is deliberately not required: this driver never uses the
 * magnetometer, and refusing to deliver acceleration because a sensor nobody
 * reads is unhappy would be its own kind of invented failure. */
static bool identify(void)
{
    for (unsigned i = 0; i < 2; i++) {
        uint8_t addr = bno_addr ? bno_addr : BNO_ADDRS[i];
        uint8_t id[4];

        if (read_regs(addr, REG_CHIP_ID, id, sizeof id) &&
            id[0] == CHIP_ID && id[1] == ACC_ID && id[3] == GYR_ID) {
            bno_addr = addr;
            return true;
        }
        if (bno_addr)
            break; /* already latched: do not wander to the other address */
    }
    return false;
}

/* Ask for CONFIGMODE. Writable in any mode (3.3.1), which is what makes this
 * the one write that may be issued before the 19 ms wait rather than after. */
static bool enter_config(void)
{
    return write_reg(bno_addr, REG_PAGE_ID, 0x00) &&
           write_reg(bno_addr, REG_OPR_MODE, OPR_CONFIG);
}

/* The CONFIGMODE-only writes, issued once the switch has had its 19 ms.
 * Order matters: OPR_MODE goes last, because it is what leaves CONFIGMODE. */
static bool configure(void)
{
    return write_reg(bno_addr, REG_PWR_MODE, PWR_NORMAL) &&
           write_reg(bno_addr, REG_SYS_TRIGGER, SYS_TRIGGER_INTERNAL_CLK) &&
           write_reg(bno_addr, REG_UNIT_SEL, UNIT_SEL_VALUE) &&
           write_reg(bno_addr, REG_OPR_MODE, OPR_ACCGYRO);
}

static int16_t le16(const uint8_t *p)
{
    return (int16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static bool read_vectors(int16_t accel_mg[3], int16_t gyro_ddps[3])
{
    uint8_t acc[6], gyr[6];

    if (!read_regs(bno_addr, REG_ACC_DATA, acc, sizeof acc))
        return false;
    if (!read_regs(bno_addr, REG_GYR_DATA, gyr, sizeof gyr))
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

void bno055_init(uint64_t now_ms)
{
    state = ST_POWER_WAIT;
    due_ms = now_ms + POWER_UP_MS;
    read_fails = 0;
    bno_addr = 0;
}

uint8_t bno055_address(void)
{
    return bno_addr;
}

bool bno055_read(uint64_t now_ms, int16_t accel_mg[3], int16_t gyro_ddps[3])
{
    switch (state) {
    case ST_POWER_WAIT:
        /* Nothing is on the bus yet on purpose: TSup has to elapse before the
         * part can acknowledge anything, and a reset it cannot hear is worse
         * than no reset - it starts the boot timer against a boot that never
         * happened. */
        if (now_ms < due_ms)
            return false;
        start_boot(now_ms);
        return false;

    case ST_BOOT_WAIT:
        if (now_ms < due_ms)
            return false;
        /* The one place the fitted-but-faulted verdict may be pronounced:
         * after a reset this driver issued and a boot it timed. */
        if (!identify() || !enter_config()) {
            stand_down(now_ms);
            return false;
        }
        state = ST_CONFIG_WAIT;
        due_ms = now_ms + CONFIG_SWITCH_MS;
        return false;

    case ST_CONFIG_WAIT:
        if (now_ms < due_ms)
            return false;
        if (!configure()) {
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
        if (!read_regs(bno_addr, REG_OPR_MODE, &mode, 1) ||
            mode != OPR_ACCGYRO) {
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
