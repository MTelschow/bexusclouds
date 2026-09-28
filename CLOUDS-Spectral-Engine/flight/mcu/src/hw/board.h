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
 *                        GP31/32 unnamed (never move; were the encoder placeholder)
 *   GP14 SD_1_CS                              GP47 SPI_1_CS4
 *   GP15 SD_2_SENS
 *   GP16 SD_2_CS
 *
 * It CONFIRMS what was measured: i2c0 on GP28/GP29, the dispersion motor's
 * driver pair on GP17/GP18 (ACT_HB_IN1/IN2 - an H-bridge, which is what the
 * measurement found), the membrane on GP26 (ACT_R_1), and GP12/GP13 as
 * SPI_1 chip selects rather than the i2c0 the old map claimed.
 *
 * It CONTRADICTED the valve pins this file used to carry - GP2/GP3 are the
 * Pi's RTS/CTS and GP4..GP7 are SPI_0, so firing a "pinch valve" would have
 * toggled a UART flow-control line and a "valve" drive the SD bus. That is
 * settled by subtraction: the valves came off the experiment on 2026-09-18
 * and their defines went with them (see below).
 *
 * The board's remaining actuator channels are ACT_R_1..4 (GP26/25/24/23),
 * the ACT_EC driver (GP19..GP22) and the ACT_HB bridge (GP17/GP18/GP46). Only
 * two are mapped here - the membrane on ACT_R_1 and the dispersion motor on
 * ACT_HB, both measured. The rest stay unmapped: the schematic page names
 * channels, not loads, and guessing which relay holds which load is how an
 * actuator gets driven from the wrong pin. They need the load side of the
 * schematic, or a measurement in the manner of DEVLOG 2026-08-31.
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
 * switch added on 2026-09-17: a push button on the push-pull solenoid's
 * plunger, wired to ground, released (open) while the solenoid rests and
 * pressed (closed) when it actuates. See PIN_MEMBRANE_SENSE.
 * --------------------------------------------------------------------------- */
#ifndef CLOUDS_BOARD_H
#define CLOUDS_BOARD_H

/* UART0 to the Raspberry Pi 5. Schematic: RP->PI / RP<-PI. Flow control
 * (PI_RTS GP2, PI_CTS GP3) exists on the board and is unused by uart_io.c. */
#define PIN_UART_TX 0
#define PIN_UART_RX 1
#define UART_BAUD 115200

/* THE VALVES ARE GONE (2026-09-18). The two pinch valves (GP2/GP3) and the
 * two equalisation ball valves (GP4..GP7) are not on the experiment any
 * more, so their pins, drives and HK bits went with them. Nothing in this
 * file claims those nets now, which is also how the long-standing "WRONG PER
 * SCHEMATIC" note on them is finally settled: GP2/GP3 are the Pi's RTS/CTS
 * and GP4..GP7 are SPI_0, and no actuator is mapped onto either any more.
 * Two actuators remain: the dispersion motor and the membrane solenoid. */

/* Drive time for one scheduled dispersion-motor pulse. Was VALVE_PULSE_MS,
 * from the ball valves' datasheet; the motor pulse has always used the same
 * 5 s and keeps it. Longer than the 2 s watchdog on purpose - see
 * core/pulse.h for why that is scheduled rather than slept. */
#define DISPERSE_PULSE_MS 5000

/* Membrane push-pull solenoid (HS-1564B) via inverter stage.
 * GP26, measured: a 0.5 Hz then 2 Hz square wave on GP26 visibly actuated the
 * solenoid, and the pad read back its driven level both ways, so the drive
 * wins. GP8, which this used to name, measures as unconnected. The driver
 * input carries an external pull-down (GP26 reads pu=0 pd=0), so the solenoid
 * is de-energized whenever the MCU is not driving it. DEVLOG 2026-08-31. */
#define PIN_MEMBRANE_PWM 26

/* Membrane position switch: a push button under the solenoid plunger, one
 * side on GP30, the other on ground. Input with the internal pull-up. The
 * resting plunger PRESSES the button (closed, LOW); actuating the solenoid
 * lifts the plunger off it (open, HIGH). So HIGH means actuated (pulled),
 * LOW means resting (pushed). It is read into HK as
 * HKV_MEMBRANE_PULLED, a sensed state and not a drive: it can coexist with a
 * drive bit. At the membrane's 2 Hz that one bit is NOT enough to see motion:
 * HK is sent every 1000 ms and the 500 ms cycle is timed by the same loop, so
 * the 1 Hz sample lands at the same phase every time and reads one constant
 * value whether the plunger moves or not (found on the loopback mock,
 * DEVLOG 2026-09-17). So the loop also samples the switch every 10 ms pass
 * and latches any change into HKV_MEMBRANE_CYCLING, cleared when HK is
 * built. Drive on: CYCLING every packet. Drive off: neither bit. Drive on
 * without CYCLING is the fault this switch exists to show.
 *
 * GP30 exists only on the RP2350B carrier (boards/clouds_carrier.h). A
 * pico2 build has NUM_BANK0_GPIOS 30, so hw.c compiles the read out and
 * raises HKE_NO_MEMBRANE_SENSE instead of touching GPIO registers that the
 * RP2350A does not have.
 *
 * The pin is read INVERTED in hw_membrane_pulled(): the button is pressed
 * (LOW) when the plunger is out, so LOW = pulled/actuated and HIGH =
 * pushed/resting.
 *
 * MEASURED 2026-09-17 on the carrier (pu=0 pd=0,
 * tools/membrane_switch_probe.c): LOW with no drive, HIGH for as long as
 * GP26 was held high, ~40 ms release lag on the falling edge - i.e. the pin
 * followed the drive one for one, which is the OPPOSITE sense to the
 * inversion above. The inversion is the mechanical assignment currently
 * asked for; re-run the probe against the fitted plunger before trusting
 * either. DEVLOG 2026-09-17. */
#define PIN_MEMBRANE_SENSE 30

/* CaCO3 dispersion motor current sense: the ACT_HB_SENS net on GP46, read on
 * ADC channel 6 (the RP2350B's ADC base pin is GP40, so GP46 is ADC6).
 *
 * It belongs to the DISPERSION MOTOR, not the membrane solenoid: ACT_HB is
 * one driver channel on the carrier and it carries GP17/GP18 (the motor's
 * two drive lines, PIN_DISPERSE_FWD/REV below) together with this sense pin.
 * The membrane solenoid is GP26 and has no current sense of its own.
 *
 * The driver is a DRV8251A H-bridge with integrated current sensing: no power
 * shunt in the load path, an internal current mirror on the low-side FETs
 * instead, whose IPROPI pin sources I_motor x AIPROPI (1500 uA/A typ) into an
 * external resistor to ground. The carrier fits 1.5 kOhm, so the pin reads
 * 0.444 A/V and the ADC's 3.3 V full scale is 1.47 A. Sampled once per 1 Hz
 * HK sweep and downlinked RAW, as 12-bit counts, in hk_t.hb_sense_raw - the
 * conversion to amps happens on the ground (clouds_link/hk.py
 * HB_SENSE_A_PER_V), for the same reason the INA226 shunt voltages go down
 * raw: a resistor value or a measured gain that turns out to be wrong is
 * correctable against a logged session, where one baked into firmware is not.
 *
 * TWO THINGS THE READING DOES NOT SAY. IPROPI only mirrors current flowing
 * drain-to-source through a low-side FET, so it is valid in drive and brake
 * and reads ZERO IN COAST, while the winding current freewheels through the
 * body diodes - 0 counts is "no low-side current", not "no current". And the
 * motor runs in bounded 5 s pulses (one per release or DISPERSE pulse), so
 * at 1 Hz a pulse is a handful of samples and everything between releases is
 * a legitimate zero; only an operator's DISPERSE run holds it on longer. A
 * drive whose samples never rise is the fault this exists to show.
 *
 * GP46 exists only on the RP2350B carrier (boards/clouds_carrier.h); a pico2
 * build compiles the read out and downlinks HB_SENSE_INVALID. */
#define PIN_HB_SENSE 46

/* CaCO3 dispersion motor (M-07): a two-line driver pair, GP17 forward and
 * GP18 reverse, measured on the carrier. Driving GP17 high with GP18 low ran
 * the motor; the reverse sense is UNVERIFIED, so only the forward drive is
 * used. Not in the SED - undocumented hardware, see DEVLOG 2026-08-31.
 * Driven through core/pulse like the valves, with the opposite line held low
 * as its interlock, so the pair can never be energized together and no drive
 * can outlive the watchdog; the operator's DISPERSE run holds the line
 * beside that queue (hw.c motor_held) until DISPERSE stop, and a watchdog
 * reset drops it like everything else. Its driver is the DRV8251A whose current sense
 * is PIN_HB_SENSE above - same ACT_HB channel, so that ADC reading is this
 * motor's current. */
#define PIN_DISPERSE_FWD 17
#define PIN_DISPERSE_REV 18

/* Dispersion motor encoder, Faulhaber IE3-1024L (data-sheets/DE_IE3-1024L_DFF.pdf):
 * magnetic incremental, A/B quadrature + index, 1024 lines/rev, differential
 * TIA-422 outputs, 5 V. The carrier has NO receiver; the harness puts single
 * legs of the pairs on the ACT_EC nets. MEASURED 2026-09-28
 * (tools/encoder_pin_probe found the pins, tools/encoder_trace_probe timed
 * them at 80 ns; docs/HARDWARE.md has the numbers):
 *
 *   GP19 ACT_EC_AL   one channel, clean 50 % square, 2048 edges/rev - with an
 *                    ~80 ns low glitch on ~37 % of periods (crosstalk from the
 *                    legs that are not on a pin). This is PIN_ENC_A.
 *   GP21 ACT_EC_IN1  the resistor MIDPOINT of GP19's channel and the other
 *                    one: low only while both are low, ~2.5 V (reads high,
 *                    marginally) with one high. Not a channel - but at every
 *                    genuine falling edge of GP19 it is a solid low under the
 *                    flight forward drive (the other channel leads by 90 deg;
 *                    3381 of 3388 edges) and would be high in reverse. So it
 *                    is the DIRECTION sample. This is PIN_ENC_B.
 *   GP22 ACT_EC_IN2  80 ns glitches coincident with the others' edges, 99.7 %
 *                    high otherwise: a coupled victim, not a signal. Unused.
 *   GP20 ACT_EC_EN   static high. Unused.
 *   GP31/GP32        never move (the placeholder this replaced).
 *
 * hw/quadrature_encoder.pio therefore counts GP19's falling edges after a
 * 0.3 us deglitch hold and signs each by GP21 (x1, MOTOR_ENC_COUNTS_PER_REV
 * = 1024). Forward drive (GP17 PWM) counts UP, so hk.motor_rpm is positive
 * for the flight direction - verified against the trace, not yet against a
 * reverse run. The pins stay at their reset pull-down (never a pull-up: the
 * schematic calls these driver inputs, and an unplugged encoder must read a
 * steady 0 = no edges = stall-while-driving, never a phantom speed).
 * NEVER drive GP19..GP22 as outputs: the encoder's line driver is on them.
 *
 * The pico-examples x4 decoder that was here needs two clean channels on
 * consecutive pins; it is in git history for the day a receiver is fitted.
 * Both pins are below GP30, so a pico2 build has them too; HAVE_ENCODER in
 * hw.c keeps the NUM_BANK0_GPIOS guard for symmetry with the other pins. */
#define PIN_ENC_A 19 /* channel: edges = speed */
#define PIN_ENC_B 21 /* midpoint: level at A's fall = direction */

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

/* SPI_1, the second bus on the carrier: GP8 MISO, GP10 SCK, GP11 MOSI, with
 * four chip selects (SPI_1_CS1 GP9, CS2 GP12, CS3 GP13, CS4 GP47).
 *
 * This bus is brought up where SPI_0 is not, and the difference is the whole
 * reason it is safe to: NOTHING ELSE IN THIS FILE CLAIMS GP8/GP10/GP11. The
 * SD bus above is blocked because its pins are also the equalisation valve
 * pins, so an spi_init() there would drive an actuator line; here there is
 * no such collision, and the only pin driven is a chip select whose net the
 * schematic names as one.
 *
 * GP12/GP13 are on this bus and not a second I2C, which is what the old
 * pre-schematic map called them. Nothing has ever been probed on GP12/GP13
 * as I2C, and nothing should be.
 *
 * 1 MHz: well inside the BME280's 10 MHz SPI limit, slow enough that a long
 * chamber harness is not the thing under test during bring-up, and fast
 * enough that the 26-byte calibration burst costs ~210 us. Raise it once a
 * fitted harness has been shown to work at all. */
/* MEASURED 2026-09-28, twice: NOTHING ON THIS BUS ANSWERS, AND THE PIN
 * LEVELS CANNOT BE TRUSTED TO SAY WHY.
 *
 * tools/bme280_probe now runs three bus-integrity tests before its chip-id
 * table. What they establish, and what they do not:
 *
 *   SOLID: with the bus parked as high-impedance inputs, MISO idles HIGH on
 *   its pull-up as it should, and asserting each of GP9/GP12/GP13/GP47 in
 *   turn changes NOTHING. A fitted part leaves hi-Z when selected, so nothing
 *   is responding on any chip select. Every clocked read is 0x00.
 *
 *   NOT SOLID: the apparent "GP8 held low", and the apparent shorts between
 *   GP8/GP10/GP11. Both were artifacts. The held-low reading was our own
 *   spi1 MOSI idling low, reaching GP8 because the probe had left the other
 *   two pins on the SPI peripheral while measuring - a measurement of the
 *   peripheral, not of the board. And on an RP2350 a FLOATING pad does not
 *   read as a clean float: this project measured one latching high against
 *   its own internal pull-down on 2026-09-11 (sensor-driver/pico_bringup).
 *   A latched high-impedance input is also nudged by a neighbour through a
 *   few pF, which the cross-short test reports as "tied together" when
 *   nothing is tied.
 *
 * So the evidence is consistent with the simplest explanation: THESE THREE
 * PINS ARE FLOATING - the SPI_1 harness is not connected, or the parts are
 * not fitted, or their supply rails are not up. That is a hardware state, not
 * a fault to debug in firmware, and it is what to confirm first.
 *
 * Settle it physically before theorising: unplug the sensor harness and
 * re-run the probe - output that does not change was never about the sensor -
 * or fit an external 10k pull-up to GP8 and see whether it reads 1 and drives
 * both ways. Only once the net is known not to be floating do the drive and
 * cross-short results mean anything.
 *
 * The i2c0 half of the board is healthy in the same run (BME280 0x76, chip id
 * 0x60, trim identical to DEVLOG 2026-08-31; three INA226s ACK), so the tool
 * and the 1 Hz loop are not the problem. */
#define PIN_SPI1_MISO 8
#define PIN_SPI1_SCK 10
#define PIN_SPI1_MOSI 11
#define SPI1_BAUD_HZ (1000 * 1000)

/* Chamber BME280 chip select: SPI_1_CS1 on GP9.
 *
 * A SECOND BME280, in the test chamber, on SPI - the ambient part on i2c0
 * at 0x76 is unchanged and unaffected. Two identical parts on two different
 * buses is deliberate: the I2C part has one alternate address (0x77) and it
 * is the chamber half that has to move, so putting it on its own bus keeps
 * an address strap out of the flight configuration entirely.
 *
 * The part auto-selects SPI when CSB is pulled low - there is no mode
 * register and no strap to set - so this pin is driven as plain GPIO,
 * idling HIGH, rather than handed to the SPI peripheral's hardware CSn.
 * spi1's own CSn pad happens to be this pin, but hardware CSn on the RP2350
 * deasserts between bytes, which breaks the BME280's address-then-burst
 * transaction; a manual GPIO is not an accident here.
 *
 * RUN AGAINST THE CARRIER 2026-09-28 (serial 21DD2AE08840C863,
 * tools/bme280_probe): NOTHING ANSWERS ON THIS BUS AT ALL. Chip id reads 0x00
 * on all four chip selects (GP9, GP12, GP13, GP47), in mode 0 and mode 3, at
 * 100 kHz and 1 MHz, and the bit-banged swapped-MOSI/MISO read is 0x00 on all
 * four too. The same sweep found the ambient part on i2c0 at 0x76 with the
 * DEVLOG 2026-08-31 trim values, so the tool and the loop are fine.
 *
 * The CS assignment is therefore still UNTESTED, not disproved - the bus does
 * not idle correctly, so a chip select cannot be ruled in or out yet. See the
 * GP8 note below, which is the thing to fix first. Until then
 * bme280_init() fails, hw_read_sensors() raises HKE_BME280_CHM_FAIL and the
 * chamber fields stay zero, which is the wrong-CS case reporting itself
 * rather than downlinking a number from nothing. */
#define PIN_BME_CHAMBER_CS 9

/* BMV080 particulate sensor chip select: SPI_1_CS2 on GP12.
 *
 * The second part on this bus, and the reason bme280.c and bmv080_port.c both
 * set the SPI frame width inside their own chip-select window: this one
 * transfers 16-bit words (a header then payload words - the vendor API has no
 * register map at all), the BME280 transfers bytes, and a width set once at
 * bus init belongs to whichever driver touched the bus last.
 *
 * Driven as plain GPIO idling HIGH, for the same reason as the BME280's:
 * hardware CSn deasserts between frames and the vendor API requires the
 * select to be held across a whole burst.
 *
 * 1 MHz (SPI1_BAUD_HZ) is the FLOOR of this part's range, not a comfortable
 * middle - the datasheet specifies 1..10 MHz, where the BME280 has no lower
 * bound. It is also what both Bosch embedded examples use. If the bus is ever
 * raised for the BME280's sake, this part is happy: the vendor's own
 * Raspberry Pi example runs it at 10 MHz.
 *
 * RUN AGAINST THE CARRIER 2026-09-28 (tools/bmv080_probe): DOES NOT ANSWER.
 * bmv080_open() returns E_BMV080_ERROR_MISMATCH_CHIP_ID (107) on GP12, GP13
 * and GP47, and the raw 16-bit reads are all-0x0000 at 1 MHz and 4 MHz for tx
 * patterns 0x0000, 0xFFFF and 0xA5A5. The vendor library itself is fine in the
 * same run - bmv080_get_driver_version() reports 24.2.0.b8c488edbf8.0, which
 * executes library code and needs no sensor, so the archives, the softfp ABI
 * choice and the link group are all proven.
 *
 * This 107 is NOT yet evidence about the sensor. Nothing answers on any
 * SPI_1 chip select, including the chamber BME280's, and the bus pins look
 * floating (see the SPI_1 note above). A part that is absent, unplugged or
 * unpowered returns exactly this. Confirm the harness and the four supply
 * domains first, re-run this probe second, and only then suspect the part.
 *
 * When it is the part's turn, check the two things that cannot be fixed in
 * software: the PS pin must be tied LOW at power-up to latch SPI (it is
 * latched once and cannot be renegotiated), and the part needs four supply
 * domains up - VDDL/VDDA/VDDD and VDDIO.
 *
 * The IRQ line (pin 12, active low) is NOT wired on this carrier, so the
 * driver is polled - which the vendor supports and which costs one second
 * LESS first-sample latency than the interrupt path. */
#define PIN_BMV080_CS 12

/* The two SPI_1 selects with no load assigned yet: SPI_1_CS3 on GP13 and
 * SPI_1_CS4 on GP47 (schematic net names; the page names channels, not
 * parts). They are defined so that hw_init() can PARK THEM HIGH, not so that
 * anything drives them low.
 *
 * Why every select must be a driven-high output before the first clock edge
 * on the bus: an RP2350 pad comes out of reset as an input with its
 * pull-down enabled (PADS_BANK0_GPIOx reset 0x116, PDE=1), and an active-low
 * chip select left in that state is ASSERTED. Until 2026-09-28 the flight
 * image drove only GP9 before clocking the chamber BME280; GP12 was claimed
 * later inside bmv080_dev_init() and GP13/GP47 never. With parts fitted that
 * is two drivers on MISO during the BME280's id and calibration reads, 8-bit
 * traffic into a BMV080 that has not been opened, and a part behind an
 * undriven select that never sees a falling edge and so never frames a
 * command. Every probe tool must do the same before its first transaction. */
#define PIN_SPI1_CS3 13
#define PIN_SPI1_CS4 47

/* How often hw_read_sensors() re-runs a failed boot-time init for the
 * drivers whose bring-up is a handful of timeout-bounded transfers with no
 * sleep in them (both BME280s, the INA226s). Without this a part that missed
 * its probe at boot - I2C glitch, harness plugged in after power-up - stays
 * failed until the next power cycle; for the ambient BME280 that means
 * p_amb_pa pinned at P_AMB_COLD_START_PA with HKE_P_AMB_STALE for the whole
 * flight. 5 s is long against the 1 Hz sweep so the retry costs nothing when
 * the part is really absent, and short against the ascent. The BMV080 is
 * NOT retried: its bring-up sleeps inside the vendor library and belongs
 * before hw_watchdog_enable() only (hw/bmv080_port.c). */
#define SENSOR_RETRY_MS 5000u

/* I2C0 as measured on the carrier and since confirmed by the schematic
 * (SDA_0 / SCL_0): BME280 0x76 (the only source of ambient T/RH/p), INA226 x3
 * on 0x40/0x44/0x45 watching the 24 V, 5 V and 3.3 V rails. A BNO055 IMU
 * answered at 0x28 on 2026-08-31 and does NOT answer at all on 2026-09-11
 * (0/50 ACK at 0x28 and 0x29 while the other four parts answered in the same
 * sweep), so hw/bno055.c currently drives nothing and reports HKE_IMU_FAIL.
 * GP12/GP13 are SPI_1 chip selects, not a second I2C. Nothing on THIS bus
 * measures the chamber: the chamber BME280 is a second, separate part on
 * SPI_1 (PIN_BME_CHAMBER_CS above), so 0x76 here stays the ambient channel
 * and nothing about it changes. There is still no second RH channel on i2c0.
 * The STLM20 pair the old map put on the ADC is not populated - see the
 * note below.
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
