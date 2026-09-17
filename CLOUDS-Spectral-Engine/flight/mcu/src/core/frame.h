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
#define FRAME_MAX_PAYLOAD 256 /* MCU never sends/needs more (HK=50) */
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
    CMD_MEMBRANE = 0x09, /* key = duty percent, 0 = off */
    CMD_DISPERSE = 0x0A, /* key = 1 -> one dispersion-motor pulse */
};

typedef struct {
    uint8_t type;
    uint16_t seq;
    uint32_t t_s;
    uint16_t t_ms;
    const uint8_t *payload; /* points into the decoded buffer */
    uint16_t plen;
} frame_view_t;

/* Housekeeping payload - 56 bytes, mirror of clouds_link/hk.py.
 *
 * No chamber pressure and no second humidity channel: the Keller 23SY pair
 * that was to source them is off the design (absent at every address on the
 * carrier, DEVLOG 2026-08-31), and a field no part can fill reads as data on
 * a display. Their six bytes now carry the INA226 shunt voltages instead.
 *
 * Four rails are carried and three monitors are fitted: the 24 V rail's
 * INA226 is not populated yet, and its slot is reserved so that fitting the
 * part is a firmware change rather than a wire-format change.
 *
 * The ceiling is 67 B: the 2 kbit/s continuous E-Link budget leaves ~83 B for
 * a framed HK packet alongside a 1 Hz quick-look. Growing past that means
 * binning the quick-look harder or slowing its cadence, and
 * tests/test_fsw_telemetry.py::TestDownlinkBudget fails first, by design. */
#define HK_SIZE 56

/* "No reading" for a rail_mv entry - mirror of RAIL_MV_INVALID in
 * clouds_link/hk.py. Not 0: a rail can legitimately *be* at 0 mV when its
 * supply is absent (the 24 V bus on a USB-powered bench), and collapsing that
 * into the same value as a failed I2C transfer throws away the distinction
 * ground most needs. 0xFFFF is 65.535 V, above the part's 36 V input rating,
 * so it cannot be a real measurement. Lives here, with the rest of the wire
 * schema, rather than in hw/ina226.h - it is a protocol value.
 *
 * It invalidates the matching shunt_raw entry too: both registers come from
 * the same part in the same sweep, so the pair is reported together rather
 * than needing a second sentinel for a bus-ok / shunt-failed split nobody
 * would chase on its own. */
#define RAIL_MV_INVALID 0xFFFFu

/* "No reading" for hk_t.hb_sense_raw - mirror of HB_SENSE_INVALID in
 * clouds_link/hk.py. The ADC is 12-bit, so no real sample exceeds 4095 and
 * 0xFFFF cannot be one. Downlinked by a build that cannot reach GP46 (pico2 /
 * RP2350A), where 0 would read as "no current", a reading a de-energized
 * solenoid legitimately produces. */
#define HB_SENSE_INVALID 0xFFFFu

/* Rails carried in hk_t, in wire order: V_in, 24 V, 5 V, 3.3 V. One more
 * than the monitors that exist - see the note above HK_SIZE. Indexed by
 * enum ina226_rail in hw/ina226.h. */
#define RAIL_COUNT 4

typedef struct {
    uint8_t state, flags, fired, valve_status, membrane_duty, error_flags;
    int16_t temp1_cc, temp2_cc, bme_temp_cc;
    uint16_t rh1_cpct;
    uint32_t p_amb_pa;
    int16_t accel_mg[3], gyro_ddps[3];
    /* Bus voltage of the V_in, 24 V, 5 V and 3.3 V rails, mV, indexed by
     * enum ina226_rail. RAIL_MV_INVALID (0xFFFF) means no reading - which is
     * NOT the same as 0 mV, a value a rail can legitimately hold when its
     * supply is absent (as V_in does on a USB-powered bench). The 24 V slot
     * reads RAIL_MV_INVALID always: no monitor is fitted on that rail yet. */
    uint16_t rail_mv[RAIL_COUNT];
    /* Raw INA226 shunt-voltage register per rail, same order: signed, 2.5 uV
     * per count, absolute (it does not depend on the part's calibration
     * register). Sent raw and turned into amps on the ground, where the shunt
     * resistances live (clouds_link/hk.py RAIL_SHUNT_MOHM) - so a logged
     * session can be re-derived if one of those values turns out to be wrong,
     * which an amp value computed in firmware could not be. Meaningful only
     * where rail_mv is not RAIL_MV_INVALID. */
    int16_t shunt_raw[RAIL_COUNT];
    uint32_t uptime_s, mission_t_s;
    /* Push-pull solenoid current sense (ACT_HB_SENS, GP46 / ADC6): the raw
     * 12-bit ADC sample, 0..4095 over the ADC reference. Appended after
     * mission_t_s so every older field keeps its offset. Sent raw and scaled
     * on the ground (clouds_link/hk.py HB_SENSE_A_PER_V), like shunt_raw: the
     * sense gain is a ground-side constant that can be corrected against a
     * logged session. HB_SENSE_INVALID means the pin is not reachable in
     * this build. */
    uint16_t hb_sense_raw;
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
/* Bit 2 was HKE_NO_CHAMBER_P and bit 3 HKE_NO_RH2; both went out with the
 * Keller pair and the fields they flagged. Bit 2 has since been reused for
 * the membrane switch; bit 3 is free. The surviving bits keep their
 * positions so an older session log still decodes. */
#define HKE_NO_MEMBRANE_SENSE (1u << 2) /* GP30 is not reachable in this build
                                         * (pico2 / RP2350A), so
                                         * HKV_MEMBRANE_PULLED has no source */
#define HKE_IMU_FAIL (1u << 4)      /* IMU absent or reporting a fault */
#define HKE_NO_TEMP (1u << 5)       /* STLM20 pair not fitted: temps unsourced */
#define HKE_RAIL_FAIL (1u << 6)     /* one or more INA226 rails unreadable;
                                     * that rail's rail_mv is
                                     * RAIL_MV_INVALID */

/* Actuator drive bits (hk_t.valve_status) - mirror of clouds_link/hk.py
 * ValveStatus. A set bit means that line is energized *now*, which is how
 * ground sees a manually commanded drive happen: the pinch valves and the
 * dispersion motor are bounded pulses that are over long before the next 1 Hz
 * HK, so an operator who cannot see this field cannot see them at all. Only
 * one *drive* bit is ever set at a time - core/pulse drives one line at a
 * time to cap peak actuator current. The membrane drive is not here; it is a
 * repeating waveform, reported as a percentage in hk_t.membrane_duty.
 *
 * Bit 5 is different in kind: it is an INPUT, the membrane position switch on
 * GP30 (hw/board.h PIN_MEMBRANE_SENSE), set while the switch reads the
 * solenoid as energized (pulled). It says what the plunger is doing, not what
 * the MCU is driving, so it may be set alongside a drive bit - and it is what
 * tells ground a commanded membrane drive is moving anything. When the sense
 * pin is not reachable in the build, HKE_NO_MEMBRANE_SENSE says the bit is
 * unsourced rather than "pushed". */
#define HKV_PINCH_1 (1u << 0)
#define HKV_PINCH_2 (1u << 1)
#define HKV_EQ1_CLOSE (1u << 2)
#define HKV_EQ2_CLOSE (1u << 3)
#define HKV_DISPERSE (1u << 4)
#define HKV_MEMBRANE_PULLED (1u << 5)

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
/* Severity levels of an EVENT payload - mirror of
 * clouds_link.frames.EventSeverity. */
#define EVS_INFO 0
#define EVS_WARNING 1
#define EVS_ERROR 2
#define EVS_CRITICAL 3

uint16_t event_pack(uint8_t code, uint8_t severity, const char *text,
                    uint8_t *out, size_t cap);

#endif
