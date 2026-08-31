/* CLOUDS packet frame - byte-for-byte mirror of clouds_link/frames.py.
 * Header 14 B (magic u16, version u8, type u8, seq u16, t_s u32, t_ms u16,
 * plen u16, all LE) + payload + CRC-16 LE over everything before it. */
#ifndef CLOUDS_FRAME_H
#define CLOUDS_FRAME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define FRAME_MAGIC0 0xC7
#define FRAME_MAGIC1 0x1D
#define FRAME_VERSION 1
#define FRAME_HEADER_LEN 14
#define FRAME_CRC_LEN 2
#define FRAME_MAX_PAYLOAD 256 /* MCU never sends/needs more (HK=44) */
#define FRAME_MAX (FRAME_HEADER_LEN + FRAME_MAX_PAYLOAD + FRAME_CRC_LEN)

enum packet_type {
    PKT_HK = 0x01,
    PKT_EVENT = 0x02,
    PKT_QUICKLOOK = 0x03,
    PKT_PISTATUS = 0x04,
    PKT_CMD = 0x10,
    PKT_ACK = 0x11,
    PKT_TIMESYNC = 0x12,
};

/* ACK results - mirror of clouds_link/frames.py AckResult. The MCU answers
 * every command frame with one of these, so ground learns what the *MCU*
 * decided rather than only that the Pi managed to write to the UART. */
enum ack_result {
    ACK_OK = 0,
    ACK_REJECTED = 1,   /* well-formed, but not allowed in this state */
    ACK_INVALID = 2,    /* unparseable, unknown command, or out-of-range value */
    ACK_NOT_ARMED = 3,  /* arm/execute violated (S.8) */
    ACK_INTERLOCK = 4,  /* ground interlock (S.10) - enforced on the Pi */
};

enum command {
    CMD_NONE = 0xFF, /* internal sentinel, never on the wire */
    CMD_PING = 0x00,
    CMD_START = 0x01,
    CMD_HOLD = 0x02,
    CMD_RESUME = 0x03,
    CMD_ABORT = 0x04,
    CMD_RELEASE = 0x05,
    CMD_SET_PARAM = 0x06,
    CMD_STATUS_REQ = 0x07,
    CMD_ARM = 0x08,
};

typedef struct {
    uint8_t type;
    uint16_t seq;
    uint32_t t_s;
    uint16_t t_ms;
    const uint8_t *payload; /* points into the decoded buffer */
    uint16_t plen;
} frame_view_t;

/* Housekeeping payload - 44 bytes, mirror of clouds_link/hk.py. */
#define HK_SIZE 44

typedef struct {
    uint8_t state, flags, fired, valve_status, membrane_duty, error_flags;
    int16_t temp1_cc, temp2_cc, bme_temp_cc;
    uint16_t rh1_cpct, rh2_cpct;
    uint32_t p_amb_pa, p_ch_pa;
    int16_t accel_mg[3], gyro_ddps[3];
    uint32_t uptime_s, mission_t_s;
} hk_t;

/* MCU flag bits (hk_t.flags) - mirror of clouds_link/hk.py McuFlags. */
#define MCUF_AUTONOMOUS_LATCHED (1u << 0)
#define MCUF_LINK_OK (1u << 1)
#define MCUF_PI_OK (1u << 2)
#define MCUF_SEAL_VERIFIED (1u << 3)
#define MCUF_HOLD (1u << 4)

/* Sensor error bits (hk_t.error_flags) - mirror of clouds_link/hk.py
 * HkErrors. A set bit means the matching HK field is NOT a live measurement,
 * so ground can tell a stale reading from a real one. */
#define HKE_BME280_FAIL (1u << 0)   /* BME280 absent or read failed */
#define HKE_P_AMB_STALE (1u << 1)   /* p_amb_pa is a held last-good value */
#define HKE_NO_CHAMBER_P (1u << 2)  /* no chamber pressure sensor fitted */
#define HKE_NO_RH2 (1u << 3)        /* no second humidity channel fitted */
#define HKE_IMU_FAIL (1u << 4)      /* IMU absent or reporting a fault */
#define HKE_NO_TEMP (1u << 5)       /* STLM20 pair not fitted: temps unsourced */

size_t frame_encode(uint8_t type, uint16_t seq, uint32_t t_s, uint16_t t_ms,
                    const uint8_t *payload, uint16_t plen,
                    uint8_t *out, size_t cap);
bool frame_decode(const uint8_t *data, size_t len, frame_view_t *view);

void hk_pack(const hk_t *hk, uint8_t out[HK_SIZE]);

/* CMD payload: cmd u8, key u8, value i32 LE (6 bytes). */
bool cmd_unpack(const frame_view_t *view, uint8_t *cmd, uint8_t *key,
                int32_t *value);
/* ACK payload: cmd_seq u16, cmd u8, result u8 LE (4 bytes). */
#define ACK_SIZE 4
void ack_pack(uint16_t cmd_seq, uint8_t cmd, uint8_t result,
              uint8_t out[ACK_SIZE]);
/* TIMESYNC payload: t_s u32, t_ms u16 LE. */
bool timesync_unpack(const frame_view_t *view, uint32_t *t_s, uint16_t *t_ms);
/* EVENT payload builder: code u8, severity u8, text. Returns plen. */
uint16_t event_pack(uint8_t code, uint8_t severity, const char *text,
                    uint8_t *out, size_t cap);

#endif
