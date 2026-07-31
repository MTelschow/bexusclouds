#include "cobs.h"

size_t cobs_encode(const uint8_t *in, size_t len, uint8_t *out, size_t out_cap)
{
    size_t out_i = 0, code_i = 0, code = 1;

    if (out_cap < 1)
        return 0;
    out_i = 1; /* reserve the first code byte */

    for (size_t i = 0; i < len; i++) {
        if (in[i] == 0) {
            out[code_i] = (uint8_t)code;
            code_i = out_i;
            if (++out_i > out_cap)
                return 0;
            code = 1;
        } else {
            if (out_i >= out_cap)
                return 0;
            out[out_i++] = in[i];
            if (++code == 0xFF) {
                out[code_i] = 0xFF;
                code_i = out_i;
                if (++out_i > out_cap)
                    return 0;
                code = 1;
            }
        }
    }
    out[code_i] = (uint8_t)code;
    return out_i;
}

size_t cobs_decode(const uint8_t *in, size_t len, uint8_t *out, size_t out_cap)
{
    size_t out_i = 0, i = 0;

    if (len == 0)
        return 0;
    while (i < len) {
        uint8_t code = in[i];
        if (code == 0 || i + code > len) /* group must fit */
            return 0;
        for (size_t j = 1; j < code; j++) {
            uint8_t b = in[i + j];
            if (b == 0)
                return 0;
            if (out_i >= out_cap)
                return 0;
            out[out_i++] = b;
        }
        i += code;
        if (code < 0xFF && i < len) {
            if (out_i >= out_cap)
                return 0;
            out[out_i++] = 0;
        }
    }
    return out_i;
}
