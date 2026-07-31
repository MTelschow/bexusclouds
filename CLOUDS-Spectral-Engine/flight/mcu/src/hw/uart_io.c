#include "uart_io.h"

#include "hardware/uart.h"
#include "pico/stdlib.h"

#include "../core/cobs.h"
#include "board.h"

#define UART_ID uart0

static uint8_t rx_buf[COBS_ENC_MAX(FRAME_MAX) + 1];
static size_t rx_len;
static uint8_t decoded[FRAME_MAX];

void uart_io_init(void)
{
    uart_init(UART_ID, UART_BAUD);
    gpio_set_function(PIN_UART_TX, GPIO_FUNC_UART);
    gpio_set_function(PIN_UART_RX, GPIO_FUNC_UART);
}

void uart_io_send(uint8_t type, uint16_t seq, uint32_t t_s, uint16_t t_ms,
                  const uint8_t *payload, uint16_t plen)
{
    uint8_t frame[FRAME_MAX];
    uint8_t wire[COBS_ENC_MAX(FRAME_MAX) + 1];
    size_t flen, wlen;

    flen = frame_encode(type, seq, t_s, t_ms, payload, plen, frame,
                        sizeof frame);
    if (flen == 0)
        return;
    wlen = cobs_encode(frame, flen, wire, sizeof wire - 1);
    if (wlen == 0)
        return;
    wire[wlen++] = 0x00;
    uart_write_blocking(UART_ID, wire, wlen);
}

bool uart_io_poll(frame_view_t *view)
{
    while (uart_is_readable(UART_ID)) {
        uint8_t b = uart_getc(UART_ID);

        if (b != 0x00) {
            if (rx_len < sizeof rx_buf)
                rx_buf[rx_len++] = b;
            else
                rx_len = 0; /* overlong garbage: resync on next delimiter */
            continue;
        }
        /* delimiter: try to decode what we collected */
        size_t n = cobs_decode(rx_buf, rx_len, decoded, sizeof decoded);

        rx_len = 0;
        if (n != 0 && frame_decode(decoded, n, view))
            return true;
    }
    return false;
}
