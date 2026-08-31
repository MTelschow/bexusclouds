/* PWM divider/wrap solver (M-07 membrane drive).
 *
 * Lives in core/ rather than hw/ because the bug it exists to prevent was a
 * wrong output frequency: ops_membrane once set wrap=999 with the default
 * divider, which is 150 kHz on a 150 MHz part rather than the configured
 * 50 Hz, and a push-pull solenoid at 150 kHz only sees a DC average. Pure
 * arithmetic here means the native suite can check the numbers.
 */
#ifndef CLOUDS_PWMDIV_H
#define CLOUDS_PWMDIV_H

#include <stdint.h>

/* RP2xxx PWM limits: divider is 8.4 fixed point (1/16 steps, max 255+15/16)
 * and the counter wraps at 16 bits. */
#define PWMDIV_MIN_DIV16 16u
#define PWMDIV_MAX_DIV16 4095u
#define PWMDIV_MAX_WRAP 65536u

/* Slowest frequency the hardware can produce from sys_hz. Below this a
 * request cannot be honoured and must be clamped, not silently mistuned. */
uint32_t pwmdiv_min_hz(uint32_t sys_hz);

/* Solve for the divider (in 1/16 steps) and counter period that put the
 * output closest to target_hz, preferring the smallest divider so the duty
 * keeps the most resolution. Both outputs are clamped to the hardware range.
 * *wrap_period is the full period in counts, i.e. what pwm_set_wrap() takes
 * plus one. */
void pwmdiv_solve(uint32_t sys_hz, uint32_t target_hz, uint32_t *div16,
                  uint32_t *wrap_period);

/* Frequency a given divider/period actually yields, for verification. */
uint32_t pwmdiv_actual_hz(uint32_t sys_hz, uint32_t div16,
                          uint32_t wrap_period);

#endif
