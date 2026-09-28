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
    /* 1, 3 and 4 are no longer produced anywhere (2026-09-18): with the
       ground interlock and the arm/execute gate gone, a command that this
       build can parse is executed. The values stay defined so an older
       session log still decodes to the name it was written with. */
    ACK_REJECTED = 1,   /* retired: "not allowed in this state" */
    ACK_INVALID = 2,    /* unparseable, unknown command, or out-of-range value */
    ACK_NOT_ARMED = 3,  /* retired with the arm/execute gate (was S.8) */
    ACK_INTERLOCK = 4,  /* retired with the ground interlock (was S.10) */
};

enum command {
    CMD_NONE = 0xFF, /* internal sentinel, never on the wire */
    CMD_PING = 0x00,
    CMD_START = 0x01,   /* autonomy armed: -> RUNNING, inhibit lifted */
    /* 0x02 (HOLD) and 0x03 (RESUME) are retired (2026-09-28): answered
     * ACK_INVALID, numbers not reused. See clouds_link/commands.py. */
    CMD_STOP = 0x04,    /* manual, and stay manual: -> TERMINATION -> SAFE
                         * with automatic mode inhibited. Was CMD_ABORT, and
                         * keeps its opcode because it keeps its effect. */
    CMD_RELEASE = 0x05, /* retired with the valves: answered ACK_INVALID */
    CMD_SET_PARAM = 0x06,
    CMD_STATUS_REQ = 0x07,
    CMD_ARM = 0x08,
    CMD_MEMBRANE = 0x09, /* key = duty percent, 0 = off */
    CMD_DISPERSE = 0x0A, /* key = DISPERSE_* below: stop / pulse / run */
    CMD_AUTOPILOT = 0x0B, /* run the automatic cycle now, link up or not;
                           * STOP, START or a manual drive ends it */
};

/* CMD_DISPERSE keys - mirror of clouds_link/commands.py DisperseKey. The key
 * is the request, never the speed (that is PARAM_DISPERSE_DUTY): PULSE is the
 * bounded 5 s drive a release also schedules, RUN holds the motor on until
 * STOP, and STOP ends whichever of the two is under way. */
#define DISPERSE_STOP 0u
#define DISPERSE_PULSE 1u
#define DISPERSE_RUN 2u

typedef struct {
    uint8_t type;
    uint16_t seq;
    uint32_t t_s;
    uint16_t t_ms;
    const uint8_t *payload; /* points into the decoded buffer */
    uint16_t plen;
} frame_view_t;

/* Housekeeping payload - 80 bytes, mirror of clouds_link/hk.py.
 *
 * Chamber temperature, humidity and pressure come from a SECOND BME280 on
 * SPI_1 (hw/board.h PIN_BME_CHAMBER_CS), at the end of the packet and
 * behind a flag of their own. Chamber acceleration and rate come from a
 * SECOND BNO055 on i2c0 at 0x28, appended after those, behind
 * HKE_IMU_CHM_FAIL. PM2.5 comes from a BMV080, also on SPI_1
 * (PIN_BMV080_CS), last on the wire and behind pm_status - a byte of its
 * own, because error_flags has no bits left.
 *
 * There is no second humidity channel on i2c0.
 *
 * Four rails are carried and three monitors are fitted: the 24 V rail's
 * INA226 is not populated yet, and its slot is reserved so that fitting the
 * part is a firmware change rather than a wire-format change.
 *
 * There is no size ceiling any more (2026-09-29): the downlink is budgeted
 * against the E-Link's own 100 kbit/s average, and an 80 B packet is 138 B
 * on the wire at 1 Hz, ~1 % of that. The 67 B ceiling that used to live here
 * came from a self-imposed 2 kbit/s figure and went with it; the Pi now
 * meters and shapes the downlink itself (clouds_link/linkrate.py), and
 * tests/test_fsw_telemetry.py::TestDownlinkBudget checks the whole mix.
 *
 * 78 B: the chamber IMU's 12 B were added on the operator's instruction
 * (2026-09-28) to get both IMUs on screen, and the BMV080's 2 B followed the
 * same day. PM2.5 is a single u16 rather than the six floats the vendor
 * library produces - chosen under the old ceiling and kept: PM1, PM10 and
 * all three number concentrations are dropped at the MCU, not binned on the
 * ground.
 *
 * 80 B: the dispersion motor encoder's speed (motor_rpm, i16) followed on
 * the operator's instruction the same day. */
#define HK_SIZE 80

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
 * RP2350A), where 0 would read as "no current", a reading an idle motor
 * legitimately produces. */
#define HB_SENSE_INVALID 0xFFFFu

/* "No reading" for hk_t.motor_rpm - mirror of MOTOR_RPM_INVALID in
 * clouds_link/hk.py. INT16_MIN, which motor_enc_rpm() never returns (it
 * saturates at +-INT16_MAX). Downlinked by a build that cannot reach the
 * encoder pins (pico2 / RP2350A) or whose counter did not start - where 0
 * would read as "motor stopped", the reading a stall produces. */
#define MOTOR_RPM_INVALID ((int16_t)-32768)

/* Rails carried in hk_t, in wire order: V_in, 24 V, 5 V, 3.3 V. One more
 * than the monitors that exist - see the note above HK_SIZE. Indexed by
 * enum ina226_rail in hw/ina226.h. */
#define RAIL_COUNT 4

/* The byte at offset 2 was `fired`, the two pinch-valve bits, until the
 * valves were removed from the experiment (2026-09-18); it then sat reserved
 * at 0, on the rule that this packet only ever grows by appending and no
 * field after it may move. It said the next field needing a byte should take
 * it, and the BMV080 is that field (2026-09-28): error_flags has no bits
 * left, so the particulate sensor's state lives here as pm_status.
 *
 * Cost of that, stated plainly: a session logged BEFORE 2026-09-18 decodes
 * its real valve bits into pm_status. Read an old log against the HK_SIZE
 * its frames carry. */
typedef struct {
    uint8_t state, flags, pm_status, valve_status, membrane_duty, error_flags;
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
    /* CaCO3 dispersion motor current sense (ACT_HB_SENS, GP46 / ADC6): the
     * raw 12-bit ADC sample, 0..4095 over the ADC reference, of the IPROPI
     * output of the motor's DRV8251A - the ACT_HB channel is GP17/GP18 drive
     * plus this sense, and it is NOT the membrane solenoid. Appended after
     * mission_t_s so every older field keeps its offset. Sent raw and scaled
     * on the ground (clouds_link/hk.py HB_SENSE_A_PER_V), like shunt_raw: the
     * IPROPI gain and its sense resistor are ground-side constants that can
     * be corrected against a logged session. HB_SENSE_INVALID means the pin
     * is not reachable in this build. */
    uint16_t hb_sense_raw;
    /* Chamber BME280 (SPI_1, chip select GP9): the test chamber's own
     * temperature, humidity and pressure, in the same units as the ambient
     * part's bme_temp_cc / rh1_cpct / p_amb_pa. Appended after
     * hb_sense_raw so every older field keeps its offset.
     *
     * INSTRUMENTATION ONLY. Nothing in core/ reads these: autonomy_step()
     * detects launch and float from p_amb_pa, the AMBIENT part, and giving
     * it a second pressure source would mean a chamber sensor fault could
     * fire valves. A chamber read failure is HKE_BME280_CHM_FAIL, its own
     * bit, for the same reason - the two parts fail independently and only
     * one of them is in the sequencer's path.
     *
     * Zeroed, not held, when the read fails: the holding rule exists
     * because a 0 Pa on p_amb_pa mimics a 100 kPa fall into launch
     * detection, and that hazard does not exist here. A held chamber value
     * would be a number that looks current and is not. */
    int16_t chm_temp_cc;
    uint16_t chm_rh_cpct;
    uint32_t chm_p_pa;
    /* Chamber BNO055 (i2c0, 0x28, COM3 low): same units as the ambient
     * part's accel_mg / gyro_ddps. Appended after chm_p_pa so every older
     * field keeps its offset. Zeros behind HKE_IMU_CHM_FAIL when the part has
     * nothing to give. Instrumentation only - nothing in core/ reads it. */
    int16_t chm_accel_mg[3], chm_gyro_ddps[3];
    /* BMV080 PM2.5 mass concentration (SPI_1, chip select GP12), ug/m3,
     * saturated at the part's specified 1000 ug/m3 range ceiling. Appended
     * after chm_gyro_ddps so every older field keeps its offset.
     *
     * Whether this is a measurement at all is in pm_status, not here: 0 is a
     * reading clean air legitimately produces, so there is no in-band
     * sentinel available. PM_FAIL means no sample; PM_STALE means this sweep
     * repeats the last one, which happens about one sweep in thirty-three
     * because the part's maximum output rate is 0.97 Hz against a 1 Hz
     * sweep.
     *
     * INSTRUMENTATION ONLY, like the chamber fields - nothing in core/ reads
     * it. Zeroed, not held, on a failed read. */
    uint16_t pm2_5_ugm3;
    /* Dispersion motor speed from its encoder (hw/board.h PIN_ENC_A), rpm,
     * the MEAN over the time since the previous packet (core/motor_enc.h),
     * signed - the sign is the direction, and which sign is forward is
     * unverified. No gearhead, so this is the output shaft too. Appended
     * after pm2_5_ugm3 so every older field keeps its offset.
     * MOTOR_RPM_INVALID when there is no encoder in this build. */
    int16_t motor_rpm;
} hk_t;

/* MCU flag bits (hk_t.flags) - mirror of clouds_link/hk.py McuFlags. */
#define MCUF_AUTONOMOUS_LATCHED (1u << 0)
#define MCUF_LINK_OK (1u << 1)
#define MCUF_PI_OK (1u << 2)
#define MCUF_SEAL_VERIFIED (1u << 3)
/* Automatic mode is inhibited: the operator sent STOP and no START has
 * lifted it. Bit unchanged from the MCUF_HOLD it replaces. */
#define MCUF_STOPPED (1u << 4)
/* The automatic cycle is running because the operator sent AUTOPILOT, not
 * because the link went silent. Cleared by STOP, START, a manual drive and
 * a reset. */
#define MCUF_AUTOPILOT (1u << 5)

/* Sensor error bits (hk_t.error_flags) - mirror of clouds_link/hk.py
 * HkErrors. A set bit means the matching HK field is NOT a live measurement,
 * so ground can tell a stale reading from a real one. */
#define HKE_BME280_FAIL (1u << 0)   /* BME280 absent or read failed */
#define HKE_P_AMB_STALE (1u << 1)   /* p_amb_pa is a held last-good value */
/* Bits 2 and 3 carried two retired sensor flags before 2026-09-11 and have
 * been reused since - bit 2 for the membrane switch, bit 3 for the chamber
 * BME280. Every other bit has kept its position, so an older session log
 * still decodes on those; these two do not, which is why a log has to be
 * read against the HK_SIZE its header implies. */
#define HKE_NO_MEMBRANE_SENSE (1u << 2) /* GP30 is not reachable in this build
                                         * (pico2 / RP2350A), so
                                         * HKV_MEMBRANE_PULLED has no source */
#define HKE_BME280_CHM_FAIL (1u << 3)   /* chamber BME280 (SPI_1 / GP9) absent
                                         * or read failed: chm_* are zeros,
                                         * not a measurement. Separate from
                                         * HKE_BME280_FAIL because the two
                                         * parts are on different buses and
                                         * only the ambient one feeds the
                                         * sequencer */
#define HKE_IMU_FAIL (1u << 4)      /* ambient IMU (0x29) absent or faulted */
#define HKE_NO_TEMP (1u << 5)       /* STLM20 pair not fitted: temps unsourced */
#define HKE_RAIL_FAIL (1u << 6)     /* one or more INA226 rails unreadable;
                                     * that rail's rail_mv is
                                     * RAIL_MV_INVALID */
#define HKE_IMU_CHM_FAIL (1u << 7)  /* chamber IMU (0x28) absent or faulted:
                                     * chm_accel_mg / chm_gyro_ddps are
                                     * zeros. The last free bit - which is
                                     * why the BMV080 got a byte of its own
                                     * instead (PM_* below). */

/* BMV080 state bits (hk_t.pm_status) - mirror of clouds_link/hk.py PmStatus.
 * A byte rather than more error_flags bits because that field is full, and
 * because this part needs to say more than "failed": an obstructed sensor is
 * answering correctly and still has no usable number.
 *
 * PM_FAIL clear and every other bit clear is the only state in which
 * pm2_5_ugm3 is a measurement. */
#define PM_FAIL (1u << 0)        /* no sample: open/start failed, the part
                                  * stopped answering, or the first reading
                                  * (~1.9 s after start) has not arrived */
#define PM_OBSTRUCTED (1u << 1)  /* something static is in the optical path,
                                  * within the datasheet's ~350 mm
                                  * obstruction-sensitive cone. The library
                                  * filters a passing hand; it cannot filter
                                  * an enclosure */
#define PM_RANGE (1u << 2)       /* outside the specified 0..1000 ug/m3
                                  * range, so pm2_5_ugm3 is saturated at
                                  * 1000 and is a floor, not a value */
#define PM_STALE (1u << 3)       /* this sweep repeats the previous sample.
                                  * Expected, not a fault: the part produces
                                  * 0.97 samples/s against a 1 Hz sweep */

/* Actuator drive bits (hk_t.valve_status) - mirror of clouds_link/hk.py
 * ValveStatus. A set bit means that line is energized *now*, which is how
 * ground sees a commanded drive happen: the dispersion motor's pulse is a
 * bounded drive that is over long before the next 1 Hz HK, so an operator
 * who cannot see this field cannot see it at all. HKV_DISPERSE is also set
 * for the length of a DISPERSE_RUN hold, which is not a pulse. The membrane
 * drive is not here; it is a repeating waveform, reported as a percentage in
 * hk_t.membrane_duty.
 *
 * Bit 5 is different in kind: it is an INPUT, the membrane position switch on
 * GP30 (hw/board.h PIN_MEMBRANE_SENSE), set while the plunger holds the
 * button pressed (pin LOW), i.e. the solenoid is actuated (pulled); clear
 * while the button is released (pin HIGH) and the solenoid rests. The pin
 * level is inverted into the bit. It says what the plunger is doing, not what
 * the MCU is driving, so it may be set alongside a drive bit - and it is what
 * tells ground a commanded membrane drive is moving anything. When the sense
 * pin is not reachable in the build, HKE_NO_MEMBRANE_SENSE says the bit is
 * unsourced rather than "pushed".
 *
 * Bit 6 is the switch's history over the last HK period: set when it changed
 * state at least once since the previous HK packet. It exists because bit 5
 * alone cannot show motion at 2 Hz: HK goes out every 1000 ms and the
 * membrane's 500 ms cycle is timed by the same 10 ms loop, so the 1 Hz sample
 * sits at a fixed phase and reads the same value packet after packet - a
 * running solenoid and a stuck one look identical in bit 5. The loop samples
 * the switch every pass and latches any edge into this bit. Drive on: CYCLING
 * set every packet. Drive off: clear, with PULLED clear too. Drive on and
 * CYCLING clear: the plunger is not moving. */
/* Bits 0..3 were the two pinch valves and the two equalisation valves. They
 * are retired with the valves (2026-09-18) and deliberately not reused: an
 * old session log still decodes bit 0 as the pinch valve it was, and a new
 * packet never sets it. */
#define HKV_DISPERSE (1u << 4)
#define HKV_MEMBRANE_PULLED (1u << 5)
#define HKV_MEMBRANE_CYCLING (1u << 6)
/* Bit 7 is sensed too, from the motor encoder: a drive was on, past its
 * spin-up grace, while the shaft turned slower than the stall floor, at any
 * point since the previous packet (core/motor_enc.h, latched every pass,
 * consumed per packet). A flag for ground, nothing on the MCU acts on it.
 * Never set while motor_rpm is MOTOR_RPM_INVALID - no encoder, no verdict. */
#define HKV_DISPERSE_STALLED (1u << 7)

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
