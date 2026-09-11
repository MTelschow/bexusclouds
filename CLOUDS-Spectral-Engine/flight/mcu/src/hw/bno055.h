/* BNO055 inertial sensor on I2C0 at 0x28 (M-09): accelerometer and gyroscope.
 *
 * The part is run in ACCGYRO (0x05), a non-fusion mode: raw accelerometer and
 * gyroscope, no magnetometer, no sensor fusion. hk_t carries accel_mg and
 * gyro_ddps and nothing else, the gondola's iron and the motor's field make a
 * magnetometer heading worthless here, and every fusion mode needs a
 * calibration the flight has no opportunity to perform. Launch and float
 * detection (core/autonomy.c) wants acceleration, not attitude.
 *
 * **Why this exists at all.** The 2026-08-31 survey found the part fitted and
 * answering with a genuine CHIP_ID (0xA0), SW_REV (0x0311) and BL_REV (0x15)
 * while ACC_ID / MAG_ID / GYR_ID all read 0x00, and wrote it up as an
 * internally faulted package. Those reads were taken from a probe that ran
 * within milliseconds of MCU boot, and the BNO055 needs 650 ms from power-on
 * reset before it is configured: the constants that read correctly are the
 * ones its ROM and bootloader serve immediately, and the three that read 0x00
 * are exactly the ones written by the boot sequence when it brings the accel,
 * mag and gyro dies up. Reading them at t=0 cannot distinguish "dead die"
 * from "not booted yet", and the probe never waited. So this driver resets the
 * part deliberately, waits out the full boot, and only then reads the IDs.
 *
 * That hypothesis is still untested: on 2026-09-11 the part stopped answering
 * on i2c0 altogether (0/50 ACK at 0x28 and 0x29 while the BME280 and all three
 * INA226 answered in the same sweep), so there is nothing on the bus to test
 * it against. It stays the first thing to re-check when a part is fitted.
 *
 * The driver is written so that it does not matter which way that falls: if the dies really
 * are dead the ID check fails, HKE_IMU_FAIL is raised exactly as before and
 * the vectors stay zero. Nothing invents a number. What changes is that the
 * flag now reports a measurement taken at a time when the answer means
 * something.
 *
 * Never reads above register 0x6A. The page-0 map ends there, and the earlier
 * probe's reads at 0xFE/0xFF are what provoked the SYS_ERR 0x05 ("register map
 * address out of range") that the next pass then read back as evidence of a
 * boot failure.
 *
 * Nothing here sleeps or spins. The 650 ms boot and the 30 ms mode switch are
 * waited out across calls to bno055_read() from the 1 Hz sweep, so a part that
 * is slow, absent or wedged costs a bounded number of microseconds per pass
 * and never pushes the loop towards the 2 s watchdog (S.9).
 */
#ifndef CLOUDS_BNO055_H
#define CLOUDS_BNO055_H

#include <stdbool.h>
#include <stdint.h>

/* Starts the bring-up: issues a system reset and arms the boot timer. Does
 * not talk to the part beyond that write and does not wait for it, so a
 * missing or wedged IMU cannot slow hw_init(). Returns whether the reset
 * write was acknowledged, which is not yet evidence the part works - during
 * the reset itself the BNO055 stops acknowledging, so a NACK here is normal
 * and bring-up continues regardless. */
bool bno055_init(uint64_t now_ms);

/* Latest sample, or false while the part is booting, being configured,
 * unusable, or waiting to be retried. Outputs are untouched when false.
 *   accel_mg    milli-g, one LSB per mg (UNIT_SEL)
 *   gyro_ddps   deci-degrees per second, converted from the part's 16 LSB/dps
 * Must be called periodically even while it returns false: the bring-up and
 * the retry after a failure are driven from here. Never sleeps. */
bool bno055_read(uint64_t now_ms, int16_t accel_mg[3], int16_t gyro_ddps[3]);

#endif
