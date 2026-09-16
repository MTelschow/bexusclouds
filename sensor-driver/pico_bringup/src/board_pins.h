/*
 * Pin map for the BMV080 bring-up board.
 *
 * These are the DEV BOARD numbers (bare Pico 2, USB serial E273FB5C22FF6E70).
 * Every one of them is overridable from the command line, because the sensor
 * moves to the CLOUDS carrier later and that board's pinout is not known yet:
 *
 *   cmake -DBMV080_PIN_SCK=... -DBMV080_PIN_MOSI=... (see CMakeLists.txt)
 *
 * The four bus pins must all belong to the same SPI instance. On RP2350A:
 *   spi0: RX  GP0 /GP4 /GP16/GP20, SCK GP2 /GP6 /GP18/GP22, TX GP3 /GP7 /GP19/GP23
 *   spi1: RX  GP8 /GP12/GP24/GP28, SCK GP10/GP14/GP26,      TX GP11/GP15/GP27
 * Chip selects are driven as plain SIO, so they can be any free GPIO.
 */
#ifndef BOARD_PINS_H_
#define BOARD_PINS_H_

/* --- dev board defaults ---------------------------------------------------*/
#ifndef BMV080_SPI_INSTANCE
#define BMV080_SPI_INSTANCE 0 /* spi0 */
#endif

#ifndef BMV080_PIN_MISO
#define BMV080_PIN_MISO 16u
#endif

#ifndef BMV080_PIN_CS1
#define BMV080_PIN_CS1 17u
#endif

#ifndef BMV080_PIN_SCK
#define BMV080_PIN_SCK 18u
#endif

#ifndef BMV080_PIN_MOSI
#define BMV080_PIN_MOSI 19u
#endif

/* Second chip select. Set to BMV080_PIN_NONE when only one sensor is wired. */
#ifndef BMV080_PIN_CS2
#define BMV080_PIN_CS2 20u
#endif

#define BMV080_PIN_NONE 0xFFu

/* SPI clock. The Bosch examples run 1 MHz; the part is specified well above
 * that, but bring-up is not the place to find the ceiling. */
#ifndef BMV080_SPI_CLK_HZ
#define BMV080_SPI_CLK_HZ 1000000u
#endif

#endif /* BOARD_PINS_H_ */
