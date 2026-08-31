/* Pico SDK hardware layer. Compiles only in the pico-sdk build (CMake);
 * the native test build uses mock ops instead (test/test_core).
 *
 * TODO markers = integration points awaiting the real PCB / sensor
 * driver bring-up (features M-06/M-09/M-11 hardware halves). The
 * sequencing logic they serve is already final and tested.
 */
#include "hw.h"

#include <string.h>

#include "hardware/adc.h"
#include "hardware/gpio.h"
#include "hardware/i2c.h"
#include "hardware/pwm.h"
#include "hardware/watchdog.h"
#include "pico/stdlib.h"

#include "../core/config.h"
#include "../core/crc16.h"
#include "../core/pulse.h"
#include "bme280.h"
#include "board.h"

/* ---- time base (S.4) ---------------------------------------------------- */

static uint32_t sync_wall_s;
static uint64_t sync_mono_ms;

uint64_t hw_monotonic_ms(void)
{
    return to_ms_since_boot(get_absolute_time());
}

void hw_timesync(uint32_t t_s, uint16_t t_ms)
{
    (void)t_ms;
    sync_wall_s = t_s;
    sync_mono_ms = hw_monotonic_ms();
}

uint32_t hw_wall_s(void)
{
    if (sync_wall_s == 0)
        return (uint32_t)(hw_monotonic_ms() / 1000u); /* pre-sync fallback */
    return sync_wall_s + (uint32_t)((hw_monotonic_ms() - sync_mono_ms) / 1000u);
}

/* ---- watchdog (S.9) ------------------------------------------------------ */

void hw_watchdog_enable(void)
{
    watchdog_enable(WATCHDOG_TIMEOUT_MS, true);
}

void hw_watchdog_kick(void)
{
    watchdog_update();
}

/* ---- actuators (M-06, M-07) ---------------------------------------------- */
/* VALVE_PULSE_MS (5 s) is longer than WATCHDOG_TIMEOUT_MS (2 s), so a drive
 * can NEVER be a blocking wait here - it would reset the MCU mid-actuation
 * and, with the fired bit already persisted, resume into a second fire.
 * Every drive is handed to core/pulse and released from the main loop by
 * hw_actuators_service(); nothing in this file sleeps. */

static pulse_sched_t pulses;

static void drive_pin(void *ctx, uint8_t pin, bool level)
{
    (void)ctx;
    gpio_put(pin, level);
}

void hw_actuators_service(uint64_t now_ms)
{
    pulse_service(&pulses, now_ms, VALVE_PULSE_MS, drive_pin, NULL);
}

static void ops_fire_pinch(void *ctx, uint8_t n)
{
    (void)ctx;
    /* one-shot fire via MOSFET; no open/close pair to interlock */
    pulse_request(&pulses, n == 1 ? PIN_PINCH_1 : PIN_PINCH_2,
                  PULSE_PIN_NONE);
}

static void ops_close_eq_valves(void *ctx)
{
    (void)ctx;
    pulse_request(&pulses, PIN_EQ1_CLOSE, PIN_EQ1_OPEN);
    pulse_request(&pulses, PIN_EQ2_CLOSE, PIN_EQ2_OPEN);
}

static bool ops_busy(void *ctx)
{
    (void)ctx;
    return pulse_busy(&pulses);
}

static void ops_membrane(void *ctx, uint8_t duty_pct)
{
    uint slice = pwm_gpio_to_slice_num(PIN_MEMBRANE_PWM);

    (void)ctx;
    if (duty_pct == 0) {
        pwm_set_enabled(slice, false);
        gpio_put(PIN_MEMBRANE_PWM, 0);
        return;
    }
    /* TODO: set divider from PARAM_MEMBRANE_HZ once cfg is plumbed here */
    pwm_set_wrap(slice, 999);
    pwm_set_gpio_level(PIN_MEMBRANE_PWM, (uint16_t)(duty_pct * 10u));
    pwm_set_enabled(slice, true);
}

static bool ops_seal_ok(void *ctx)
{
    (void)ctx;
    /* TODO (M-15): compare Keller chamber vs ambient divergence. The
     * sequencer only calls this once the close pulses have finished (see
     * ops_busy), so the reading is taken with the lines already at rest.
     * Until the plumbing exists, report success so the sequence proceeds
     * (matches spec: proceed flagged on failure). */
    return true;
}

static bool ops_self_test(void *ctx)
{
    (void)ctx;
    /* TODO (M-17): sensor plausibility, SD write test, actuator
     * continuity check via sense resistors. */
    return true;
}

/* ---- persistence + logging (S.3, S.6) ------------------------------------ */
/* TODO (M-08/M-11): FatFs on SPI0 with both chip selects; records carry
 * CRC-16 (core/crc16). Layout documented in flight/mcu/README.md.
 * The stubs below keep persistence in RAM so bench bring-up works before
 * the SD stack lands - flight code MUST replace them. */

static seq_persist_t ram_persist;
static bool ram_persist_valid;

static void ops_persist(void *ctx, const seq_persist_t *p)
{
    (void)ctx;
    ram_persist = *p;
    ram_persist_valid = true;
}

bool hw_restore_persist(seq_persist_t *out)
{
    if (!ram_persist_valid)
        return false;
    *out = ram_persist;
    return true;
}

void hw_log_hk(const hk_t *hk, uint32_t wall_s)
{
    (void)hk;
    (void)wall_s;
}

void hw_log_event(uint8_t code, const char *msg, uint32_t wall_s)
{
    (void)code;
    (void)msg;
    (void)wall_s;
}

static void ops_event(void *ctx, uint8_t code, const char *msg)
{
    (void)ctx;
    hw_log_event(code, msg, hw_wall_s());
}

const seq_ops_t hw_seq_ops = {
    .ctx = NULL,
    .persist = ops_persist,
    .fire_pinch = ops_fire_pinch,
    .close_eq_valves = ops_close_eq_valves,
    .membrane = ops_membrane,
    .busy = ops_busy,
    .seal_ok = ops_seal_ok,
    .self_test = ops_self_test,
    .event = ops_event,
};

/* ---- sensors (M-09) ------------------------------------------------------- */
/* What is actually on i2c0 of the carrier, measured (DEVLOG 2026-08-31):
 *   0x76  BME280            -> ambient temp, RH and pressure. Confirmed.
 *   0x40  INA226  24 V bus  -> power monitoring; no field in hk_t (HK is 44 B
 *   0x44  INA226  5 V rail     against a 67 B ceiling), so not sampled here.
 *   0x45  INA226  3.3 V rail
 *   0x28  BNO055 IMU        -> chip id, SW rev and bootloader rev all match a
 *                              genuine part, but its accel/mag/gyro IDs read
 *                              0x00 instead of 0xFB/0x32/0x0F: fitted, talking,
 *                              and not usable. Reported via HKE_IMU_FAIL.
 * There is NO chamber pressure sensor and NO second humidity channel on this
 * bus, so p_ch_pa and rh2_cpct have no source; both are flagged rather than
 * invented. Keller 23SY parts are not present at any address. */

/* Why p_amb_pa is held rather than zeroed on a failed read: autonomy_step()
 * detects launch from a *drop* below p_ground - PARAM_LAUNCH_DP_PA. Reporting
 * 0 Pa on an I2C glitch would look like a 100 kPa fall and trip launch
 * detection on the bench, firing valves. Holding the last good value fails in
 * the safe direction (no drop), and HKE_P_AMB_STALE tells ground it is held.
 * The cold-start value is sea-level pressure for the same reason: high is
 * safe, low is not. */
#define P_AMB_COLD_START_PA 101325u

static uint32_t last_p_amb_pa = P_AMB_COLD_START_PA;

void hw_read_sensors(hk_t *hk)
{
    int16_t bme_temp_cc;
    uint16_t rh_cpct;
    uint32_t p_pa;

    /* STLM20: Vout = -11.69 mV/degC * T + 1.8663 V (datasheet) */
    adc_select_input(ADC_TEMP1);
    uint16_t raw1 = adc_read();
    adc_select_input(ADC_TEMP2);
    uint16_t raw2 = adc_read();
    /* 12-bit ADC, 3.3 V ref: mV = raw * 3300 / 4096 */
    int32_t mv1 = (int32_t)raw1 * 3300 / 4096;
    int32_t mv2 = (int32_t)raw2 * 3300 / 4096;
    hk->temp1_cc = (int16_t)((186630 - mv1 * 100) * 10 / 1169);
    hk->temp2_cc = (int16_t)((186630 - mv2 * 100) * 10 / 1169);

    hk->error_flags = 0;

    if (bme280_read(&bme_temp_cc, &rh_cpct, &p_pa)) {
        hk->bme_temp_cc = bme_temp_cc;
        hk->rh1_cpct = rh_cpct;
        hk->p_amb_pa = p_pa;
        last_p_amb_pa = p_pa;
    } else {
        /* Hold, never drop - see the note above. */
        hk->bme_temp_cc = 0;
        hk->rh1_cpct = 0;
        hk->p_amb_pa = last_p_amb_pa;
        hk->error_flags |= HKE_BME280_FAIL | HKE_P_AMB_STALE;
    }

    /* No sensor exists for these. p_ch_pa mirrors ambient so that a future
     * M-15 divergence check reads "not sealed" (the conservative direction)
     * instead of the huge fake divergence a 0 would produce; M-15 must test
     * HKE_NO_CHAMBER_P before trusting it. */
    hk->p_ch_pa = hk->p_amb_pa;
    hk->rh2_cpct = 0;
    hk->error_flags |= HKE_NO_CHAMBER_P | HKE_NO_RH2 | HKE_IMU_FAIL;

    memset(hk->accel_mg, 0, sizeof hk->accel_mg);
    memset(hk->gyro_ddps, 0, sizeof hk->gyro_ddps);
}

/* ---- init ----------------------------------------------------------------- */

void hw_init(void)
{
    const uint out_pins[] = {PIN_PINCH_1, PIN_PINCH_2, PIN_EQ1_OPEN,
                             PIN_EQ1_CLOSE, PIN_EQ2_OPEN, PIN_EQ2_CLOSE};

    for (unsigned i = 0; i < sizeof out_pins / sizeof out_pins[0]; i++) {
        gpio_init(out_pins[i]);
        gpio_set_dir(out_pins[i], GPIO_OUT);
        gpio_put(out_pins[i], 0); /* everything de-energized at boot */
    }
    pulse_init(&pulses);
    gpio_set_function(PIN_MEMBRANE_PWM, GPIO_FUNC_PWM);
    adc_init();
    adc_gpio_init(26 + ADC_TEMP1);
    adc_gpio_init(26 + ADC_TEMP2);

    /* i2c0 at 100 kHz: the speed the bus was surveyed and the devices
     * identified at. Internal pull-ups are belt-and-braces; the carrier has
     * real ones on both lines (measured pu=1 pd=1 on GP28/GP29). */
    i2c_init(i2c0, 100 * 1000);
    gpio_set_function(PIN_I2C_SDA, GPIO_FUNC_I2C);
    gpio_set_function(PIN_I2C_SCL, GPIO_FUNC_I2C);
    gpio_pull_up(PIN_I2C_SDA);
    gpio_pull_up(PIN_I2C_SCL);
    /* Failure is not fatal: hw_read_sensors() falls back and raises
     * HKE_BME280_FAIL, and the sequencer is required to survive it. */
    (void)bme280_init();
}
