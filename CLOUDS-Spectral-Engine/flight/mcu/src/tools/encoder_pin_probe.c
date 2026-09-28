/* Bench tool: which carrier pins does the dispersion motor encoder land on?
 * USB CDC output, like the other probes. NOT flight software - built only
 * with -DCLOUDS_BUILD_TOOLS=ON, and it DRIVES THE MOTOR.
 *
 * Why it exists: the first flight image with the encoder (2026-09-28) read
 * motor_rpm = 0 through a DISPERSE run with the motor visibly turning. The
 * counter is on GP31/GP32 (hw/board.h PIN_ENC_A), and those pins were a
 * placeholder - nobody knew where the encoder, or its TIA-422 receiver, is
 * actually wired. HK cannot answer that; counting edges on every pin can.
 *
 * Every GPIO except the three actuator drive lines is made a plain SIO input
 * and never driven. Pulls are NOT touched: GP19..GP25 are relay / driver
 * inputs and GP39 is the 24 V regulator enable, and an internal pull-up on
 * one of those could switch a load. The pads keep their reset pull state,
 * which is also what the flight image leaves them in.
 *
 * Sequence:
 *   1. static levels of every sampled pin, motor off.
 *   2. three rounds of: motor OFF 3 s, then motor ON (GP17 20 kHz PWM at
 *      PROBE_DUTY_PCT, GP18 low - the flight forward drive) with 500 ms
 *      spin-up and a 3 s window. Edges counted per pin in each window.
 *      A pin that toggles only while the motor runs is an encoder line; one
 *      that toggles in both windows is noise, the Pi's UART (GP1), or a
 *      floating pad.
 *   3. motor off, 10 x 1 s windows: turn the shaft BY HAND here. Pins that
 *      count now carry the encoder with no PWM noise in the picture.
 *   4. phase: the pins that toggled only with the motor on (up to four)
 *      are sampled together during a 2 s drive, and every change of their
 *      joint state is tallied. A quadrature pair steps 00-01-11-10 (only one
 *      bit changes per step); a line and its complement are never equal; an
 *      index pulse is short and rare. Prints the fraction of time each pair
 *      is equal and the per-step bit-change counts.
 *   5. motor off for good, idle.
 *
 * Reading the numbers: a 1024-line channel gives 2048 edges per revolution,
 * so a pin's edges/s x 60 / 2048 is the rpm it implies. A and B of one
 * encoder show near-identical counts. A differential line wired straight to
 * a pin (no receiver) may still count, but noisily.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/pwm.h"
#include "pico/stdlib.h"

#include "../core/pwmdiv.h"
#include "../hw/board.h"

#define PROBE_DUTY_PCT 50u
#define PROBE_PWM_HZ 20000u
#define NPINS NUM_BANK0_GPIOS

static bool sampled(uint pin)
{
    return pin != PIN_DISPERSE_FWD && pin != PIN_DISPERSE_REV &&
           pin != PIN_MEMBRANE_PWM;
}

static const char *net(uint pin)
{
    static const char *const names[48] = {
        "RP->PI", "RP<-PI", "PI_RTS", "PI_CTS", "SPI_0_MISO", "SD_1_SENS",
        "SPI_0_SCK", "SPI_0_MOSI", "SPI_1_MISO", "SPI_1_CS1", "SPI_1_SCK",
        "SPI_1_MOSI", "SPI_1_CS2", "SPI_1_CS3", "SD_1_CS", "SD_2_SENS",
        "SD_2_CS", "ACT_HB_IN1", "ACT_HB_IN2", "ACT_EC_AL", "ACT_EC_EN",
        "ACT_EC_IN1", "ACT_EC_IN2", "ACT_R_4", "ACT_R_3", "ACT_R_2",
        "ACT_R_1", "BNO_INT", "SDA_0", "SCL_0", "membrane sw", "(unnamed)",
        "(unnamed)", "DEBUG_LED", "DEBUG_SENS", "INA_3V3_ALERT",
        "INA_5V_ALERT", "INA_VIN_ALERT", "INA_24V_ALERT", "VR_24V_EN",
        "VR_24V_PG", "ADC_1", "ADC_2", "ADC_3", "ADC_4", "ADC_5",
        "ACT_HB_SENS", "SPI_1_CS4"};
    return pin < 48 ? names[pin] : "?";
}

static void motor(bool on)
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
                       (uint16_t)((uint64_t)period * PROBE_DUTY_PCT / 100u));
    gpio_set_function(PIN_DISPERSE_FWD, GPIO_FUNC_PWM);
    pwm_set_enabled(slice, true);
}

/* Count edges on every sampled pin for ms milliseconds. Returns the number
 * of samples taken, so the sample rate can be printed beside the counts. */
static uint32_t count_edges(uint32_t ms, uint32_t edges[NPINS], uint64_t mask)
{
    uint64_t prev = gpio_get_all64() & mask;
    uint64_t end = time_us_64() + (uint64_t)ms * 1000u;
    uint32_t n = 0;

    for (uint i = 0; i < NPINS; i++)
        edges[i] = 0;
    while (time_us_64() < end) {
        /* inner burst without the timer read, to keep the rate up */
        for (unsigned k = 0; k < 64; k++) {
            uint64_t now = gpio_get_all64() & mask;
            uint64_t d = now ^ prev;
            while (d) {
                edges[__builtin_ctzll(d)]++;
                d &= d - 1;
            }
            prev = now;
        }
        n += 64;
    }
    return n;
}

static void report(const char *what, uint32_t ms, uint32_t samples,
                   const uint32_t edges[NPINS])
{
    bool any = false;

    printf("%s: %lu samples in %lu ms (%.2f MS/s)\n", what,
           (unsigned long)samples, (unsigned long)ms,
           samples / (ms * 1000.0));
    for (uint i = 0; i < NPINS; i++) {
        if (!edges[i])
            continue;
        any = true;
        printf("   GP%-2u %-14s %8lu edges  -> %7.0f rpm if 1024-line\n", i,
               net(i), (unsigned long)edges[i],
               edges[i] * 60000.0 / ms / 2048.0);
    }
    if (!any)
        printf("   (no pin changed)\n");
}

int main(void)
{
    static uint32_t edges[NPINS];
    uint64_t mask = 0;

    stdio_init_all();

    /* The three actuator lines de-energized before anything else, as in
     * hw_init(): the motor pair and the membrane solenoid. */
    const uint out_pins[] = {PIN_DISPERSE_FWD, PIN_DISPERSE_REV,
                             PIN_MEMBRANE_PWM};
    for (unsigned i = 0; i < 3; i++) {
        gpio_init(out_pins[i]);
        gpio_set_dir(out_pins[i], GPIO_OUT);
        gpio_put(out_pins[i], 0);
    }
    /* Everything else: plain input, pulls untouched (see the header). */
    for (uint i = 0; i < NPINS; i++) {
        if (!sampled(i))
            continue;
        gpio_init(i);
        gpio_set_dir(i, GPIO_IN);
        mask |= 1ull << i;
    }

    /* The motor never runs before someone is watching. */
    while (!stdio_usb_connected())
        sleep_ms(100);
    sleep_ms(500);

    printf("\n=== encoder pin probe (bench tool) - DRIVES THE MOTOR ===\n");
    printf("NUM_BANK0_GPIOS = %u, drive GP%u fwd PWM %u %% @ %u Hz, "
           "GP%u rev low, GP%u membrane low\n",
           NPINS, PIN_DISPERSE_FWD, PROBE_DUTY_PCT, PROBE_PWM_HZ,
           PIN_DISPERSE_REV, PIN_MEMBRANE_PWM);
    printf("flight counter expects A = GP%u, B = GP%u\n", PIN_ENC_A,
           PIN_ENC_B);

    printf("\n-- 1. static levels, motor off --\n");
    {
        uint64_t v = gpio_get_all64();
        for (uint i = 0; i < NPINS; i++)
            if (sampled(i))
                printf("   GP%-2u %-14s %d\n", i, net(i),
                       (int)((v >> i) & 1u));
    }

    printf("\n-- 2. motor off vs on, 3 rounds --\n");
    for (unsigned r = 1; r <= 3; r++) {
        char label[32];
        uint32_t n;

        motor(false);
        sleep_ms(500);
        n = count_edges(3000, edges, mask);
        snprintf(label, sizeof label, "round %u OFF", r);
        report(label, 3000, n, edges);

        motor(true);
        sleep_ms(500); /* spin-up */
        n = count_edges(3000, edges, mask);
        motor(false);
        snprintf(label, sizeof label, "round %u ON ", r);
        report(label, 3000, n, edges);
    }
    motor(false);

    /* The live pins: toggled in the last ON window and (almost) not in the
     * OFF window before it. */
    {
        static uint32_t off[NPINS], on[NPINS];
        uint live[4], nl = 0;

        motor(false);
        sleep_ms(500);
        count_edges(1000, off, mask);
        motor(true);
        sleep_ms(500);
        count_edges(1000, on, mask);
        for (uint i = 0; i < NPINS && nl < 4; i++)
            if (on[i] > 1000u && on[i] > 20u * off[i] + 100u)
                live[nl++] = i;

        printf("\n-- 4. phase of the %u live pin(s):", nl);
        for (uint j = 0; j < nl; j++)
            printf(" GP%u", live[j]);
        printf(" (bit j = j-th pin) --\n");
        if (nl >= 2) {
            static uint32_t hist[16], flips[5], eq[4][4];
            uint64_t end = time_us_64() + 2000000u;
            uint32_t n = 0;
            uint prev_st = 0;
            bool first = true;

            while (time_us_64() < end) {
                for (unsigned k = 0; k < 64; k++) {
                    uint64_t v = gpio_get_all64();
                    uint st = 0;
                    for (uint j = 0; j < nl; j++)
                        st |= (uint)((v >> live[j]) & 1u) << j;
                    hist[st]++;
                    for (uint a = 0; a < nl; a++)
                        for (uint b = a + 1; b < nl; b++)
                            eq[a][b] += ((st >> a) & 1u) == ((st >> b) & 1u);
                    if (!first && st != prev_st)
                        flips[__builtin_popcount(st ^ prev_st)]++;
                    prev_st = st;
                    first = false;
                }
                n += 64;
            }
            motor(false);
            printf("   state histogram (%lu samples):\n", (unsigned long)n);
            for (uint st = 0; st < (1u << nl); st++)
                printf("     %c%c%c%c  %5.1f %%\n",
                       nl > 3 ? '0' + ((st >> 3) & 1) : ' ',
                       nl > 2 ? '0' + ((st >> 2) & 1) : ' ',
                       '0' + ((st >> 1) & 1), '0' + (st & 1),
                       100.0 * hist[st] / n);
            printf("   state changes by bits flipped at once: 1=%lu 2=%lu "
                   "3=%lu 4=%lu\n", (unsigned long)flips[1],
                   (unsigned long)flips[2], (unsigned long)flips[3],
                   (unsigned long)flips[4]);
            for (uint a = 0; a < nl; a++)
                for (uint b = a + 1; b < nl; b++)
                    printf("   GP%u == GP%u  %5.1f %% of samples "
                           "(quadrature ~50, complement ~0, copy ~100)\n",
                           live[a], live[b], 100.0 * eq[a][b] / n);
        }
        motor(false);
    }

    printf("\n-- 3. motor off: TURN THE SHAFT BY HAND now, 10 x 1 s --\n");
    for (unsigned s = 1; s <= 10; s++) {
        char label[32];
        uint32_t n = count_edges(1000, edges, mask);
        snprintf(label, sizeof label, "hand %2u", s);
        report(label, 1000, n, edges);
    }

    printf("\n=== done, motor off. Reflash the flight image. ===\n");
    for (;;) {
        motor(false);
        sleep_ms(1000);
    }
}
