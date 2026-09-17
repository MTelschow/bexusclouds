/* Bench tool: is the membrane position switch on GP30 wired, and does it
 * follow the solenoid? USB CDC output, like bno055_probe. NOT flight software
 * - built only with -DCLOUDS_BUILD_TOOLS=ON, and it drives the membrane.
 *
 * Why it exists: the first on-carrier run of PIN_MEMBRANE_SENSE (2026-09-17)
 * read the switch as "pulled" (LOW) in every 1 Hz HK packet, drive on or off.
 * HK cannot separate the candidate causes - a switch that is closed at rest
 * and opens when the plunger moves (inverted sense), a line held low by the
 * board or a wiring short, a solenoid that never moves, or a button on some
 * other pin - so this samples the pin directly, against known drive states,
 * and then watches it live so the button can be pressed by hand.
 *
 * Sequence:
 *   1. passive pull survey of GP30/31/32: pu / pd reads. pu=0 pd=0 = held
 *      low externally (closed switch, or a short); pu=1 pd=0 = floating,
 *      nothing holds it; pu=1 pd=1 = driven high.
 *   2. GP26 (the solenoid drive) held LOW then HIGH, 700 ms each, x3, GP30
 *      sampled with the internal pull-up in each state.
 *   3. 2 Hz / 60 % on GP26 for 6 s, GP26 and GP30 sampled every 20 ms and
 *      printed side by side, one line per second.
 *   4. the H-bridge (ACT_HB_IN1/IN2, GP17/GP18 - the "dispersion motor" of
 *      board.h): forward, off, reverse, off, GP30 sampled in each. If the
 *      push-pull solenoid is in fact on the bridge, this is what lifts it.
 *   5. drive off, then a live watch: GP30 printed on every change, forever.
 *      Press the button by hand here.
 *
 * Switch sense (from the mechanics, 2026-09-17): pressed by the resting
 * plunger = LOW; lifted when the solenoid actuates = HIGH.
 */
#include <stdbool.h>
#include <stdio.h>
#include "hardware/gpio.h"
#include "pico/stdlib.h"
#include "../hw/board.h"
#include "../hw/hw.h"

static void survey(uint pin)
{
    bool pu, pd;

    gpio_init(pin);
    gpio_set_dir(pin, GPIO_IN);
    gpio_pull_up(pin);
    sleep_ms(2);
    pu = gpio_get(pin);
    gpio_set_pulls(pin, false, true);
    sleep_ms(2);
    pd = gpio_get(pin);
    gpio_set_pulls(pin, false, false);
    printf("GP%-2u: pu=%d pd=%d -> %s\n", pin, pu, pd,
           (!pu && !pd) ? "held LOW externally (closed switch / short / pull-down)"
           : (pu && pd) ? "driven HIGH externally"
           : (pu && !pd) ? "floating: follows the pull, nothing holds it"
                         : "pu=0 pd=1 - not a state a pin can be in");
}

static unsigned count_high(uint pin, unsigned n, unsigned gap_ms)
{
    unsigned hi = 0;
    for (unsigned i = 0; i < n; i++) {
        hi += gpio_get(pin);
        sleep_ms(gap_ms);
    }
    return hi;
}

int main(void)
{
    stdio_init_all();
    hw_init(); /* GP26 SIO output low; GP30 input with pull-up (carrier build) */

    while (!stdio_usb_connected())
        sleep_ms(100);
    sleep_ms(500);

    printf("\n=== membrane switch probe (bench tool) ===\n");
    printf("PIN_MEMBRANE_SENSE = GP%u, PIN_MEMBRANE_PWM = GP%u, NUM_BANK0_GPIOS = %u\n",
           PIN_MEMBRANE_SENSE, PIN_MEMBRANE_PWM, NUM_BANK0_GPIOS);

    printf("\n-- 1. passive pull survey (drive low) --\n");
    survey(30);
    survey(31);
    survey(32);
    printf("   24 V regulator pins, read only (GP39 VR_24V_EN, GP40 VR_24V_PG):\n");
    survey(39);
    survey(40);

    /* restore the flight configuration of the sense pin */
    gpio_init(PIN_MEMBRANE_SENSE);
    gpio_set_dir(PIN_MEMBRANE_SENSE, GPIO_IN);
    gpio_pull_up(PIN_MEMBRANE_SENSE);

    printf("\n-- 2. steady drive states, GP30 with pull-up (20 samples each) --\n");
    for (unsigned rep = 0; rep < 3; rep++) {
        unsigned hi;
        gpio_put(PIN_MEMBRANE_PWM, 0);
        sleep_ms(300);
        hi = count_high(PIN_MEMBRANE_SENSE, 20, 20);
        printf("GP26=0 (released): GP30 high %2u/20\n", hi);
        gpio_put(PIN_MEMBRANE_PWM, 1);
        sleep_ms(300);
        hi = count_high(PIN_MEMBRANE_SENSE, 20, 20);
        printf("GP26=1 (energized): GP30 high %2u/20\n", hi);
    }
    gpio_put(PIN_MEMBRANE_PWM, 0);

    printf("\n-- 3. 2 Hz / 60 %% on GP26 for 6 s; 20 ms samples, 1 line/s --\n");
    printf("   (# = high, . = low)\n");
    for (unsigned s = 0; s < 6; s++) {
        char d[51], g[51];
        for (unsigned i = 0; i < 50; i++) {
            unsigned ms = (s * 1000u + i * 20u) % 500u; /* 2 Hz period */
            bool level = ms < 300u;                      /* 60 % high */
            gpio_put(PIN_MEMBRANE_PWM, level);
            sleep_ms(20);
            d[i] = level ? '#' : '.';
            g[i] = gpio_get(PIN_MEMBRANE_SENSE) ? '#' : '.';
        }
        d[50] = g[50] = 0;
        printf("t=%u  GP26 %s\n      GP30 %s\n", s + 1, d, g);
    }
    gpio_put(PIN_MEMBRANE_PWM, 0);

    printf("\n-- 4. H-bridge GP17/GP18, GP30 with pull-up (20 samples each) --\n");
    for (unsigned rep = 0; rep < 2; rep++) {
        unsigned hi;
        gpio_put(PIN_DISPERSE_REV, 0);
        gpio_put(PIN_DISPERSE_FWD, 1);
        sleep_ms(400);
        hi = count_high(PIN_MEMBRANE_SENSE, 20, 20);
        printf("HB fwd (GP17=1 GP18=0): GP30 high %2u/20\n", hi);
        sleep_ms(600);
        gpio_put(PIN_DISPERSE_FWD, 0);
        sleep_ms(400);
        hi = count_high(PIN_MEMBRANE_SENSE, 20, 20);
        printf("HB off (GP17=0 GP18=0): GP30 high %2u/20\n", hi);
        gpio_put(PIN_DISPERSE_REV, 1);
        sleep_ms(400);
        hi = count_high(PIN_MEMBRANE_SENSE, 20, 20);
        printf("HB rev (GP17=0 GP18=1): GP30 high %2u/20\n", hi);
        sleep_ms(600);
        gpio_put(PIN_DISPERSE_REV, 0);
        sleep_ms(400);
        hi = count_high(PIN_MEMBRANE_SENSE, 20, 20);
        printf("HB off (GP17=0 GP18=0): GP30 high %2u/20\n", hi);
    }
    gpio_put(PIN_DISPERSE_FWD, 0);
    gpio_put(PIN_DISPERSE_REV, 0);

    printf("\n-- 5. all drives off. live watch: press the button by hand. --\n");
    {
        bool last = gpio_get(PIN_MEMBRANE_SENSE);
        uint32_t t0 = to_ms_since_boot(get_absolute_time());
        printf("t=%6lu ms  GP30=%d (%s)\n", 0ul, last, last ? "HIGH / lifted = actuated" : "LOW / pressed = resting");
        for (;;) {
            bool now = gpio_get(PIN_MEMBRANE_SENSE);
            if (now != last) {
                printf("t=%6lu ms  GP30=%d (%s)\n",
                       (unsigned long)(to_ms_since_boot(get_absolute_time()) - t0),
                       now, now ? "HIGH / lifted = actuated" : "LOW / pressed = resting");
                last = now;
            }
            sleep_ms(5);
        }
    }
}
