/* Native (host) unit tests for the portable FSW-MCU core.
 * Run with:  pio test -e native        (from flight/mcu/)
 * or:        ./test/run_native.sh      (plain cc, no PlatformIO)
 *
 * Includes the simulated-flight harness (feature X-03): a pressure profile
 * drives the sequencer through the full autonomous double release - the
 * bench rehearsal for T-07.
 */
#include <stdio.h>
#include <string.h>

#include <unity.h>

#include "../../src/core/autonomy.h"
#include "../../src/core/cobs.h"
#include "../../src/core/config.h"
#include "../../src/core/pwmdiv.h"
#include "../../src/core/sqwave.h"
#include "../../src/core/crc16.h"
#include "../../src/core/frame.h"
#include "../../src/core/link.h"
#include "../../src/core/pulse.h"
#include "../../src/core/sequencer.h"
#include "../../src/hw/board.h" /* pin map + timing constants only, no SDK */

void setUp(void) {}
void tearDown(void) {}

/* ---- crc16: must match clouds_link/crc16.py -------------------------- */

static void test_crc16_check_vector(void)
{
    TEST_ASSERT_EQUAL_HEX16(0x29B1, crc16((const uint8_t *)"123456789", 9));
}

static void test_crc16_empty_is_init(void)
{
    TEST_ASSERT_EQUAL_HEX16(0xFFFF, crc16(NULL, 0));
}

/* ---- cobs: canonical vectors + roundtrip ------------------------------ */

static void test_cobs_known_vectors(void)
{
    uint8_t out[600];
    /* encode(b"\x00") == 01 01 */
    uint8_t z = 0x00;
    TEST_ASSERT_EQUAL_size_t(2, cobs_encode(&z, 1, out, sizeof out));
    TEST_ASSERT_EQUAL_HEX8(0x01, out[0]);
    TEST_ASSERT_EQUAL_HEX8(0x01, out[1]);
    /* encode(b"\x11\x22\x00\x33") == 03 11 22 02 33 */
    uint8_t in[] = {0x11, 0x22, 0x00, 0x33};
    uint8_t want[] = {0x03, 0x11, 0x22, 0x02, 0x33};
    TEST_ASSERT_EQUAL_size_t(5, cobs_encode(in, 4, out, sizeof out));
    TEST_ASSERT_EQUAL_MEMORY(want, out, 5);
}

static void test_cobs_roundtrip_long(void)
{
    uint8_t in[500], enc[600], dec[600];
    size_t elen, dlen;

    for (int i = 0; i < 500; i++)
        in[i] = (uint8_t)(i % 7 == 0 ? 0 : i); /* zeros sprinkled in */
    elen = cobs_encode(in, sizeof in, enc, sizeof enc);
    TEST_ASSERT_TRUE(elen > 0);
    for (size_t i = 0; i < elen; i++)
        TEST_ASSERT_NOT_EQUAL(0, enc[i]); /* no delimiter inside */
    dlen = cobs_decode(enc, elen, dec, sizeof dec);
    TEST_ASSERT_EQUAL_size_t(sizeof in, dlen);
    TEST_ASSERT_EQUAL_MEMORY(in, dec, sizeof in);
}

static void test_cobs_decode_rejects_garbage(void)
{
    uint8_t out[16];
    uint8_t overrun[] = {0x05, 0x11};
    uint8_t embedded[] = {0x02, 0x00, 0x02, 0x11};

    TEST_ASSERT_EQUAL_size_t(0, cobs_decode(overrun, 2, out, sizeof out));
    TEST_ASSERT_EQUAL_size_t(0, cobs_decode(embedded, 4, out, sizeof out));
}

/* ---- frame: roundtrip + corruption ------------------------------------ */

static void test_frame_roundtrip(void)
{
    uint8_t payload[] = {1, 2, 3, 4, 5, 6};
    uint8_t buf[FRAME_MAX];
    frame_view_t v;
    size_t n;

    n = frame_encode(PKT_CMD, 42, 1750000000u, 250, payload, 6, buf,
                     sizeof buf);
    TEST_ASSERT_EQUAL_size_t(FRAME_HEADER_LEN + 6 + FRAME_CRC_LEN, n);
    TEST_ASSERT_TRUE(frame_decode(buf, n, &v));
    TEST_ASSERT_EQUAL_UINT8(PKT_CMD, v.type);
    TEST_ASSERT_EQUAL_UINT16(42, v.seq);
    TEST_ASSERT_EQUAL_UINT32(1750000000u, v.t_s);
    TEST_ASSERT_EQUAL_UINT16(250, v.t_ms);
    TEST_ASSERT_EQUAL_UINT16(6, v.plen);
    TEST_ASSERT_EQUAL_MEMORY(payload, v.payload, 6);
}

static void test_frame_corrupt_rejected(void)
{
    uint8_t buf[FRAME_MAX];
    frame_view_t v;
    size_t n = frame_encode(PKT_HK, 0, 0, 0, (const uint8_t *)"xy", 2, buf,
                            sizeof buf);

    buf[FRAME_HEADER_LEN] ^= 0xFF;
    TEST_ASSERT_FALSE(frame_decode(buf, n, &v));
    buf[FRAME_HEADER_LEN] ^= 0xFF;
    buf[0] = 0; /* bad magic */
    TEST_ASSERT_FALSE(frame_decode(buf, n, &v));
}

static void test_hk_pack_layout(void)
{
    hk_t hk = {0};
    uint8_t out[HK_SIZE];

    hk.state = 5;             /* MEASURE_1 */
    hk.fired = 0x01;
    hk.temp1_cc = -5512;      /* -55.12 C */
    hk.p_amb_pa = 5300;
    hk.rail_mv[0] = 24012;    /* V_in */
    hk.shunt_raw[0] = 514;    /* +1.285 mV -> 128.5 mA over 10 mOhm */
    hk.rail_mv[1] = RAIL_MV_INVALID;  /* 24 V: no monitor fitted */
    hk.rail_mv[2] = 5003;
    hk.shunt_raw[2] = -40;    /* current can flow either way: sign survives */
    hk.mission_t_s = 4210;
    hk.hb_sense_raw = 1500;   /* ADC counts, ~1.2 V at IPROPI = ~0.54 A */
    hk.chm_temp_cc = 2450;    /* chamber BME280 on SPI_1: 24.50 C */
    hk.chm_rh_cpct = 3812;    /* 38.12 %RH */
    hk.chm_p_pa = 98765;
    hk_pack(&hk, out);
    TEST_ASSERT_EQUAL_UINT8(5, out[0]);
    TEST_ASSERT_EQUAL_UINT8(0x01, out[2]);
    /* temp1_cc LE at offset 6: -5512 = 0xEA78 */
    TEST_ASSERT_EQUAL_HEX8(0x78, out[6]);
    TEST_ASSERT_EQUAL_HEX8(0xEA, out[7]);
    /* p_amb_pa LE u32 at offset 14 */
    TEST_ASSERT_EQUAL_HEX8(0xB4, out[14]); /* 5300 = 0x14B4 */
    TEST_ASSERT_EQUAL_HEX8(0x14, out[15]);
    /* rail_mv[] LE u16 x4 at offset 30, after the two IMU vectors */
    TEST_ASSERT_EQUAL_HEX8(0xCC, out[30]); /* 24012 = 0x5DCC */
    TEST_ASSERT_EQUAL_HEX8(0x5D, out[31]);
    /* an unreadable or unfitted rail is the sentinel on the wire, never 0 - a
     * rail that genuinely sits at 0 mV must stay distinguishable from one
     * with no reading behind it */
    TEST_ASSERT_EQUAL_HEX8(0xFF, out[32]);
    TEST_ASSERT_EQUAL_HEX8(0xFF, out[33]);
    /* shunt_raw[] LE i16 x4 at offset 38 */
    TEST_ASSERT_EQUAL_HEX8(0x02, out[38]); /* 514 = 0x0202 */
    TEST_ASSERT_EQUAL_HEX8(0x02, out[39]);
    TEST_ASSERT_EQUAL_HEX8(0xD8, out[42]); /* -40 = 0xFFD8, two's complement */
    TEST_ASSERT_EQUAL_HEX8(0xFF, out[43]);
    /* mission_t_s at offset 50 */
    TEST_ASSERT_EQUAL_HEX8(0x72, out[50]); /* 4210 = 0x1072 */
    TEST_ASSERT_EQUAL_HEX8(0x10, out[51]);
    /* hb_sense_raw LE u16 at offset 54, appended after mission_t_s so no
     * older field moved */
    TEST_ASSERT_EQUAL_HEX8(0xDC, out[54]); /* 1500 = 0x05DC */
    TEST_ASSERT_EQUAL_HEX8(0x05, out[55]);
    /* The chamber BME280 triple at offsets 56..63, appended after
     * hb_sense_raw so no older field moved. p_amb_pa above is 5300 Pa and
     * chm_p_pa here is 98765: the two pressures are deliberately far apart,
     * because a pack that crossed them would still decode to two plausible
     * pressures and only differing values catch it. */
    TEST_ASSERT_EQUAL_HEX8(0x92, out[56]); /* 2450 = 0x0992 */
    TEST_ASSERT_EQUAL_HEX8(0x09, out[57]);
    TEST_ASSERT_EQUAL_HEX8(0xE4, out[58]); /* 3812 = 0x0EE4 */
    TEST_ASSERT_EQUAL_HEX8(0x0E, out[59]);
    TEST_ASSERT_EQUAL_HEX8(0xCD, out[60]); /* 98765 = 0x000181CD */
    TEST_ASSERT_EQUAL_HEX8(0x81, out[61]);
    TEST_ASSERT_EQUAL_HEX8(0x01, out[62]);
    TEST_ASSERT_EQUAL_HEX8(0x00, out[63]);
    TEST_ASSERT_EQUAL_UINT32(64, (uint32_t)HK_SIZE);
}

/* ---- config ------------------------------------------------------------ */

static void test_config_defaults_and_limits(void)
{
    cfg_t c;

    cfg_defaults(&c);
    TEST_ASSERT_EQUAL_INT32(5500, cfg_get(&c, PARAM_FLOAT_P_PA));
    /* automatic mode's cycle: 2 min motor, 3 min solenoid, 5 min neither */
    TEST_ASSERT_EQUAL_INT32(120, cfg_get(&c, PARAM_AUTO_DISPERSE_S));
    TEST_ASSERT_EQUAL_INT32(180, cfg_get(&c, PARAM_AUTO_MEMBRANE_S));
    TEST_ASSERT_EQUAL_INT32(300, cfg_get(&c, PARAM_AUTO_WAIT_S));
    TEST_ASSERT_EQUAL_INT32(600, cfg_get(&c, PARAM_LINKLOSS_S));
    TEST_ASSERT_TRUE(cfg_set(&c, PARAM_AUTO_WAIT_S, 30));
    TEST_ASSERT_FALSE(cfg_set(&c, PARAM_AUTO_WAIT_S, 4));
    TEST_ASSERT_FALSE(cfg_set(&c, PARAM_AUTO_WAIT_S, 3601));
    /* 8 and 11 are retired keys (T_MEASURE_S, SEAL_RETRY). A sender that
     * still knows them must be refused, not quietly obeyed - including the
     * 0 that a {0,0,0} row would otherwise accept. */
    TEST_ASSERT_FALSE(cfg_set(&c, 8, 300));
    TEST_ASSERT_FALSE(cfg_set(&c, 8, 0));
    TEST_ASSERT_FALSE(cfg_set(&c, 11, 3));
    TEST_ASSERT_EQUAL_INT32(0, cfg_get(&c, 8));
    TEST_ASSERT_TRUE(cfg_set(&c, PARAM_FLOAT_P_PA, 6000));
    TEST_ASSERT_EQUAL_INT32(6000, cfg_get(&c, PARAM_FLOAT_P_PA));
    /* out-of-envelope values are refused (M-16 safety) */
    TEST_ASSERT_FALSE(cfg_set(&c, PARAM_FLOAT_P_PA, 999999));
    TEST_ASSERT_FALSE(cfg_set(&c, 0, 1));
    TEST_ASSERT_FALSE(cfg_set(&c, PARAM_COUNT_, 1));
    TEST_ASSERT_EQUAL_INT32(6000, cfg_get(&c, PARAM_FLOAT_P_PA));
}

/* ---- actuator pulses: non-blocking, timed, interlocked (S.8, S.9) ------ */

#define LOOP_MS 10u /* main.c's loop period */
#define EDGE_MAX 32

/* Records every pin edge the scheduler emits, with the virtual clock at
 * which it happened, and tracks how many outputs were high at once. */
static struct {
    uint8_t pin[EDGE_MAX];
    bool level[EDGE_MAX];
    uint64_t at_ms[EDGE_MAX];
    int n;
    bool high[64];
    int n_high, max_high;
} E;
static uint64_t SIM_MS;

static void rec_drive(void *ctx, uint8_t pin, bool level)
{
    (void)ctx;
    if (E.n < EDGE_MAX) {
        E.pin[E.n] = pin;
        E.level[E.n] = level;
        E.at_ms[E.n] = SIM_MS;
        E.n++;
    }
    if (level != E.high[pin]) {
        E.high[pin] = level;
        E.n_high += level ? 1 : -1;
        if (E.n_high > E.max_high)
            E.max_high = E.n_high;
    }
}

static void rec_reset(void)
{
    memset(&E, 0, sizeof E);
    SIM_MS = 0;
}

static void test_pulse_outlasts_the_watchdog_without_blocking(void)
{
    pulse_sched_t p;
    uint64_t held_ms;

    /* the reason core/pulse exists: a slept-through drive would reset the
     * MCU mid-actuation (S.9), and the resume path would re-fire (S.3) */
    TEST_ASSERT_TRUE(VALVE_PULSE_MS > WATCHDOG_TIMEOUT_MS);

    rec_reset();
    pulse_init(&p);
    TEST_ASSERT_FALSE(pulse_busy(&p));
    TEST_ASSERT_TRUE(pulse_request(&p, PIN_PINCH_1, PULSE_PIN_NONE));
    TEST_ASSERT_TRUE(pulse_busy(&p)); /* scheduled, nothing driven yet */

    /* main.c's loop: every pass is 10 ms, so every pass kicks the watchdog */
    for (SIM_MS = 0; SIM_MS <= 2 * VALVE_PULSE_MS; SIM_MS += LOOP_MS)
        pulse_service(&p, SIM_MS, VALVE_PULSE_MS, rec_drive, NULL);

    TEST_ASSERT_EQUAL_INT(2, E.n); /* exactly one energize + one release */
    TEST_ASSERT_EQUAL_UINT8(PIN_PINCH_1, E.pin[0]);
    TEST_ASSERT_TRUE(E.level[0]);
    TEST_ASSERT_EQUAL_UINT8(PIN_PINCH_1, E.pin[1]);
    TEST_ASSERT_FALSE(E.level[1]);
    /* full datasheet drive time, overrunning by at most one loop pass */
    held_ms = E.at_ms[1] - E.at_ms[0];
    TEST_ASSERT_TRUE(held_ms >= VALVE_PULSE_MS);
    TEST_ASSERT_TRUE(held_ms < VALVE_PULSE_MS + LOOP_MS);
    TEST_ASSERT_FALSE(pulse_busy(&p));
    TEST_ASSERT_EQUAL_UINT16(0, p.dropped);
}

static void test_eq_close_serialises_with_interlock(void)
{
    pulse_sched_t p;

    rec_reset();
    pulse_init(&p);
    /* exactly what hw.c's ops_close_eq_valves() queues */
    pulse_request(&p, PIN_EQ1_CLOSE, PIN_EQ1_OPEN);
    pulse_request(&p, PIN_EQ2_CLOSE, PIN_EQ2_OPEN);

    for (SIM_MS = 0; SIM_MS <= 3 * VALVE_PULSE_MS; SIM_MS += LOOP_MS)
        pulse_service(&p, SIM_MS, VALVE_PULSE_MS, rec_drive, NULL);

    /* never two solenoids energized at once (current budget, S.8) */
    TEST_ASSERT_EQUAL_INT(1, E.max_high);
    TEST_ASSERT_EQUAL_INT(6, E.n);
    /* the pair line is forced low before its partner is energized */
    TEST_ASSERT_EQUAL_UINT8(PIN_EQ1_OPEN, E.pin[0]);
    TEST_ASSERT_FALSE(E.level[0]);
    TEST_ASSERT_EQUAL_UINT8(PIN_EQ1_CLOSE, E.pin[1]);
    TEST_ASSERT_TRUE(E.level[1]);
    /* valve 2 starts only after valve 1 had its full drive */
    TEST_ASSERT_EQUAL_UINT8(PIN_EQ1_CLOSE, E.pin[2]);
    TEST_ASSERT_FALSE(E.level[2]);
    TEST_ASSERT_TRUE(E.at_ms[2] - E.at_ms[1] >= VALVE_PULSE_MS);
    TEST_ASSERT_EQUAL_UINT8(PIN_EQ2_CLOSE, E.pin[4]);
    TEST_ASSERT_TRUE(E.level[4]);
    TEST_ASSERT_TRUE(E.at_ms[4] >= VALVE_PULSE_MS);
    TEST_ASSERT_EQUAL_INT(0, E.n_high); /* everything de-energized at the end */
}

static void test_repeat_requests_coalesce(void)
{
    pulse_sched_t p;

    rec_reset();
    pulse_init(&p);
    /* the 1 Hz seal retry re-requests the same lines while they drive */
    for (int i = 0; i < 20; i++) {
        TEST_ASSERT_TRUE(pulse_request(&p, PIN_EQ1_CLOSE, PIN_EQ1_OPEN));
        TEST_ASSERT_TRUE(pulse_request(&p, PIN_EQ2_CLOSE, PIN_EQ2_OPEN));
    }
    TEST_ASSERT_EQUAL_UINT8(2, p.count); /* no pile-up, no overflow */
    TEST_ASSERT_EQUAL_UINT16(0, p.dropped);

    pulse_service(&p, 0, VALVE_PULSE_MS, rec_drive, NULL);
    TEST_ASSERT_EQUAL_UINT8(PIN_EQ1_CLOSE, p.active_pin);
    pulse_request(&p, PIN_EQ1_CLOSE, PIN_EQ1_OPEN);
    TEST_ASSERT_EQUAL_UINT8(1, p.count); /* the driving pin is not re-queued */
}

static void test_disperse_motor_drive_is_interlocked_and_timed(void)
{
    pulse_sched_t p;
    uint64_t held_ms;

    rec_reset();
    pulse_init(&p);
    /* exactly what hw.c's ops_disperse() queues. Only the forward line is
     * driven - the reverse sense is unverified - and the reverse line is its
     * interlock, so the pair can never be energized together. */
    pulse_request(&p, PIN_DISPERSE_FWD, PIN_DISPERSE_REV);

    for (SIM_MS = 0; SIM_MS <= 2 * VALVE_PULSE_MS; SIM_MS += LOOP_MS)
        pulse_service(&p, SIM_MS, VALVE_PULSE_MS, rec_drive, NULL);

    TEST_ASSERT_EQUAL_INT(1, E.max_high); /* never both lines at once */
    TEST_ASSERT_EQUAL_INT(3, E.n);
    TEST_ASSERT_EQUAL_UINT8(PIN_DISPERSE_REV, E.pin[0]);
    TEST_ASSERT_FALSE(E.level[0]); /* reverse forced low first */
    TEST_ASSERT_EQUAL_UINT8(PIN_DISPERSE_FWD, E.pin[1]);
    TEST_ASSERT_TRUE(E.level[1]);
    TEST_ASSERT_EQUAL_UINT8(PIN_DISPERSE_FWD, E.pin[2]);
    TEST_ASSERT_FALSE(E.level[2]); /* and released, not left running */
    held_ms = E.at_ms[2] - E.at_ms[1];
    TEST_ASSERT_TRUE(held_ms >= VALVE_PULSE_MS);
    TEST_ASSERT_TRUE(held_ms < VALVE_PULSE_MS + LOOP_MS);
    TEST_ASSERT_EQUAL_INT(0, E.n_high);
}

static void test_release_serialises_the_pinch_valve_and_the_motor(void)
{
    pulse_sched_t p;
    int fwd_high = -1, pinch_low = -1;

    rec_reset();
    pulse_init(&p);
    /* what fire() schedules for one release: the pinch valve, then the
     * dispersion motor. One drive at a time, so the motor waits its turn. */
    pulse_request(&p, PIN_PINCH_1, PULSE_PIN_NONE);
    pulse_request(&p, PIN_DISPERSE_FWD, PIN_DISPERSE_REV);

    for (SIM_MS = 0; SIM_MS <= 3 * VALVE_PULSE_MS; SIM_MS += LOOP_MS)
        pulse_service(&p, SIM_MS, VALVE_PULSE_MS, rec_drive, NULL);

    TEST_ASSERT_EQUAL_INT(1, E.max_high); /* peak current stays one drive */
    for (int i = 0; i < E.n; i++) {
        if (E.pin[i] == PIN_DISPERSE_FWD && E.level[i] && fwd_high < 0)
            fwd_high = i;
        if (E.pin[i] == PIN_PINCH_1 && !E.level[i])
            pinch_low = i;
    }
    TEST_ASSERT_TRUE(pinch_low >= 0);
    TEST_ASSERT_TRUE(fwd_high >= 0);
    /* the motor starts only after the valve had its full drive */
    TEST_ASSERT_TRUE(fwd_high > pinch_low);
    TEST_ASSERT_TRUE(E.at_ms[fwd_high] >= VALVE_PULSE_MS);
    TEST_ASSERT_EQUAL_INT(0, E.n_high);
}

static void test_queue_holds_every_drivable_line(void)
{
    pulse_sched_t p;
    const uint8_t lines[] = {PIN_PINCH_1,   PIN_PINCH_2,  PIN_EQ1_OPEN,
                            PIN_EQ1_CLOSE, PIN_EQ2_OPEN, PIN_EQ2_CLOSE,
                            PIN_DISPERSE_FWD, PIN_DISPERSE_REV};

    /* PULSE_SLOTS must cover every output on the board: a dropped request is
     * an actuation that silently never happens. */
    pulse_init(&p);
    for (unsigned i = 0; i < sizeof lines / sizeof lines[0]; i++)
        TEST_ASSERT_TRUE(pulse_request(&p, lines[i], PULSE_PIN_NONE));
    TEST_ASSERT_EQUAL_UINT16(0, p.dropped);
}

static void test_cancel_cuts_one_line_short_and_leaves_the_rest(void)
{
    pulse_sched_t p;

    rec_reset();
    pulse_init(&p);
    /* a release with the operator's Stop landing mid-motor: valve first,
     * motor after it, then a second valve queued behind the motor */
    pulse_request(&p, PIN_PINCH_1, PULSE_PIN_NONE);
    pulse_request(&p, PIN_DISPERSE_FWD, PIN_DISPERSE_REV);
    pulse_request(&p, PIN_PINCH_2, PULSE_PIN_NONE);

    for (SIM_MS = 0; SIM_MS <= VALVE_PULSE_MS + 500; SIM_MS += LOOP_MS)
        pulse_service(&p, SIM_MS, VALVE_PULSE_MS, rec_drive, NULL);
    TEST_ASSERT_EQUAL_UINT8(PIN_DISPERSE_FWD, p.active_pin);

    /* Stop: the motor line goes low now, not at its deadline */
    TEST_ASSERT_TRUE(pulse_cancel(&p, PIN_DISPERSE_FWD, rec_drive, NULL));
    TEST_ASSERT_EQUAL_UINT8(PIN_DISPERSE_FWD, E.pin[E.n - 1]);
    TEST_ASSERT_FALSE(E.level[E.n - 1]);
    TEST_ASSERT_EQUAL_UINT8(PULSE_PIN_NONE, p.active_pin);
    TEST_ASSERT_EQUAL_INT(0, E.n_high);
    /* the second valve still waits its turn, untouched */
    TEST_ASSERT_EQUAL_UINT8(1, p.count);
    pulse_service(&p, SIM_MS, VALVE_PULSE_MS, rec_drive, NULL);
    TEST_ASSERT_EQUAL_UINT8(PIN_PINCH_2, p.active_pin);

    /* a queued (not yet driving) motor pulse is dropped the same way */
    pulse_request(&p, PIN_DISPERSE_FWD, PIN_DISPERSE_REV);
    TEST_ASSERT_EQUAL_UINT8(1, p.count);
    TEST_ASSERT_TRUE(pulse_cancel(&p, PIN_DISPERSE_FWD, rec_drive, NULL));
    TEST_ASSERT_EQUAL_UINT8(0, p.count);
    TEST_ASSERT_EQUAL_UINT8(PIN_PINCH_2, p.active_pin); /* still driving */
    /* nothing to cancel is not an error, and drives nothing */
    TEST_ASSERT_FALSE(pulse_cancel(&p, PIN_DISPERSE_FWD, rec_drive, NULL));
    TEST_ASSERT_EQUAL_UINT8(PIN_PINCH_2, E.pin[E.n - 1]);
    TEST_ASSERT_TRUE(E.level[E.n - 1]);
}

/* ---- mock ops + simulated flight harness (X-03) ------------------------ */

typedef struct {
    seq_persist_t last_persist;
    int persist_calls;
    int fire_order[8]; /* interleaved log: 100+n = persist w/ bit n,
                          200+n = fire n */
    int fire_log_n;
    int fires[3];
    int membrane_duty;
    int disperse_calls;
    bool motor_on;        /* last disperse_run(on) */
    int motor_run_calls;  /* disperse_run(true) count: a re-latch is one */
    int eq_close_calls;
    bool self_test_result;
    uint8_t last_event;
} mock_t;

static mock_t M;

static void m_persist(void *ctx, const seq_persist_t *p)
{
    (void)ctx;
    M.last_persist = *p;
    M.persist_calls++;
    for (int n = 1; n <= 2; n++)
        if ((p->fired & (1 << (n - 1))) && M.fire_log_n < 8 && !M.fires[n]) {
            /* record the persist that first carries bit n */
            int already = 0;
            for (int i = 0; i < M.fire_log_n; i++)
                if (M.fire_order[i] == 100 + n)
                    already = 1;
            if (!already)
                M.fire_order[M.fire_log_n++] = 100 + n;
        }
}

static void m_fire(void *ctx, uint8_t n)
{
    (void)ctx;
    M.fires[n]++;
    if (M.fire_log_n < 8)
        M.fire_order[M.fire_log_n++] = 200 + n;
}

static void m_close_eq(void *ctx)
{
    (void)ctx;
    M.eq_close_calls++;
}

static void m_disperse(void *ctx)
{
    (void)ctx;
    M.disperse_calls++;
}

static void m_disperse_run(void *ctx, bool on)
{
    (void)ctx;
    M.motor_on = on;
    if (on)
        M.motor_run_calls++;
}

static void m_membrane(void *ctx, uint8_t duty)
{
    (void)ctx;
    M.membrane_duty = duty;
}

static bool m_self_test(void *ctx)
{
    (void)ctx;
    return M.self_test_result;
}

static void m_event(void *ctx, uint8_t code, const char *msg)
{
    (void)ctx;
    (void)msg;
    M.last_event = code;
}

static const seq_ops_t mock_ops = {
    .persist = m_persist,
    .fire_pinch = m_fire,
    .close_eq_valves = m_close_eq,
    .disperse = m_disperse,
    .disperse_run = m_disperse_run,
    .membrane = m_membrane,
    .self_test = m_self_test,
    .event = m_event,
};

/* Second ops table: the valve calls go through the real pulse scheduler, so
 * the sequencer sees flight timing (5 s per line, released by the loop)
 * instead of an instantaneous mock. `MP` mirrors hw.c's static scheduler. */
static pulse_sched_t MP;

static void m_close_eq_pulsed(void *ctx)
{
    (void)ctx;
    M.eq_close_calls++;
    pulse_request(&MP, PIN_EQ1_CLOSE, PIN_EQ1_OPEN);
    pulse_request(&MP, PIN_EQ2_CLOSE, PIN_EQ2_OPEN);
}

static void m_fire_pulsed(void *ctx, uint8_t n)
{
    m_fire(ctx, n);
    pulse_request(&MP, n == 1 ? PIN_PINCH_1 : PIN_PINCH_2, PULSE_PIN_NONE);
}

static void m_disperse_pulsed(void *ctx)
{
    m_disperse(ctx);
    pulse_request(&MP, PIN_DISPERSE_FWD, PIN_DISPERSE_REV);
}

static bool m_busy(void *ctx)
{
    (void)ctx;
    return pulse_busy(&MP);
}

static const seq_ops_t mock_ops_pulsed = {
    .persist = m_persist,
    .fire_pinch = m_fire_pulsed,
    .close_eq_valves = m_close_eq_pulsed,
    .disperse = m_disperse_pulsed,
    .disperse_run = m_disperse_run,
    .membrane = m_membrane,
    .busy = m_busy,
    .self_test = m_self_test,
    .event = m_event,
};

static void mock_reset(void)
{
    memset(&M, 0, sizeof M);
    M.self_test_result = true;
    pulse_init(&MP);
    rec_reset();
}

/* Simulated BEXUS profile: ground 101325 Pa -> linear descent in pressure
 * to 5000 Pa over 90 min -> float. Time compressed: 1 step = 1 s. */
static uint32_t profile_pa(uint32_t t_s)
{
    const uint32_t ground = 101325, flt = 5000, ascent_s = 5400;

    if (t_s < 600)
        return ground; /* on the pad */
    if (t_s < 600 + ascent_s) {
        uint64_t d = (uint64_t)(ground - flt) * (t_s - 600) / ascent_s;
        return ground - (uint32_t)d;
    }
    return flt;
}

static void run_sim(sequencer_t *s, cfg_t *cfg, uint32_t from_s,
                    uint32_t to_s)
{
    (void)cfg;
    for (uint32_t t = from_s; t < to_s; t++)
        seq_step(s, (uint64_t)t * 1000u, t, profile_pa(t));
}

/* The automatic-mode tests care about time and silence, not about a
 * pressure profile: nothing in the cycle reads the pressure. SIM_T is the
 * wall/monotonic second the next step happens at. */
static uint32_t SIM_T;

static void quiet_to(sequencer_t *s, uint32_t target_s)
{
    while (SIM_T <= target_s) {
        seq_step(s, (uint64_t)SIM_T * 1000u, SIM_T, 101325);
        SIM_T++;
    }
}

/* INIT -> STANDBY -> the operator's start button. Leaves SIM_T at 2 s and
 * the link-loss timer running from the START at 1 s. */
static void start_experiment(sequencer_t *s, cfg_t *cfg)
{
    SIM_T = 0;
    quiet_to(s, 0);
    TEST_ASSERT_EQUAL_INT(ST_STANDBY, s->state);
    TEST_ASSERT_EQUAL_UINT8(ACK_OK,
                            seq_command(s, 1000, 1, CMD_START, 0, 0, cfg));
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s->state);
    SIM_T = 2;
}

/* The second the current automatic phase was entered. */
static uint32_t phase_t0(const sequencer_t *s)
{
    return (uint32_t)(s->state_entered_ms / 1000u);
}

static void test_link_loss_runs_the_cycle(void)
{
    cfg_t cfg;
    sequencer_t s;
    uint32_t t0;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    start_experiment(&s, &cfg);

    /* Nine minutes of ground silence are not ten: still RUNNING, and
     * nothing is energized. */
    quiet_to(&s, 540);
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);
    TEST_ASSERT_FALSE(M.motor_on);
    TEST_ASSERT_EQUAL_INT(0, M.membrane_duty);

    /* PARAM_LINKLOSS_S (600 s) after the last command, the electronics take
     * over: motor first, and the solenoid stays off - "just dispersion". */
    quiet_to(&s, 620);
    TEST_ASSERT_EQUAL_INT(ST_AUTO_DISPERSE, s.state);
    TEST_ASSERT_TRUE(M.motor_on);
    TEST_ASSERT_EQUAL_INT(0, M.membrane_duty);

    /* 2 min of it, to the second. */
    t0 = phase_t0(&s);
    quiet_to(&s, t0 + 119);
    TEST_ASSERT_EQUAL_INT(ST_AUTO_DISPERSE, s.state);
    quiet_to(&s, t0 + 120);
    TEST_ASSERT_EQUAL_INT(ST_AUTO_MEMBRANE, s.state);
    TEST_ASSERT_FALSE(M.motor_on); /* solenoid ONLY */
    TEST_ASSERT_EQUAL_INT(cfg_get(&cfg, PARAM_MEMBRANE_DUTY),
                          M.membrane_duty);

    /* 3 min of solenoid. */
    t0 = phase_t0(&s);
    quiet_to(&s, t0 + 179);
    TEST_ASSERT_EQUAL_INT(ST_AUTO_MEMBRANE, s.state);
    quiet_to(&s, t0 + 180);
    TEST_ASSERT_EQUAL_INT(ST_AUTO_WAIT, s.state);
    TEST_ASSERT_FALSE(M.motor_on); /* neither: measure and save only */
    TEST_ASSERT_EQUAL_INT(0, M.membrane_duty);

    /* 5 min of waiting, then round again. */
    t0 = phase_t0(&s);
    quiet_to(&s, t0 + 299);
    TEST_ASSERT_EQUAL_INT(ST_AUTO_WAIT, s.state);
    quiet_to(&s, t0 + 300);
    TEST_ASSERT_EQUAL_INT(ST_AUTO_DISPERSE, s.state);
    TEST_ASSERT_TRUE(M.motor_on);

    /* Through all of it the pinch valves stayed shut: a release is never
     * automatic (S.8). */
    TEST_ASSERT_EQUAL_INT(0, M.fires[1] + M.fires[2]);
}

static void test_a_command_ends_the_cycle_at_once(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    start_experiment(&s, &cfg);
    quiet_to(&s, 700); /* into the motor phase */
    TEST_ASSERT_EQUAL_INT(ST_AUTO_DISPERSE, s.state);
    TEST_ASSERT_TRUE(M.motor_on);

    /* A bare heartbeat is enough - it is the link that matters, not what
     * the operator sent. The drives stop in the same call, not at the end
     * of the phase. */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 701000ull, 701, CMD_PING,
                                                0, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);
    TEST_ASSERT_FALSE(M.motor_on);
    TEST_ASSERT_EQUAL_INT(0, M.membrane_duty);
    TEST_ASSERT_EQUAL_UINT8(0, s.membrane_duty);

    /* And it stays off while the link is up. */
    SIM_T = 702;
    quiet_to(&s, 1000);
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);
    TEST_ASSERT_FALSE(M.motor_on);
}

static void test_the_cycle_restarts_at_the_motor_phase(void)
{
    cfg_t cfg;
    sequencer_t s;
    uint32_t t0;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    start_experiment(&s, &cfg);

    /* Far enough in to be past the motor phase... */
    quiet_to(&s, 900);
    TEST_ASSERT_EQUAL_INT(ST_AUTO_MEMBRANE, s.state);
    /* ...the link comes back... */
    seq_command(&s, 901000ull, 901, CMD_PING, 0, 0, &cfg);
    SIM_T = 902;
    /* ...and goes again. The cycle does not resume where it stopped: every
     * entry starts at the motor, so what the electronics do after a given
     * drop-out never depends on the one before it. */
    quiet_to(&s, 1550);
    TEST_ASSERT_EQUAL_INT(ST_AUTO_DISPERSE, s.state);
    t0 = phase_t0(&s);
    quiet_to(&s, t0 + 120);
    TEST_ASSERT_EQUAL_INT(ST_AUTO_MEMBRANE, s.state);
}

static void test_standby_never_starts_the_cycle(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    SIM_T = 0;
    /* Twenty minutes on the pad with nobody talking to it. A link that was
     * never up is not a link that was lost: without the start button the
     * experiment does nothing at all. */
    quiet_to(&s, 1200);
    TEST_ASSERT_EQUAL_INT(ST_STANDBY, s.state);
    TEST_ASSERT_FALSE(M.motor_on);
    TEST_ASSERT_EQUAL_INT(0, M.membrane_duty);
    TEST_ASSERT_EQUAL_INT(0, M.fires[1] + M.fires[2]);
}

static void test_release_works_without_a_dispersion_motor(void)
{
    cfg_t cfg;
    sequencer_t s;
    seq_ops_t no_motor = mock_ops;

    /* the motor is not in the SED and a board may not have it; a NULL op
     * must not stop a release. */
    no_motor.disperse = NULL;
    no_motor.disperse_run = NULL;
    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &no_motor, NULL, 0, 0);
    start_experiment(&s, &cfg);

    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 3000, 3, CMD_RELEASE, 1,
                                                0, &cfg));
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 4000, 4, CMD_RELEASE, 2,
                                                0, &cfg));
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]);
    TEST_ASSERT_EQUAL_INT(1, M.fires[2]);
    TEST_ASSERT_EQUAL_INT(0, M.disperse_calls);

    /* and the cycle still runs on a board without the motor: its motor
     * phase simply drives nothing. */
    quiet_to(&s, 700);
    TEST_ASSERT_EQUAL_INT(ST_AUTO_DISPERSE, s.state);
}

static void test_persist_before_fire_ordering(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    start_experiment(&s, &cfg);
    seq_command(&s, 3000, 3, CMD_RELEASE, 1, 0, &cfg);
    seq_command(&s, 4000, 4, CMD_RELEASE, 2, 0, &cfg);
    /* S.3: the persist carrying each fired bit precedes its fire call */
    TEST_ASSERT_EQUAL_INT(101, M.fire_order[0]); /* persist bit 1 */
    TEST_ASSERT_EQUAL_INT(201, M.fire_order[1]); /* fire 1 */
    TEST_ASSERT_EQUAL_INT(102, M.fire_order[2]); /* persist bit 2 */
    TEST_ASSERT_EQUAL_INT(202, M.fire_order[3]); /* fire 2 */
}

static void test_resume_after_reset_does_not_refire(void)
{
    cfg_t cfg;
    sequencer_t s;
    seq_persist_t saved;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    start_experiment(&s, &cfg);
    seq_command(&s, 3000, 3, CMD_RELEASE, 1, 0, &cfg);
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]);
    saved = M.last_persist;

    /* brownout reset: restore from the persisted snapshot */
    mock_reset();
    seq_init(&s, &cfg, &mock_ops, &saved, 10000, 10);
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);
    TEST_ASSERT_EQUAL_UINT8(0x01, s.fired);
    /* A ground command asking for valve 1 again is answered OK like every
     * other, and still cannot re-fire it: the persisted bit is the guard,
     * not the ACK (S.3). */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 11000, 11,
                                                CMD_RELEASE, 1, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(0, M.fires[1]);
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 12000, 12, CMD_RELEASE, 2,
                                                0, &cfg));
    TEST_ASSERT_EQUAL_INT(1, M.fires[2]);
}

static void test_resume_out_of_automatic_mode_comes_back_running(void)
{
    cfg_t cfg;
    sequencer_t s;
    /* persisted mid-cycle, one valve already fired by ground */
    seq_persist_t saved = {.state = ST_AUTO_MEMBRANE, .fired = 0x01,
                           .mission_start_s = 700, .launch_detected = true};

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, &saved, 1000000ull, 1000);
    /* A reset leaves the actuators off, so resuming into a phase that
     * believes they are on would be a lie. Back to RUNNING, and the cycle
     * re-enters from its first phase if the link is still gone. */
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);
    TEST_ASSERT_FALSE(s.motor_running);
    TEST_ASSERT_EQUAL_UINT8(0, s.membrane_duty);
    TEST_ASSERT_EQUAL_UINT8(0x01, s.fired);

    SIM_T = 1001;
    quiet_to(&s, 1700);
    TEST_ASSERT_EQUAL_INT(ST_AUTO_DISPERSE, s.state);
    TEST_ASSERT_EQUAL_INT(0, M.fires[1]); /* still not re-fired */
}

static void test_self_test_failure_goes_safe(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    M.self_test_result = false;
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    seq_step(&s, 1000, 1, 101325);
    TEST_ASSERT_EQUAL_INT(ST_SAFE, s.state);
    TEST_ASSERT_EQUAL_INT(0, M.fires[1] + M.fires[2]);
}

static void test_hold_keeps_the_cycle_off(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    start_experiment(&s, &cfg);

    /* HOLD is how an operator says "do nothing without me", and it outlives
     * the link: ten minutes of silence do not start the cycle. */
    seq_command(&s, 2000, 2, CMD_HOLD, 0, 0, &cfg);
    SIM_T = 3;
    quiet_to(&s, 1200);
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);
    TEST_ASSERT_TRUE(s.hold);
    TEST_ASSERT_FALSE(M.motor_on);

    /* RESUME is itself a command, so the link is up again; the next silence
     * runs the cycle as usual. */
    seq_command(&s, 1201000ull, 1201, CMD_RESUME, 0, 0, &cfg);
    SIM_T = 1202;
    quiet_to(&s, 1850);
    TEST_ASSERT_EQUAL_INT(ST_AUTO_DISPERSE, s.state);
    TEST_ASSERT_TRUE(M.motor_on);
}

static void test_abort_goes_safe_without_firing(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    start_experiment(&s, &cfg);
    quiet_to(&s, 700); /* let the cycle take over first */
    TEST_ASSERT_EQUAL_INT(ST_AUTO_DISPERSE, s.state);

    seq_command(&s, 701000ull, 701, CMD_ABORT, 0, 0, &cfg);
    seq_step(&s, 702000ull, 702, 101325);
    TEST_ASSERT_EQUAL_INT(ST_SAFE, s.state);
    TEST_ASSERT_EQUAL_INT(0, M.fires[1] + M.fires[2]);
    TEST_ASSERT_EQUAL_INT(0, M.membrane_duty);
    TEST_ASSERT_FALSE(M.motor_on);

    /* and the cycle cannot come back after an abort, however long the link
     * stays down */
    SIM_T = 703;
    quiet_to(&s, 1500);
    TEST_ASSERT_EQUAL_INT(ST_SAFE, s.state);
    TEST_ASSERT_FALSE(M.motor_on);
}

static void test_ground_release_fires_where_it_stands(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    seq_step(&s, 0, 0, 101325); /* INIT -> STANDBY */

    /* Even on the pad: while ground is connected the command executes. */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 500, 0, CMD_RELEASE, 1,
                                                0, &cfg));
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]);
    /* The release is an act, not a phase: the state it happens in is the
     * state it leaves behind. */
    TEST_ASSERT_EQUAL_INT(ST_STANDBY, s.state);
    TEST_ASSERT_EQUAL_INT(1, M.disperse_calls); /* the motor moves it out */

    start_experiment(&s, &cfg);
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 3000, 3, CMD_RELEASE, 2,
                                                0, &cfg));
    TEST_ASSERT_EQUAL_INT(1, M.fires[2]);
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);

    /* a duplicate is answered OK and still fires nothing */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 4000, 4, CMD_RELEASE, 2,
                                                0, &cfg));
    TEST_ASSERT_EQUAL_INT(1, M.fires[2]);
}

static void test_a_release_during_the_cycle_stops_it_first(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    start_experiment(&s, &cfg);
    quiet_to(&s, 700);
    TEST_ASSERT_EQUAL_INT(ST_AUTO_DISPERSE, s.state);
    TEST_ASSERT_TRUE(M.motor_on);

    /* The operator is back, so the cycle's motor stops before their release
     * is acted on - and the release then gets its own bounded drive rather
     * than landing on a motor that was already turning. */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 701000ull, 701,
                                                CMD_RELEASE, 1, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]);
    TEST_ASSERT_EQUAL_INT(1, M.disperse_calls);
    TEST_ASSERT_FALSE(s.motor_running);
}

static void test_start_button_starts_and_restarts(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    seq_step(&s, 1000, 1, 101325); /* INIT -> STANDBY */
    /* STANDBY still moves on nothing but the button - it is the automatic
     * path that cannot leave it, not a refusal of anything ground sends. */
    TEST_ASSERT_EQUAL_INT(ST_STANDBY, s.state);
    TEST_ASSERT_EQUAL_UINT8(ACK_OK,
                            seq_command(&s, 2000, 2, CMD_START, 0, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);
    TEST_ASSERT_TRUE(s.mission_start_s > 0);
    /* mission time runs from the first button press, and a second one does
     * not restart the clock */
    TEST_ASSERT_EQUAL_UINT32(8, seq_mission_t_s(&s, 10));
    TEST_ASSERT_EQUAL_UINT8(ACK_OK,
                            seq_command(&s, 3000, 3, CMD_START, 0, 5, &cfg));
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);
    TEST_ASSERT_EQUAL_UINT32(8, seq_mission_t_s(&s, 10));

    /* and it is the way back out of SAFE after an abort */
    seq_command(&s, 4000, 4, CMD_ABORT, 0, 0, &cfg);
    seq_step(&s, 5000, 5, 101325);
    TEST_ASSERT_EQUAL_INT(ST_SAFE, s.state);
    TEST_ASSERT_EQUAL_UINT8(ACK_OK,
                            seq_command(&s, 6000, 6, CMD_START, 0, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);
}

static void test_launch_and_float_are_reported_but_move_nothing(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    /* The whole BEXUS profile, with nobody pressing anything: detection
     * still runs and still reports, because ground wants to know when the
     * balloon left and when it levelled off - but since 2026-09-18 no state
     * depends on it, so the experiment sits in STANDBY throughout. */
    run_sim(&s, &cfg, 0, 8000);
    TEST_ASSERT_TRUE(s.autonomy.launch_detected);
    TEST_ASSERT_TRUE(s.autonomy.float_detected);
    TEST_ASSERT_EQUAL_INT(ST_STANDBY, s.state);
    TEST_ASSERT_EQUAL_INT(0, M.fires[1] + M.fires[2]);
    TEST_ASSERT_EQUAL_INT(0, M.eq_close_calls);
    TEST_ASSERT_EQUAL_UINT32(0, seq_mission_t_s(&s, 8000));
}


/* main.c's cadence: service the timed drives every 10 ms, step at 1 Hz. */
static void run_sim_pulsed(sequencer_t *s, uint32_t from_s, uint32_t to_s)
{
    for (SIM_MS = (uint64_t)from_s * 1000u; SIM_MS < (uint64_t)to_s * 1000u;
         SIM_MS += LOOP_MS) {
        pulse_service(&MP, SIM_MS, VALVE_PULSE_MS, rec_drive, NULL);
        if (SIM_MS % 1000u == 0) {
            uint32_t t = (uint32_t)(SIM_MS / 1000u);
            seq_step(s, SIM_MS, t, profile_pa(t));
        }
    }
}


static void test_releases_with_timed_drives(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops_pulsed, NULL, 0, 0);

    /* Both releases with every actuation taking its real 5 s and being
     * released by the loop rather than slept through. */
    SIM_MS = 0;
    pulse_service(&MP, SIM_MS, VALVE_PULSE_MS, rec_drive, NULL);
    seq_step(&s, 0, 0, 101325);
    seq_command(&s, 1000, 1, CMD_START, 0, 0, &cfg);
    seq_command(&s, 2000, 2, CMD_RELEASE, 1, 0, &cfg);
    seq_command(&s, 3000, 3, CMD_RELEASE, 2, 0, &cfg);
    for (SIM_MS = 3000; SIM_MS < 60000; SIM_MS += LOOP_MS) {
        pulse_service(&MP, SIM_MS, VALVE_PULSE_MS, rec_drive, NULL);
        if (SIM_MS % 1000u == 0)
            seq_step(&s, SIM_MS, (uint32_t)(SIM_MS / 1000u), 101325);
    }

    TEST_ASSERT_EQUAL_INT(1, M.fires[1]); /* exactly one each (O.2) */
    TEST_ASSERT_EQUAL_INT(1, M.fires[2]);
    TEST_ASSERT_EQUAL_INT(1, E.max_high);    /* one solenoid at a time */
    TEST_ASSERT_EQUAL_INT(0, E.n_high);      /* everything released again */
    TEST_ASSERT_FALSE(pulse_busy(&MP));      /* no drive left pending */
    TEST_ASSERT_EQUAL_UINT16(0, MP.dropped); /* no request was refused */
}

static void test_linkloss_latch_and_recovery(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    seq_command(&s, 1000, 1, CMD_PING, 0, 0, &cfg); /* link alive */
    for (uint32_t t = 2; t < 700; t++)
        seq_step(&s, (uint64_t)t * 1000u, t, 101325);
    TEST_ASSERT_TRUE(s.autonomy.autonomous_latched); /* > 600 s silent */
    seq_command(&s, 700000ull, 700, CMD_PING, 0, 0, &cfg);
    TEST_ASSERT_FALSE(s.autonomy.autonomous_latched); /* link back */
}

static void test_set_param_range_checked(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    seq_command(&s, 1000, 1, CMD_SET_PARAM, PARAM_AUTO_DISPERSE_S, 300, &cfg);
    TEST_ASSERT_EQUAL_INT32(300, cfg_get(&cfg, PARAM_AUTO_DISPERSE_S));
    seq_command(&s, 2000, 2, CMD_SET_PARAM, PARAM_AUTO_DISPERSE_S, -5, &cfg);
    TEST_ASSERT_EQUAL_INT32(300, cfg_get(&cfg, PARAM_AUTO_DISPERSE_S));
    /* a retired key is INVALID, not a silent write */
    TEST_ASSERT_EQUAL_UINT8(ACK_INVALID, seq_command(&s, 3000, 3,
                                                     CMD_SET_PARAM, 8, 300,
                                                     &cfg));
}


/* ---- M-07 membrane drive frequency (core/pwmdiv) ------------------------- */
/* The bug this guards: ops_membrane once set wrap=999 with the default
 * divider, i.e. 150 kHz on a 150 MHz part instead of the configured 50 Hz.
 * A push-pull solenoid at 150 kHz never oscillates, it just sees a DC
 * average, so the membrane would have done nothing in flight. */

#define SYS_150M 150000000u

static void test_membrane_default_is_below_the_pwm_floor(void)
{
    /* The membrane runs at 2 Hz, under the ~9 Hz PWM floor. This is the whole
     * reason core/sqwave exists: if the default ever rises above the floor,
     * the drive silently changes mechanism. */
    TEST_ASSERT_TRUE(cfg_default(PARAM_MEMBRANE_MHZ) <
                     (int32_t)pwmdiv_min_hz(SYS_150M) * 1000);
    TEST_ASSERT_EQUAL_INT32(2000, cfg_default(PARAM_MEMBRANE_MHZ));
}

static void test_membrane_frequency_is_millihertz_down_to_a_tenth(void)
{
    /* The operator drives the membrane at tenths of a hertz. In millihertz
     * 0.1 Hz is 100: a 10 s cycle, 6 s high at 60 %. Whole hertz could not
     * say this at all, and the range check must let it through while still
     * refusing a stale sender's "2" (2 mHz, a 500 s cycle). */
    sqwave_t w;
    cfg_t cfg;

    sqwave_init(&w);
    sqwave_start(&w, 100, 60, 0);
    TEST_ASSERT_EQUAL_UINT32(6000, w.on_ms);
    TEST_ASSERT_EQUAL_UINT32(4000, w.off_ms);
    sqwave_start(&w, 500, 50, 0);            /* 0.5 Hz */
    TEST_ASSERT_EQUAL_UINT32(1000, w.on_ms);
    TEST_ASSERT_EQUAL_UINT32(1000, w.off_ms);
    sqwave_start(&w, 400000, 50, 0);         /* 400 Hz: 2.5 ms -> 2 ms floor */
    TEST_ASSERT_EQUAL_UINT32(1, w.on_ms);
    TEST_ASSERT_EQUAL_UINT32(1, w.off_ms);

    cfg_defaults(&cfg);
    TEST_ASSERT_TRUE(cfg_set(&cfg, PARAM_MEMBRANE_MHZ, 100));
    TEST_ASSERT_TRUE(cfg_set(&cfg, PARAM_MEMBRANE_MHZ, 900));
    TEST_ASSERT_TRUE(cfg_set(&cfg, PARAM_MEMBRANE_MHZ, 400000));
    TEST_ASSERT_FALSE(cfg_set(&cfg, PARAM_MEMBRANE_MHZ, 99));
    TEST_ASSERT_FALSE(cfg_set(&cfg, PARAM_MEMBRANE_MHZ, 2));   /* old unit */
    TEST_ASSERT_FALSE(cfg_set(&cfg, PARAM_MEMBRANE_MHZ, 400001));
}

static void test_membrane_default_square_wave_timing(void)
{
    /* 2 Hz at the configured 20 % duty is 100 ms high, 400 ms low. */
    sqwave_t w;
    uint64_t t = 1000;
    int highs = 0, lows = 0;
    uint64_t last_edge = 0;

    sqwave_init(&w);
    sqwave_start(&w, (uint32_t)cfg_default(PARAM_MEMBRANE_MHZ),
                 (uint8_t)cfg_default(PARAM_MEMBRANE_DUTY), t);
    TEST_ASSERT_TRUE(sqwave_level(&w));   /* starts energized */
    TEST_ASSERT_EQUAL_UINT32(100, w.on_ms);
    TEST_ASSERT_EQUAL_UINT32(400, w.off_ms);

    /* run 3 s at the real 10 ms loop cadence and measure the phases */
    last_edge = t;
    for (int i = 0; i < 300; i++) {
        t += 10;
        if (sqwave_service(&w, t)) {
            uint32_t held = (uint32_t)(t - last_edge);
            last_edge = t;
            if (sqwave_level(&w)) {
                /* just went high, so the previous phase was the low one */
                TEST_ASSERT_UINT32_WITHIN(10, 400, held);
                lows++;
            } else {
                TEST_ASSERT_UINT32_WITHIN(10, 100, held);
                highs++;
            }
        }
    }
    TEST_ASSERT_TRUE(highs >= 5);
    TEST_ASSERT_TRUE(lows >= 5);
}

static void test_membrane_stop_leaves_the_output_low(void)
{
    sqwave_t w;

    sqwave_init(&w);
    TEST_ASSERT_FALSE(sqwave_level(&w));
    sqwave_start(&w, 2000, 60, 0);
    TEST_ASSERT_TRUE(sqwave_level(&w));
    sqwave_stop(&w);
    TEST_ASSERT_FALSE(sqwave_level(&w));
    TEST_ASSERT_FALSE(sqwave_active(&w));
    /* servicing a stopped wave must never re-energize it */
    for (uint64_t t = 0; t < 5000; t += 10)
        TEST_ASSERT_FALSE(sqwave_service(&w, t));
    TEST_ASSERT_FALSE(sqwave_level(&w));
}

static void test_membrane_late_service_does_not_burst_edges(void)
{
    /* A pass that arrives long after an edge was due must produce one edge,
     * not a catch-up burst: the late pass is the one where the loop had real
     * work to do. */
    sqwave_t w;

    sqwave_init(&w);
    sqwave_start(&w, 2000, 60, 0);
    TEST_ASSERT_TRUE(sqwave_service(&w, 5000)); /* 4.7 s late */
    TEST_ASSERT_FALSE(sqwave_level(&w));
    TEST_ASSERT_FALSE(sqwave_service(&w, 5000)); /* no second edge */
    TEST_ASSERT_FALSE(sqwave_service(&w, 5100));
    TEST_ASSERT_TRUE(sqwave_service(&w, 5200)); /* off_ms later */
}

static void test_membrane_duty_extremes_still_oscillate(void)
{
    /* duty 0 means "off" and must be expressed by stopping, not by starting
     * a wave that never rises - so a started wave always has both phases. */
    sqwave_t w;
    const uint8_t duties[] = {1, 50, 99, 100};

    for (unsigned i = 0; i < sizeof duties / sizeof duties[0]; i++) {
        sqwave_init(&w);
        sqwave_start(&w, 2000, duties[i], 0);
        TEST_ASSERT_TRUE(w.on_ms >= 1);
        TEST_ASSERT_TRUE(w.off_ms >= 1);
        TEST_ASSERT_EQUAL_UINT32(500, w.on_ms + w.off_ms);
    }
}

static void test_membrane_frequency_across_the_config_range(void)
{
    /* Every settable value that the hardware can reach must come out right. */
    const uint32_t hz[] = {9, 10, 25, 50, 100, 200, 400};

    for (unsigned i = 0; i < sizeof hz / sizeof hz[0]; i++) {
        uint32_t div16, period, actual;

        pwmdiv_solve(SYS_150M, hz[i], &div16, &period);
        actual = pwmdiv_actual_hz(SYS_150M, div16, period);
        /* 1 % tolerance: the divider is 1/16-quantised */
        TEST_ASSERT_UINT32_WITHIN(hz[i] / 100u + 1u, hz[i], actual);
        TEST_ASSERT_TRUE(period <= PWMDIV_MAX_WRAP);
    }
}

static void test_frequencies_below_the_hardware_floor_are_known(void)
{
    /* PARAM_MEMBRANE_MHZ allows 0.1 Hz but the hardware bottoms out near 9 Hz.
     * The floor must be reported honestly so the caller can clamp instead of
     * silently emitting some other frequency. */
    uint32_t floor_hz = pwmdiv_min_hz(SYS_150M);
    uint32_t div16, period, actual;

    TEST_ASSERT_TRUE(floor_hz > 1);
    TEST_ASSERT_TRUE(floor_hz < 20);

    /* at the floor itself the hardware must still be accurate */
    pwmdiv_solve(SYS_150M, floor_hz, &div16, &period);
    actual = pwmdiv_actual_hz(SYS_150M, div16, period);
    TEST_ASSERT_UINT32_WITHIN(1, floor_hz, actual);
}

static void test_cfg_default_matches_cfg_defaults(void)
{
    cfg_t c;

    cfg_defaults(&c);
    for (int k = 1; k < PARAM_COUNT_; k++)
        TEST_ASSERT_EQUAL_INT32(cfg_get(&c, (uint8_t)k), cfg_default((uint8_t)k));
    TEST_ASSERT_EQUAL_INT32(0, cfg_default(0));
    TEST_ASSERT_EQUAL_INT32(0, cfg_default(PARAM_COUNT_));
}


/* ---- core/link: Pi liveness + the MCU's own arm gate (M-13, S.7, S.8) ----- */
/* The Pi is a peer, not a dependency: everything here is reporting and
 * command safety. Nothing in link_step() may reach into the sequence. */

static void test_pi_liveness_needs_a_first_frame(void)
{
    cfg_t cfg;
    link_t l;

    cfg_defaults(&cfg);
    link_init(&l, 0);
    /* Never heard from: not "ok" and not a transition to report either -
     * a cold boot with the UART unplugged must not emit a link-lost event. */
    TEST_ASSERT_FALSE(link_step(&l, &cfg, 1000));
    TEST_ASSERT_FALSE(l.pi_ok);

    link_rx(&l, 1000);
    TEST_ASSERT_TRUE(link_step(&l, &cfg, 1000)); /* one transition: up */
    TEST_ASSERT_TRUE(l.pi_ok);
    TEST_ASSERT_FALSE(link_step(&l, &cfg, 2000)); /* steady, no repeat event */
}

static void test_pi_declared_lost_after_the_configured_silence(void)
{
    cfg_t cfg;
    link_t l;

    cfg_defaults(&cfg);
    link_init(&l, 0);
    link_rx(&l, 0);
    (void)link_step(&l, &cfg, 0);

    /* default PARAM_PI_SILENT_S = 60 */
    TEST_ASSERT_FALSE(link_step(&l, &cfg, 60000));
    TEST_ASSERT_TRUE(l.pi_ok);
    TEST_ASSERT_TRUE(link_step(&l, &cfg, 60001));
    TEST_ASSERT_FALSE(l.pi_ok);

    link_rx(&l, 70000); /* Pi comes back */
    TEST_ASSERT_TRUE(link_step(&l, &cfg, 70000));
    TEST_ASSERT_TRUE(l.pi_ok);
}

static void test_pi_silence_threshold_is_settable(void)
{
    cfg_t cfg;
    link_t l;

    cfg_defaults(&cfg);
    TEST_ASSERT_TRUE(cfg_set(&cfg, PARAM_PI_SILENT_S, 5));
    link_init(&l, 0);
    link_rx(&l, 0);
    (void)link_step(&l, &cfg, 0);
    TEST_ASSERT_TRUE(link_step(&l, &cfg, 5001));
    TEST_ASSERT_FALSE(l.pi_ok);
}





/* ---- command results: ground hears the MCU's verdict --------------------- */

static void test_no_command_is_refused_for_state(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    seq_step(&s, 1000, 1, 101325); /* INIT -> STANDBY */

    TEST_ASSERT_EQUAL_UINT8(ACK_OK,
                            seq_command(&s, 2000, 2, CMD_PING, 0, 0, &cfg));
    /* On the pad, before START: the release goes through. Nothing is held
     * back for state any more (2026-09-18). */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK,
                            seq_command(&s, 2100, 2, CMD_RELEASE, 1, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]);
    /* A second one is answered OK too, and still cannot re-fire the valve. */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK,
                            seq_command(&s, 2150, 2, CMD_RELEASE, 1, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]);
    /* An ARM is a no-op that is answered, not a gate. */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK,
                            seq_command(&s, 2160, 2, CMD_ARM, CMD_RELEASE, 0,
                                        &cfg));

    /* What is still INVALID is input this build cannot act on at all: a
     * corrupted frame must not come back as an OK. */
    TEST_ASSERT_EQUAL_UINT8(ACK_INVALID,
                            seq_command(&s, 2200, 2, CMD_RELEASE, 7, 0, &cfg));
    TEST_ASSERT_EQUAL_UINT8(ACK_INVALID,
                            seq_command(&s, 2300, 2, 0x7F, 0, 0, &cfg));
    TEST_ASSERT_EQUAL_UINT8(ACK_INVALID,
                            seq_command(&s, 2350, 2, CMD_MEMBRANE, 101, 0,
                                        &cfg));
    TEST_ASSERT_EQUAL_UINT8(ACK_INVALID,
                            seq_command(&s, 2400, 2, CMD_SET_PARAM,
                                        PARAM_AUTO_WAIT_S, -5, &cfg));
    TEST_ASSERT_EQUAL_UINT8(ACK_OK,
                            seq_command(&s, 2500, 2, CMD_SET_PARAM,
                                        PARAM_AUTO_WAIT_S, 300, &cfg));
    /* START works from STANDBY and from RUNNING alike. */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK,
                            seq_command(&s, 2600, 2, CMD_START, 0, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);
    TEST_ASSERT_EQUAL_UINT8(ACK_OK,
                            seq_command(&s, 2700, 2, CMD_START, 0, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);
}

static void test_a_drive_after_an_abort_wakes_the_experiment(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    start_experiment(&s, &cfg);
    seq_command(&s, 3000, 3, CMD_ABORT, 0, 0, &cfg);
    seq_step(&s, 4000, 4, 101325);
    TEST_ASSERT_EQUAL_INT(ST_SAFE, s.state);
    TEST_ASSERT_EQUAL_INT(0, M.membrane_duty);

    /* SAFE is no longer a lock-out: the drive runs, and the state follows
     * the hardware rather than reporting SAFE over a turning motor. */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 5000, 5, CMD_MEMBRANE, 60,
                                                0, &cfg));
    TEST_ASSERT_EQUAL_INT(60, M.membrane_duty);
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);

    seq_command(&s, 6000, 6, CMD_ABORT, 0, 0, &cfg);
    seq_step(&s, 7000, 7, 101325);
    TEST_ASSERT_EQUAL_INT(ST_SAFE, s.state);
    TEST_ASSERT_EQUAL_INT(0, M.membrane_duty);
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 8000, 8, CMD_DISPERSE,
                                                DISPERSE_RUN, 0, &cfg));
    TEST_ASSERT_TRUE(M.motor_on);
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);
    /* STOP still only de-energizes, and leaves the state where it is. */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 8100, 8, CMD_DISPERSE,
                                                DISPERSE_STOP, 0, &cfg));
    TEST_ASSERT_FALSE(M.motor_on);
}

/* ---- operator drives of the dispersion hardware (M-07) ------------------ */

static void test_manual_membrane_drive_and_stop(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    seq_step(&s, 1000, 1, 101325); /* INIT -> STANDBY, on the pad */

    /* On the pad is exactly where this is used: bench bring-up. No arm. */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 2000, 2, CMD_MEMBRANE,
                                                60, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(60, M.membrane_duty);
    TEST_ASSERT_EQUAL_UINT8(60, s.membrane_duty); /* what HK will report */
    TEST_ASSERT_EQUAL_UINT8(EV_MANUAL_DRIVE, M.last_event);

    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 3000, 3, CMD_MEMBRANE,
                                                0, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(0, M.membrane_duty);
    TEST_ASSERT_EQUAL_UINT8(0, s.membrane_duty);

    /* Out of range must not reach the hardware at all. */
    seq_command(&s, 4000, 4, CMD_MEMBRANE, 60, 0, &cfg);
    TEST_ASSERT_EQUAL_UINT8(ACK_INVALID, seq_command(&s, 4100, 4, CMD_MEMBRANE,
                                                     101, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(60, M.membrane_duty); /* unchanged */
    TEST_ASSERT_EQUAL_UINT8(60, s.membrane_duty);
}

static void test_manual_disperse_runs_one_motor_pulse(void)
{
    cfg_t cfg;
    sequencer_t s;
    seq_ops_t no_motor;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    seq_step(&s, 1000, 1, 101325);

    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 2000, 2, CMD_DISPERSE,
                                                1, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(1, M.disperse_calls);
    TEST_ASSERT_EQUAL_UINT8(EV_MANUAL_DRIVE, M.last_event);

    /* key is the request, not a duty: anything past DISPERSE_RUN is a bad
     * command (a speed sent as the key must not become a drive). */
    TEST_ASSERT_EQUAL_UINT8(ACK_INVALID, seq_command(&s, 2100, 2, CMD_DISPERSE,
                                                     3, 0, &cfg));
    TEST_ASSERT_EQUAL_UINT8(ACK_INVALID, seq_command(&s, 2200, 2, CMD_DISPERSE,
                                                     40, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(1, M.disperse_calls);
    TEST_ASSERT_EQUAL_INT(0, M.motor_run_calls);

    /* A board without the motor answers OK - nothing is refused any more -
     * and drives nothing, because there is no line to drive. */
    mock_reset();
    no_motor = mock_ops;
    no_motor.disperse = NULL;
    seq_init(&s, &cfg, &no_motor, NULL, 0, 0);
    seq_step(&s, 1000, 1, 101325);
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 2000, 2,
                                                CMD_DISPERSE, 1, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(0, M.disperse_calls);
}

static void test_manual_disperse_run_and_stop(void)
{
    cfg_t cfg;
    sequencer_t s;
    seq_ops_t no_motor;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    seq_step(&s, 1000, 1, 101325);

    /* Start: the motor is held on, HK will say so, and the event names it */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 2000, 2, CMD_DISPERSE,
                                                DISPERSE_RUN, 0, &cfg));
    TEST_ASSERT_TRUE(M.motor_on);
    TEST_ASSERT_TRUE(s.motor_running);
    TEST_ASSERT_EQUAL_INT(1, M.motor_run_calls);
    TEST_ASSERT_EQUAL_UINT8(EV_MANUAL_DRIVE, M.last_event);

    /* a pulse while it runs schedules nothing on top of the hold, and is
     * answered OK: the motor is turning, which is what was asked for */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 2100, 2, CMD_DISPERSE,
                                                DISPERSE_PULSE, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(0, M.disperse_calls);
    TEST_ASSERT_TRUE(M.motor_on);

    /* a new speed reaches a running motor at once, via one more run(true) */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 2200, 2, CMD_SET_PARAM,
                                                PARAM_DISPERSE_DUTY, 40,
                                                &cfg));
    TEST_ASSERT_EQUAL_INT(2, M.motor_run_calls);
    TEST_ASSERT_EQUAL_INT32(40, cfg_get(&cfg, PARAM_DISPERSE_DUTY));
    /* ...but an out-of-range speed touches neither cfg nor motor */
    TEST_ASSERT_EQUAL_UINT8(ACK_INVALID, seq_command(&s, 2250, 2,
                                                     CMD_SET_PARAM,
                                                     PARAM_DISPERSE_DUTY, 5,
                                                     &cfg));
    TEST_ASSERT_EQUAL_INT(2, M.motor_run_calls);
    /* and another parameter does not re-latch it */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 2260, 2, CMD_SET_PARAM,
                                                PARAM_MEMBRANE_MHZ, 3000, &cfg));
    TEST_ASSERT_EQUAL_INT(2, M.motor_run_calls);

    /* a second Start is idempotent: re-latch, still running */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 2300, 2, CMD_DISPERSE,
                                                DISPERSE_RUN, 0, &cfg));
    TEST_ASSERT_TRUE(s.motor_running);

    /* Stop */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 3000, 3, CMD_DISPERSE,
                                                DISPERSE_STOP, 0, &cfg));
    TEST_ASSERT_FALSE(M.motor_on);
    TEST_ASSERT_FALSE(s.motor_running);
    TEST_ASSERT_EQUAL_UINT8(EV_MANUAL_DRIVE, M.last_event);
    /* speed changes with the motor off do not start it */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 3100, 3, CMD_SET_PARAM,
                                                PARAM_DISPERSE_DUTY, 60,
                                                &cfg));
    TEST_ASSERT_FALSE(M.motor_on);
    /* a Stop with nothing running is harmless */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 3200, 3, CMD_DISPERSE,
                                                DISPERSE_STOP, 0, &cfg));
    /* and a pulse is possible again */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 3300, 3, CMD_DISPERSE,
                                                DISPERSE_PULSE, 0, &cfg));
    TEST_ASSERT_EQUAL_INT(1, M.disperse_calls);

    /* a release while the operator holds the motor on still fires its
     * valve, and does not ask for a bounded pulse on top of a motor that is
     * already turning */
    M.disperse_calls = 0;
    seq_command(&s, 4000, 4, CMD_START, 0, 0, &cfg);
    seq_command(&s, 4100, 4, CMD_DISPERSE, DISPERSE_RUN, 0, &cfg);
    seq_command(&s, 4200, 4, CMD_RELEASE, 1, 0, &cfg);
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]);
    TEST_ASSERT_EQUAL_INT(0, M.disperse_calls);
    TEST_ASSERT_TRUE(s.motor_running);

    /* No motor on the board: both are answered OK and neither reaches a
     * line. HK keeps saying the motor is held, because that is what the
     * sequencer was told to do with a motor it cannot see. */
    mock_reset();
    no_motor = mock_ops;
    no_motor.disperse = NULL;
    no_motor.disperse_run = NULL;
    seq_init(&s, &cfg, &no_motor, NULL, 0, 0);
    seq_step(&s, 1000, 1, 101325);
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 2000, 2, CMD_DISPERSE,
                                                DISPERSE_RUN, 0, &cfg));
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 2100, 2, CMD_DISPERSE,
                                                DISPERSE_STOP, 0, &cfg));
    TEST_ASSERT_FALSE(s.motor_running);
    TEST_ASSERT_EQUAL_INT(0, M.motor_run_calls);
}

static void test_termination_stops_a_running_motor(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    seq_step(&s, 1000, 1, 101325);
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 2000, 2, CMD_DISPERSE,
                                                DISPERSE_RUN, 0, &cfg));
    TEST_ASSERT_TRUE(M.motor_on);

    /* an abort takes the held motor down with the membrane */
    seq_command(&s, 3000, 3, CMD_ABORT, 0, 0, &cfg);
    seq_step(&s, 4000, 4, 101325); /* TERMINATION -> SAFE */
    TEST_ASSERT_EQUAL_INT(ST_SAFE, s.state);
    TEST_ASSERT_FALSE(M.motor_on);
    TEST_ASSERT_FALSE(s.motor_running);

    /* SAFE is not a lock-out: a Start after the abort runs the motor again
     * and takes the state with it, and Stop still only de-energizes. */
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 5000, 5, CMD_DISPERSE,
                                                DISPERSE_RUN, 0, &cfg));
    TEST_ASSERT_TRUE(M.motor_on);
    TEST_ASSERT_EQUAL_INT(ST_RUNNING, s.state);
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 5100, 5, CMD_DISPERSE,
                                                DISPERSE_STOP, 0, &cfg));
    TEST_ASSERT_FALSE(M.motor_on);
}

/* Motor speed (PARAM_DISPERSE_DUTY). The PWM programming itself lives in
 * hw.c and needs the SDK, so what is guarded here is the envelope: the
 * default is the configured half-speed drive, and no SET_PARAM may take the
 * motor to a duty that draws current without turning it. */
static void test_disperse_duty_default_and_bounds(void)
{
    cfg_t cfg;

    cfg_defaults(&cfg);
    TEST_ASSERT_EQUAL_INT32(50, cfg_default(PARAM_DISPERSE_DUTY));
    TEST_ASSERT_EQUAL_INT32(50, cfg_get(&cfg, PARAM_DISPERSE_DUTY));

    TEST_ASSERT_TRUE(cfg_set(&cfg, PARAM_DISPERSE_DUTY, 20));
    TEST_ASSERT_EQUAL_INT32(20, cfg_get(&cfg, PARAM_DISPERSE_DUTY));
    TEST_ASSERT_FALSE(cfg_set(&cfg, PARAM_DISPERSE_DUTY, 19));
    TEST_ASSERT_FALSE(cfg_set(&cfg, PARAM_DISPERSE_DUTY, 0));
    TEST_ASSERT_FALSE(cfg_set(&cfg, PARAM_DISPERSE_DUTY, 101));
    TEST_ASSERT_EQUAL_INT32(20, cfg_get(&cfg, PARAM_DISPERSE_DUTY));
}


static void test_sequencer_membrane_duty_tracks_the_automatic_drive(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    start_experiment(&s, &cfg);
    quiet_to(&s, 740); /* motor phase, then its 2 min */
    quiet_to(&s, phase_t0(&s) + 120);
    TEST_ASSERT_EQUAL_INT(ST_AUTO_MEMBRANE, s.state);
    /* HK read the duty as a constant 0 while the solenoid oscillated until
     * the sequencer started recording what it commanded. */
    TEST_ASSERT_EQUAL_UINT8((uint8_t)cfg_get(&cfg, PARAM_MEMBRANE_DUTY),
                            s.membrane_duty);
    TEST_ASSERT_EQUAL_INT(M.membrane_duty, s.membrane_duty);
}

static void test_release_already_fired_never_fires_twice(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    start_experiment(&s, &cfg);
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 3000, 3, CMD_RELEASE, 1,
                                                0, &cfg));
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]);
    TEST_ASSERT_EQUAL_UINT8(ACK_OK, seq_command(&s, 4000, 4, CMD_RELEASE, 1,
                                                0, &cfg));
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]); /* still exactly one fire (S.3) */
}

static void test_ground_link_latch_refreshes_without_the_sequencer(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    for (uint32_t t = 1; t < 700; t++)
        seq_step(&s, (uint64_t)t * 1000u, t, 101325);
    TEST_ASSERT_TRUE(s.autonomy.autonomous_latched);
    /* An ARM is answered by core/link and never reaches seq_command, but it
     * is still ground traffic - the latch must clear on it (O.2). */
    seq_note_ground_cmd(&s, 700000ull);
    TEST_ASSERT_FALSE(s.autonomy.autonomous_latched);
}

static void test_ack_payload_layout(void)
{
    uint8_t out[ACK_SIZE];

    ack_pack(0x1234, CMD_RELEASE, ACK_NOT_ARMED, out);
    TEST_ASSERT_EQUAL_UINT8(0x34, out[0]); /* cmd_seq LE */
    TEST_ASSERT_EQUAL_UINT8(0x12, out[1]);
    TEST_ASSERT_EQUAL_UINT8(CMD_RELEASE, out[2]);
    TEST_ASSERT_EQUAL_UINT8(3, out[3]);
}

static void test_event_severity_separates_faults_from_progress(void)
{
    /* Every event used to downlink at EVS_WARNING, so the field told ground
     * nothing and the panel could only show the raw number. */
    TEST_ASSERT_EQUAL_UINT8(EVS_CRITICAL, event_severity(EV_ABORTED));
    TEST_ASSERT_EQUAL_UINT8(EVS_ERROR, event_severity(EV_SELF_TEST_FAIL));
    TEST_ASSERT_EQUAL_UINT8(EVS_ERROR, event_severity(EV_SEAL_FAILED));
    TEST_ASSERT_EQUAL_UINT8(EVS_WARNING, event_severity(EV_PI_LINK_LOST));
    TEST_ASSERT_EQUAL_UINT8(EVS_WARNING,
                            event_severity(EV_AUTONOMOUS_LATCHED));
    TEST_ASSERT_EQUAL_UINT8(EVS_WARNING,
                            event_severity(EV_RESUMED_AFTER_RESET));
    TEST_ASSERT_EQUAL_UINT8(EVS_INFO, event_severity(EV_STATE_CHANGE));
    TEST_ASSERT_EQUAL_UINT8(EVS_INFO, event_severity(EV_RELEASE_FIRED));
    TEST_ASSERT_EQUAL_UINT8(EVS_INFO, event_severity(EV_PI_LINK_OK));
    /* An operator's own drive is not a fault. */
    TEST_ASSERT_EQUAL_UINT8(EVS_INFO, event_severity(EV_MANUAL_DRIVE));
}

static void test_not_every_event_is_one_severity(void)
{
    /* The regression this guards: a blanket return would pass every check
     * above that happens to expect that level. */
    bool seen[4] = {false, false, false, false};
    uint8_t code;

    for (code = EV_STATE_CHANGE; code <= EV_MANUAL_DRIVE; code++)
        seen[event_severity(code)] = true;
    TEST_ASSERT_TRUE(seen[EVS_INFO]);
    TEST_ASSERT_TRUE(seen[EVS_WARNING]);
    TEST_ASSERT_TRUE(seen[EVS_ERROR]);
    TEST_ASSERT_TRUE(seen[EVS_CRITICAL]);
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_crc16_check_vector);
    RUN_TEST(test_crc16_empty_is_init);
    RUN_TEST(test_cobs_known_vectors);
    RUN_TEST(test_cobs_roundtrip_long);
    RUN_TEST(test_cobs_decode_rejects_garbage);
    RUN_TEST(test_frame_roundtrip);
    RUN_TEST(test_frame_corrupt_rejected);
    RUN_TEST(test_hk_pack_layout);
    RUN_TEST(test_config_defaults_and_limits);
    RUN_TEST(test_pulse_outlasts_the_watchdog_without_blocking);
    RUN_TEST(test_eq_close_serialises_with_interlock);
    RUN_TEST(test_repeat_requests_coalesce);
    RUN_TEST(test_disperse_motor_drive_is_interlocked_and_timed);
    RUN_TEST(test_release_serialises_the_pinch_valve_and_the_motor);
    RUN_TEST(test_queue_holds_every_drivable_line);
    RUN_TEST(test_cancel_cuts_one_line_short_and_leaves_the_rest);
    RUN_TEST(test_link_loss_runs_the_cycle);
    RUN_TEST(test_a_command_ends_the_cycle_at_once);
    RUN_TEST(test_the_cycle_restarts_at_the_motor_phase);
    RUN_TEST(test_standby_never_starts_the_cycle);
    RUN_TEST(test_release_works_without_a_dispersion_motor);
    RUN_TEST(test_persist_before_fire_ordering);
    RUN_TEST(test_resume_after_reset_does_not_refire);
    RUN_TEST(test_resume_out_of_automatic_mode_comes_back_running);
    RUN_TEST(test_self_test_failure_goes_safe);
    RUN_TEST(test_hold_keeps_the_cycle_off);
    RUN_TEST(test_abort_goes_safe_without_firing);
    RUN_TEST(test_ground_release_fires_where_it_stands);
    RUN_TEST(test_a_release_during_the_cycle_stops_it_first);
    RUN_TEST(test_start_button_starts_and_restarts);
    RUN_TEST(test_launch_and_float_are_reported_but_move_nothing);
    RUN_TEST(test_releases_with_timed_drives);
    RUN_TEST(test_linkloss_latch_and_recovery);
    RUN_TEST(test_set_param_range_checked);
    RUN_TEST(test_membrane_default_is_below_the_pwm_floor);
    RUN_TEST(test_membrane_frequency_is_millihertz_down_to_a_tenth);
    RUN_TEST(test_membrane_default_square_wave_timing);
    RUN_TEST(test_membrane_stop_leaves_the_output_low);
    RUN_TEST(test_membrane_late_service_does_not_burst_edges);
    RUN_TEST(test_membrane_duty_extremes_still_oscillate);
    RUN_TEST(test_membrane_frequency_across_the_config_range);
    RUN_TEST(test_frequencies_below_the_hardware_floor_are_known);
    RUN_TEST(test_pi_liveness_needs_a_first_frame);
    RUN_TEST(test_pi_declared_lost_after_the_configured_silence);
    RUN_TEST(test_pi_silence_threshold_is_settable);
    RUN_TEST(test_no_command_is_refused_for_state);
    RUN_TEST(test_a_drive_after_an_abort_wakes_the_experiment);
    RUN_TEST(test_release_already_fired_never_fires_twice);
    RUN_TEST(test_manual_membrane_drive_and_stop);
    RUN_TEST(test_manual_disperse_runs_one_motor_pulse);
    RUN_TEST(test_manual_disperse_run_and_stop);
    RUN_TEST(test_termination_stops_a_running_motor);
    RUN_TEST(test_disperse_duty_default_and_bounds);
    RUN_TEST(test_sequencer_membrane_duty_tracks_the_automatic_drive);
    RUN_TEST(test_ground_link_latch_refreshes_without_the_sequencer);
    RUN_TEST(test_event_severity_separates_faults_from_progress);
    RUN_TEST(test_not_every_event_is_one_severity);
    RUN_TEST(test_ack_payload_layout);
    RUN_TEST(test_cfg_default_matches_cfg_defaults);
    return UNITY_END();
}
