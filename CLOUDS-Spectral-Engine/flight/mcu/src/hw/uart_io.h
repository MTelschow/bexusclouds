/* UART0 to the Pi: COBS-framed CLOUDS frames (M-12). */
#ifndef CLOUDS_UART_IO_H
#define CLOUDS_UART_IO_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "../core/frame.h"

void uart_io_init(void);
/* Encode + COBS + delimiter, blocking write. */
void uart_io_send(uint8_t type, uint16_t seq, uint32_t t_s, uint16_t t_ms,
                  const uint8_t *payload, uint16_t plen);
/* Non-blocking poll: returns true when a complete valid frame arrived.
 * The view's payload points into an internal buffer, valid until the next
 * call. */
bool uart_io_poll(frame_view_t *view);

#endif
