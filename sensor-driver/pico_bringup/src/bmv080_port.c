#include "bmv080_port.h"

#include "pico/stdlib.h"
#include "pico/time.h"

uint32_t bmv080_port_init_bus(spi_inst_t *spi, uint8_t sck_pin, uint8_t mosi_pin,
                              uint8_t miso_pin, uint32_t clk_hz)
{
    uint32_t baudrate = spi_init(spi, clk_hz);

    gpio_set_function(sck_pin, GPIO_FUNC_SPI);
    gpio_set_function(mosi_pin, GPIO_FUNC_SPI);
    gpio_set_function(miso_pin, GPIO_FUNC_SPI);

    /* 16-bit frames, MSB first, CPOL=0/CPHA=0. The BMV080 transfers a 16-bit
     * header followed by 16-bit payload words; an 8-bit format would insert a
     * frame boundary in the middle of every word. */
    spi_set_format(spi, 16, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);

    return baudrate;
}

void bmv080_port_init_cs(uint8_t cs_pin)
{
    gpio_init(cs_pin);
    gpio_put(cs_pin, 1);
    gpio_set_dir(cs_pin, GPIO_OUT);
    gpio_put(cs_pin, 1);
}

/* Chip select is asserted for the whole header+payload burst: the vendor API
 * requires burst transfers, so releasing between words would end the access. */
static inline void cs_select(const bmv080_spi_device_t *device)
{
    gpio_put(device->cs_pin, 0);
    __asm volatile("nop \n nop \n nop");
}

static inline void cs_deselect(const bmv080_spi_device_t *device)
{
    __asm volatile("nop \n nop \n nop");
    gpio_put(device->cs_pin, 1);
}

int8_t bmv080_port_spi_read_16bit(bmv080_sercom_handle_t handle, uint16_t header,
                                  uint16_t *payload, uint16_t payload_length)
{
    bmv080_spi_device_t *device = (bmv080_spi_device_t *)handle;

    if ((device == NULL) || ((payload == NULL) && (payload_length > 0)))
    {
        return E_COMBRIDGE_ERROR_READ;
    }

    cs_select(device);

    uint16_t header_response = 0;
    int written = spi_write16_read16_blocking(device->spi, &header, &header_response, 1);
    if (written != 1)
    {
        cs_deselect(device);
        return E_COMBRIDGE_ERROR_WRITE;
    }

    int8_t return_value = E_COMBRIDGE_OK;
    if (payload_length > 0)
    {
        /* spi_read16_blocking clocks out the repeated tx value and captures MISO. */
        int read = spi_read16_blocking(device->spi, 0x0000, payload, payload_length);
        if (read != (int)payload_length)
        {
            return_value = E_COMBRIDGE_ERROR_READ;
        }
    }

    cs_deselect(device);

    return return_value;
}

int8_t bmv080_port_spi_write_16bit(bmv080_sercom_handle_t handle, uint16_t header,
                                   const uint16_t *payload, uint16_t payload_length)
{
    bmv080_spi_device_t *device = (bmv080_spi_device_t *)handle;

    if ((device == NULL) || ((payload == NULL) && (payload_length > 0)))
    {
        return E_COMBRIDGE_ERROR_WRITE;
    }

    cs_select(device);

    int written = spi_write16_blocking(device->spi, &header, 1);
    if (written != 1)
    {
        cs_deselect(device);
        return E_COMBRIDGE_ERROR_WRITE;
    }

    int8_t return_value = E_COMBRIDGE_OK;
    if (payload_length > 0)
    {
        written = spi_write16_blocking(device->spi, payload, payload_length);
        if (written != (int)payload_length)
        {
            return_value = E_COMBRIDGE_ERROR_WRITE;
        }
    }

    cs_deselect(device);

    return return_value;
}

int8_t bmv080_port_delay_ms(uint32_t duration_in_ms)
{
    sleep_ms(duration_in_ms);
    return E_COMBRIDGE_OK;
}

uint32_t bmv080_port_tick_ms(void)
{
    return to_ms_since_boot(get_absolute_time());
}
