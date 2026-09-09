/* INA226 rail monitors - see ina226.h for why this reads the two absolute
 * registers and leaves the calibration register alone. */
#include "ina226.h"

#include "hardware/i2c.h"

#include "board.h"

#define REG_CONFIG 0x00
#define REG_SHUNT_V 0x01
#define REG_BUS_V 0x02
#define REG_MFG_ID 0xFE
#define REG_DIE_ID 0xFF

#define INA_MFG_ID 0x5449 /* "TI" */
#define INA_DIE_ID 0x2260

/* Averaging 16, 1.1 ms conversion on both channels, continuous mode:
 * AVG=010, VSHCT=100, VBUSCT=100, MODE=111. ~8.5 ms per averaged sample, so a
 * fresh one is always waiting and a read is a single register fetch. */
#define INA_CONFIG 0x4527u

/* One transfer's patience. A 2-byte register read at 100 kHz is ~0.4 ms; 4 ms
 * covers it with margin and still bounds a dead bus tightly. Three rails at
 * this timeout is 12 ms worst case against a 2 s watchdog. */
#define INA_TIMEOUT_US 4000

/* No part on that rail. 0x00 is the I2C general-call address and can never be
 * a monitor's own, so it cannot collide with a real one. */
#define INA_ADDR_NONE 0x00

/* Mirrors RAIL_I2C_ADDR in clouds_link/hk.py. The 24 V monitor is not fitted
 * on the carrier yet - see ina226.h. */
static const uint8_t addr_of[INA_RAIL_COUNT] = {0x40, INA_ADDR_NONE, 0x44,
                                                0x45};
static bool present[INA_RAIL_COUNT];

static bool read_reg(uint8_t addr, uint8_t reg, uint16_t *out)
{
    uint8_t buf[2];

    if (i2c_write_timeout_us(i2c0, addr, &reg, 1, true, INA_TIMEOUT_US) < 0)
        return false;
    if (i2c_read_timeout_us(i2c0, addr, buf, 2, false, INA_TIMEOUT_US) < 0)
        return false;
    /* INA226 registers are big-endian on the wire, unlike the BME280's. */
    *out = (uint16_t)((buf[0] << 8) | buf[1]);
    return true;
}

static bool write_reg(uint8_t addr, uint8_t reg, uint16_t val)
{
    uint8_t buf[3] = {reg, (uint8_t)(val >> 8), (uint8_t)(val & 0xFF)};

    return i2c_write_timeout_us(i2c0, addr, buf, 3, false,
                                INA_TIMEOUT_US) >= 0;
}

unsigned ina226_init(void)
{
    unsigned found = 0;

    for (unsigned i = 0; i < INA_RAIL_COUNT; i++) {
        uint16_t mfg, die;

        present[i] = false;
        if (addr_of[i] == INA_ADDR_NONE)
            continue;       /* no part on this rail - not a failure */
        /* An ACK is not an identity. Both ID registers must match, because
         * four of five parts on this bus were mis-identified from their
         * default addresses alone. */
        if (!read_reg(addr_of[i], REG_MFG_ID, &mfg) || mfg != INA_MFG_ID)
            continue;
        if (!read_reg(addr_of[i], REG_DIE_ID, &die) || die != INA_DIE_ID)
            continue;
        if (!write_reg(addr_of[i], REG_CONFIG, INA_CONFIG))
            continue;
        present[i] = true;
        found++;
    }
    return found;
}

bool ina226_fitted(enum ina226_rail rail)
{
    return rail < INA_RAIL_COUNT && addr_of[rail] != INA_ADDR_NONE;
}

bool ina226_read_bus_mv(enum ina226_rail rail, uint16_t *mv)
{
    uint16_t raw;

    if (rail >= INA_RAIL_COUNT || !present[rail])
        return false;
    if (!read_reg(addr_of[rail], REG_BUS_V, &raw))
        return false;
    /* 1.25 mV/LSB, absolute - no calibration register involved. The register
     * is 15-bit, so the top bit is always clear and raw * 5 / 4 cannot
     * overflow u16: 0x7FFF -> 40959 mV. */
    *mv = (uint16_t)((uint32_t)(raw & 0x7FFFu) * 5u / 4u);
    return true;
}

bool ina226_read_shunt_raw(enum ina226_rail rail, int16_t *raw)
{
    uint16_t reg;

    if (rail >= INA_RAIL_COUNT || !present[rail])
        return false;
    if (!read_reg(addr_of[rail], REG_SHUNT_V, &reg))
        return false;
    /* Two's complement over the full 16 bits, 2.5 uV/LSB: the register is
     * signed because current can flow either way through the shunt, and a
     * negative reading is real data (a rail sourcing back into the supply),
     * not an error to clamp away. Cast via the u16 the wire gave us rather
     * than arithmetic, so the sign comes from the bits and not from an
     * implementation-defined shift. */
    *raw = (int16_t)reg;
    return true;
}
