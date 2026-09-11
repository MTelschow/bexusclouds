/* INA226 rail monitors on I2C0 (M-09): V_in, 5 V and 3.3 V rails.
 *
 * The hk_t rail arrays carry a fourth rail, 24 V, whose monitor is not fitted
 * on the carrier yet. It is not an error: ina226_fitted() says which rails
 * the design populates, so an empty slot downlinks RAIL_MV_INVALID without
 * raising HKE_RAIL_FAIL, the way an absent part is reported everywhere else
 * in this HK packet.
 *
 * Confirmed on the CLOUDS carrier at 0x40 / 0x44 / 0x45 (DEVLOG 2026-08-31),
 * identified by their manufacturer and die IDs rather than by answering at a
 * default address - guessing parts from addresses got four of five wrong on
 * this board.
 *
 * **Absolute registers only, deliberately.** Both registers this driver
 * reads are absolute and need no configuration beyond averaging: bus voltage
 * at 1.25 mV/LSB, and shunt voltage at 2.5 uV/LSB signed. The part's own
 * current and power registers are NOT - it computes them from a calibration
 * register that has to be programmed with the shunt resistance, and a wrong
 * shunt there produces confident, wrong amps with nothing on the ground able
 * to undo them. So the calibration register is left alone, the raw shunt
 * voltage goes down the link, and Ohm's law is applied on the ground where
 * the resistances live (clouds_link/hk.py RAIL_SHUNT_MOHM: 10, 15, 50, 50
 * mOhm) -
 * a logged session stays re-derivable if one of those values is wrong.
 *
 * Nothing here sleeps or spins: every transfer carries a timeout, so a wedged
 * bus costs a bounded number of microseconds and reports failure rather than
 * stalling the 1 Hz loop into the 2 s watchdog (S.9).
 */
#ifndef CLOUDS_INA226_H
#define CLOUDS_INA226_H

#include <stdbool.h>
#include <stdint.h>

#include "../core/frame.h"

/* Rail order, and the index into hk_t.rail_mv. INA_RAIL_24V has no part
 * fitted; it holds its place in the wire schema (RAIL_COUNT in
 * core/frame.h). */
enum ina226_rail {
    INA_RAIL_VIN = 0,
    INA_RAIL_24V = 1,
    INA_RAIL_5V = 2,
    INA_RAIL_3V3 = 3,
    INA_RAIL_COUNT = RAIL_COUNT,
};

/* RAIL_MV_INVALID - the "no reading" value for hk_t.rail_mv - is part of the
 * wire schema and lives in core/frame.h with the rest of it.
 */

/* True where the carrier populates a monitor for that rail. A rail that is
 * not fitted has no reading and no fault: it is left out of HKE_RAIL_FAIL,
 * which exists for a part that should have answered and did not. */
bool ina226_fitted(enum ina226_rail rail);

/* Probes every fitted monitor and sets them to average 16 samples (~8.5 ms per
 * conversion, so a sample is always waiting and reads never block). Returns
 * the number of rails that answered with a valid INA226 identity; 0 means
 * none, and every later ina226_read_bus_mv() then reports failure. Never
 * sleeps. */
unsigned ina226_init(void);

/* Latest bus voltage for one rail, in mV. Returns false if that monitor is
 * absent or the transfer failed, leaving *mv untouched. Never sleeps. */
bool ina226_read_bus_mv(enum ina226_rail rail, uint16_t *mv);

/* Latest shunt-voltage register for one rail, raw: signed, 2.5 uV/LSB. Not
 * converted here - the shunt resistance is a ground-side constant, see the
 * note above. Returns false if that monitor is absent or the transfer failed,
 * leaving *raw untouched. Never sleeps. */
bool ina226_read_shunt_raw(enum ina226_rail rail, int16_t *raw);

#endif
