/* COBS framing for the UART link - mirror of clouds_link/cobs.py.
 * Wire format: cobs_encode(frame) followed by a 0x00 delimiter. */
#ifndef CLOUDS_COBS_H
#define CLOUDS_COBS_H

#include <stddef.h>
#include <stdint.h>

/* Worst-case encoded size for n input bytes: n + n/254 + 1. */
#define COBS_ENC_MAX(n) ((n) + ((n) / 254) + 1)

/* Returns encoded length, or 0 if out_cap is too small. */
size_t cobs_encode(const uint8_t *in, size_t len, uint8_t *out, size_t out_cap);

/* Returns decoded length, or 0 on malformed input (embedded zero / overrun). */
size_t cobs_decode(const uint8_t *in, size_t len, uint8_t *out, size_t out_cap);

#endif
