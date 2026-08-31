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

/* Membrane push-pull solenoid (HS-1564B) via inverter stage.
 * GP26, measured: a 0.5 Hz then 2 Hz square wave on GP26 visibly actuated the
 * solenoid, and the pad read back its driven level both ways, so the drive
 * wins. GP8, which this used to name, measures as unconnected. The driver
 * input carries an external pull-down (GP26 reads pu=0 pd=0), so the solenoid
 * is de-energized whenever the MCU is not driving it. DEVLOG 2026-08-31. */
#define PIN_MEMBRANE_PWM 26

/* SPI0: two redundant SD cards (separate chip selects).
 * UNVERIFIED - these pins are almost certainly wrong for the current carrier.
 * GP16/GP17/GP18 measure as unconnected and an SD probe on exactly these pins
 * got CMD0 = 0xff on both chip selects (DEVLOG 2026-08-31). Confirm against
 * the schematic before building M-11 on them; the I2C pins below were wrong
 * in the same way. */
#define PIN_SD_SCK 18
#define PIN_SD_MOSI 19
#define PIN_SD_MISO 16
#define PIN_SD_CS_A 17
#define PIN_SD_CS_B 20

/* I2C0 as measured on the carrier, not assumed: BME280 0x76 (the only source
 * of ambient T/RH/p), INA226 x3 on 0x40/0x44/0x45 watching the 24 V, 5 V and
 * 3.3 V rails, and a BNO055 IMU at 0x28 whose sub-sensor IDs read 0x00, so it
 * answers but cannot be used. GP12/GP13 are unconnected here. No chamber pressure sensor and no
 * second RH channel exist on this bus. ADC: STLM20 x2 on GP26/GP27.
 * Identities and method: DEVLOG 2026-08-31. */
#define PIN_I2C_SDA 28
#define PIN_I2C_SCL 29

/* STLM20 x2: NOT POPULATED on this carrier, and GP26 - which the old map gave
 * to ADC_TEMP1 - is the membrane solenoid, so the two cannot coexist. The ADC
 * is left uninitialised rather than sampling floating pins into HK: a floating
 * input yields a confident wrong temperature, which is worse than none. When
 * the parts are fitted, define their real ADC channels here and drop
 * HKE_NO_TEMP from hw_read_sensors(). */

#define WATCHDOG_TIMEOUT_MS 2000 /* S.9 */

#endif
