/*
 * Serial-communication port ("combridge") for the BMV080 driver on the
 * Raspberry Pi Pico SDK.
 *
 * The vendor library never touches hardware itself: it calls back into the
 * four functions below. Everything the library needs to reach one sensor unit
 * is in bmv080_spi_device_t, which is handed back to us as the opaque
 * bmv080_sercom_handle_t - so several sensors on one bus are just several of
 * these structs with different chip selects.
 *
 * Moved here from sensor-driver/pico_bringup/src/, where it was brought up on
 * a bare Pico 2 (2026-09-11). Two things changed on the way in, both because
 * this is flight software now and not a bench sketch:
 *
 *   - the frame width is set per transaction rather than once at bus init,
 *     because the chamber BME280 shares spi1 and transfers bytes;
 *   - the delay callback kicks the watchdog and refuses an unreasonable
 *     delay, instead of sleeping blind (S.9).
 */
#ifndef BMV080_PORT_H_
#define BMV080_PORT_H_

#include <stdint.h>

#include "hardware/spi.h"

#include "bmv080_defs.h"

/* Error codes returned to the vendor library from the read/write callbacks.
 * The library only checks for zero / non-zero. */
#define E_COMBRIDGE_OK 0
#define E_COMBRIDGE_ERROR_WRITE (-1)
#define E_COMBRIDGE_ERROR_READ (-2)
#define E_COMBRIDGE_ERROR_DELAY (-3)

/* The longest delay this port will serve. The library asks for delays during
 * bring-up and should ask for none in steady state; anything past this is a
 * fault, and serving it by feeding the watchdog would hide exactly the hang
 * the watchdog exists to catch. Refusing it instead surfaces as
 * E_BMV080_ERROR_CALLBACK_DELAY (303) in the driver's status. */
#define BMV080_DELAY_MAX_MS 5000u

typedef struct
{
    spi_inst_t *spi;  /*!< SPI instance the sensor is wired to */
    uint8_t cs_pin;   /*!< chip select, driven as plain SIO (active low) */
} bmv080_spi_device_t;

/*!
 * @brief Configure the SPI instance and its three bus pins.
 *
 * Does NOT set the frame format: the read/write callbacks set 16-bit frames
 * themselves, per transaction, because another driver on the same bus uses a
 * different width. Call once, before any per-sensor chip select is used.
 *
 * @return the baud rate the SPI block actually settled on, in Hz.
 */
uint32_t bmv080_port_init_bus(spi_inst_t *spi, uint8_t sck_pin, uint8_t mosi_pin,
                              uint8_t miso_pin, uint32_t clk_hz);

/*!
 * @brief Claim one chip select line and park it inactive (high).
 */
void bmv080_port_init_cs(uint8_t cs_pin);

/* Callbacks handed to bmv080_open(). Signatures are fixed by the vendor API. */
int8_t bmv080_port_spi_read_16bit(bmv080_sercom_handle_t handle, uint16_t header,
                                  uint16_t *payload, uint16_t payload_length);
int8_t bmv080_port_spi_write_16bit(bmv080_sercom_handle_t handle, uint16_t header,
                                   const uint16_t *payload, uint16_t payload_length);
int8_t bmv080_port_delay_ms(uint32_t duration_in_ms);
uint32_t bmv080_port_tick_ms(void);

#endif /* BMV080_PORT_H_ */
