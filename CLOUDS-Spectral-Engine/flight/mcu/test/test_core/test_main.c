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
#include "../../src/core/crc16.h"
#include "../../src/core/frame.h"
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
    hk.mission_t_s = 4210;
    hk_pack(&hk, out);
    TEST_ASSERT_EQUAL_UINT8(5, out[0]);
    TEST_ASSERT_EQUAL_UINT8(0x01, out[2]);
    /* temp1_cc LE at offset 6: -5512 = 0xEA78 */
    TEST_ASSERT_EQUAL_HEX8(0x78, out[6]);
    TEST_ASSERT_EQUAL_HEX8(0xEA, out[7]);
    /* p_amb_pa LE u32 at offset 16 */
    TEST_ASSERT_EQUAL_HEX8(0xB4, out[16]); /* 5300 = 0x14B4 */
    TEST_ASSERT_EQUAL_HEX8(0x14, out[17]);
    /* mission_t_s at offset 40 */
    TEST_ASSERT_EQUAL_HEX8(0x72, out[40]); /* 4210 = 0x1072 */
    TEST_ASSERT_EQUAL_HEX8(0x10, out[41]);
}

/* ---- config ------------------------------------------------------------ */

static void test_config_defaults_and_limits(void)
{
    cfg_t c;

    cfg_defaults(&c);
    TEST_ASSERT_EQUAL_INT32(5500, cfg_get(&c, PARAM_FLOAT_P_PA));
    TEST_ASSERT_EQUAL_INT32(480, cfg_get(&c, PARAM_T_MEASURE_S));
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

/* ---- mock ops + simulated flight harness (X-03) ------------------------ */

typedef struct {
    seq_persist_t last_persist;
    int persist_calls;
    int fire_order[8]; /* interleaved log: 100+n = persist w/ bit n,
                          200+n = fire n */
    int fire_log_n;
    int fires[3];
    int membrane_duty;
    int eq_close_calls;
    int seal_calls;
    uint64_t first_seal_ms;
    bool seal_result;
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

static void m_membrane(void *ctx, uint8_t duty)
{
    (void)ctx;
    M.membrane_duty = duty;
}

static bool m_seal_ok(void *ctx)
{
    (void)ctx;
    if (M.seal_calls++ == 0)
        M.first_seal_ms = SIM_MS;
    return M.seal_result;
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
    .membrane = m_membrane,
    .seal_ok = m_seal_ok,
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

static bool m_busy(void *ctx)
{
    (void)ctx;
    return pulse_busy(&MP);
}

static const seq_ops_t mock_ops_pulsed = {
    .persist = m_persist,
    .fire_pinch = m_fire_pulsed,
    .close_eq_valves = m_close_eq_pulsed,
    .membrane = m_membrane,
    .busy = m_busy,
    .seal_ok = m_seal_ok,
    .self_test = m_self_test,
    .event = m_event,
};

static void mock_reset(void)
{
    memset(&M, 0, sizeof M);
    M.seal_result = true;
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
        seq_step(s, (uint64_t)t * 1000u, t, profile_pa(t), profile_pa(t));
}

static void test_full_autonomous_flight(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);

    run_sim(&s, &cfg, 0, 300);
    TEST_ASSERT_EQUAL_INT(ST_STANDBY, s.state); /* on the pad */

    run_sim(&s, &cfg, 300, 1000);
    TEST_ASSERT_EQUAL_INT(ST_ASCENT, s.state); /* launch detected */
    TEST_ASSERT_TRUE(s.autonomy.launch_detected);

    /* through float + both releases + both measure phases */
    run_sim(&s, &cfg, 1000, 6000 + 300 /*hold*/ + 2 * 480 + 60);
    TEST_ASSERT_EQUAL_INT(ST_SAFE, s.state);
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]); /* exactly one fire each (O.2) */
    TEST_ASSERT_EQUAL_INT(1, M.fires[2]);
    TEST_ASSERT_EQUAL_INT(0, M.membrane_duty); /* off in SAFE */
    TEST_ASSERT_TRUE(M.eq_close_calls >= 2);   /* seal + termination */
    TEST_ASSERT_TRUE(s.seal_verified);
    /* zero ground commands were sent: full autonomy (O.2, T-07) */
}

static void test_persist_before_fire_ordering(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    run_sim(&s, &cfg, 0, 8000);
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
    run_sim(&s, &cfg, 0, 6350); /* into MEASURE_1, valve 1 fired */
    TEST_ASSERT_EQUAL_INT(ST_MEASURE_1, s.state);
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]);
    saved = M.last_persist;

    /* brownout reset: restore from the persisted snapshot */
    mock_reset();
    seq_init(&s, &cfg, &mock_ops, &saved, 6350000ull, 6350);
    run_sim(&s, &cfg, 6351, 6351 + 2 * 480 + 60);
    TEST_ASSERT_EQUAL_INT(ST_SAFE, s.state);
    TEST_ASSERT_EQUAL_INT(0, M.fires[1]); /* valve 1 NOT re-fired (S.3) */
    TEST_ASSERT_EQUAL_INT(1, M.fires[2]); /* valve 2 fired once */
}

static void test_resume_mid_release_treats_fired_as_done(void)
{
    cfg_t cfg;
    sequencer_t s;
    /* persisted DURING RELEASE_1, bit already set (persist-before-fire) */
    seq_persist_t saved = {.state = ST_RELEASE_1, .fired = 0x01,
                           .mission_start_s = 700, .launch_detected = true};

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, &saved, 1000000ull, 1000);
    TEST_ASSERT_EQUAL_INT(ST_MEASURE_1, s.state); /* measure, don't refire */
    run_sim(&s, &cfg, 1001, 1001 + 2 * 480 + 60);
    TEST_ASSERT_EQUAL_INT(0, M.fires[1]);
    TEST_ASSERT_EQUAL_INT(1, M.fires[2]);
    TEST_ASSERT_EQUAL_INT(ST_SAFE, s.state);
}

static void test_self_test_failure_goes_safe(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    M.self_test_result = false;
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    seq_step(&s, 1000, 1, 101325, 101325);
    TEST_ASSERT_EQUAL_INT(ST_SAFE, s.state);
    TEST_ASSERT_EQUAL_INT(0, M.fires[1] + M.fires[2]);
}

static void test_hold_blocks_resume_continues(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    run_sim(&s, &cfg, 0, 1000); /* ASCENT */
    seq_command(&s, 1000000ull, 1000, CMD_HOLD, 0, 0, &cfg);
    run_sim(&s, &cfg, 1001, 8000);
    TEST_ASSERT_EQUAL_INT(ST_ASCENT, s.state); /* held at float */
    TEST_ASSERT_EQUAL_INT(0, M.fires[1]);
    seq_command(&s, 8000000ull, 8000, CMD_RESUME, 0, 0, &cfg);
    run_sim(&s, &cfg, 8001, 8001 + 400 + 2 * 480 + 60);
    TEST_ASSERT_EQUAL_INT(ST_SAFE, s.state);
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]);
    TEST_ASSERT_EQUAL_INT(1, M.fires[2]);
}

static void test_abort_goes_safe_without_firing(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    run_sim(&s, &cfg, 0, 1000);
    seq_command(&s, 1000000ull, 1000, CMD_ABORT, 0, 0, &cfg);
    seq_step(&s, 1001000ull, 1001, profile_pa(1001), profile_pa(1001));
    TEST_ASSERT_EQUAL_INT(ST_SAFE, s.state);
    TEST_ASSERT_EQUAL_INT(0, M.fires[1] + M.fires[2]);
    TEST_ASSERT_EQUAL_INT(0, M.membrane_duty);
}

static void test_ground_release_override(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    run_sim(&s, &cfg, 0, 1000); /* ASCENT, before float */
    seq_command(&s, 1000000ull, 1000, CMD_RELEASE, 1, 0, &cfg);
    seq_step(&s, 1001000ull, 1001, profile_pa(1001), profile_pa(1001));
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]); /* early release accepted (S.2) */
    /* duplicate command must not double-fire */
    seq_command(&s, 1002000ull, 1002, CMD_RELEASE, 1, 0, &cfg);
    seq_step(&s, 1003000ull, 1003, profile_pa(1003), profile_pa(1003));
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]);
}

static void test_start_command_accelerates_standby(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    seq_step(&s, 1000, 1, 101325, 101325); /* INIT -> STANDBY */
    seq_command(&s, 2000, 2, CMD_START, 0, 0, &cfg);
    TEST_ASSERT_EQUAL_INT(ST_ASCENT, s.state);
    TEST_ASSERT_TRUE(s.mission_start_s > 0);
}

static void test_float_timer_fallback(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    /* pressure never satisfies the float criterion: stuck at 60000 Pa */
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    for (uint32_t t = 0; t < 700; t++)
        seq_step(&s, (uint64_t)t * 1000u, t, t < 600 ? 101325 : 60000,
                 101325);
    TEST_ASSERT_EQUAL_INT(ST_ASCENT, s.state);
    /* T_FLOAT_S (7200 s) after launch: fallback trips (S.1) */
    for (uint32_t t = 700; t < 700 + 7300; t++)
        seq_step(&s, (uint64_t)t * 1000u, t, 60000, 101325);
    TEST_ASSERT_TRUE(s.autonomy.float_detected);
    TEST_ASSERT_TRUE(s.state >= ST_SEAL);
}

static void test_seal_failure_retries_then_proceeds_flagged(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    M.seal_result = false;
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops, NULL, 0, 0);
    run_sim(&s, &cfg, 0, 6400);
    TEST_ASSERT_TRUE(s.state >= ST_RELEASE_1); /* proceeded anyway */
    TEST_ASSERT_FALSE(s.seal_verified);
    TEST_ASSERT_TRUE(s.seal_attempts > 3); /* default retries exhausted */
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]);
}

/* main.c's cadence: service the timed drives every 10 ms, step at 1 Hz. */
static void run_sim_pulsed(sequencer_t *s, uint32_t from_s, uint32_t to_s)
{
    for (SIM_MS = (uint64_t)from_s * 1000u; SIM_MS < (uint64_t)to_s * 1000u;
         SIM_MS += LOOP_MS) {
        pulse_service(&MP, SIM_MS, VALVE_PULSE_MS, rec_drive, NULL);
        if (SIM_MS % 1000u == 0) {
            uint32_t t = (uint32_t)(SIM_MS / 1000u);
            seq_step(s, SIM_MS, t, profile_pa(t), profile_pa(t));
        }
    }
}

static void test_seal_check_waits_for_the_valve_drive(void)
{
    cfg_t cfg;
    sequencer_t s;
    /* resume straight into SEAL so the state is exercised in isolation */
    seq_persist_t at_seal = {.state = ST_SEAL, .fired = 0,
                             .mission_start_s = 700, .launch_detected = true};

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops_pulsed, &at_seal, 0, 6000);

    for (SIM_MS = 0; SIM_MS <= 20000; SIM_MS += LOOP_MS) {
        pulse_service(&MP, SIM_MS, VALVE_PULSE_MS, rec_drive, NULL);
        if (SIM_MS % 1000u == 0)
            seq_step(&s, SIM_MS, 6000 + (uint32_t)(SIM_MS / 1000u), 5000,
                     5000);
    }

    /* one close command, not a burst of retries fired at the queue */
    TEST_ASSERT_EQUAL_INT(1, M.eq_close_calls);
    TEST_ASSERT_EQUAL_INT(1, M.seal_calls);
    /* and it was judged only after both lines finished driving (2 x 5 s):
     * a chamber pressure read while the valves move means nothing (M-15) */
    TEST_ASSERT_TRUE(M.first_seal_ms >= 2 * VALVE_PULSE_MS);
    TEST_ASSERT_TRUE(s.seal_verified);
    TEST_ASSERT_TRUE(s.state >= ST_RELEASE_1);
    TEST_ASSERT_EQUAL_INT(1, E.max_high);
}

static void test_full_flight_with_timed_drives(void)
{
    cfg_t cfg;
    sequencer_t s;

    mock_reset();
    cfg_defaults(&cfg);
    seq_init(&s, &cfg, &mock_ops_pulsed, NULL, 0, 0);

    /* the X-03 rehearsal again, this time with every actuation taking its
     * real 5 s and being released by the loop rather than slept through */
    run_sim_pulsed(&s, 0, 6000 + 300 + 2 * 480 + 120);

    TEST_ASSERT_EQUAL_INT(ST_SAFE, s.state);
    TEST_ASSERT_EQUAL_INT(1, M.fires[1]); /* still exactly one each (O.2) */
    TEST_ASSERT_EQUAL_INT(1, M.fires[2]);
    TEST_ASSERT_TRUE(s.seal_verified);
    TEST_ASSERT_EQUAL_INT(1, E.max_high);      /* one solenoid at a time */
    TEST_ASSERT_EQUAL_INT(0, E.n_high);        /* SAFE leaves nothing on */
    TEST_ASSERT_FALSE(pulse_busy(&MP));        /* no drive left pending */
    TEST_ASSERT_EQUAL_UINT16(0, MP.dropped);   /* no request was refused */
    TEST_ASSERT_EQUAL_INT(0, M.membrane_duty); /* membrane off in SAFE */
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
        seq_step(&s, (uint64_t)t * 1000u, t, 101325, 101325);
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
    seq_command(&s, 1000, 1, CMD_SET_PARAM, PARAM_T_MEASURE_S, 300, &cfg);
    TEST_ASSERT_EQUAL_INT32(300, cfg_get(&cfg, PARAM_T_MEASURE_S));
    seq_command(&s, 2000, 2, CMD_SET_PARAM, PARAM_T_MEASURE_S, -5, &cfg);
    TEST_ASSERT_EQUAL_INT32(300, cfg_get(&cfg, PARAM_T_MEASURE_S));
}


/* ---- M-07 membrane drive frequency (core/pwmdiv) ------------------------- */
/* The bug this guards: ops_membrane once set wrap=999 with the default
 * divider, i.e. 150 kHz on a 150 MHz part instead of the configured 50 Hz.
 * A push-pull solenoid at 150 kHz never oscillates, it just sees a DC
 * average, so the membrane would have done nothing in flight. */

#define SYS_150M 150000000u

static void test_membrane_default_frequency_is_actually_produced(void)
{
    uint32_t div16, period, actual;

    pwmdiv_solve(SYS_150M, (uint32_t)cfg_default(PARAM_MEMBRANE_HZ), &div16,
                 &period);
    actual = pwmdiv_actual_hz(SYS_150M, div16, period);

    /* within 1 % of the 50 Hz default, and nowhere near 150 kHz */
    TEST_ASSERT_UINT32_WITHIN(1, 50, actual);
    TEST_ASSERT_TRUE(period <= PWMDIV_MAX_WRAP);
    TEST_ASSERT_TRUE(div16 >= PWMDIV_MIN_DIV16 && div16 <= PWMDIV_MAX_DIV16);
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
    /* PARAM_MEMBRANE_HZ allows 1 Hz but the hardware bottoms out near 9 Hz.
     * The floor must be reported honestly so the caller can clamp instead of
     * silently emitting some other frequency. */
    uint32_t floor_hz = pwmdiv_min_hz(SYS_150M);
    uint32_t div16, period, actual;

    TEST_ASSERT_TRUE(floor_hz > 1);
    TEST_ASSERT_TRUE(floor_hz < 20);
    TEST_ASSERT_TRUE((int32_t)floor_hz > cfg_default(PARAM_MEMBRANE_HZ) - 50);

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
    RUN_TEST(test_full_autonomous_flight);
    RUN_TEST(test_persist_before_fire_ordering);
    RUN_TEST(test_resume_after_reset_does_not_refire);
    RUN_TEST(test_resume_mid_release_treats_fired_as_done);
    RUN_TEST(test_self_test_failure_goes_safe);
    RUN_TEST(test_hold_blocks_resume_continues);
    RUN_TEST(test_abort_goes_safe_without_firing);
    RUN_TEST(test_ground_release_override);
    RUN_TEST(test_start_command_accelerates_standby);
    RUN_TEST(test_float_timer_fallback);
    RUN_TEST(test_seal_failure_retries_then_proceeds_flagged);
    RUN_TEST(test_seal_check_waits_for_the_valve_drive);
    RUN_TEST(test_full_flight_with_timed_drives);
    RUN_TEST(test_linkloss_latch_and_recovery);
    RUN_TEST(test_set_param_range_checked);
    RUN_TEST(test_membrane_default_frequency_is_actually_produced);
    RUN_TEST(test_membrane_frequency_across_the_config_range);
    RUN_TEST(test_frequencies_below_the_hardware_floor_are_known);
    RUN_TEST(test_cfg_default_matches_cfg_defaults);
    return UNITY_END();
}
