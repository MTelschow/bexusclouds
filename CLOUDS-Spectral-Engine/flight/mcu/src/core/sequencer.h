/* Experiment sequencer (M-01..M-08): the authoritative state machine.
 *
 * Pure logic - all hardware effects go through seq_ops_t callbacks, all
 * inputs (time, pressure, commands) are injected, so the full autonomous
 * sequence runs on a desk (test harness X-03 = test/test_core).
 *
 * Invariants (spec S.1..S.3):
 *  - No state waits indefinitely for ground input; commands only
 *    accelerate, hold, or abort the default sequence.
 *  - persist() is called with the fired bit set BEFORE fire_pinch(): a
 *    brownout between the two loses one release but can never double-fire.
 *  - Any restore path never re-fires a valve whose bit is persisted.
 */
#ifndef CLOUDS_SEQUENCER_H
#define CLOUDS_SEQUENCER_H

#include <stdbool.h>
#include <stdint.h>

#include "autonomy.h"
#include "config.h"

/* Mirror of clouds_link/hk.py SeqState. */
typedef enum {
    ST_INIT = 0,
    ST_STANDBY = 1,
    ST_ASCENT = 2,
    ST_SEAL = 3,
    ST_RELEASE_1 = 4,
    ST_MEASURE_1 = 5,
    ST_RELEASE_2 = 6,
    ST_MEASURE_2 = 7,
    ST_TERMINATION = 8,
    ST_SAFE = 9,
} seq_state_t;

/* Event codes (PKT_EVENT payloads + log). */
enum seq_event {
    EV_STATE_CHANGE = 0x01,
    EV_SELF_TEST_FAIL = 0x02,
    EV_LAUNCH_DETECTED = 0x03,
    EV_FLOAT_DETECTED = 0x04,
    EV_SEAL_FAILED = 0x05,
    EV_RELEASE_FIRED = 0x06,
    EV_ABORTED = 0x07,
    EV_RESUMED_AFTER_RESET = 0x08,
    EV_AUTONOMOUS_LATCHED = 0x09,
    EV_PI_LINK_LOST = 0x0A,
    EV_PI_LINK_OK = 0x0B,
};

/* What survives a reset (persisted to SD/flash before it matters, S.3). */
typedef struct {
    uint8_t state;
    uint8_t fired; /* bit0 = pinch valve 1, bit1 = pinch valve 2 */
    uint32_t mission_start_s; /* wall-clock s of launch, 0 = none */
    bool launch_detected;
} seq_persist_t;

typedef struct {
    void *ctx;
    /* MUST be durable before returning - called before every fire. */
    void (*persist)(void *ctx, const seq_persist_t *p);
    /* The actuator calls only *schedule* the drive (core/pulse): they
     * return immediately, so nothing here can outrun the watchdog. */
    void (*fire_pinch)(void *ctx, uint8_t n); /* n = 1 | 2 */
    void (*close_eq_valves)(void *ctx);
    /* CaCO3 dispersion motor, one scheduled drive per release. Optional
     * (may be NULL): the carrier grew it after the SED was written, so a
     * board without it still sequences. */
    void (*disperse)(void *ctx);
    void (*membrane)(void *ctx, uint8_t duty_pct); /* 0 = off */
    /* Optional (may be NULL): true while a scheduled drive is still
     * running. Used to hold off seal_ok until the lines stopped moving. */
    bool (*busy)(void *ctx);
    bool (*seal_ok)(void *ctx);   /* chamber-vs-ambient divergence check */
    bool (*self_test)(void *ctx); /* sensors + SD + actuator continuity */
    void (*event)(void *ctx, uint8_t code, const char *msg);
} seq_ops_t;

typedef struct {
    seq_state_t state;
    uint8_t fired;
    bool hold;
    bool seal_verified;
    uint8_t seal_attempts;
    uint64_t state_entered_ms;
    uint64_t last_seal_try_ms;
    uint32_t mission_start_s;
    autonomy_t autonomy;
    const cfg_t *cfg;
    const seq_ops_t *ops;
} sequencer_t;

/* restored = NULL for a cold start; non-NULL resumes after a reset. */
void seq_init(sequencer_t *s, const cfg_t *cfg, const seq_ops_t *ops,
              const seq_persist_t *restored, uint64_t t_ms, uint32_t wall_s);
/* Call at ~1 Hz with fresh sensor data. */
void seq_step(sequencer_t *s, uint64_t t_ms, uint32_t wall_s,
              uint32_t p_amb_pa, uint32_t p_ch_pa);
/* Ground command, already arm-gated by core/link (and by the Pi before
 * that). Returns the enum ack_result to answer with: ACK_OK when it was
 * acted on, ACK_REJECTED when the command is not allowed in this state,
 * ACK_INVALID for an unknown command or an out-of-range parameter. Ground
 * gets the MCU's own verdict, not merely "the Pi wrote to the UART". */
uint8_t seq_command(sequencer_t *s, uint64_t t_ms, uint32_t wall_s,
                    uint8_t cmd, uint8_t key, int32_t value, cfg_t *cfg);
/* Any valid ground command refreshes the link-loss latch (O.2), including
 * the ones core/link answers itself and never passes on. */
void seq_note_ground_cmd(sequencer_t *s, uint64_t t_ms);
/* Mission-elapsed seconds for HK (0 before launch). */
uint32_t seq_mission_t_s(const sequencer_t *s, uint32_t wall_s);

#endif
