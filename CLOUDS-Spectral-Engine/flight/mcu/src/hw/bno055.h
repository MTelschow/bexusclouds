/* BNO055 inertial sensor on I2C0 (M-09): accelerometer and gyroscope.
 *
 * The part is run in ACCGYRO (0x05), a non-fusion mode: raw accelerometer and
 * gyroscope, no magnetometer, no sensor fusion. hk_t carries accel_mg and
 * gyro_ddps and nothing else, the gondola's iron and the motor's field make a
 * magnetometer heading worthless here, and every fusion mode needs a
 * calibration the flight has no opportunity to perform. Launch and float
 * detection (core/autonomy.c) wants acceleration, not attitude.
 *
 * Everything below cites BST-BNO055-DS000-18 rev 1.8 (October 2021).
 *
 * **Two parts, two fixed addresses.** Table 4-7 makes 0x29 the default and
 * 0x28 the alternative reached by pulling COM3 low; Table 4-6 puts a 20-60
 * kOhm internal pull-up on COM3, so a COM3 left open is 0x29. The ambient
 * IMU is at 0x29, the chamber IMU at 0x28 (COM3 low), both on i2c0. One
 * bno055_t per part, each bound to its own address - the driver used to try
 * both and latch whichever answered, which with two parts fitted would claim
 * the wrong one. A part strapped to the other address reads as absent, so
 * src/tools/bno055_probe.c, which scans both, is what settles the strap.
 *
 * **Two boot numbers, not one.** Table 0-2 gives TSup = 400 ms "From Off to
 * configuration mode" *and* TPOR = 650 ms "From Reset to Config mode". Only
 * the second was honoured. The IMU shares the MCU's 3V3 rail, so hw_init()
 * runs inside the part's TSup: the RST_SYS write issued there went to a part
 * that could not acknowledge it, no reset happened, and the 650 ms timer was
 * measured from an instant that meant nothing. The driver now touches the bus
 * for the first time only after TSup, and times TPOR from a reset it issued
 * to a part that was awake to hear it.
 *
 * **The 19 ms is honoured too.** Table 3-6: 7 ms CONFIGMODE -> operation mode,
 * but 19 ms the other way, and 3.3.1 says only OPR_MODE and the interrupt
 * registers are writable outside CONFIGMODE. The old configure() wrote
 * OPR_MODE = CONFIG and then PWR_MODE, SYS_TRIGGER and UNIT_SEL back to back,
 * inside that window, where the part accepts them on the wire and drops them.
 * The mode read-back caught the result and called it a failure; the cause was
 * this file.
 *
 * **Why the boot wait exists at all.** The 2026-08-31 survey found the part
 * answering with a genuine CHIP_ID (0xA0), SW_REV (0x0311) and BL_REV (0x15)
 * while ACC_ID / MAG_ID / GYR_ID all read 0x00, and wrote it up as an
 * internally faulted package. Those reads were taken within milliseconds of
 * MCU boot. The constants that read correctly are the ones the ROM and
 * bootloader serve immediately; the three that read 0x00 are exactly the ones
 * written by the boot sequence when it brings the accel, mag and gyro dies up.
 * Reading them at t=0 cannot distinguish "dead die" from "not booted yet".
 *
 * That hypothesis is still untested: on 2026-09-11 the part did not answer on
 * i2c0 at either address (0/50 ACK at 0x28 and 0x29 while the BME280 and all
 * three INA226 answered in the same sweep), so there is nothing on the bus to
 * test it against. It stays the first thing to re-check when a part is fitted.
 *
 * The driver is written so that it does not matter which way that falls: if
 * the dies really are dead the ID check fails, HKE_IMU_FAIL is raised exactly
 * as before and the vectors stay zero. Nothing invents a number. What changes
 * is that the flag now reports a measurement taken at a time, and at an
 * address, where the answer means something.
 *
 * Never reads above register 0x6A. The page-0 map ends there, and the earlier
 * probe's reads at 0xFE/0xFF are what provoked the SYS_ERR 0x05 ("register map
 * address out of range") that the next pass then read back as evidence of a
 * boot failure.
 *
 * Nothing here sleeps or spins. The 400 ms start-up, the 650 ms boot, the
 * 19 ms and the 7 ms mode switches are waited out across calls to
 * bno055_read() from the 1 Hz sweep - five sweeps to a first sample on a
 * healthy part - so one that is slow, absent or wedged costs a bounded number
 * of microseconds per pass and never pushes the loop towards the 2 s watchdog
 * (S.9).
 */
#ifndef CLOUDS_BNO055_H
#define CLOUDS_BNO055_H

#include <stdbool.h>
#include <stdint.h>

#define BNO055_ADDR_AMBIENT 0x29 /* COM3 high or open: datasheet default */
#define BNO055_ADDR_CHAMBER 0x28 /* COM3 pulled low: the alternative */

enum bno055_state {
    ST_POWER_WAIT,  /* waiting out the part's own start-up; bus untouched */
    ST_BOOT_WAIT,   /* reset issued, waiting out the 650 ms boot */
    ST_CONFIG_WAIT, /* CONFIGMODE requested, waiting out the 19 ms switch */
    ST_MODE_WAIT,   /* configured, waiting out the mode switch */
    ST_RUN,         /* identified, configured, delivering samples */
    ST_DOWN,        /* unusable; waiting to retry */
};

/* One per fitted part. Set addr, then bno055_init(); everything else is the
 * driver's. */
typedef struct {
    uint8_t addr;
    enum bno055_state state;
    uint64_t due_ms;
    unsigned read_fails;
    bool identified; /* ID block read back since the last reset */
} bno055_t;

/* Arms the bring-up. Writes NOTHING to the bus: the part is still inside its
 * 400 ms start-up when hw_init() runs, so the first transfer - the reset that
 * starts the 650 ms boot - is issued from bno055_read() once that has
 * elapsed. There is therefore no hardware verdict to return here, and none is
 * returned: the first honest one is the ID check after the boot. */
void bno055_init(bno055_t *dev, uint64_t now_ms);

/* The two parts on i2c0. Defined in bno055.c. */
extern bno055_t bno055_ambient; /* BNO055_ADDR_AMBIENT, HKE_IMU_FAIL */
extern bno055_t bno055_chamber; /* BNO055_ADDR_CHAMBER, HKE_IMU_CHM_FAIL */

/* True once the part has returned a whole ID block since its last reset.
 * Diagnostics only - nothing in the flight path branches on it. */
bool bno055_identified(const bno055_t *dev);

/* Latest sample, or false while the part is booting, being configured,
 * unusable, or waiting to be retried. Outputs are untouched when false.
 *   accel_mg    milli-g, one LSB per mg (UNIT_SEL)
 *   gyro_ddps   deci-degrees per second, converted from the part's 16 LSB/dps
 * Must be called periodically even while it returns false: the bring-up and
 * the retry after a failure are driven from here. Never sleeps. */
bool bno055_read(bno055_t *dev, uint64_t now_ms, int16_t accel_mg[3],
                 int16_t gyro_ddps[3]);

#endif
