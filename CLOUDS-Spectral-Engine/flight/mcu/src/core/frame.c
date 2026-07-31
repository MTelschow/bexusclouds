#include "frame.h"

#include <string.h>

#include "crc16.h"

static void put_u16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}

static void put_u32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

static uint16_t get_u16(const uint8_t *p)
{
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t get_u32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
           ((uint32_t)p[3] << 24);
}

size_t frame_encode(uint8_t type, uint16_t seq, uint32_t t_s, uint16_t t_ms,
                    const uint8_t *payload, uint16_t plen,
                    uint8_t *out, size_t cap)
{
    size_t total = FRAME_HEADER_LEN + plen + FRAME_CRC_LEN;

    if (plen > FRAME_MAX_PAYLOAD || cap < total)
        return 0;
    out[0] = FRAME_MAGIC0;
    out[1] = FRAME_MAGIC1;
    out[2] = FRAME_VERSION;
    out[3] = type;
    put_u16(out + 4, seq);
    put_u32(out + 6, t_s);
    put_u16(out + 10, t_ms);
    put_u16(out + 12, plen);
    if (plen)
        memcpy(out + FRAME_HEADER_LEN, payload, plen);
    put_u16(out + FRAME_HEADER_LEN + plen,
            crc16(out, FRAME_HEADER_LEN + plen));
    return total;
}

bool frame_decode(const uint8_t *data, size_t len, frame_view_t *view)
{
    uint16_t plen;

    if (len < FRAME_HEADER_LEN + FRAME_CRC_LEN)
        return false;
    if (data[0] != FRAME_MAGIC0 || data[1] != FRAME_MAGIC1 ||
        data[2] != FRAME_VERSION)
        return false;
    plen = get_u16(data + 12);
    if (len != (size_t)FRAME_HEADER_LEN + plen + FRAME_CRC_LEN)
        return false;
    if (get_u16(data + FRAME_HEADER_LEN + plen) !=
        crc16(data, FRAME_HEADER_LEN + plen))
        return false;
    view->type = data[3];
    view->seq = get_u16(data + 4);
    view->t_s = get_u32(data + 6);
    view->t_ms = get_u16(data + 10);
    view->payload = data + FRAME_HEADER_LEN;
    view->plen = plen;
    return true;
}

void hk_pack(const hk_t *hk, uint8_t out[HK_SIZE])
{
    uint8_t *p = out;

    *p++ = hk->state;
    *p++ = hk->flags;
    *p++ = hk->fired;
    *p++ = hk->valve_status;
    *p++ = hk->membrane_duty;
    *p++ = hk->error_flags;
    put_u16(p, (uint16_t)hk->temp1_cc), p += 2;
    put_u16(p, (uint16_t)hk->temp2_cc), p += 2;
    put_u16(p, (uint16_t)hk->bme_temp_cc), p += 2;
    put_u16(p, hk->rh1_cpct), p += 2;
    put_u16(p, hk->rh2_cpct), p += 2;
    put_u32(p, hk->p_amb_pa), p += 4;
    put_u32(p, hk->p_ch_pa), p += 4;
    for (int i = 0; i < 3; i++)
        put_u16(p, (uint16_t)hk->accel_mg[i]), p += 2;
    for (int i = 0; i < 3; i++)
        put_u16(p, (uint16_t)hk->gyro_ddps[i]), p += 2;
    put_u32(p, hk->uptime_s), p += 4;
    put_u32(p, hk->mission_t_s);
}

bool cmd_unpack(const frame_view_t *view, uint8_t *cmd, uint8_t *key,
                int32_t *value)
{
    if (view->type != PKT_CMD || view->plen < 6)
        return false;
    *cmd = view->payload[0];
    *key = view->payload[1];
    *value = (int32_t)get_u32(view->payload + 2);
    return true;
}

bool timesync_unpack(const frame_view_t *view, uint32_t *t_s, uint16_t *t_ms)
{
    if (view->type != PKT_TIMESYNC || view->plen < 6)
        return false;
    *t_s = get_u32(view->payload);
    *t_ms = get_u16(view->payload + 4);
    return true;
}

uint16_t event_pack(uint8_t code, uint8_t severity, const char *text,
                    uint8_t *out, size_t cap)
{
    size_t n = text ? strlen(text) : 0;

    if (n > 64)
        n = 64;
    if (cap < 2 + n)
        return 0;
    out[0] = code;
    out[1] = severity;
    if (n)
        memcpy(out + 2, text, n);
    return (uint16_t)(2 + n);
}
