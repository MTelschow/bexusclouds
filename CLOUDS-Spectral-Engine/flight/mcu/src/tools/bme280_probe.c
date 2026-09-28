/* BME280 bring-up probe - a BENCH TOOL, not flight software.
 *
 * Built as its own target (bme280_probe), never linked into clouds_fsw_mcu.
 * It exists because HKE_BME280_CHM_FAIL is one bit, and one bit cannot say
 * whether the chamber part is on another chip select, wants another SPI
 * mode, or was wired to i2c0 instead.
 *
 * Output is USB CDC only; UART stdio stays off (uart0 is the HK downlink).
 *
 * hw_init() runs first because it drives every actuator line low and brings
 * up i2c0 and spi1. No actuator is commanded below.
 *
 * Every second it reads CHIP_ID (0xD0, expect 0x60) from:
 *   - spi1 behind each of the four SPI_1 chip selects (GP9, GP12, GP13,
 *     GP47), in mode 0 and in mode 3, at 100 kHz and at SPI1_BAUD_HZ;
 *   - i2c0 at 0x76 and 0x77.
 * and prints the whole table when it changes, so a part can be plugged or
 * reseated while watching.
 */
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "hardware/gpio.h"
#include "hardware/i2c.h"
#include "hardware/spi.h"
#include "pico/stdlib.h"

#include "../hw/board.h"
#include "../hw/hw.h"

#define REG_CHIP_ID 0xD0
#define BME_CHIP_ID 0x60
#define TIMEOUT_US 8000
#define WATCH_S 120u

static const uint8_t CS_PINS[] = {9, 12, 13, 47};
static const uint8_t I2C_ADDRS[] = {0x76, 0x77};
static const unsigned BAUDS[] = {100 * 1000, SPI1_BAUD_HZ};

static uint8_t spi_chip_id(uint8_t cs, bool mode3, unsigned baud)
{
    uint8_t a = REG_CHIP_ID | 0x80u, id = 0;

    spi_set_baudrate(spi1, baud);
    spi_set_format(spi1, 8, mode3 ? SPI_CPOL_1 : SPI_CPOL_0,
                   mode3 ? SPI_CPHA_1 : SPI_CPHA_0, SPI_MSB_FIRST);
    gpio_put(cs, 0);
    spi_write_blocking(spi1, &a, 1);
    spi_read_blocking(spi1, 0, &id, 1);
    gpio_put(cs, 1);
    return id;
}

static int i2c_chip_id(uint8_t addr)
{
    uint8_t reg = REG_CHIP_ID, id = 0;

    if (i2c_write_timeout_us(i2c0, addr, &reg, 1, true, TIMEOUT_US) < 0)
        return -1;
    if (i2c_read_timeout_us(i2c0, addr, &id, 1, false, TIMEOUT_US) < 0)
        return -1;
    return id;
}

/* Bit-banged mode-0 read with an arbitrary MOSI/MISO pair, so a harness
 * with SDI and SDO crossed is found too. spi1 is released from the pins for
 * the duration and handed back afterwards. */
static uint8_t bb_chip_id(uint8_t cs, uint8_t mosi, uint8_t miso)
{
    uint8_t a = REG_CHIP_ID | 0x80u, id = 0;
    const uint8_t pins[3] = {PIN_SPI1_MISO, PIN_SPI1_SCK, PIN_SPI1_MOSI};

    for (int i = 0; i < 3; i++)
        gpio_init(pins[i]);
    gpio_set_dir(PIN_SPI1_SCK, GPIO_OUT);
    gpio_put(PIN_SPI1_SCK, 0);
    gpio_set_dir(mosi, GPIO_OUT);
    gpio_set_dir(miso, GPIO_IN);
    gpio_put(cs, 0);
    busy_wait_us(5);
    for (int i = 7; i >= 0; i--) {
        gpio_put(mosi, (a >> i) & 1);
        busy_wait_us(5);
        gpio_put(PIN_SPI1_SCK, 1);
        busy_wait_us(5);
        gpio_put(PIN_SPI1_SCK, 0);
    }
    gpio_put(mosi, 0);
    for (int i = 7; i >= 0; i--) {
        busy_wait_us(5);
        gpio_put(PIN_SPI1_SCK, 1);
        id |= (uint8_t)(gpio_get(miso) << i);
        busy_wait_us(5);
        gpio_put(PIN_SPI1_SCK, 0);
    }
    gpio_put(cs, 1);
    for (int i = 0; i < 3; i++)
        gpio_set_function(pins[i], GPIO_FUNC_SPI);
    return id;
}

static void scan(char *out, size_t len)
{
    size_t n = 0;

    out[0] = '\0';
    /* Pads default to pull-down, so an undriven MISO reads 0x00. With a
     * pull-up it reads 0xFF instead - that separates "nothing drives MISO"
     * from "a part drives it low". */
    gpio_pull_up(PIN_SPI1_MISO);
    n += (size_t)snprintf(out + n, len - n,
                          "  MISO GP8 pulled up, CS GP9 mode 0: 0x%02X\n",
                          spi_chip_id(9, false, BAUDS[0]));
    gpio_pull_down(PIN_SPI1_MISO);
    for (size_t c = 0; c < sizeof CS_PINS; c++) {
        uint8_t id = bb_chip_id(CS_PINS[c], PIN_SPI1_MISO, PIN_SPI1_MOSI);

        n += (size_t)snprintf(out + n, len - n,
                              "  bitbang CS GP%-2u MOSI/MISO SWAPPED: 0x%02X%s\n",
                              CS_PINS[c], id,
                              id == BME_CHIP_ID ? "  <-- BME280" : "");
    }
    n += (size_t)snprintf(out + n, len - n, "  i2c0 ACK:");
    for (uint8_t a = 0x08; a < 0x78; a++) {
        uint8_t d;

        if (i2c_read_timeout_us(i2c0, a, &d, 1, false, TIMEOUT_US) >= 0)
            n += (size_t)snprintf(out + n, len - n, " 0x%02X", a);
    }
    n += (size_t)snprintf(out + n, len - n, "\n");
    for (size_t c = 0; c < sizeof CS_PINS; c++)
        for (int m = 0; m < 2; m++)
            for (size_t b = 0; b < sizeof BAUDS / sizeof BAUDS[0]; b++) {
                uint8_t id = spi_chip_id(CS_PINS[c], m, BAUDS[b]);

                n += (size_t)snprintf(out + n, len - n,
                                      "  spi1 CS GP%-2u mode %d %4u kHz: "
                                      "0x%02X%s\n",
                                      CS_PINS[c], m ? 3 : 0, BAUDS[b] / 1000,
                                      id, id == BME_CHIP_ID ? "  <-- BME280"
                                                            : "");
            }
    for (size_t i = 0; i < sizeof I2C_ADDRS; i++) {
        int id = i2c_chip_id(I2C_ADDRS[i]);

        if (id < 0)
            n += (size_t)snprintf(out + n, len - n, "  i2c0 0x%02X: NACK\n",
                                  I2C_ADDRS[i]);
        else
            n += (size_t)snprintf(out + n, len - n, "  i2c0 0x%02X: 0x%02X%s\n",
                                  I2C_ADDRS[i], id,
                                  id == BME_CHIP_ID ? "  <-- BME280" : "");
    }
}

int main(void)
{
    static char prev[4096], now[4096];

    stdio_init_all();
    hw_init(); /* actuators low; i2c0 + spi1 up, GP9 CS high */

    /* Every candidate chip select idles high, so only one part is ever
     * selected at a time. GP9 is already an output from hw_init(). */
    for (size_t c = 0; c < sizeof CS_PINS; c++) {
        gpio_init(CS_PINS[c]);
        gpio_set_dir(CS_PINS[c], GPIO_OUT);
        gpio_put(CS_PINS[c], 1);
    }

    while (!stdio_usb_connected())
        sleep_ms(100);
    sleep_ms(500);

    printf("\n=== BME280 probe (bench tool) ===\n");
    {
        uint8_t reg = 0x88, c[26];

        if (i2c_write_timeout_us(i2c0, 0x76, &reg, 1, true, TIMEOUT_US) >= 0 &&
            i2c_read_timeout_us(i2c0, 0x76, c, 26, false, TIMEOUT_US) >= 0)
            printf("i2c0 0x76 trim: dig_T1=%u dig_P1=%u dig_H1=%u "
                   "(ambient DEVLOG 2026-08-31: 28323 37257 75)\n",
                   c[0] | c[1] << 8, c[6] | c[7] << 8, c[25]);
        gpio_init(PIN_SPI1_MISO);
        gpio_set_dir(PIN_SPI1_MISO, GPIO_IN);
        gpio_pull_up(PIN_SPI1_MISO);
        sleep_ms(1);
        printf("GP8 (MISO) as input, pull-up, all CS high: %d\n",
               gpio_get(PIN_SPI1_MISO));
        gpio_put(9, 0);
        sleep_ms(1);
        printf("GP8 (MISO) as input, pull-up, GP9 low:     %d\n",
               gpio_get(PIN_SPI1_MISO));
        gpio_put(9, 1);
        gpio_pull_down(PIN_SPI1_MISO);
        gpio_set_function(PIN_SPI1_MISO, GPIO_FUNC_SPI);
    }
    printf("-- watching for %u s (plug/reseat now) --\n", WATCH_S);
    for (unsigned t = 0; t < WATCH_S; t++) {
        scan(now, sizeof now);
        if (strcmp(now, prev) != 0) {
            printf("t=%3u s:\n%s", t, now);
            memcpy(prev, now, sizeof prev);
        }
        sleep_ms(1000);
    }
    printf("=== done ===\n");
    for (;;)
        sleep_ms(1000);
}
