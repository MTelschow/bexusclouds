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
#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/i2c.h"
#include "hardware/pwm.h"
#include "hardware/watchdog.h"
#include "pico/stdlib.h"

#include "../core/config.h"
#include "../core/crc16.h"
#include "../core/pulse.h"
#include "../core/pwmdiv.h"
#include "../core/sqwave.h"
#include "bme280.h"
#include "bno055.h"
#include "ina226.h"
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
static sqwave_t membrane_wave; /* used below the PWM frequency floor */

/* CaCO3 motor speed, latched from PARAM_DISPERSE_DUTY when the pulse is
 * queued rather than read when it starts: the drive is one 5 s shot with no
 * way to change it mid-run, so the speed the panel showed at the press is
 * the speed that runs. Initialised to the compiled-in default so a pulse
 * before any cfg reaches ops_disperse() still turns the motor. */
static uint8_t disperse_duty_pct = 100;

/* True while the operator holds the motor on (DISPERSE_RUN .. DISPERSE_STOP).
 * A hold is a state like the membrane's, not a pulse: it lives beside
 * core/pulse rather than in its one-at-a-time queue, so a running motor can
 * neither delay a release's pinch valve nor keep ops_busy() true and stall
 * the SEAL step. While held, the pulse scheduler's release edge on the
 * forward line is ignored (drive_pin) and a new motor pulse is not queued
 * (ops_disperse) - the motor is already turning. */
static bool motor_held;

/* Motor PWM frequency. Well above the ~9 Hz hardware floor (so this is real
 * PWM, not core/sqwave) and above audible - a brushed motor chopped at a few
 * hundred Hz whines and heats the driver without turning any faster. The
 * speed is the duty against this period. */
#define DISPERSE_PWM_HZ 20000u

/* Drive or release the motor's forward line. It is the one pulse output that
 * is not a plain GPIO: its level carries the speed, so the pin is handed to
 * the PWM slice for the length of the drive and taken back as an SIO output
 * driven low afterwards - de-energized by the MCU, not merely by whatever
 * pull the driver input has (see hw_init, GP17/GP18 have no measured one).
 *
 * At 100 % the compare level equals the wrap+1 the counter never reaches, so
 * the line is held high exactly as the pre-PWM drive held it. */
static void disperse_drive(bool on)
{
    uint slice = pwm_gpio_to_slice_num(PIN_DISPERSE_FWD);
    uint32_t div16, period;

    if (!on) {
        pwm_set_enabled(slice, false);
        gpio_set_function(PIN_DISPERSE_FWD, GPIO_FUNC_SIO);
        gpio_set_dir(PIN_DISPERSE_FWD, GPIO_OUT);
        gpio_put(PIN_DISPERSE_FWD, 0);
        return;
    }
    pwmdiv_solve(clock_get_hz(clk_sys), DISPERSE_PWM_HZ, &div16, &period);
    pwm_set_clkdiv_int_frac(slice, (uint8_t)(div16 / 16u),
                            (uint8_t)(div16 % 16u));
    pwm_set_wrap(slice, (uint16_t)(period - 1u));
    pwm_set_gpio_level(PIN_DISPERSE_FWD,
                       (uint16_t)((uint64_t)period * disperse_duty_pct / 100u));
    gpio_set_function(PIN_DISPERSE_FWD, GPIO_FUNC_PWM);
    pwm_set_enabled(slice, true);
}

static void drive_pin(void *ctx, uint8_t pin, bool level)
{
    (void)ctx;
    /* The motor's forward line is speed-controlled; every other output is a
     * solenoid that is either energized or not. */
    if (pin == PIN_DISPERSE_FWD) {
        /* The end of a pulse must not release a motor the operator is
         * holding on; the hold ends only through ops_disperse_run(false). */
        if (!level && motor_held)
            return;
        disperse_drive(level);
        return;
    }
    gpio_put(pin, level);
}

/* Membrane switch history between two HK packets (board.h, frame.h
 * HKV_MEMBRANE_CYCLING): sampled every loop pass below, consumed by
 * hw_actuator_status(). Both start "released": a switch that is closed at
 * boot then registers its first read as a change, which is what happened. */
static bool sense_last_pulled;
static bool sense_changed;

void hw_actuators_service(uint64_t now_ms)
{
    bool pulled;

    pulse_service(&pulses, now_ms, VALVE_PULSE_MS, drive_pin, NULL);
    /* The membrane's low-frequency edges are released here too, for the same
     * reason the valve pulses are: a hung loop must not be able to leave a
     * solenoid energized. Only touch the pin when an edge actually falls due. */
    if (sqwave_service(&membrane_wave, now_ms))
        gpio_put(PIN_MEMBRANE_PWM, sqwave_level(&membrane_wave));

    /* Sample the position switch on every pass (~10 ms): at 2 Hz the 1 Hz HK
     * sample alone sits at a fixed phase of the cycle and cannot tell a
     * moving plunger from a stuck one. Any edge since the last HK is latched. */
    pulled = hw_membrane_pulled();
    if (pulled != sense_last_pulled) {
        sense_changed = true;
        sense_last_pulled = pulled;
    }
}

/* The membrane position switch is the one pin above GP29 in use, and GP30
 * exists only on the RP2350B carrier. NUM_BANK0_GPIOS comes from the board
 * header (48 for boards/clouds_carrier.h, 30 for pico2), so a pico2 build
 * compiles the read out instead of poking a GPIO register the RP2350A does
 * not have - and says so in HK via HKE_NO_MEMBRANE_SENSE. */
#define HAVE_MEMBRANE_SENSE (PIN_MEMBRANE_SENSE < NUM_BANK0_GPIOS)

/* The push-pull solenoid's current sense (ACT_HB_SENS) is on GP46, an ADC
 * pin that likewise exists only on the RP2350B. Same guard, same reason: a
 * pico2 build must not call adc_gpio_init() on a pin outside its ADC range
 * (the SDK asserts on it), so the read is compiled out and the field carries
 * HB_SENSE_INVALID instead of a number. */
#define HAVE_HB_SENSE (PIN_HB_SENSE < NUM_BANK0_GPIOS)
#if HAVE_HB_SENSE
#define HB_SENSE_ADC_CH (PIN_HB_SENSE - ADC_BASE_PIN)
#endif

/* Raw 12-bit sample of the dispersion motor's current sense, or
 * HB_SENSE_INVALID when this build cannot reach GP46. Eight conversions
 * summed and divided, not one: a single 2 us sample rides the ADC's own
 * noise, and the sum is cheap - ~16 us total, nowhere near the 2 s watchdog.
 * It is still one point per 1 Hz sweep of a drive that lasts 5 s, so a run
 * shows a handful of in-pulse samples and nothing between releases;
 * averaging or integrating is a ground-side job over the logged series, not
 * something to hide in the sample. */
uint16_t hw_hb_sense_raw(void)
{
#if HAVE_HB_SENSE
    uint32_t sum = 0;

    adc_select_input(HB_SENSE_ADC_CH);
    for (unsigned i = 0; i < 8; i++)
        sum += adc_read();
    return (uint16_t)(sum / 8u);
#else
    return HB_SENSE_INVALID;
#endif
}

bool hw_membrane_pulled(void)
{
#if HAVE_MEMBRANE_SENSE
    /* Internal pull-up, switch to ground. The button sits under the plunger
     * and is PRESSED (closed, LOW) while the solenoid rests; actuating the
     * solenoid lifts the plunger off it (open, HIGH). So HIGH = actuated.
     * Measured 2026-09-17: LOW at rest, as described. */
    return gpio_get(PIN_MEMBRANE_SENSE);
#else
    return false;
#endif
}

uint8_t hw_actuator_status(void)
{
    uint8_t bits;

    /* core/pulse drives one line at a time, so at most one pulsed drive bit
     * is set. The open lines are never energized (they are interlocks forced
     * low), and the membrane drive is a waveform, reported as a duty instead.
     * A held motor (DISPERSE_RUN) is not a pulse and is added below, so it
     * may sit beside a pinch bit if a release fires while it runs. */
    switch (pulses.active_pin) {
    case PIN_PINCH_1:
        bits = HKV_PINCH_1;
        break;
    case PIN_PINCH_2:
        bits = HKV_PINCH_2;
        break;
    case PIN_EQ1_CLOSE:
        bits = HKV_EQ1_CLOSE;
        break;
    case PIN_EQ2_CLOSE:
        bits = HKV_EQ2_CLOSE;
        break;
    case PIN_DISPERSE_FWD:
        bits = HKV_DISPERSE;
        break;
    default:
        bits = 0;
        break;
    }
    if (motor_held)
        bits |= HKV_DISPERSE;
    /* Plus the sensed bits, which are allowed alongside a drive: they report
     * the plunger, not a line the MCU is holding. PULLED is the switch now;
     * CYCLING is whether it moved since the last HK, latched by
     * hw_actuators_service() and consumed here, once per packet. */
    if (hw_membrane_pulled())
        bits |= HKV_MEMBRANE_PULLED;
    if (sense_changed) {
        bits |= HKV_MEMBRANE_CYCLING;
        sense_changed = false;
    }
    return bits;
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

/* CaCO3 dispersion motor (M-07). GP17/GP18 are a driver pair; the reverse
 * sense has not been verified, so only the forward line is ever driven and
 * GP18 rides along as its interlock - forced low before GP17 goes high, so
 * the pair cannot be energized together whatever the wiring turns out to be.
 *
 * Scheduled, not slept: the drive is 5 s and the watchdog bites at 2 s. It
 * shares the one-at-a-time queue with the pinch valve fired in the same
 * step, so the motor runs after that valve rather than alongside it, which
 * keeps peak actuator current at one drive.
 *
 * Speed is PARAM_DISPERSE_DUTY, latched here and applied by disperse_drive()
 * when the queue reaches this pulse. The automatic release path and the
 * manual CMD_DISPERSE both arrive through here, so both run the motor at the
 * one configured speed - there is no separate bench setting to forget. */
static void ops_disperse(void *ctx)
{
    const cfg_t *c = (const cfg_t *)ctx;

    if (motor_held)
        return; /* already turning under the operator's hold */
    disperse_duty_pct = (uint8_t)(c ? cfg_get(c, PARAM_DISPERSE_DUTY)
                                    : cfg_default(PARAM_DISPERSE_DUTY));
    pulse_request(&pulses, PIN_DISPERSE_FWD, PIN_DISPERSE_REV);
}

/* The operator's Start/Stop for the same motor (DISPERSE_RUN / STOP). Start
 * latches the speed like a pulse does and drives the line directly, with the
 * reverse line forced low first for the same interlock reason; a repeat
 * Start (the sequencer sends one on SET_PARAM DISPERSE_DUTY while running)
 * only reprograms the duty. Stop releases the hold and also cancels any
 * motor pulse that is driving or queued - a Stop that left a 5 s pulse
 * running would be a button that does nothing for up to 5 s. The pinch and
 * equalisation pulses in the same queue are untouched. */
static void ops_disperse_run(void *ctx, bool on)
{
    const cfg_t *c = (const cfg_t *)ctx;

    if (!on) {
        motor_held = false;
        pulse_cancel(&pulses, PIN_DISPERSE_FWD, drive_pin, NULL);
        disperse_drive(false);
        return;
    }
    disperse_duty_pct = (uint8_t)(c ? cfg_get(c, PARAM_DISPERSE_DUTY)
                                    : cfg_default(PARAM_DISPERSE_DUTY));
    gpio_put(PIN_DISPERSE_REV, 0);
    motor_held = true;
    disperse_drive(true);
}

static bool ops_busy(void *ctx)
{
    (void)ctx;
    return pulse_busy(&pulses);
}

/* Program the slice for `hz` and set the duty against the period that
 * required. The arithmetic is core/pwmdiv so it can be unit-tested. */
static void membrane_program(uint slice, uint32_t hz, uint8_t duty_pct)
{
    uint32_t sys = clock_get_hz(clk_sys);
    uint32_t div16, period;

    pwmdiv_solve(sys, hz, &div16, &period);
    pwm_set_clkdiv_int_frac(slice, (uint8_t)(div16 / 16u),
                            (uint8_t)(div16 % 16u));
    pwm_set_wrap(slice, (uint16_t)(period - 1u));
    pwm_set_gpio_level(PIN_MEMBRANE_PWM,
                       (uint16_t)((uint64_t)period * duty_pct / 100u));
}

/* Membrane dispersion (M-07). Frequency comes from PARAM_MEMBRANE_MHZ (in
 * millihertz) via ops->ctx; without a cfg the compiled-in default is used rather than the
 * 150 kHz that an unset divider produces - at that rate a push-pull solenoid
 * only sees a DC average and never oscillates.
 *
 * The pin is left as a plain SIO output driven low whenever the drive is off,
 * so the solenoid is de-energized by the MCU and not merely by the external
 * pull-down on its driver input. */
static void membrane_release_pin_low(uint slice)
{
    pwm_set_enabled(slice, false);
    sqwave_stop(&membrane_wave);
    gpio_set_function(PIN_MEMBRANE_PWM, GPIO_FUNC_SIO);
    gpio_set_dir(PIN_MEMBRANE_PWM, GPIO_OUT);
    gpio_put(PIN_MEMBRANE_PWM, 0);
}

static void ops_membrane(void *ctx, uint8_t duty_pct)
{
    const cfg_t *c = (const cfg_t *)ctx;
    uint slice = pwm_gpio_to_slice_num(PIN_MEMBRANE_PWM);
    uint32_t mhz;

    if (duty_pct == 0) {
        membrane_release_pin_low(slice);
        return;
    }

    mhz = (uint32_t)(c ? cfg_get(c, PARAM_MEMBRANE_MHZ)
                      : cfg_default(PARAM_MEMBRANE_MHZ));

    if (mhz < pwmdiv_min_hz(clock_get_hz(clk_sys)) * 1000u) {
        /* Below the PWM floor - which is where the membrane actually runs,
         * at 2 Hz and down to 0.1 Hz. Toggle from the main loop instead;
         * core/sqwave explains why that is the safe mechanism for an
         * actuator. */
        membrane_release_pin_low(slice);
        sqwave_start(&membrane_wave, mhz, duty_pct, hw_monotonic_ms());
        gpio_put(PIN_MEMBRANE_PWM, sqwave_level(&membrane_wave));
        return;
    }

    sqwave_stop(&membrane_wave);
    /* Above the floor the slice takes whole hertz; at >= 9 Hz the rounding
     * is under 6 % and the mechanism does not care. */
    membrane_program(slice, (mhz + 500u) / 1000u, duty_pct);
    gpio_set_function(PIN_MEMBRANE_PWM, GPIO_FUNC_PWM);
    pwm_set_enabled(slice, true);
}

static bool ops_seal_ok(void *ctx)
{
    (void)ctx;
    /* TODO (M-15): verify the seal. The chamber-vs-ambient pressure
     * divergence this was to use is gone with the Keller pair, so the check
     * needs a source that exists - a chamber sensor if one is fitted, or the
     * equalisation valves' own position sense. The sequencer only calls this
     * once the close pulses have finished (see ops_busy), so whatever the
     * source, it is read with the lines already at rest. Until one exists,
     * report success so the sequence proceeds (matches spec: proceed flagged
     * on failure). */
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
    .disperse = ops_disperse,
    .disperse_run = ops_disperse_run,
    .membrane = ops_membrane,
    .busy = ops_busy,
    .seal_ok = ops_seal_ok,
    .self_test = ops_self_test,
    .event = ops_event,
};

/* ---- sensors (M-09) ------------------------------------------------------- */
/* What is actually on i2c0 of the carrier, measured (DEVLOG 2026-08-31):
 *   0x76  BME280            -> ambient temp, RH and pressure. Confirmed.
 *   0x40  INA226  V_in       -> bus voltage into hk_t.rail_mv[] and raw shunt
 *   0x44  INA226  5 V rail     voltage into hk_t.shunt_raw[]. Identified by
 *   0x45  INA226  3.3 V rail   their mfg/die IDs, not by address. Both
 *                              registers are absolute; amps are computed on
 *                              the ground from the shunt resistances
 *                              (10 / 15 / 10 / 50 mOhm), see ina226.h.
 *   --    INA226  24 V rail  -> not fitted yet. The rail keeps its slot in
 *                              hk_t and downlinks RAIL_MV_INVALID; an absent
 *                              part is not HKE_RAIL_FAIL.
 *   0x29  BNO055 IMU        -> accel and gyro, in the non-fusion ACCGYRO mode.
 *   or 0x28                    Which of the two is a board strap, not a
 *                              property of the part: 0x29 is the datasheet
 *                              default and COM3 carries an internal pull-up,
 *                              so bno055.c tries both and latches whichever
 *                              returns a whole ID block. The 2026-08-31
 *                              survey read the accel/mag/gyro IDs as 0x00 and
 *                              called the part faulted; it read them before
 *                              the part's 400 ms start-up and 650 ms boot
 *                              could have written them. bno055.c waits both
 *                              out and checks the IDs when they mean
 *                              something - and still reports HKE_IMU_FAIL,
 *                              with zeroed vectors, if they do not come up.
 * There is no chamber pressure sensor and no second humidity channel: the
 * Keller 23SY pair is off the design, and the HK fields they were to fill
 * went with them rather than being downlinked as zeros. */

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

    hk->error_flags = 0;

    /* The STLM20 pair is not fitted (board.h), and the pin the old map used
     * for ADC_TEMP1 is the membrane solenoid. Sampling an unconnected input
     * would produce a confident wrong temperature, so report none and say so.
     * Restore the datasheet conversion
     *     Vout = -11.69 mV/degC * T + 1.8663 V
     * when the parts and their real ADC channels exist. */
    hk->temp1_cc = 0;
    hk->temp2_cc = 0;
    hk->error_flags |= HKE_NO_TEMP;

#if !HAVE_MEMBRANE_SENSE
    /* A pico2 build has no GP30: HKV_MEMBRANE_PULLED is then always clear,
     * and without this flag ground would read that as "pushed". */
    hk->error_flags |= HKE_NO_MEMBRANE_SENSE;
#endif

    /* Solenoid current, raw ADC counts; the sentinel says "no pin in this
     * build", never 0, because 0 counts is what an idle solenoid reads. */
    hk->hb_sense_raw = hw_hb_sense_raw();

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

    /* The IMU is allowed to be late: bno055_read() returns false through the
     * 400 ms start-up and the 650 ms boot behind it, through a re-reset after
     * a bus glitch, and forever if the part really is faulted or absent. All
     * of those cases downlink zeros behind
     * HKE_IMU_FAIL, because a zero acceleration is a reading a working
     * accelerometer can produce and the flag is the only thing that says this
     * one is not. The bring-up runs from here rather than from hw_init() so
     * that it can also recover a part that drops out in flight. */
    if (!bno055_read(hw_monotonic_ms(), hk->accel_mg, hk->gyro_ddps)) {
        memset(hk->accel_mg, 0, sizeof hk->accel_mg);
        memset(hk->gyro_ddps, 0, sizeof hk->gyro_ddps);
        hk->error_flags |= HKE_IMU_FAIL;
    }

    /* Rail voltage and shunt voltage, per rail. A rail that does not answer
     * reports RAIL_MV_INVALID and not 0: 0 mV is a legitimate reading for a
     * rail whose supply is absent (V_in on a USB-powered bench), and
     * the two are different faults. One flag covers "at least one rail is
     * unreadable"; which one is in the field itself, because error_flags has
     * only eight bits.
     *
     * The two registers stand or fall together. They come from the same part
     * over the same bus microseconds apart, so a half-read entry would be a
     * distinction without a use - and a shunt_raw kept alongside an invalid
     * rail_mv is an amp reading for a rail whose voltage is unknown. */
    for (unsigned i = 0; i < INA_RAIL_COUNT; i++) {
        uint16_t mv;
        int16_t shunt;

        if (ina226_read_bus_mv((enum ina226_rail)i, &mv) &&
            ina226_read_shunt_raw((enum ina226_rail)i, &shunt)) {
            hk->rail_mv[i] = mv;
            hk->shunt_raw[i] = shunt;
        } else {
            hk->rail_mv[i] = RAIL_MV_INVALID;
            hk->shunt_raw[i] = 0;
            /* A rail with no monitor in the design reads as no reading, not
             * as a fault - HKE_RAIL_FAIL is for a part that should have
             * answered, and a permanently set flag stops being read. */
            if (ina226_fitted((enum ina226_rail)i))
                hk->error_flags |= HKE_RAIL_FAIL;
        }
    }
}

/* ---- init ----------------------------------------------------------------- */

void hw_init(void)
{
    /* The membrane pin is in this list deliberately: it must be an SIO output
     * driven low before anything else, so the solenoid is off by the MCU's own
     * action. Its PWM function is applied only while a drive is running.
     * The dispersion-motor pair is in it for a stronger reason: unlike the
     * membrane's driver input, GP17/GP18 have no measured external pull, so
     * before hw_init they are floating inputs and the motor's state at boot is
     * whatever its driver makes of that. Driving both low is what makes it
     * off. */
    const uint out_pins[] = {PIN_PINCH_1,      PIN_PINCH_2,
                             PIN_EQ1_OPEN,     PIN_EQ1_CLOSE,
                             PIN_EQ2_OPEN,     PIN_EQ2_CLOSE,
                             PIN_MEMBRANE_PWM, PIN_DISPERSE_FWD,
                             PIN_DISPERSE_REV};

    for (unsigned i = 0; i < sizeof out_pins / sizeof out_pins[0]; i++) {
        gpio_init(out_pins[i]);
        gpio_set_dir(out_pins[i], GPIO_OUT);
        gpio_put(out_pins[i], 0); /* everything de-energized at boot */
    }
    pulse_init(&pulses);
    sqwave_init(&membrane_wave);

#if HAVE_MEMBRANE_SENSE
    /* Membrane position switch: input, internal pull-up, switch to ground.
     * Pressed by the resting plunger (closed) reads 0; lifted when the
     * solenoid actuates (open) reads 1. Not in out_pins above and must never
     * be: driving it would look exactly like a stuck solenoid. */
    gpio_init(PIN_MEMBRANE_SENSE);
    gpio_set_dir(PIN_MEMBRANE_SENSE, GPIO_IN);
    gpio_pull_up(PIN_MEMBRANE_SENSE);
#endif
#if HAVE_HB_SENSE
    /* The ADC exists for one input: the motor current sense on GP46
     * (ADC6). adc_gpio_init() disables the pin's digital input and pulls, so
     * it cannot end up in out_pins by mistake and read back as something
     * driven. The STLM20 channels are still not sampled - those pins are
     * unpopulated, and a floating input yields a confident wrong number. */
    adc_init();
    adc_gpio_init(PIN_HB_SENSE);
#endif

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
    (void)ina226_init();
    /* Arms the IMU's bring-up without touching the bus: the BNO055 is still
     * inside its own 400 ms start-up (datasheet TSup) while this runs, so the
     * reset that starts its 650 ms boot is issued from the 1 Hz sweep once
     * that has elapsed. Nothing here waits for any of it. */
    bno055_init(hw_monotonic_ms());
}
