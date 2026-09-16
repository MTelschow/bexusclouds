/*
 * Serial-communication port ("combridge") for the BMV080 driver on the
 * Raspberry Pi Pico SDK.
 *
 * The vendor library never touches hardware itself: it calls back into the
 * four functions below. Everything the library needs to reach one sensor unit
 * is in bmv080_spi_device_t, which is handed back to us as the opaque
 * bmv080_sercom_handle_t - so several sensors on one bus are just several of
 * these structs with different chip selects.
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

typedef struct
{
    spi_inst_t *spi;  /*!< SPI instance the sensor is wired to */
    uint8_t cs_pin;   /*!< chip select, driven as plain SIO (active low) */
} bmv080_spi_device_t;

/*!
 * @brief Configure the SPI instance and its three bus pins.
 *
 * Sets 16-bit frames, MSB first, mode 0 - the format the BMV080 transfers
 * require. Call once, before any per-sensor chip select is used.
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
