/* BMV080 driver (see bmv080_dev.h for why this part is unlike the others).
 *
 * The file is bmv080_dev.c and not bmv080.c because the vendor API's own
 * header is bmv080.h: a driver named after the part would shadow it for
 * every translation unit in src/hw/, since a quoted include searches the
 * including file's directory first. */
#include "bmv080_dev.h"

#include <string.h>

#include "board.h"
#include "bmv080_port.h"

/* The vendor API, from CLOUDS_BMV080_SDK_DIR/api/inc (flight/mcu/CMakeLists.txt). */
#include "bmv080.h"

/* How often the library is served. The vendor requires at least once per
 * second; both Bosch embedded examples use 100 ms, and the datasheet gives
 * the reason - at high particle concentrations a longer interval drops
 * events. The main loop's pass is 10 ms, so this divides it evenly. */
#define BMV080_SERVICE_INTERVAL_MS 100u

/* The part's specified measurement range ceiling (datasheet Table 3). A
 * reading above it is reported saturated AND flagged out-of-range, rather
 * than wrapped into a small number by the uint16 cast. */
#define BMV080_PM_MAX_UGM3 1000u

static bmv080_spi_device_t device;
static bmv080_handle_t handle;
static char sensor_id[13];
static int last_status;

/* The newest sample the data-ready callback has seen, and whether anything
 * has read it yet. `serial` increments per sample so bmv080_dev_read() can
 * tell a repeat from a fresh one without comparing floats. */
static struct {
    uint16_t pm2_5_ugm3;
    bool obstructed;
    bool out_of_range;
    bool valid;
    uint32_t serial;
} latest;

static uint32_t last_read_serial;
static uint64_t next_service_ms;

/* Called by bmv080_serve_interrupt(), possibly several times in one call if
 * the service was late - the library replays one reading per elapsed second.
 * Keeping only the newest is deliberate: housekeeping downlinks one value per
 * second and a queue would only decide which second's value to show.
 *
 * NOTE the vendor struct's field order is PM2.5, PM1, PM10 - not ascending.
 * bmv080_defs.h. */
static void on_data_ready(bmv080_output_t out, void *params)
{
    float pm = out.pm2_5_mass_concentration;

    (void)params;

    /* The library hands us a float. A negative or NaN value is not a reading;
     * a NaN fails both comparisons below and lands on 0 with the
     * out-of-range flag, which is the honest answer. */
    if (pm > (float)BMV080_PM_MAX_UGM3) {
        latest.pm2_5_ugm3 = (uint16_t)BMV080_PM_MAX_UGM3;
        latest.out_of_range = true;
    } else if (pm > 0.0f) {
        latest.pm2_5_ugm3 = (uint16_t)(pm + 0.5f);
        latest.out_of_range = out.is_outside_measurement_range;
    } else {
        latest.pm2_5_ugm3 = 0;
        latest.out_of_range = out.is_outside_measurement_range || !(pm >= 0.0f);
    }

    latest.obstructed = out.is_obstructed;
    latest.valid = true;
    latest.serial++;
}

bool bmv080_dev_init(void)
{
    bmv080_status_code_t status;
    bmv080_measurement_algorithm_t algorithm =
        E_BMV080_MEASUREMENT_ALGORITHM_HIGH_PRECISION;

    memset(sensor_id, 0, sizeof sensor_id);
    memset(&latest, 0, sizeof latest);
    last_read_serial = 0;
    next_service_ms = 0;
    last_status = 0;
    handle = NULL;

    device.spi = spi1;
    device.cs_pin = PIN_BMV080_CS;

    /* spi1 is already up from hw_init() for the chamber BME280, and the baud
     * rate is shared. This re-runs spi_init() on it, which is idempotent, and
     * claims the chip select. The frame width is not set here - see
     * bmv080_port.c. */
    (void)bmv080_port_init_bus(device.spi, PIN_SPI1_SCK, PIN_SPI1_MOSI,
                               PIN_SPI1_MISO, SPI1_BAUD_HZ);
    bmv080_port_init_cs(device.cs_pin);

    status = bmv080_open(&handle, (bmv080_sercom_handle_t)&device,
                         (const bmv080_callback_read_t)bmv080_port_spi_read_16bit,
                         (const bmv080_callback_write_t)bmv080_port_spi_write_16bit,
                         (const bmv080_callback_delay_t)bmv080_port_delay_ms);
    if (status != E_BMV080_OK) {
        last_status = (int)status;
        handle = NULL;
        return false;
    }

    /* Reset before configuring, never after: bmv080_reset() reverts every
     * parameter to its default. */
    status = bmv080_reset(handle);
    if (status != E_BMV080_OK)
        goto fail;

    /* Not a chip id - there is no such register on this part - but it is the
     * only identity the library exposes, and reading it back proves the link
     * carries data in both directions. */
    status = bmv080_get_sensor_id(handle, sensor_id);
    if (status != E_BMV080_OK)
        goto fail;

    /* Every set_parameter must precede the start, or it does not apply.
     * HIGH_PRECISION is the vendor default and is set explicitly anyway: a
     * parameter that reads back as its documented default is weak evidence,
     * and a later bmv080_reset() elsewhere would silently restore it. */
    status = bmv080_set_parameter(handle, "measurement_algorithm", &algorithm);
    if (status != E_BMV080_OK)
        goto fail;

    status = bmv080_start_continuous_measurement(handle);
    if (status != E_BMV080_OK)
        goto fail;

    return true;

fail:
    last_status = (int)status;
    (void)bmv080_close(&handle);
    handle = NULL;
    memset(sensor_id, 0, sizeof sensor_id);
    return false;
}

void bmv080_dev_service(uint64_t now_ms)
{
    bmv080_status_code_t status;

    if (handle == NULL)
        return;
    if (now_ms < next_service_ms)
        return;
    next_service_ms = now_ms + BMV080_SERVICE_INTERVAL_MS;

    status = bmv080_serve_interrupt(handle, on_data_ready, NULL);
    /* A warning (the 200s, e.g. a full FIFO) means the service was late and
     * the library coped; an error is kept for the bench, but neither is
     * allowed to stop the sweep. The measurement is not restarted here: a
     * part that has stopped answering reports PM_FAIL through
     * bmv080_dev_read() returning false, and a recovery attempt inside the
     * 1 Hz sweep would reintroduce the bring-up delays the watchdog is
     * protected from. */
    if (status != E_BMV080_OK)
        last_status = (int)status;
}

bool bmv080_dev_read(uint16_t *pm2_5_ugm3, bool *fresh, bool *obstructed,
                     bool *out_of_range)
{
    if ((handle == NULL) || !latest.valid)
        return false;

    *pm2_5_ugm3 = latest.pm2_5_ugm3;
    *fresh = (latest.serial != last_read_serial);
    *obstructed = latest.obstructed;
    *out_of_range = latest.out_of_range;
    last_read_serial = latest.serial;
    return true;
}

int bmv080_dev_status(void)
{
    return last_status;
}

const char *bmv080_dev_sensor_id(void)
{
    return sensor_id;
}

void bmv080_dev_close(void)
{
    if (handle == NULL)
        return;

    (void)bmv080_stop_measurement(handle);
    (void)bmv080_close(&handle);
    handle = NULL;
    memset(&latest, 0, sizeof latest);
}
