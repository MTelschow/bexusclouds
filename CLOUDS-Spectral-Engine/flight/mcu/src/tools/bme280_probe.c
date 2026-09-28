/* BME280 bring-up probe - a BENCH TOOL, not flight software.
 *
 * Built as its own target (bme280_probe), never linked into clouds_fsw_mcu.
 * It exists because HKE_BME280_CHM_FAIL is one bit, and one bit cannot say
 * whether the chamber part is on another chip select, wants another SPI
 * mode, or was wired to i2c0 instead.
 *
 * Output is USB CDC only; UART stdio stays off (uart0 is the HK downlink).
 *
 * hw_init() runs first because it drives every actuator line low and brings
 * up i2c0 and spi1. No actuator is commanded below.
 *
 * FIRST it checks the bus can carry a transaction at all (added 2026-09-28,
 * after a run where every chip select read 0x00 because GP8 was held low):
 *   (a) MISO with a pull-up, one chip select asserted at a time - a release
 *       on exactly one select means a part is fitted there, and points the
 *       blame at SCK/MOSI rather than MISO;
 *   (b) each bus pin driven high and low and read back at the pad - the
 *       meter-free "is GP8 shorted to ground" test;
 *   (c) the three bus pins cross-driven, to find a tied pair.
 * Read those three before the chip-id table: the table is meaningless while
 * MISO cannot idle high.
 *
 * Then, every second, it reads CHIP_ID (0xD0, expect 0x60) from:
 *   - spi1 behind each of the four SPI_1 chip selects (GP9, GP12, GP13,
 *     GP47), in mode 0 and in mode 3, at 100 kHz and at SPI1_BAUD_HZ;
 *   - i2c0 at 0x76 and 0x77.
 * and prints the whole table when it changes, so a part can be plugged or
 * reseated while watching.
 */
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "hardware/gpio.h"
#include "hardware/i2c.h"
#include "hardware/spi.h"
#include "pico/stdlib.h"

#include "../hw/board.h"
#include "../hw/hw.h"

#define REG_CHIP_ID 0xD0
#define BME_CHIP_ID 0x60
#define TIMEOUT_US 8000
#define WATCH_S 120u

static const uint8_t CS_PINS[] = {9, 12, 13, 47};
static const uint8_t I2C_ADDRS[] = {0x76, 0x77};
static const unsigned BAUDS[] = {100 * 1000, SPI1_BAUD_HZ};

static uint8_t spi_chip_id(uint8_t cs, bool mode3, unsigned baud)
{
    uint8_t a = REG_CHIP_ID | 0x80u, id = 0;

    spi_set_baudrate(spi1, baud);
    spi_set_format(spi1, 8, mode3 ? SPI_CPOL_1 : SPI_CPOL_0,
                   mode3 ? SPI_CPHA_1 : SPI_CPHA_0, SPI_MSB_FIRST);
    gpio_put(cs, 0);
    spi_write_blocking(spi1, &a, 1);
    spi_read_blocking(spi1, 0, &id, 1);
    gpio_put(cs, 1);
    return id;
}

static int i2c_chip_id(uint8_t addr)
{
    uint8_t reg = REG_CHIP_ID, id = 0;

    if (i2c_write_timeout_us(i2c0, addr, &reg, 1, true, TIMEOUT_US) < 0)
        return -1;
    if (i2c_read_timeout_us(i2c0, addr, &id, 1, false, TIMEOUT_US) < 0)
        return -1;
    return id;
}

/* Bit-banged mode-0 read with an arbitrary MOSI/MISO pair, so a harness
 * with SDI and SDO crossed is found too. spi1 is released from the pins for
 * the duration and handed back afterwards. */
static uint8_t bb_chip_id(uint8_t cs, uint8_t mosi, uint8_t miso)
{
    uint8_t a = REG_CHIP_ID | 0x80u, id = 0;
    const uint8_t pins[3] = {PIN_SPI1_MISO, PIN_SPI1_SCK, PIN_SPI1_MOSI};

    for (int i = 0; i < 3; i++)
        gpio_init(pins[i]);
    gpio_set_dir(PIN_SPI1_SCK, GPIO_OUT);
    gpio_put(PIN_SPI1_SCK, 0);
    gpio_set_dir(mosi, GPIO_OUT);
    gpio_set_dir(miso, GPIO_IN);
    gpio_put(cs, 0);
    busy_wait_us(5);
    for (int i = 7; i >= 0; i--) {
        gpio_put(mosi, (a >> i) & 1);
        busy_wait_us(5);
        gpio_put(PIN_SPI1_SCK, 1);
        busy_wait_us(5);
        gpio_put(PIN_SPI1_SCK, 0);
    }
    gpio_put(mosi, 0);
    for (int i = 7; i >= 0; i--) {
        busy_wait_us(5);
        gpio_put(PIN_SPI1_SCK, 1);
        id |= (uint8_t)(gpio_get(miso) << i);
        busy_wait_us(5);
        gpio_put(PIN_SPI1_SCK, 0);
    }
    gpio_put(cs, 1);
    for (int i = 0; i < 3; i++)
        gpio_set_function(pins[i], GPIO_FUNC_SPI);
    return id;
}

/* ---- bus integrity tests (2026-09-28) -----------------------------------
 *
 * Added after the run that found GP8 reading 0 with its own pull-up on and
 * every chip select high. The chip-id table below cannot tell the candidate
 * causes apart, and it cannot tell a dead MISO from a dead MOSI either: a
 * part that never receives its register address answers 0x00 just like a part
 * that is not there.
 *
 * THE RULE THESE TESTS LEARNED THE HARD WAY: every pin not under test must be
 * a high-impedance input for the duration. The first version of this code
 * handed the others back to GPIO_FUNC_SPI between steps, which means the SPI
 * PERIPHERAL drives SCK and MOSI - so on a bus where the lines turn out to be
 * tied together, the peripheral's idle levels showed up as "held low" and as
 * phantom shorts. Park them, or measure the peripheral instead of the board.
 *
 * Each condition is sampled several times, because the reading that started
 * this was not stable: the same pin, same configuration, read 0 in one block
 * and 1 in the next. An unstable pin is itself a result, so it is reported
 * rather than averaged away.
 *
 * All of this is reads and pin toggles on the SPI_1 bus only. No actuator
 * line is touched and no chip select is left asserted.
 */

#define BUS_SAMPLES 5

static const uint8_t BUS_PINS[] = {PIN_SPI1_MISO, PIN_SPI1_SCK, PIN_SPI1_MOSI};

/* High-impedance input, no pull: the pin is neither driven by us nor by the
 * SPI peripheral, so it cannot contaminate a measurement on a pin it may be
 * shorted to. */
static void bus_park(uint8_t pin)
{
    gpio_init(pin);
    gpio_set_dir(pin, GPIO_IN);
    gpio_disable_pulls(pin);
}

static void bus_park_all(void)
{
    for (size_t i = 0; i < sizeof BUS_PINS; i++)
        bus_park(BUS_PINS[i]);
}

/* Hands the bus back to spi1 so the chip-id table below still works. */
static void bus_restore_all(void)
{
    for (size_t i = 0; i < sizeof BUS_PINS; i++) {
        gpio_set_dir(BUS_PINS[i], GPIO_IN);
        gpio_pull_down(BUS_PINS[i]);
        gpio_set_function(BUS_PINS[i], GPIO_FUNC_SPI);
    }
}

/* Samples a pin BUS_SAMPLES times. Returns 0 or 1 if every sample agreed, or
 * -1 if the pin changed under us - which is a finding, not noise. */
static int bus_sample(uint8_t pin)
{
    int first;

    busy_wait_us(200);
    first = gpio_get(pin);
    for (int i = 1; i < BUS_SAMPLES; i++) {
        busy_wait_us(200);
        if (gpio_get(pin) != first)
            return -1;
    }
    return first;
}

static const char *bus_level(int v)
{
    return v < 0 ? "UNSTABLE" : (v ? "1" : "0");
}

/* (a) Does asserting a chip select CHANGE what MISO reads?
 *
 * MISO leaving hi-Z when a select is asserted is what a PRESENT device does.
 * The test is the CHANGE against the idle baseline, not the level: with a
 * pull-up an idle bus already reads 1, so "reads 1 while CS is low" on its own
 * says nothing. The first version of this test flagged exactly that and
 * claimed all four selects had a part behind them.
 */
static void miso_release_per_cs(void)
{
    int idle;

    printf("-- (a) does a chip select change what MISO GP8 reads? --\n");
    bus_park_all();
    gpio_pull_up(PIN_SPI1_MISO);
    idle = bus_sample(PIN_SPI1_MISO);
    printf("     baseline, all CS high, pull-up:  %s   "
           "(an idle bus must read 1)\n", bus_level(idle));

    for (size_t c = 0; c < sizeof CS_PINS; c++) {
        int low, back;

        gpio_put(CS_PINS[c], 0);
        low = bus_sample(PIN_SPI1_MISO);
        gpio_put(CS_PINS[c], 1);
        back = bus_sample(PIN_SPI1_MISO);
        printf("     CS GP%-2u low: %-8s  released: %-8s%s\n",
               CS_PINS[c], bus_level(low), bus_level(back),
               (low >= 0 && idle >= 0 && low != idle)
                   ? "   <-- CHANGED: something is on this select"
                   : "");
    }
    bus_restore_all();
}

/* (b) Can each bus pin be driven both ways at the pad?
 *
 * Drives the pin and reads the pad back, which on the RP2350 reports the
 * ACTUAL level - so a pin that cannot be pulled high is held by something
 * low-impedance. This is the meter-free version of "GP8 to GND resistance":
 * a hard short reads 0 while driven high; an external pull-down of a few
 * kOhm loses to the driver and reads 1. The weakest drive strength is used
 * and each level is held for well under a millisecond, so a genuine short
 * costs the pad very little.
 *
 * Chip selects are left HIGH and the other two bus pins are parked hi-Z, so
 * neither a fitted part nor our own SPI block is fighting the driver.
 */
static void pin_drive_test(void)
{
    printf("-- (b) can each SPI_1 pin be driven high and low at the pad? --\n");
    for (size_t c = 0; c < sizeof CS_PINS; c++)
        gpio_put(CS_PINS[c], 1);
    bus_park_all();

    for (size_t i = 0; i < sizeof BUS_PINS; i++) {
        uint8_t pin = BUS_PINS[i];
        int hi, lo;

        gpio_set_dir(pin, GPIO_OUT);
        gpio_set_drive_strength(pin, GPIO_DRIVE_STRENGTH_2MA);
        gpio_put(pin, 1);
        hi = bus_sample(pin);
        gpio_put(pin, 0);
        lo = bus_sample(pin);
        bus_park(pin);
        printf("     GP%-2u driven high: %-8s  driven low: %-8s%s%s\n",
               pin, bus_level(hi), bus_level(lo),
               (hi == 0) ? "   <-- HELD LOW, cannot drive it high" : "",
               (lo == 1) ? "   <-- HELD HIGH, cannot drive it low" : "");
    }
    bus_restore_all();
}

/* (c) Are any two bus pins shorted together?
 *
 * Drives one and watches the others, with the victim's pull set AGAINST the
 * driven level so a float cannot be mistaken for a short: driving high, a
 * pulled-down victim that reads 1 is tied to the driver. The third pin stays
 * parked hi-Z - if it were left on the SPI peripheral it would drive the net
 * and invent shorts, which is what the first version of this test did.
 *
 * Only the three bus pins are cross-tested. The chip selects stay driven
 * outputs rather than being floated into inputs: floating a select can let a
 * fitted part see a spurious assertion, and test (a) covers select-to-MISO
 * shorts from the driving side.
 */
static void cross_short_test(void)
{
    bool found = false;

    printf("-- (c) are any two SPI_1 bus pins tied together? --\n");
    bus_park_all();

    for (size_t d = 0; d < sizeof BUS_PINS; d++) {
        uint8_t drv = BUS_PINS[d];

        for (int level = 1; level >= 0; level--) {
            gpio_set_dir(drv, GPIO_OUT);
            gpio_set_drive_strength(drv, GPIO_DRIVE_STRENGTH_2MA);
            gpio_put(drv, level);

            for (size_t v = 0; v < sizeof BUS_PINS; v++) {
                uint8_t vic = BUS_PINS[v];
                int got;

                if (vic == drv)
                    continue;
                if (level)
                    gpio_pull_down(vic);
                else
                    gpio_pull_up(vic);
                got = bus_sample(vic);
                gpio_disable_pulls(vic);
                if (got == level) {
                    printf("     GP%-2u driven %d -> GP%-2u follows it"
                           "   <-- TIED TOGETHER\n", drv, level, vic);
                    found = true;
                }
            }
            bus_park(drv);
        }
    }
    if (!found)
        printf("     none: each pin moves on its own\n");
    /* READ THIS BEFORE BELIEVING ANY LINE ABOVE.
     *
     * On an RP2350 a FLOATING pad does not read as a clean float: this
     * project has already measured one latching high against its own
     * internal pull-down (2026-09-11, sensor-driver/pico_bringup). A latched
     * high-impedance input can also be nudged by activity on a neighbouring
     * pin through a few pF, which reads here as "TIED TOGETHER" when nothing
     * is tied at all.
     *
     * So (b) and (c) only mean something once the net is known NOT to be
     * floating. If the harness is unplugged or the part is unpowered, expect
     * exactly the output above and do not chase a short. Settle it
     * physically: unplug the sensor harness and re-run - a result that does
     * not change was never about the sensor - or fit an external 10k pull-up
     * to GP8 and see whether it then reads 1 and drives both ways. */
    printf("     NOTE: (b) and (c) are only meaningful if these pins are\n"
           "     NOT floating. An unconnected RP2350 pad latches and couples\n"
           "     to its neighbours, which reads exactly like a short.\n"
           "     Confirm the harness is plugged in and the part is powered\n"
           "     before chasing one.\n");
    bus_restore_all();
}

static void scan(char *out, size_t len)
{
    size_t n = 0;

    out[0] = '\0';
    /* Pads default to pull-down, so an undriven MISO reads 0x00. With a
     * pull-up it reads 0xFF instead - that separates "nothing drives MISO"
     * from "a part drives it low". */
    gpio_pull_up(PIN_SPI1_MISO);
    n += (size_t)snprintf(out + n, len - n,
                          "  MISO GP8 pulled up, CS GP9 mode 0: 0x%02X\n",
                          spi_chip_id(9, false, BAUDS[0]));
    gpio_pull_down(PIN_SPI1_MISO);
    for (size_t c = 0; c < sizeof CS_PINS; c++) {
        uint8_t id = bb_chip_id(CS_PINS[c], PIN_SPI1_MISO, PIN_SPI1_MOSI);

        n += (size_t)snprintf(out + n, len - n,
                              "  bitbang CS GP%-2u MOSI/MISO SWAPPED: 0x%02X%s\n",
                              CS_PINS[c], id,
                              id == BME_CHIP_ID ? "  <-- BME280" : "");
    }
    n += (size_t)snprintf(out + n, len - n, "  i2c0 ACK:");
    for (uint8_t a = 0x08; a < 0x78; a++) {
        uint8_t d;

        if (i2c_read_timeout_us(i2c0, a, &d, 1, false, TIMEOUT_US) >= 0)
            n += (size_t)snprintf(out + n, len - n, " 0x%02X", a);
    }
    n += (size_t)snprintf(out + n, len - n, "\n");
    for (size_t c = 0; c < sizeof CS_PINS; c++)
        for (int m = 0; m < 2; m++)
            for (size_t b = 0; b < sizeof BAUDS / sizeof BAUDS[0]; b++) {
                uint8_t id = spi_chip_id(CS_PINS[c], m, BAUDS[b]);

                n += (size_t)snprintf(out + n, len - n,
                                      "  spi1 CS GP%-2u mode %d %4u kHz: "
                                      "0x%02X%s\n",
                                      CS_PINS[c], m ? 3 : 0, BAUDS[b] / 1000,
                                      id, id == BME_CHIP_ID ? "  <-- BME280"
                                                            : "");
            }
    for (size_t i = 0; i < sizeof I2C_ADDRS; i++) {
        int id = i2c_chip_id(I2C_ADDRS[i]);

        if (id < 0)
            n += (size_t)snprintf(out + n, len - n, "  i2c0 0x%02X: NACK\n",
                                  I2C_ADDRS[i]);
        else
            n += (size_t)snprintf(out + n, len - n, "  i2c0 0x%02X: 0x%02X%s\n",
                                  I2C_ADDRS[i], id,
                                  id == BME_CHIP_ID ? "  <-- BME280" : "");
    }
}

int main(void)
{
    static char prev[4096], now[4096];

    stdio_init_all();
    hw_init(); /* actuators low; i2c0 + spi1 up, all four SPI_1 CS high */

    /* Every candidate chip select idles high, so only one part is ever
     * selected at a time. hw_init() parks all four before its first clock
     * edge (spi1_park_chip_selects); this loop restates it where the tool
     * reads it, because an undriven RP2350 pad is a pulled-down input and an
     * active-low select left there is asserted. */
    for (size_t c = 0; c < sizeof CS_PINS; c++) {
        gpio_init(CS_PINS[c]);
        gpio_set_dir(CS_PINS[c], GPIO_OUT);
        gpio_put(CS_PINS[c], 1);
    }

    while (!stdio_usb_connected())
        sleep_ms(100);
    sleep_ms(500);

    printf("\n=== BME280 probe (bench tool) ===\n");
    {
        uint8_t reg = 0x88, c[26];

        if (i2c_write_timeout_us(i2c0, 0x76, &reg, 1, true, TIMEOUT_US) >= 0 &&
            i2c_read_timeout_us(i2c0, 0x76, c, 26, false, TIMEOUT_US) >= 0)
            printf("i2c0 0x76 trim: dig_T1=%u dig_P1=%u dig_H1=%u "
                   "(ambient DEVLOG 2026-08-31: 28323 37257 75)\n",
                   c[0] | c[1] << 8, c[6] | c[7] << 8, c[25]);
        /* GP10 and GP11 are parked hi-Z first, not left on the SPI
         * peripheral. Until 2026-09-28 they were not, and this block
         * reported GP8 low on a bus whose pins turned out to be coupled -
         * it was measuring our own MOSI idling low through that coupling,
         * and it disagreed with test (a) a few lines further down. A pin
         * measurement is only about the board if nothing else is driving. */
        bus_park(PIN_SPI1_SCK);
        bus_park(PIN_SPI1_MOSI);
        bus_park(PIN_SPI1_MISO);
        gpio_pull_up(PIN_SPI1_MISO);
        sleep_ms(1);
        printf("GP8 (MISO) as input, pull-up, all CS high: %d\n",
               gpio_get(PIN_SPI1_MISO));
        gpio_put(9, 0);
        sleep_ms(1);
        printf("GP8 (MISO) as input, pull-up, GP9 low:     %d\n",
               gpio_get(PIN_SPI1_MISO));
        gpio_put(9, 1);
        bus_restore_all();
    }

    /* Bus integrity before the chip-id table, because the table cannot be
     * read at all until these three pass: every chip select returns 0x00
     * when MISO is held low, and that looks exactly like an absent part. */
    miso_release_per_cs();
    pin_drive_test();
    cross_short_test();

    printf("-- watching for %u s (plug/reseat now) --\n", WATCH_S);
    for (unsigned t = 0; t < WATCH_S; t++) {
        scan(now, sizeof now);
        if (strcmp(now, prev) != 0) {
            printf("t=%3u s:\n%s", t, now);
            memcpy(prev, now, sizeof prev);
        }
        sleep_ms(1000);
    }
    printf("=== done ===\n");
    for (;;)
        sleep_ms(1000);
}
