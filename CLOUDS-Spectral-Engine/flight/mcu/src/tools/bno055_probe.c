/* BNO055 bring-up probe - a BENCH TOOL, not flight software.
 *
 * Built as its own target (bno055_probe), never linked into clouds_fsw_mcu.
 * It exists because hk_t carries one bit for the IMU, and one bit cannot say
 * which of the boot, the identity, the mode write or the bus failed.
 *
 * Output is USB CDC only. UART stdio stays off, as everywhere in this project:
 * the SDK default stdio UART is uart0 on GP0/GP1, the HK downlink's own pins.
 *
 * It calls hw_init() first for one reason: that is the code that drives every
 * actuator line low. GP17/GP18 have no external pull, so a firmware that skips
 * it leaves the dispersion motor's state to its driver's idea of a floating
 * input. No actuator is commanded anywhere below.
 *
 * Rules inherited from the 2026-08-31 survey's mistakes: never read above
 * register 0x6A (the page-0 map ends there, and reads past it provoke
 * SYS_ERR 0x05), and never report one sample as a measurement - the ID block
 * is read at eight points across the boot so the timing question is answered
 * by a curve rather than by a single read.
 */
#include <stdbool.h>
#include <stdio.h>

#include "hardware/i2c.h"
#include "pico/stdlib.h"

#include "../hw/board.h"
#include "../hw/hw.h"

#define BNO_ADDR 0x28
#define TIMEOUT_US 4000

static int read_reg(uint8_t addr, uint8_t reg, uint8_t *val)
{
    if (i2c_write_timeout_us(i2c0, addr, &reg, 1, true, TIMEOUT_US) < 0)
        return -1;
    if (i2c_read_timeout_us(i2c0, addr, val, 1, false, TIMEOUT_US) < 0)
        return -2;
    return 0;
}

static int read_burst(uint8_t addr, uint8_t reg, uint8_t *buf, size_t n)
{
    if (i2c_write_timeout_us(i2c0, addr, &reg, 1, true, TIMEOUT_US) < 0)
        return -1;
    if (i2c_read_timeout_us(i2c0, addr, buf, n, false, TIMEOUT_US) < 0)
        return -2;
    return 0;
}

static int write_reg(uint8_t addr, uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = {reg, val};

    return i2c_write_timeout_us(i2c0, addr, buf, 2, false, TIMEOUT_US) < 0 ? -1
                                                                          : 0;
}

static void show_named(const char *what, uint8_t reg)
{
    uint8_t v = 0;
    int rc = read_reg(BNO_ADDR, reg, &v);

    if (rc)
        printf("  %-14s (0x%02X) I2C ERROR %d\n", what, reg, rc);
    else
        printf("  %-14s (0x%02X) = 0x%02X\n", what, reg, v);
}

/* The ID block, byte-wise and as a burst. The survey read it byte-wise; if the
 * two disagree the fault is in how it is read, not in the part. */
static void show_ids(unsigned t_ms)
{
    uint8_t burst[7] = {0}, one[7] = {0};
    int rc_b = read_burst(BNO_ADDR, 0x00, burst, sizeof burst);
    int rc_1 = 0;

    for (unsigned i = 0; i < sizeof one; i++)
        if (read_reg(BNO_ADDR, (uint8_t)i, &one[i]))
            rc_1 = -1;

    printf("t=%4u ms  burst[%d] ", t_ms, rc_b);
    for (unsigned i = 0; i < sizeof burst; i++)
        printf("%02X ", burst[i]);
    printf("  bytewise[%d] ", rc_1);
    for (unsigned i = 0; i < sizeof one; i++)
        printf("%02X ", one[i]);
    printf("  (CHIP ACC MAG GYR SWl SWh BL; want A0 FB 32 0F .. .. 15)\n");
}

/* Two scans, not one. A read-probe leaves the device's register pointer where
 * it lies and some parts NACK a bare read; a write-probe (a zero-length data
 * phase) only asks whether the address is acknowledged. A part that appears in
 * one and not the other is a fact about the scan, not about the board - which
 * is the whole lesson of the GPIO_FUNC_I2C and SYS_ERR 0x05 traps. */
static bool ack_read(uint8_t a)
{
    uint8_t d;

    return i2c_read_timeout_us(i2c0, a, &d, 1, false, TIMEOUT_US) >= 0;
}

static bool ack_write(uint8_t a)
{
    uint8_t reg = 0x00;

    return i2c_write_timeout_us(i2c0, a, &reg, 1, false, TIMEOUT_US) >= 0;
}

static void bus_scan(void)
{
    printf("i2c0 read-probe :");
    for (uint8_t a = 0x08; a < 0x78; a++)
        if (ack_read(a))
            printf(" 0x%02X", a);
    printf("\n");

    printf("i2c0 write-probe:");
    for (uint8_t a = 0x08; a < 0x78; a++)
        if (ack_write(a))
            printf(" 0x%02X", a);
    printf("\n");

    /* Both BNO055 addresses, hammered: a part that answers intermittently is a
     * different fault from one that is not there, and one sample cannot tell
     * them apart (DEVLOG: the 24 V "collapse" that 880 samples disproved). */
    for (unsigned k = 0; k < 2; k++) {
        const uint8_t a = k ? 0x29 : 0x28;
        unsigned nr = 0, nw = 0;

        for (unsigned i = 0; i < 50; i++) {
            if (ack_read(a))
                nr++;
            if (ack_write(a))
                nw++;
            sleep_ms(2);
        }
        printf("0x%02X: %u/50 read-ACK, %u/50 write-ACK\n", a, nr, nw);
    }
}

int main(void)
{
    static const unsigned points[] = {0, 100, 300, 650, 800, 1200, 2000, 3000};
    unsigned elapsed = 0;
    uint8_t v;

    stdio_init_all();
    hw_init(); /* actuators low; i2c0 up at 100 kHz on GP28/GP29 */

    /* No host, no probe: this prints once and the output is the whole point. */
    while (!stdio_usb_connected())
        sleep_ms(100);
    sleep_ms(500);

    printf("\n=== BNO055 probe (bench tool) ===\n");
    bus_scan();

    printf("\n-- state as hw_init() left it --\n");
    show_named("CHIP_ID", 0x00);
    show_named("PAGE_ID", 0x07);
    show_named("OPR_MODE", 0x3D);
    show_named("PWR_MODE", 0x3E);
    show_named("SYS_STATUS", 0x39);
    show_named("SYS_ERR", 0x3A);
    show_named("SYS_CLK_ST", 0x38);
    show_named("ST_RESULT", 0x36);

    printf("\n-- RST_SYS, then the ID block across the boot --\n");
    (void)write_reg(BNO_ADDR, 0x3F, 0x20); /* NACK here is expected */
    for (unsigned i = 0; i < sizeof points / sizeof points[0]; i++) {
        while (elapsed < points[i]) {
            sleep_ms(10);
            elapsed += 10;
        }
        show_ids(elapsed);
    }

    printf("\n-- after the full boot --\n");
    show_named("SYS_STATUS", 0x39); /* 0=idle 1=err 5=fusion 6=non-fusion */
    show_named("SYS_ERR", 0x3A);
    show_named("SYS_CLK_ST", 0x38);
    show_named("ST_RESULT", 0x36); /* POST: b0 acc b1 mag b2 gyr b3 mcu */
    show_named("OPR_MODE", 0x3D);
    show_named("PWR_MODE", 0x3E);
    show_named("PAGE_ID", 0x07);

    /* Self-test on demand, in CONFIGMODE, the one write that asks the dies to
     * answer for themselves. ST_RESULT is the decisive measurement: it names
     * which die failed POST, which no amount of ID reading can. */
    printf("\n-- BIST (SYS_TRIGGER bit0) --\n");
    (void)write_reg(BNO_ADDR, 0x3D, 0x00); /* CONFIGMODE */
    sleep_ms(30);
    (void)write_reg(BNO_ADDR, 0x3F, 0x01);
    sleep_ms(1000);
    show_named("ST_RESULT", 0x36);
    show_named("SYS_ERR", 0x3A);

    printf("\n-- try ACCGYRO (0x05) and read the data registers --\n");
    (void)write_reg(BNO_ADDR, 0x3F, 0x00); /* internal clock, clear triggers */
    (void)write_reg(BNO_ADDR, 0x3E, 0x00); /* PWR normal */
    (void)write_reg(BNO_ADDR, 0x3B, 0x01); /* UNIT_SEL: accel in mg */
    (void)write_reg(BNO_ADDR, 0x3D, 0x05);
    sleep_ms(50);
    show_named("OPR_MODE", 0x3D);
    for (unsigned i = 0; i < 5; i++) {
        uint8_t acc[6] = {0}, gyr[6] = {0};

        (void)read_burst(BNO_ADDR, 0x08, acc, sizeof acc);
        (void)read_burst(BNO_ADDR, 0x14, gyr, sizeof gyr);
        printf("  acc %6d %6d %6d mg   gyr %6d %6d %6d raw\n",
               (int16_t)(acc[0] | (acc[1] << 8)),
               (int16_t)(acc[2] | (acc[3] << 8)),
               (int16_t)(acc[4] | (acc[5] << 8)),
               (int16_t)(gyr[0] | (gyr[1] << 8)),
               (int16_t)(gyr[2] | (gyr[3] << 8)),
               (int16_t)(gyr[4] | (gyr[5] << 8)));
        sleep_ms(200);
    }

    /* An external crystal is the leading hypothesis for dead dies. CLK_SEL can
     * only be set in CONFIGMODE; if a crystal is fitted and oscillating,
     * SYS_CLK_ST clears and the IDs come up. If it is not, this hangs the
     * clock - which is why the flight driver never asserts it and why this is
     * the last thing the probe does. */
    printf("\n-- CLK_SEL (external crystal) probe --\n");
    (void)write_reg(BNO_ADDR, 0x3D, 0x00);
    sleep_ms(30);
    (void)write_reg(BNO_ADDR, 0x3F, 0x80);
    sleep_ms(1000);
    show_named("SYS_CLK_ST", 0x38);
    show_named("SYS_STATUS", 0x39);
    show_named("SYS_ERR", 0x3A);
    show_ids(0);
    if (read_reg(BNO_ADDR, 0x00, &v) == 0)
        printf("  (chip still answers)\n");

    printf("\n=== probe done ===\n");
    for (;;)
        sleep_ms(1000);
}
