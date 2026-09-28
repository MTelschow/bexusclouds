/* BMV080 bring-up probe - a BENCH TOOL, not flight software.
 *
 * Built as its own target (bmv080_probe), never linked into clouds_fsw_mcu.
 * It exists because PM_FAIL is one bit, and one bit cannot say whether the
 * particulate sensor is on another chip select, wired with SDI and SDO
 * crossed, missing one of its four supply rails, or latched into I2C because
 * its PS pin floated high at power-up.
 *
 * Output is USB CDC only; UART stdio stays off (uart0 is the HK downlink).
 *
 * hw_init() runs first because it drives every actuator line low and brings
 * up i2c0 and spi1. It also opens the sensor itself, so the first thing this
 * tool does afterwards is close it again - the probing below wants the bus to
 * itself. No actuator is commanded here.
 *
 * What it reports, in order:
 *   1. the vendor library's version. This runs library code and needs no
 *      sensor, so it separates a broken link from a broken build.
 *   2. a raw 16-bit SPI read on each free SPI_1 chip select (GP12, GP13,
 *      GP47) with three tx patterns, at SPI1_BAUD_HZ and at 4 MHz. All-0xFFFF
 *      means nothing is driving MISO; all-0x0000 usually means the same with
 *      the pad pulled the other way.
 *   3. bmv080_open() on each of those selects, printing the vendor status.
 *      107 (E_BMV080_ERROR_MISMATCH_CHIP_ID) is the "cannot talk to it at
 *      all" answer and is what the 2026-09-11 bench run got on a bare Pico 2.
 *   4. for the first select that answers: the 13-character sensor id, the
 *      four readable parameters, and then PM lines until reset.
 *
 * The part's own constraints worth remembering while reading the output:
 *   - the first reading is ~1.9 s after the measurement starts, then one per
 *     ~1.03 s. Silence for two seconds is normal.
 *   - the specified operating range is +15..+65 degC and the datasheet wants
 *     it on a heatsink. On a cold bench it may answer and misbehave.
 *   - a sensor might read high for its first 24 hours of operation (vendor
 *     burst-noise note), so an implausible first number is not a fault yet.
 */
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "hardware/gpio.h"
#include "hardware/spi.h"
#include "pico/stdlib.h"

#include "bmv080.h" /* the vendor API */

#include "../hw/bmv080_dev.h"
#include "../hw/bmv080_port.h"
#include "../hw/board.h"
#include "../hw/hw.h"

/* The three SPI_1 selects the chamber BME280 does not use. GP9 is deliberately
 * absent: pulling it low drives the BME280's CSB, and a BME280 answering a
 * 16-bit BMV080 transaction would be noise, not evidence. */
static const uint8_t CS_PINS[] = {12, 13, 47};

static const uint16_t TX_PATTERNS[] = {0x0000u, 0xFFFFu, 0xA5A5u};
static const unsigned BAUDS[] = {SPI1_BAUD_HZ, 4000u * 1000u};

static unsigned readings;

/* A raw transaction with no vendor library involved: send one 16-bit word,
 * read four back. There is no register map to aim at, so the point is not the
 * value - it is whether MISO moves at all, and whether it moves differently
 * for different tx patterns (which would mean it is echoing MOSI through a
 * short or a swapped harness). */
static void raw_probe(uint8_t cs, uint16_t tx, unsigned baud, uint16_t out[4])
{
    uint16_t hdr = tx;
    uint16_t resp = 0;

    spi_set_baudrate(spi1, baud);
    spi_set_format(spi1, 16, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);
    gpio_put(cs, 0);
    (void)spi_write16_read16_blocking(spi1, &hdr, &resp, 1);
    (void)spi_read16_blocking(spi1, tx, out, 4);
    gpio_put(cs, 1);
    out[0] = resp;
}

static void raw_scan(void)
{
    printf("-- raw 16-bit SPI, no vendor library --\n");
    for (size_t c = 0; c < sizeof CS_PINS; c++)
        for (size_t b = 0; b < sizeof BAUDS / sizeof BAUDS[0]; b++)
            for (size_t t = 0; t < sizeof TX_PATTERNS / sizeof TX_PATTERNS[0];
                 t++) {
                uint16_t w[4] = {0};

                raw_probe(CS_PINS[c], TX_PATTERNS[t], BAUDS[b], w);
                printf("  CS GP%-2u %5u kHz tx 0x%04X: %04X %04X %04X %04X%s\n",
                       CS_PINS[c], BAUDS[b] / 1000, TX_PATTERNS[t],
                       w[0], w[1], w[2], w[3],
                       (w[1] == 0xFFFFu && w[2] == 0xFFFFu)
                           ? "   (MISO undriven)"
                           : "");
            }
    spi_set_baudrate(spi1, SPI1_BAUD_HZ);
}

static void on_data_ready(bmv080_output_t out, void *params)
{
    (void)params;
    readings++;
    printf("  t=%7.2f s  PM1 %6.1f  PM2.5 %6.1f  PM10 %6.1f ug/m3   "
           "#PM1 %6.1f #PM2.5 %6.1f #PM10 %6.1f /cm3   "
           "obstructed=%s  out_of_range=%s\n",
           (double)out.runtime_in_sec, (double)out.pm1_mass_concentration,
           (double)out.pm2_5_mass_concentration,
           (double)out.pm10_mass_concentration,
           (double)out.pm1_number_concentration,
           (double)out.pm2_5_number_concentration,
           (double)out.pm10_number_concentration,
           out.is_obstructed ? "yes" : "no",
           out.is_outside_measurement_range ? "yes" : "no");
}

/* Opens the part on one chip select with the flight port layer, reports what
 * the vendor library says, and leaves the handle open on success. */
static bool try_open(uint8_t cs, bmv080_spi_device_t *dev,
                     bmv080_handle_t *handle)
{
    bmv080_status_code_t status;
    char id[13];

    dev->spi = spi1;
    dev->cs_pin = cs;
    *handle = NULL;

    status = bmv080_open(handle, (bmv080_sercom_handle_t)dev,
                         (const bmv080_callback_read_t)bmv080_port_spi_read_16bit,
                         (const bmv080_callback_write_t)bmv080_port_spi_write_16bit,
                         (const bmv080_callback_delay_t)bmv080_port_delay_ms);
    printf("  CS GP%-2u bmv080_open: %d%s\n", cs, (int)status,
           status == E_BMV080_OK
               ? "  <-- BMV080"
               : (status == E_BMV080_ERROR_MISMATCH_CHIP_ID
                      ? "  (107: no answer on this select)"
                      : ""));
    if (status != E_BMV080_OK) {
        *handle = NULL;
        return false;
    }

    memset(id, 0, sizeof id);
    status = bmv080_get_sensor_id(*handle, id);
    printf("    sensor id: \"%s\" (status %d)\n", id, (int)status);
    return true;
}

/* Reads back the four parameters that exist on an embedded target. A value
 * that reads back as its documented default is weak evidence on its own; the
 * write-then-read below is what proves the link both ways. */
static void report_parameters(bmv080_handle_t handle)
{
    float integration_time = 0.0f;
    bmv080_measurement_algorithm_t algorithm = 0;
    bool obstruction_detection = false;
    bool vibration_filtering = false;
    bmv080_measurement_algorithm_t wanted =
        E_BMV080_MEASUREMENT_ALGORITHM_HIGH_PRECISION;

    (void)bmv080_get_parameter(handle, "integration_time", &integration_time);
    (void)bmv080_get_parameter(handle, "measurement_algorithm", &algorithm);
    (void)bmv080_get_parameter(handle, "do_obstruction_detection",
                               &obstruction_detection);
    (void)bmv080_get_parameter(handle, "do_vibration_filtering",
                               &vibration_filtering);
    printf("    integration_time %.1f s  algorithm %d  "
           "obstruction_detection %d  vibration_filtering %d\n",
           (double)integration_time, (int)algorithm,
           (int)obstruction_detection, (int)vibration_filtering);

    printf("    set algorithm HIGH_PRECISION: %d\n",
           (int)bmv080_set_parameter(handle, "measurement_algorithm", &wanted));
    algorithm = 0;
    (void)bmv080_get_parameter(handle, "measurement_algorithm", &algorithm);
    printf("    read back: %d%s\n", (int)algorithm,
           algorithm == wanted ? "  (link proven both ways)" : "  <-- MISMATCH");
}

int main(void)
{
    bmv080_spi_device_t dev = {0};
    bmv080_handle_t handle = NULL;
    uint16_t major = 0, minor = 0, patch = 0;
    char git_hash[12] = {0};
    int32_t commits_ahead = 0;
    bmv080_status_code_t status;

    stdio_init_all();
    hw_init(); /* actuators low; i2c0 + spi1 up */

    /* hw_init() opened the sensor on PIN_BMV080_CS. Hand the bus back before
     * probing: two handles on one part is not a case the vendor library
     * covers. */
    bmv080_dev_close();

    /* Every candidate select idles high, so only one part is ever addressed.
     * hw_init() already parked all four SPI_1 selects before the first clock
     * (spi1_park_chip_selects, since 2026-09-28); this re-assert is belt and
     * braces for a tool that then drives them itself. */
    for (size_t c = 0; c < sizeof CS_PINS; c++)
        bmv080_port_init_cs(CS_PINS[c]);

    while (!stdio_usb_connected())
        sleep_ms(100);
    sleep_ms(500);

    printf("\n=== BMV080 probe (bench tool) ===\n");
    printf("spi1: MISO GP%u SCK GP%u MOSI GP%u, flight CS GP%u\n",
           PIN_SPI1_MISO, PIN_SPI1_SCK, PIN_SPI1_MOSI, PIN_BMV080_CS);

    status = bmv080_get_driver_version(&major, &minor, &patch, git_hash,
                                       &commits_ahead);
    printf("vendor library %u.%u.%u.%s.%ld (status %d) - no sensor needed\n",
           major, minor, patch, git_hash, (long)commits_ahead, (int)status);
    printf("flight-path open at boot returned status %d, id \"%s\"\n",
           bmv080_dev_status(), bmv080_dev_sensor_id());

    raw_scan();

    printf("-- bmv080_open per chip select --\n");
    for (size_t c = 0; c < sizeof CS_PINS; c++) {
        if (try_open(CS_PINS[c], &dev, &handle))
            break;
    }

    if (handle == NULL) {
        printf("no BMV080 answered on GP12/GP13/GP47.\n"
               "Check, in this order, the things firmware cannot fix:\n"
               "  - PS tied LOW at power-up (latched once; floating = I2C)\n"
               "  - VDDL/VDDA/VDDD (3.3 V) and VDDIO all present\n"
               "  - MOSI/MISO not crossed (raw reads above would echo tx)\n"
               "  - the ZIF flex seated\n");
        for (;;)
            sleep_ms(1000);
    }

    report_parameters(handle);

    status = bmv080_start_continuous_measurement(handle);
    printf("  start_continuous_measurement: %d\n", (int)status);
    if (status == E_BMV080_ERROR_INCOMPATIBLE_SENSOR_HW)
        printf("  418: this SDK does not match this sensor sample\n");
    if (status != E_BMV080_OK) {
        (void)bmv080_close(&handle);
        for (;;)
            sleep_ms(1000);
    }

    printf("-- first reading is ~1.9 s away, then ~1/s --\n");
    for (;;) {
        status = bmv080_serve_interrupt(handle, on_data_ready, NULL);
        if (status != E_BMV080_OK)
            printf("  serve_interrupt: %d\n", (int)status);
        /* 100 ms is the interval both Bosch examples use, against a
         * requirement of at least one call per second. */
        sleep_ms(100);
    }
}
