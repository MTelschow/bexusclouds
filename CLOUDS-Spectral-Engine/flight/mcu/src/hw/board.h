/* Pin map for the CLOUDS main electronics board (RP2350).
 * PRELIMINARY - update when the PCB is finalised (SED section 4.8).
 * Valve open/close pairs are ALSO hardware-interlocked on the board
 * (spec S.8); the firmware interlock here is defence in depth.
 *
 * ---------------------------------------------------------------------------
 * CARRIER SCHEMATIC, 2026-09-11 (pin_layout.jpeg, the RP2350B page). Read this
 * before changing anything below. The net names are the schematic's own:
 *
 *   GP0  RP->PI          GP17 ACT_HB_IN1      GP33 DEBUG_LED
 *   GP1  RP<-PI          GP18 ACT_HB_IN2      GP34 DEBUG_SENS
 *   GP2  PI_RTS          GP19 ACT_EC_AL       GP35 INA_3V3_ALERT
 *   GP3  PI_CTS          GP20 ACT_EC_EN       GP36 INA_5V_ALERT
 *   GP4  SPI_0_MISO      GP21 ACT_EC_IN1      GP37 INA_VIN_ALERT
 *   GP5  SD_1_SENS       GP22 ACT_EC_IN2      GP38 INA_24V_ALERT
 *   GP6  SPI_0_SCK       GP23 ACT_R_4         GP39 VR_24V_EN
 *   GP7  SPI_0_MOSI      GP24 ACT_R_3         GP40 VR_24V_PG
 *   GP8  SPI_1_MISO      GP25 ACT_R_2         GP41 ADC_1
 *   GP9  SPI_1_CS1       GP26 ACT_R_1         GP42 ADC_2
 *   GP10 SPI_1_SCK       GP27 BNO_INT         GP43 ADC_3
 *   GP11 SPI_1_MOSI      GP28 SDA_0           GP44 ADC_4
 *   GP12 SPI_1_CS2       GP29 SCL_0           GP45 ADC_5
 *   GP13 SPI_1_CS3       GP30 (see below)     GP46 ACT_HB_SENS
 *                        GP31/32 unnamed
 *   GP14 SD_1_CS                              GP47 SPI_1_CS4
 *   GP15 SD_2_SENS
 *   GP16 SD_2_CS
 *
 * It CONFIRMS what was measured: i2c0 on GP28/GP29, the dispersion motor's
 * driver pair on GP17/GP18 (ACT_HB_IN1/IN2 - an H-bridge, which is what the
 * measurement found), the membrane on GP26 (ACT_R_1), and GP12/GP13 as
 * SPI_1 chip selects rather than the i2c0 the old map claimed.
 *
 * It CONTRADICTS the valve pins below, and they have NOT been changed here.
 * GP2/GP3 are the Pi's RTS/CTS and GP4..GP7 are SPI_0 - firing a "pinch valve"
 * today toggles a UART flow-control line, and a "valve" drive toggles the SD
 * bus. The board's actuator channels are ACT_R_1..4 (GP26/25/24/23), the
 * ACT_EC driver (GP19..GP22) and the ACT_HB bridge (GP17/GP18/GP46), but the
 * schematic page names channels, not loads: it does not say which relay holds
 * pinch 1 or which holds an equalisation valve. Guessing that mapping is how
 * an actuator gets driven from the wrong pin, which is the failure this file's
 * header already carries. These need the load side of the schematic, or a
 * measurement in the manner of DEVLOG 2026-08-31, before they move.
 *
 * It also says the carrier is an RP2350B (80-pin, GP0..GP47). Since
 * 2026-09-17 the build says so too: PICO_BOARD defaults to clouds_carrier
 * (boards/clouds_carrier.h, PICO_RP2350A 0), so GP30..GP47 are reachable. The
 * old -DPICO_BOARD=pico2 build (RP2350A, 30 GPIOs) still works for a bare
 * Pico 2; on it, every use of a pin above GP29 is compiled out behind
 * NUM_BANK0_GPIOS and reported as unsourced, never read from a register that
 * is not there.
 *
 * GP30 is not named on that schematic page. It carries the membrane position
 * switch added on 2026-09-17: a push button mechanically actuated by the
 * push-pull solenoid's plunger, wired to ground, closed while the solenoid is
 * energized (pulled). See PIN_MEMBRANE_SENSE.
 * --------------------------------------------------------------------------- */
#ifndef CLOUDS_BOARD_H
#define CLOUDS_BOARD_H

/* UART0 to the Raspberry Pi 5. Schematic: RP->PI / RP<-PI. Flow control
 * (PI_RTS GP2, PI_CTS GP3) exists on the board and is unused by uart_io.c. */
#define PIN_UART_TX 0
#define PIN_UART_RX 1
#define UART_BAUD 115200

/* Pinch valves (CaCO3 release) - one-shot fire via MOSFET.
 * WRONG PER SCHEMATIC: GP2/GP3 are PI_RTS/PI_CTS. See the header block. */
#define PIN_PINCH_1 2
#define PIN_PINCH_2 3

/* Equalization ball valves: open/close line pairs (USS-MSV00025).
 * WRONG PER SCHEMATIC: GP4..GP7 are SPI_0. See the header block. */
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

/* Membrane position switch: a push button pressed by the solenoid plunger,
 * one side on GP30, the other on ground. Input with the internal pull-up, so
 * open reads 1 and the closed switch reads 0 - LOW means the solenoid is
 * energized (pulled), HIGH means released (pushed). It is read into HK as
 * HKV_MEMBRANE_PULLED, a sensed state and not a drive: it can coexist with a
 * drive bit, and at the membrane's 2 Hz the 1 Hz HK sample lands at a random
 * phase of the cycle, so over many packets it should read pulled about
 * duty_pct of the time while the drive is on and never while it is off. A
 * bit that is stuck either way against the drive is the fault this exists
 * to show.
 *
 * GP30 exists only on the RP2350B carrier (boards/clouds_carrier.h). A
 * pico2 build has NUM_BANK0_GPIOS 30, so hw.c compiles the read out and
 * raises HKE_NO_MEMBRANE_SENSE instead of touching GPIO registers that the
 * RP2350A does not have. */
#define PIN_MEMBRANE_SENSE 30

/* CaCO3 dispersion motor (M-07): a two-line driver pair, GP17 forward and
 * GP18 reverse, measured on the carrier. Driving GP17 high with GP18 low ran
 * the motor; the reverse sense is UNVERIFIED, so only the forward drive is
 * used. Not in the SED - undocumented hardware, see DEVLOG 2026-08-31.
 * Driven through core/pulse like the valves, with the opposite line held low
 * as its interlock, so the pair can never be energized together and no drive
 * can outlive the watchdog. */
#define PIN_DISPERSE_FWD 17
#define PIN_DISPERSE_REV 18

/* SPI: two redundant SD cards (separate chip selects).
 * Still no defines here, but the reason has changed. The schematic now gives
 * the pinout the 2026-08-31 survey could not: SPI_0 on GP4 (MISO), GP6 (SCK)
 * and GP7 (MOSI), with SD_1_CS GP14 / SD_1_SENS GP5 and SD_2_CS GP16 /
 * SD_2_SENS GP15, and a separate SPI_1 on GP8/GP10/GP11 with four chip
 * selects (GP9, GP12, GP13, GP47). That is why the old map's GP16..GP20 probe
 * got CMD0 = 0xff on both chip selects - it had the bus, the clock and the
 * card detects all on the wrong pins, and two of them (GP17/GP18) on the
 * dispersion motor.
 *
 * They stay undefined because GP4..GP7 are currently claimed by the
 * equalisation valves above, and those numbers cannot both be right. M-11 is
 * blocked on resolving that, not on the schematic any more: bring up SD only
 * once the valve pins have moved to real actuator channels, or an spi_init()
 * will drive whatever the valve code thinks it owns. */

/* I2C0 as measured on the carrier and since confirmed by the schematic
 * (SDA_0 / SCL_0): BME280 0x76 (the only source of ambient T/RH/p), INA226 x3
 * on 0x40/0x44/0x45 watching the 24 V, 5 V and 3.3 V rails. A BNO055 IMU
 * answered at 0x28 on 2026-08-31 and does NOT answer at all on 2026-09-11
 * (0/50 ACK at 0x28 and 0x29 while the other four parts answered in the same
 * sweep), so hw/bno055.c currently drives nothing and reports HKE_IMU_FAIL.
 * GP12/GP13 are SPI_1 chip selects, not a second I2C. No chamber pressure
 * sensor and no second RH channel exist on this bus. The STLM20 pair the old
 * map put on the ADC is not populated - see the note below.
 * Identities and method: DEVLOG 2026-08-31. */
#define PIN_I2C_SDA 28
#define PIN_I2C_SCL 29

/* BNO_INT, the BNO055's interrupt output (datasheet Table 5-1 pin 14).
 * The IMU is not interrupt-driven - hw_read_sensors() polls it at 1 Hz - so
 * nothing in the flight path configures this pin, and nothing should read a
 * presence test into it either.
 *
 * It was briefly documented here as exactly that test, on the claim that INT
 * idles low and so a fitted part would hold GP27 down. The datasheet does not
 * say that. INT_EN and INT_MSK both reset to 0x00 (4.4.8/4.4.9) and this
 * driver writes neither, so no interrupt is ever raised; 3.8.1 says only that
 * INT "is set to high" when one occurs, and specifies no idle level and no
 * output stage. A working part with no interrupt enabled may leave this line
 * undriven, indistinguishable from an empty footprint. Only a pin found
 * actively DRIVEN says anything, and then only that something is there.
 * src/tools/bno055_probe.c samples it on those terms. */
#define PIN_BNO_INT 27

/* STLM20 x2: NOT POPULATED on this carrier, and GP26 - which the old map gave
 * to ADC_TEMP1 - is the membrane solenoid, so the two cannot coexist. The ADC
 * is left uninitialised rather than sampling floating pins into HK: a floating
 * input yields a confident wrong temperature, which is worse than none. When
 * the parts are fitted, define their real ADC channels here and drop
 * HKE_NO_TEMP from hw_read_sensors(). */

#define WATCHDOG_TIMEOUT_MS 2000 /* S.9 */

#endif
