/* Bench tool: a timestamped trace of the four ACT_EC pins while the
 * dispersion motor turns, so the encoder lines can be told apart.
 * USB CDC output. NOT flight software - built only with
 * -DCLOUDS_BUILD_TOOLS=ON, and it DRIVES THE MOTOR.
 *
 * Why it exists: tools/encoder_pin_probe (2026-09-28) found the Faulhaber
 * IE3-1024L's lines on GP19 ACT_EC_AL, GP21 ACT_EC_IN1 and GP22 ACT_EC_IN2 -
 * they toggle only while the shaft turns - but its edge counts and state
 * histogram could not say which line is A, which is B, which is a
 * complement (the encoder's outputs are TIA-422 pairs and the carrier has no
 * receiver, so single legs of those pairs land on the pins) and which, if
 * any, is the index. That needs the ORDER of edges, not their number.
 *
 * What it does: every ACT_EC pin (GP19..GP22) a plain SIO input, pulls
 * untouched (GP19..GP25 are driver inputs on the schematic and an internal
 * pull could switch a load; the pads keep their reset state, as in flight).
 * The motor is driven as the flight image drives it (GP17 20 kHz PWM, GP18
 * low) and a tight loop reads SIO GPIO_IN, recording every change of the
 * four-bit state with the loop iteration it was seen on. The loop's period is
 * measured against the microsecond timer, so iteration numbers convert to
 * time. Nothing is decoded on the board: the trace is printed raw, one
 * transition per line, and analysed on the host, where mistakes are cheap.
 *
 * Captures, in order:
 *   1. motor at 50 %  - the speed the pin probe measured at (~3000 rpm)
 *   2. motor at 25 %  - a slower run: a real encoder scales, noise does not
 *   3. spin-down      - PWM off, shaft coasting, so no drive noise at all
 *   4. by hand        - motor off; if the shaft is turned within 20 s the
 *                       edges are captured with nothing else on the board
 *                       switching
 * Then motor off for good.
 *
 * Line format: "T <iter> <state>" with <state> the 4-bit value of
 * GP22 GP21 GP20 GP19 (bit 3..0) as one hex digit. "C <what> <iters>
 * <us> <n>" heads each capture with the iteration count, its duration in
 * microseconds and the number of transitions that follow.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/pwm.h"
#include "hardware/structs/sio.h"
#include "pico/stdlib.h"

#include "../core/pwmdiv.h"
#include "../hw/board.h"

#define PROBE_PWM_HZ 20000u
#define TRACE_BASE 19u  /* GP19 ACT_EC_AL */
#define TRACE_NPINS 4u  /* ..GP22 ACT_EC_IN2 */
#define TRACE_MASK (((1u << TRACE_NPINS) - 1u) << TRACE_BASE)
#define TRACE_MAX 6000u
#define TRACE_MAX_ITERS 40000000u /* ~0.5 s at the measured loop rate */

static uint32_t tr_iter[TRACE_MAX];
static uint8_t tr_state[TRACE_MAX];

static void motor(bool on, unsigned duty_pct)
{
    uint slice = pwm_gpio_to_slice_num(PIN_DISPERSE_FWD);
    uint32_t div16, period;

    gpio_put(PIN_DISPERSE_REV, 0); /* interlock: never both */
    if (!on) {
        pwm_set_enabled(slice, false);
        gpio_set_function(PIN_DISPERSE_FWD, GPIO_FUNC_SIO);
        gpio_set_dir(PIN_DISPERSE_FWD, GPIO_OUT);
        gpio_put(PIN_DISPERSE_FWD, 0);
        return;
    }
    pwmdiv_solve(clock_get_hz(clk_sys), PROBE_PWM_HZ, &div16, &period);
    pwm_set_clkdiv_int_frac(slice, (uint8_t)(div16 / 16u),
                            (uint8_t)(div16 % 16u));
    pwm_set_wrap(slice, (uint16_t)(period - 1u));
    pwm_set_gpio_level(PIN_DISPERSE_FWD,
                       (uint16_t)((uint64_t)period * duty_pct / 100u));
    gpio_set_function(PIN_DISPERSE_FWD, GPIO_FUNC_PWM);
    pwm_set_enabled(slice, true);
}

/* Records every change of the four-bit state until TRACE_MAX transitions or
 * TRACE_MAX_ITERS iterations. Returns the transition count; *iters and *us
 * get the loop length and its wall time so the host can scale. Only SIO is
 * touched inside the loop - no timer read, no function call - so the
 * iteration period is as constant as the core makes it. */
static uint32_t capture(uint32_t *iters, uint32_t *us)
{
    uint32_t n = 0, i = 0;
    uint32_t prev = sio_hw->gpio_in & TRACE_MASK;
    uint64_t t0 = time_us_64();

    while (i < TRACE_MAX_ITERS && n < TRACE_MAX) {
        uint32_t now = sio_hw->gpio_in & TRACE_MASK;

        if (now != prev) {
            tr_iter[n] = i;
            tr_state[n] = (uint8_t)(now >> TRACE_BASE);
            n++;
            prev = now;
        }
        i++;
    }
    *us = (uint32_t)(time_us_64() - t0);
    *iters = i;
    return n;
}

static void dump(const char *what, uint32_t n, uint32_t iters, uint32_t us)
{
    printf("C %s %lu %lu %lu\n", what, (unsigned long)iters,
           (unsigned long)us, (unsigned long)n);
    for (uint32_t k = 0; k < n; k++)
        printf("T %lu %x\n", (unsigned long)tr_iter[k], tr_state[k]);
}

int main(void)
{
    uint32_t n, iters, us;

    stdio_init_all();

    /* Actuator lines de-energized before anything else, as in hw_init(). */
    const uint out_pins[] = {PIN_DISPERSE_FWD, PIN_DISPERSE_REV,
                             PIN_MEMBRANE_PWM};
    for (unsigned i = 0; i < 3; i++) {
        gpio_init(out_pins[i]);
        gpio_set_dir(out_pins[i], GPIO_OUT);
        gpio_put(out_pins[i], 0);
    }
    for (uint p = TRACE_BASE; p < TRACE_BASE + TRACE_NPINS; p++) {
        gpio_init(p);
        gpio_set_dir(p, GPIO_IN);
    }

    while (!stdio_usb_connected())
        sleep_ms(100);
    sleep_ms(500);

    printf("\n=== encoder trace probe (bench tool) - DRIVES THE MOTOR ===\n");
    printf("pins GP%u..GP%u (bit0 = GP%u), drive GP%u fwd PWM @ %u Hz, "
           "GP%u rev low\n", TRACE_BASE, TRACE_BASE + TRACE_NPINS - 1u,
           TRACE_BASE, PIN_DISPERSE_FWD, PROBE_PWM_HZ, PIN_DISPERSE_REV);
    printf("static %x\n", (unsigned)((sio_hw->gpio_in & TRACE_MASK) >> TRACE_BASE));

    /* 1. 50 % */
    motor(true, 50);
    sleep_ms(1500);
    n = capture(&iters, &us);
    dump("duty50", n, iters, us);

    /* 2. 25 % */
    motor(true, 25);
    sleep_ms(1500);
    n = capture(&iters, &us);
    dump("duty25", n, iters, us);

    /* 3. coasting */
    motor(true, 50);
    sleep_ms(1500);
    motor(false, 0);
    sleep_ms(30);
    n = capture(&iters, &us);
    dump("coast", n, iters, us);
    motor(false, 0);

    /* 4. by hand: wait up to 20 s for the first edge, then capture. */
    printf("H turn the shaft BY HAND now (20 s)\n");
    {
        uint64_t end = time_us_64() + 20000000u;
        uint32_t prev = sio_hw->gpio_in & TRACE_MASK;
        bool moved = false;

        while (time_us_64() < end) {
            if ((sio_hw->gpio_in & TRACE_MASK) != prev) {
                moved = true;
                break;
            }
        }
        if (moved) {
            n = capture(&iters, &us);
            dump("hand", n, iters, us);
        } else {
            printf("C hand 0 0 0\n");
        }
    }

    printf("=== done, motor off. Reflash the flight image. ===\n");
    for (;;) {
        motor(false, 0);
        sleep_ms(1000);
    }
}
