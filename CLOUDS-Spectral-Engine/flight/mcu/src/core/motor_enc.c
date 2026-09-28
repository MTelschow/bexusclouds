#include "motor_enc.h"

/* The count is a free-running 32-bit value that wraps (~40 min at the
 * encoder's full 1.7 M counts/s). Differences taken in unsigned arithmetic
 * and read back signed are correct across the wrap. */
static int32_t delta(int32_t now, int32_t then)
{
    return (int32_t)((uint32_t)now - (uint32_t)then);
}

void motor_enc_init(motor_enc_t *m)
{
    m->primed = false;
    m->win_count = 0;
    m->win_ms = 0;
    m->hk_count = 0;
    m->hk_ms = 0;
    m->driving = false;
    m->drive_since_ms = 0;
    m->stalled = false;
}

int16_t motor_enc_rpm(int32_t dcount, uint32_t dt_ms)
{
    int64_t rpm;

    if (dt_ms == 0)
        return 0;
    /* counts / (counts/rev) / (ms / 60000 ms/min) */
    rpm = (int64_t)dcount * 60000 /
          ((int64_t)MOTOR_ENC_COUNTS_PER_REV * (int64_t)dt_ms);
    if (rpm > INT16_MAX)
        return INT16_MAX;
    if (rpm < -INT16_MAX)
        return -INT16_MAX;
    return (int16_t)rpm;
}

static void prime(motor_enc_t *m, int32_t count, uint64_t now_ms)
{
    m->primed = true;
    m->win_count = count;
    m->win_ms = now_ms;
    m->hk_count = count;
    m->hk_ms = now_ms;
}

void motor_enc_service(motor_enc_t *m, int32_t count, bool driving,
                       uint64_t now_ms)
{
    int16_t rpm;

    if (!m->primed)
        prime(m, count, now_ms);

    /* A drive starting restarts both the grace period and the window, so no
     * window that began with the motor at rest is judged against a drive. */
    if (driving && !m->driving) {
        m->drive_since_ms = now_ms;
        m->win_count = count;
        m->win_ms = now_ms;
    }
    m->driving = driving;

    if (now_ms - m->win_ms < MOTOR_ENC_STALL_WINDOW_MS)
        return;
    rpm = motor_enc_rpm(delta(count, m->win_count),
                        (uint32_t)(now_ms - m->win_ms));
    /* Judged only for a window that started after the grace period: one
     * that straddles spin-up would count the motor's acceleration as a
     * stall. Either direction counts as turning. */
    if (driving && m->win_ms >= m->drive_since_ms + MOTOR_ENC_STALL_GRACE_MS &&
        rpm < MOTOR_ENC_STALL_RPM_MIN && rpm > -MOTOR_ENC_STALL_RPM_MIN)
        m->stalled = true;
    m->win_count = count;
    m->win_ms = now_ms;
}

int16_t motor_enc_take_rpm(motor_enc_t *m, int32_t count, uint64_t now_ms)
{
    int16_t rpm;

    if (!m->primed) {
        prime(m, count, now_ms);
        return 0;
    }
    rpm = motor_enc_rpm(delta(count, m->hk_count),
                        (uint32_t)(now_ms - m->hk_ms));
    m->hk_count = count;
    m->hk_ms = now_ms;
    return rpm;
}

bool motor_enc_take_stalled(motor_enc_t *m)
{
    bool s = m->stalled;

    m->stalled = false;
    return s;
}
