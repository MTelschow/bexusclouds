/*
 * BMV080 bring-up firmware - Raspberry Pi Pico 2 (RP2350), USB CDC console.
 *
 * What it does, in order:
 *   1. passive pin survey of the four bus pins, as plain SIO inputs, BEFORE
 *      the SPI function is applied to them (a pin already in GPIO_FUNC_SPI
 *      reads back the controller's drive state, not the board's);
 *   2. probes each configured chip select with open / reset / get_sensor_id,
 *      so a two-sensor bus reports which selects answer and which do not;
 *   3. runs a continuous particle measurement on every sensor that answered,
 *      printing one line per reading.
 *
 * The sensor's hardware IRQ line is not wired on this board, so the driver is
 * polled: bmv080_serve_interrupt() every POLL_INTERVAL_MS. The vendor API
 * requires at least one call per second; 100 ms is the interval the Bosch
 * examples use, and it keeps readings from being dropped at high particle
 * concentrations.
 */

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "pico/stdlib.h"

#include "bmv080.h"
#include "bmv080_defs.h"
#include "bmv080_port.h"
#include "board_pins.h"
#include "rails.h"

#define POLL_INTERVAL_MS 100u

/* Length of the continuous measurement run per sensor, in readings. The sensor
 * emits roughly one reading per second. 0 means "never stop". */
#ifndef MEASUREMENT_READINGS
#define MEASUREMENT_READINGS 0u
#endif

/* How long to wait for a USB CDC host before giving up and printing anyway.
 * Without this the banner is emitted into a port nobody has opened yet. */
#define USB_WAIT_MS 10000u

#if BMV080_SPI_INSTANCE == 0
#define BMV080_SPI spi0
#else
#define BMV080_SPI spi1
#endif

typedef struct
{
    const char *name;
    uint8_t cs_pin;
    bmv080_spi_device_t device;
    bmv080_handle_t handle;
    char id[13];
    bool present;
} sensor_slot_t;

static sensor_slot_t sensors[] = {
    {.name = "CS1", .cs_pin = BMV080_PIN_CS1},
#if BMV080_PIN_CS2 != BMV080_PIN_NONE
    {.name = "CS2", .cs_pin = BMV080_PIN_CS2},
#endif
};

#define SENSOR_COUNT (sizeof(sensors) / sizeof(sensors[0]))

/* Set by the data-ready callback, read by the measurement loop. */
static volatile uint32_t reading_count = 0;

/*----------------------------------------------------------------------------
 * Passive pin survey
 *
 * This says what holds each line when nothing drives it. It proves "something
 * holds this line" or "nothing does" - it does NOT prove a part is absent: a
 * high-impedance input on the sensor side reads exactly like a bare pin.
 *--------------------------------------------------------------------------*/
static void survey_pin(const char *name, uint8_t pin)
{
    gpio_init(pin);
    gpio_set_dir(pin, GPIO_IN);

    gpio_pull_up(pin);
    sleep_us(200);
    bool with_pull_up = gpio_get(pin);

    gpio_pull_down(pin);
    sleep_us(200);
    bool with_pull_down = gpio_get(pin);

    gpio_disable_pulls(pin);
    sleep_us(200);
    bool floating = gpio_get(pin);

    /* Asymmetric on purpose, because the two outcomes are not equally
     * informative on this chip.
     *
     * Measured here on RP2350 A2: six GPIOs that are unconnected on a bare
     * Pico 2 all read pu=1 pd=1 float=1. A floating input latches high despite
     * the internal pull-down, so "reads high with the pull-down on" does NOT
     * distinguish an external pull-up from a bare pin, and must not be
     * reported as if it did.
     *
     * Reading low against the internal pull-up stays meaningful: something has
     * to sink that current. */
    const char *verdict = "inconclusive - floating reads like this too on RP2350";
    if ((with_pull_up == 0) && (with_pull_down == 0))
    {
        verdict = "held LOW by the board (meaningful: something sinks the pull-up)";
    }
    else if ((with_pull_up == 1) && (with_pull_down == 0))
    {
        verdict = "follows the internal pulls - nothing external holds it";
    }

    printf("  %-5s GP%-2u  pu=%d pd=%d float=%d  %s\r\n", name, pin, with_pull_up,
           with_pull_down, floating, verdict);
}

/*----------------------------------------------------------------------------
 * Active drive-back test
 *
 * Drives each line from the RP2350 and reads it back. A pin that will not
 * follow its own driver is shorted, or fought by something stronger than a
 * CMOS output - which is a different fault from "nothing holds this line".
 * MISO is driven too, deliberately and only for a moment: if a sensor is
 * driving it the two outputs fight, and 3V3 CMOS parts survive microseconds of
 * that. It is the only way to tell a hard short to GND from a sensor output.
 *--------------------------------------------------------------------------*/
static bool drive_test_pin(const char *name, uint8_t pin)
{
    gpio_init(pin);
    gpio_disable_pulls(pin);
    gpio_set_dir(pin, GPIO_IN);

    gpio_put(pin, 1);
    gpio_set_dir(pin, GPIO_OUT);
    busy_wait_us(50);
    bool reads_high = gpio_get(pin);

    gpio_put(pin, 0);
    busy_wait_us(50);
    bool reads_low = gpio_get(pin);

    gpio_set_dir(pin, GPIO_IN);

    const char *verdict = "follows its driver";
    if ((reads_high == 0) && (reads_low == 0))
    {
        verdict = "STUCK LOW - short to GND, or an output driving it low";
    }
    else if ((reads_high == 1) && (reads_low == 1))
    {
        verdict = "STUCK HIGH - short to 3V3, or an output driving it high";
    }

    printf("  %-5s GP%-2u  drive1->%d drive0->%d  %s\r\n", name, pin, reads_high, reads_low,
           verdict);

    return (reads_high == 1) && (reads_low == 0);
}

/*!
 * @return true when every bus pin follows its own driver, i.e. it is safe to
 *         start clocking the bus.
 */
static bool drive_test(void)
{
    printf("Active drive-back test (RP2350 drives, then reads its own pin):\r\n");
    bool bus_ok = true;
    bus_ok &= drive_test_pin("MISO", BMV080_PIN_MISO);
    bus_ok &= drive_test_pin("MOSI", BMV080_PIN_MOSI);
    bus_ok &= drive_test_pin("SCK", BMV080_PIN_SCK);
    for (size_t i = 0; i < SENSOR_COUNT; i++)
    {
        (void)drive_test_pin(sensors[i].name, sensors[i].cs_pin);
    }
    printf("\r\n");
    return bus_ok;
}

/*----------------------------------------------------------------------------
 * Control-pin test - rule out the instrument before the board
 *
 * Runs the same drive-back check on GPIOs that are not part of the sensor
 * harness. If those follow their drivers, the method is sound and a stuck bus
 * pin is a real external fault; if they are stuck too, the fault is in this
 * firmware or in the RP2350, and nothing measured above means anything.
 *
 * Avoids GP23/GP24/GP25 (power save, VBUS sense, LED on a Pico 2) and GP29.
 *--------------------------------------------------------------------------*/
static bool pin_is_in_harness(uint8_t pin)
{
    if ((pin == BMV080_PIN_MISO) || (pin == BMV080_PIN_MOSI) || (pin == BMV080_PIN_SCK))
    {
        return true;
    }
    for (size_t i = 0; i < SENSOR_COUNT; i++)
    {
        if (pin == sensors[i].cs_pin)
        {
            return true;
        }
    }
    return false;
}

static void control_pin_test(void)
{
    static const uint8_t control_pins[] = {2u, 3u, 10u, 11u, 21u, 22u};

    /* The passive survey first, and this is the more important half.
     *
     * These GPIOs are unconnected on a bare Pico 2, so whatever the survey says
     * about them is, by construction, what "floating" reads like on this chip.
     * If they come back "held HIGH by the board" then that verdict carries no
     * information anywhere, including on the sensor bus, and only the
     * drive-back result can be trusted. Measuring this beats quoting an
     * erratum from memory. */
    printf("Control pins, passive (unconnected on a bare Pico 2 - this is what\r\n"
           "floating reads like here):\r\n");
    for (size_t i = 0; i < (sizeof(control_pins) / sizeof(control_pins[0])); i++)
    {
        if (pin_is_in_harness(control_pins[i]))
        {
            continue;
        }
        survey_pin("ctl", control_pins[i]);
    }
    printf("\r\n");

    printf("Control pins, driven (same test, GPIOs outside the sensor harness):\r\n");
    for (size_t i = 0; i < (sizeof(control_pins) / sizeof(control_pins[0])); i++)
    {
        if (pin_is_in_harness(control_pins[i]))
        {
            continue;
        }
        drive_test_pin("ctl", control_pins[i]);
    }
    printf("  all of these must follow their drivers, or the fault is in here.\r\n\r\n");
}

/*----------------------------------------------------------------------------
 * Drive-strength escalation
 *
 * A pin held by a weak source - a pull resistor, or a translator output of a
 * few kiloohms - gives way to a stronger pad driver. A pin tied to a rail does
 * not, at any setting. This says which kind of "stuck" we are looking at.
 *--------------------------------------------------------------------------*/
static void drive_strength_test(const char *name, uint8_t pin)
{
    static const enum gpio_drive_strength strengths[] = {
        GPIO_DRIVE_STRENGTH_2MA, GPIO_DRIVE_STRENGTH_4MA, GPIO_DRIVE_STRENGTH_8MA,
        GPIO_DRIVE_STRENGTH_12MA};
    static const char *labels[] = {"2mA", "4mA", "8mA", "12mA"};

    printf("  %-5s GP%-2u:", name, pin);

    gpio_init(pin);
    gpio_disable_pulls(pin);

    for (size_t i = 0; i < 4; i++)
    {
        gpio_set_drive_strength(pin, strengths[i]);

        gpio_put(pin, 1);
        gpio_set_dir(pin, GPIO_OUT);
        busy_wait_us(200);
        bool high = gpio_get(pin);

        gpio_put(pin, 0);
        busy_wait_us(200);
        bool low = gpio_get(pin);

        gpio_set_dir(pin, GPIO_IN);
        busy_wait_us(200);

        printf("  %s:%d/%d", labels[i], high, low);
    }

    gpio_set_drive_strength(pin, GPIO_DRIVE_STRENGTH_4MA);
    printf("   (drive1/drive0 at each strength)\r\n");
}

static void drive_strength_sweep(void)
{
    printf("Drive-strength escalation on the bus pins:\r\n");
    drive_strength_test("MISO", BMV080_PIN_MISO);
    drive_strength_test("MOSI", BMV080_PIN_MOSI);
    drive_strength_test("SCK", BMV080_PIN_SCK);
    printf("  a pin that starts following at a higher strength was held by something\r\n"
           "  weak (a pull resistor, a translator); one that never follows is tied to a\r\n"
           "  rail.\r\n\r\n");
}

/*----------------------------------------------------------------------------
 * Cross-short test
 *
 * Drives one pin at a time and reads all the others. A pin that copies its
 * neighbour is bridged to it. This separates a solder bridge between two
 * GPIOs from a short to a supply rail, which the drive-back test alone cannot
 * tell apart - both read as "stuck".
 *--------------------------------------------------------------------------*/
static void cross_short_test(void)
{
    struct
    {
        const char *name;
        uint8_t pin;
    } lines[3 + SENSOR_COUNT];

    lines[0].name = "MISO";
    lines[0].pin = BMV080_PIN_MISO;
    lines[1].name = "MOSI";
    lines[1].pin = BMV080_PIN_MOSI;
    lines[2].name = "SCK";
    lines[2].pin = BMV080_PIN_SCK;
    for (size_t i = 0; i < SENSOR_COUNT; i++)
    {
        lines[3 + i].name = sensors[i].name;
        lines[3 + i].pin = sensors[i].cs_pin;
    }
    const size_t line_count = 3 + SENSOR_COUNT;

    printf("Cross-short test (drive one pin, read the others):\r\n");

    for (size_t i = 0; i < line_count; i++)
    {
        gpio_init(lines[i].pin);
        gpio_disable_pulls(lines[i].pin);
        gpio_set_dir(lines[i].pin, GPIO_IN);
    }

    for (size_t d = 0; d < line_count; d++)
    {
        printf("  drive %-5s GP%-2u:", lines[d].name, lines[d].pin);

        for (size_t level = 0; level < 2; level++)
        {
            gpio_put(lines[d].pin, level);
            gpio_set_dir(lines[d].pin, GPIO_OUT);
            busy_wait_us(50);

            printf("  %d ->", (int)level);
            for (size_t o = 0; o < line_count; o++)
            {
                if (o == d)
                {
                    continue;
                }
                printf(" %s=%d", lines[o].name, gpio_get(lines[o].pin));
            }

            gpio_set_dir(lines[d].pin, GPIO_IN);
            busy_wait_us(50);
        }
        printf("\r\n");
    }
    printf("  a pin that copies the driven one on BOTH levels is bridged to it.\r\n\r\n");
}

/*----------------------------------------------------------------------------
 * Raw SPI probe
 *
 * Clocks words out with chip select asserted and prints what came back, with
 * no interpretation. This does not guess at the register map - the point is
 * only whether MISO ever moves. All-0x0000 or all-0xFFFF means nobody is
 * driving the line; anything else means a part is answering, and then the
 * mismatch is about protocol or wiring order rather than about power.
 *--------------------------------------------------------------------------*/
static void raw_spi_probe(sensor_slot_t *slot)
{
    static const uint16_t tx_patterns[] = {0x0000, 0xFFFF, 0xA5A5};

    printf("--- %s (GP%u): raw SPI, no interpretation ---\r\n", slot->name, slot->cs_pin);

    for (size_t p = 0; p < (sizeof(tx_patterns) / sizeof(tx_patterns[0])); p++)
    {
        uint16_t tx[4];
        uint16_t rx[4] = {0};
        for (size_t i = 0; i < 4; i++)
        {
            tx[i] = tx_patterns[p];
        }

        gpio_put(slot->cs_pin, 0);
        busy_wait_us(2);
        (void)spi_write16_read16_blocking(BMV080_SPI, tx, rx, 4);
        busy_wait_us(2);
        gpio_put(slot->cs_pin, 1);
        busy_wait_us(50);

        printf("  tx %04X x4 -> rx %04X %04X %04X %04X\r\n", tx_patterns[p], rx[0], rx[1], rx[2],
               rx[3]);
    }
    printf("\r\n");
}

static void pin_survey(void)
{
    printf("Passive pin survey (plain SIO inputs, before SPI function):\r\n");
    survey_pin("MISO", BMV080_PIN_MISO);
    survey_pin("MOSI", BMV080_PIN_MOSI);
    survey_pin("SCK", BMV080_PIN_SCK);
    for (size_t i = 0; i < SENSOR_COUNT; i++)
    {
        survey_pin(sensors[i].name, sensors[i].cs_pin);
    }
    printf("  note: a high-impedance sensor input reads like a bare pin, and on this\r\n"
           "  RP2350 a bare pin reads HIGH even with the pull-down on - see the control\r\n"
           "  pins below. Only the drive-back test settles anything.\r\n\r\n");
}

/*----------------------------------------------------------------------------
 * Probe
 *--------------------------------------------------------------------------*/
static bool probe_sensor(sensor_slot_t *slot)
{
    printf("--- %s (GP%u) ---\r\n", slot->name, slot->cs_pin);

    slot->device.spi = BMV080_SPI;
    slot->device.cs_pin = slot->cs_pin;
    slot->handle = NULL;
    slot->present = false;

    bmv080_status_code_t status =
        bmv080_open(&slot->handle, (bmv080_sercom_handle_t)&slot->device,
                    (const bmv080_callback_read_t)bmv080_port_spi_read_16bit,
                    (const bmv080_callback_write_t)bmv080_port_spi_write_16bit,
                    (const bmv080_callback_delay_t)bmv080_port_delay_ms);
    if (status != E_BMV080_OK)
    {
        printf("  open failed, status %d -> no sensor answering on this select\r\n\r\n",
               (int)status);
        slot->handle = NULL;
        return false;
    }
    printf("  open OK\r\n");

    status = bmv080_reset(slot->handle);
    if (status != E_BMV080_OK)
    {
        printf("  reset failed, status %d\r\n\r\n", (int)status);
        (void)bmv080_close(&slot->handle);
        return false;
    }
    printf("  reset OK\r\n");

    memset(slot->id, 0x00, sizeof(slot->id));
    status = bmv080_get_sensor_id(slot->handle, slot->id);
    if (status != E_BMV080_OK)
    {
        printf("  get_sensor_id failed, status %d\r\n\r\n", (int)status);
        (void)bmv080_close(&slot->handle);
        return false;
    }
    printf("  sensor ID: %s\r\n", slot->id);

    /* Configuration read-back. A parameter that reads back as its documented
     * default is weak evidence on its own; a parameter that reads back as what
     * we just wrote is what actually proves the link both ways. */
    float integration_time = 0.0f;
    bmv080_measurement_algorithm_t algorithm = E_BMV080_MEASUREMENT_ALGORITHM_BALANCED;
    bool obstruction_detection = false;
    bool vibration_filtering = false;

    (void)bmv080_get_parameter(slot->handle, "integration_time", (void *)&integration_time);
    (void)bmv080_get_parameter(slot->handle, "measurement_algorithm", (void *)&algorithm);
    (void)bmv080_get_parameter(slot->handle, "do_obstruction_detection",
                               (void *)&obstruction_detection);
    (void)bmv080_get_parameter(slot->handle, "do_vibration_filtering",
                               (void *)&vibration_filtering);

    printf("  defaults: integration_time %.1f s, algorithm %d, obstruction_detection %s, "
           "vibration_filtering %s\r\n",
           integration_time, (int)algorithm, obstruction_detection ? "true" : "false",
           vibration_filtering ? "true" : "false");

    /* Write-then-read one parameter so the write path is exercised too. */
    bmv080_measurement_algorithm_t wanted = E_BMV080_MEASUREMENT_ALGORITHM_HIGH_PRECISION;
    status = bmv080_set_parameter(slot->handle, "measurement_algorithm", (void *)&wanted);
    if (status == E_BMV080_OK)
    {
        bmv080_measurement_algorithm_t read_back = 0;
        status = bmv080_get_parameter(slot->handle, "measurement_algorithm", (void *)&read_back);
        printf("  write path: set measurement_algorithm %d, read back %d -> %s\r\n",
               (int)wanted, (int)read_back,
               ((status == E_BMV080_OK) && (read_back == wanted)) ? "OK" : "MISMATCH");
    }
    else
    {
        printf("  write path: set measurement_algorithm failed, status %d\r\n", (int)status);
    }

    printf("\r\n");
    slot->present = true;
    return true;
}

/*----------------------------------------------------------------------------
 * Measurement
 *--------------------------------------------------------------------------*/
static void use_sensor_output(bmv080_output_t output, void *callback_parameters)
{
    const char *name = (const char *)callback_parameters;
    reading_count++;

    /* The laser and its heater are the load worth watching, so the rails are
     * sampled while the sensor is actually running, not only at boot. */
    if ((reading_count % 10u) == 1u)
    {
        rails_sample_t rails;
        rails_read(&rails);
        rails_print("[rails]", &rails);
    }

    printf("%s  t=%7.2f s  PM1 %6.1f  PM2.5 %6.1f  PM10 %6.1f ug/m3   "
           "#PM1 %6.1f #PM2.5 %6.1f #PM10 %6.1f /cm3   obstructed=%s  out_of_range=%s\r\n",
           name, output.runtime_in_sec, output.pm1_mass_concentration,
           output.pm2_5_mass_concentration, output.pm10_mass_concentration,
           output.pm1_number_concentration, output.pm2_5_number_concentration,
           output.pm10_number_concentration, output.is_obstructed ? "yes" : "no",
           output.is_outside_measurement_range ? "yes" : "no");
}

static void measure(sensor_slot_t *slot)
{
    printf("--- %s: continuous measurement ---\r\n", slot->name);

    bmv080_status_code_t status = bmv080_start_continuous_measurement(slot->handle);
    if (status == E_BMV080_ERROR_INCOMPATIBLE_SENSOR_HW)
    {
        printf("  the SDK is not compatible with this BMV080 sample "
               "(E_BMV080_ERROR_INCOMPATIBLE_SENSOR_HW)\r\n");
    }
    if (status != E_BMV080_OK)
    {
        printf("  start_continuous_measurement failed, status %d\r\n\r\n", (int)status);
        return;
    }

    reading_count = 0;
    uint32_t consecutive_errors = 0;

    /* Held in a variable rather than tested as a literal: with the default of
     * 0 the compiler folds the comparison and warns, and the run is endless -
     * which is what you want with one sensor on the bench, but it means a
     * second sensor is never reached. Pass -DMEASUREMENT_READINGS=<n> to
     * measure both. */
    const uint32_t target_readings = MEASUREMENT_READINGS;

    while ((target_readings == 0u) || (reading_count < target_readings))
    {
        status = bmv080_serve_interrupt(slot->handle,
                                        (bmv080_callback_data_ready_t)use_sensor_output,
                                        (void *)slot->name);
        if (status != E_BMV080_OK)
        {
            printf("  serve_interrupt failed, status %d\r\n", (int)status);
            if (++consecutive_errors >= 10u)
            {
                printf("  giving up on %s after 10 consecutive failures\r\n", slot->name);
                break;
            }
        }
        else
        {
            consecutive_errors = 0;
        }

        sleep_ms(POLL_INTERVAL_MS);
    }

    status = bmv080_stop_measurement(slot->handle);
    printf("  measurement stopped, status %d, %lu readings\r\n\r\n", (int)status,
           (unsigned long)reading_count);
}

/*--------------------------------------------------------------------------*/
int main(void)
{
    stdio_init_all();

    /* Give a USB CDC host a chance to attach, but never block on it. */
    uint32_t waited_ms = 0;
    while (!stdio_usb_connected() && (waited_ms < USB_WAIT_MS))
    {
        sleep_ms(100);
        waited_ms += 100;
    }
    sleep_ms(200);

    uint16_t major = 0, minor = 0, patch = 0;
    char git_hash[12] = {0};
    int32_t commits_ahead = 0;
    (void)bmv080_get_driver_version(&major, &minor, &patch, git_hash, &commits_ahead);

    printf("\r\n============================================================\r\n");
    printf("BMV080 bring-up - RP2350 / Pico SDK\r\n");
    printf("BMV080 driver version: %u.%u.%u.%s.%ld\r\n", major, minor, patch, git_hash,
           (long)commits_ahead);
    printf("Bus: spi%d @ %u Hz nominal, 16-bit frames, mode 0, MSB first\r\n",
           BMV080_SPI_INSTANCE, (unsigned)BMV080_SPI_CLK_HZ);
    printf("Pins: MISO GP%u, MOSI GP%u, SCK GP%u, CS1 GP%u", BMV080_PIN_MISO, BMV080_PIN_MOSI,
           BMV080_PIN_SCK, BMV080_PIN_CS1);
#if BMV080_PIN_CS2 != BMV080_PIN_NONE
    printf(", CS2 GP%u", BMV080_PIN_CS2);
#endif
    printf("\r\n============================================================\r\n\r\n");

    /* Baseline before any pin is driven, so a later reading has something to be
     * compared against. */
    rails_init();
    rails_profile("[rails baseline]", 5u, 100u);
    printf("\r\n");

    pin_survey();
    const bool bus_ok = drive_test();
    control_pin_test();
    drive_strength_sweep();
    cross_short_test();

    rails_profile("[rails after pin tests]", 5u, 100u);
    printf("\r\n");

    /* Refuse to run the bus into a short.
     *
     * A bus pin that will not follow its own driver is tied to a rail. If that
     * pin is SCK or MOSI, every SPI transfer drives a pad straight into 3V3 or
     * GND - at 1 MHz, for as long as the firmware runs. That is a way to lose
     * a pad on the RP2350, or to brown out whatever holds the rail. The
     * diagnostics above have already told us everything the bus could, so
     * there is nothing left to learn by clocking it. */
    if (!bus_ok)
    {
        printf("ABORTING: a bus pin is tied to a rail (see the drive-back test).\r\n");
        printf("SPI is NOT started - clocking it would drive a pad into a short at "
               "%u Hz.\r\n",
               (unsigned)BMV080_SPI_CLK_HZ);
        printf("Fix the wiring, then power-cycle. Build with -DBMV080_FORCE_BUS=1 to "
               "override.\r\n");
#ifndef BMV080_FORCE_BUS
        printf("\r\nLogging rails while parked. Nothing drives the bus from here.\r\n\r\n");
        while (true)
        {
            rails_profile("[rails parked]", 60u, 500u);
            printf("\r\n");
        }
#else
        printf("BMV080_FORCE_BUS set - continuing anyway.\r\n\r\n");
#endif
    }

    uint32_t baudrate = bmv080_port_init_bus(BMV080_SPI, BMV080_PIN_SCK, BMV080_PIN_MOSI,
                                             BMV080_PIN_MISO, BMV080_SPI_CLK_HZ);
    printf("SPI initialised, actual baud rate %lu Hz\r\n\r\n", (unsigned long)baudrate);

    for (size_t i = 0; i < SENSOR_COUNT; i++)
    {
        bmv080_port_init_cs(sensors[i].cs_pin);
    }

    for (size_t i = 0; i < SENSOR_COUNT; i++)
    {
        sensors[i].device.spi = BMV080_SPI;
        sensors[i].device.cs_pin = sensors[i].cs_pin;
        raw_spi_probe(&sensors[i]);
    }

    size_t present = 0;
    for (size_t i = 0; i < SENSOR_COUNT; i++)
    {
        if (probe_sensor(&sensors[i]))
        {
            present++;
        }
    }

    printf("Probe result: %u of %u chip selects answered\r\n\r\n", (unsigned)present,
           (unsigned)SENSOR_COUNT);

    if (present == 0)
    {
        printf("No sensor found. Check 3V3 and GND at the sensor, then the four bus "
               "pins against the survey above.\r\n");
        while (true)
        {
            sleep_ms(1000);
        }
    }

    for (size_t i = 0; i < SENSOR_COUNT; i++)
    {
        if (sensors[i].present)
        {
            measure(&sensors[i]);
        }
    }

    for (size_t i = 0; i < SENSOR_COUNT; i++)
    {
        if (sensors[i].handle != NULL)
        {
            (void)bmv080_close(&sensors[i].handle);
        }
    }

    printf("Done. Logging rails from here.\r\n\r\n");
    while (true)
    {
        rails_profile("[rails idle]", 60u, 500u);
        printf("\r\n");
    }
}
