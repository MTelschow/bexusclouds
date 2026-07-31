/* Pin map for the CLOUDS main electronics board (RP2350).
 * PRELIMINARY - update when the PCB is finalised (SED section 4.8).
 * Valve open/close pairs are ALSO hardware-interlocked on the board
 * (spec S.8); the firmware interlock here is defence in depth. */
#ifndef CLOUDS_BOARD_H
#define CLOUDS_BOARD_H

/* UART0 to the Raspberry Pi 5 */
#define PIN_UART_TX 0
#define PIN_UART_RX 1
#define UART_BAUD 115200

/* Pinch valves (CaCO3 release) - one-shot fire via MOSFET */
#define PIN_PINCH_1 2
#define PIN_PINCH_2 3

/* Equalization ball valves: open/close line pairs (USS-MSV00025) */
#define PIN_EQ1_OPEN 4
#define PIN_EQ1_CLOSE 5
#define PIN_EQ2_OPEN 6
#define PIN_EQ2_CLOSE 7
#define VALVE_PULSE_MS 5000 /* drive time per operation (datasheet) */

/* Membrane push-pull solenoid (HS-1564B) via inverter stage */
#define PIN_MEMBRANE_PWM 8

/* SPI0: two redundant SD cards (separate chip selects) */
#define PIN_SD_SCK 18
#define PIN_SD_MOSI 19
#define PIN_SD_MISO 16
#define PIN_SD_CS_A 17
#define PIN_SD_CS_B 20

/* I2C0: BME280 + IMU; ADC: STLM20 x2; Keller 23SY per datasheet */
#define PIN_I2C_SDA 12
#define PIN_I2C_SCL 13
#define ADC_TEMP1 0 /* GPIO26 */
#define ADC_TEMP2 1 /* GPIO27 */

#define WATCHDOG_TIMEOUT_MS 2000 /* S.9 */

#endif
