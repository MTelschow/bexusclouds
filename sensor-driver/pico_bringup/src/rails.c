#include "rails.h"

#include <stdio.h>

#include "hardware/adc.h"
#include "pico/stdlib.h"

#include "board_pins.h"

#ifndef PICO_VSYS_PIN
#error "This board header defines no PICO_VSYS_PIN - VSYS cannot be read here."
#endif

/* The sensor harness must not land on the ADC pins, or the survey would drive
 * the very inputs this module reads. Caught at compile time rather than shown
 * as a wrong voltage. */
#if (BMV080_PIN_MISO == PICO_VSYS_PIN) || (BMV080_PIN_MOSI == PICO_VSYS_PIN) ||                     \
    (BMV080_PIN_SCK == PICO_VSYS_PIN) || (BMV080_PIN_CS1 == PICO_VSYS_PIN)
#error "A BMV080 bus pin collides with PICO_VSYS_PIN."
#endif
#if (BMV080_PIN_CS2 != BMV080_PIN_NONE) && (BMV080_PIN_CS2 == PICO_VSYS_PIN)
#error "BMV080_PIN_CS2 collides with PICO_VSYS_PIN."
#endif

/* ADC channel for GP26..GP29 on RP2040 and RP2350A (QFN-60). */
#define VSYS_ADC_CHANNEL (PICO_VSYS_PIN - 26u)

/* 12-bit ADC against a nominal 3.3 V reference. */
#define ADC_VREF_V 3.3f
#define ADC_FULL_SCALE 4096.0f

/* The Pico's VSYS divider is 200k over 100k, i.e. the ADC sees VSYS/3. */
#define VSYS_DIVIDER 3.0f

/* Datasheet nominal, untrimmed: T = 27 - (V - 0.706) / 0.001721 */
#define TEMP_V_AT_27C 0.706f
#define TEMP_V_PER_C 0.001721f

/* Averaged per reading. The ADC's own noise is a couple of LSB; a single
 * conversion is not worth printing to three decimal places. */
#define SAMPLES_PER_READING 64u

static uint16_t read_averaged(uint channel)
{
    adc_select_input(channel);

    uint32_t accumulator = 0;
    for (uint32_t i = 0; i < SAMPLES_PER_READING; i++)
    {
        accumulator += adc_read();
    }

    return (uint16_t)(accumulator / SAMPLES_PER_READING);
}

void rails_init(void)
{
    adc_init();
    adc_gpio_init(PICO_VSYS_PIN);
    adc_set_temp_sensor_enabled(true);

#ifdef PICO_VBUS_PIN
    gpio_init(PICO_VBUS_PIN);
    gpio_set_dir(PICO_VBUS_PIN, GPIO_IN);
#endif

    /* The temperature sensor needs a moment after being powered up. */
    sleep_ms(10);
}

void rails_read(rails_sample_t *out)
{
    if (out == NULL)
    {
        return;
    }

    const float lsb_v = ADC_VREF_V / ADC_FULL_SCALE;

    out->vsys_v = (float)read_averaged(VSYS_ADC_CHANNEL) * lsb_v * VSYS_DIVIDER;

    float temp_v = (float)read_averaged(ADC_TEMPERATURE_CHANNEL_NUM) * lsb_v;
    out->temp_c = 27.0f - ((temp_v - TEMP_V_AT_27C) / TEMP_V_PER_C);

#ifdef PICO_VBUS_PIN
    out->vbus = gpio_get(PICO_VBUS_PIN);
#else
    out->vbus = false;
#endif
}

void rails_print(const char *tag, const rails_sample_t *sample)
{
    printf("%s  VSYS %.3f V   die %.1f C   VBUS %s\r\n", tag, sample->vsys_v, sample->temp_c,
           sample->vbus ? "present" : "absent");
}

void rails_profile(const char *tag, uint32_t duration_s, uint32_t interval_ms)
{
    if (interval_ms == 0u)
    {
        interval_ms = 100u;
    }

    rails_sample_t sample;
    rails_read(&sample);

    float vsys_min = sample.vsys_v;
    float vsys_max = sample.vsys_v;
    float vsys_sum = sample.vsys_v;
    float temp_min = sample.temp_c;
    float temp_max = sample.temp_c;
    float temp_sum = sample.temp_c;
    uint32_t count = 1;
    bool vbus_ever_absent = !sample.vbus;

    const absolute_time_t deadline = make_timeout_time_ms(duration_s * 1000u);
    while (absolute_time_diff_us(get_absolute_time(), deadline) > 0)
    {
        sleep_ms(interval_ms);
        rails_read(&sample);

        if (sample.vsys_v < vsys_min)
        {
            vsys_min = sample.vsys_v;
        }
        if (sample.vsys_v > vsys_max)
        {
            vsys_max = sample.vsys_v;
        }
        if (sample.temp_c < temp_min)
        {
            temp_min = sample.temp_c;
        }
        if (sample.temp_c > temp_max)
        {
            temp_max = sample.temp_c;
        }
        vsys_sum += sample.vsys_v;
        temp_sum += sample.temp_c;
        count++;

        if (!sample.vbus)
        {
            vbus_ever_absent = true;
        }
    }

    printf("%s  %lu samples over %lu s\r\n", tag, (unsigned long)count, (unsigned long)duration_s);
    printf("%s    VSYS  min %.3f  mean %.3f  max %.3f V  (span %.0f mV)\r\n", tag, vsys_min,
           vsys_sum / (float)count, vsys_max, (vsys_max - vsys_min) * 1000.0f);
    printf("%s    die   min %.1f  mean %.1f  max %.1f C\r\n", tag, temp_min,
           temp_sum / (float)count, temp_max);
    printf("%s    VBUS  %s\r\n", tag, vbus_ever_absent ? "DROPPED during the window" : "present throughout");
}
