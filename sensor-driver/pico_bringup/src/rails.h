/*
 * Supply monitoring for the bring-up board: VSYS, die temperature, VBUS sense.
 *
 * What this can and cannot see, stated up front because it decides what the
 * numbers are worth:
 *
 *  - VSYS is read on GP29 (ADC3) through the Pico's 200k/100k divider, so the
 *    ADC sees VSYS/3.
 *  - The ADC's reference is ADC_VREF, which on a Pico is derived from the same
 *    3V3 rail that powers the chip. **Nothing here measures 3V3 directly**, and
 *    a sagging 3V3 does not show up as a low reading - it shifts every channel
 *    the other way, because the yardstick shrank with the thing being measured.
 *  - The one absolute quantity available is the temperature sensor's output,
 *    nominally 0.706 V at 27 C. If ADC_VREF fell, that channel's raw code would
 *    rise and the reported temperature would fall. So an implausible
 *    temperature - well below ambient, with no cooling to explain it - is
 *    evidence about the 3V3 rail, not about the die. The two channels together
 *    constrain the rail; neither does on its own.
 *  - The temperature constants are the datasheet's nominal, untrimmed values.
 *    Absolute accuracy is a few degrees. Trends and steps are trustworthy;
 *    absolute readings are not.
 */
#ifndef RAILS_H_
#define RAILS_H_

#include <stdbool.h>
#include <stdint.h>

typedef struct
{
    float vsys_v;   /*!< VSYS in volts, via the on-board /3 divider */
    float temp_c;   /*!< die temperature in degrees Celsius, untrimmed */
    bool vbus;      /*!< true when USB bus power is present */
} rails_sample_t;

/*!
 * @brief Power up the ADC, the temperature sensor and the VSYS divider input.
 */
void rails_init(void);

/*!
 * @brief Take one averaged reading of every channel.
 */
void rails_read(rails_sample_t *out);

/*!
 * @brief Print one reading as a single line, prefixed with a caller tag.
 */
void rails_print(const char *tag, const rails_sample_t *sample);

/*!
 * @brief Sample for a while and report min / mean / max per channel.
 *
 * One sample is not a measurement: a single ADC read catches noise, a
 * conversion glitch or a transient and reports it as a level. Anything that
 * matters here is a statement about a distribution.
 *
 * @param[in] duration_s : how long to sample for.
 * @param[in] interval_ms : delay between samples.
 */
void rails_profile(const char *tag, uint32_t duration_s, uint32_t interval_ms);

#endif /* RAILS_H_ */
