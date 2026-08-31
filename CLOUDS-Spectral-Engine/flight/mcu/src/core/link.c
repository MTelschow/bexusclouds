#include "link.h"

#include "frame.h" /* enum command, enum ack_result */

void link_init(link_t *l, uint64_t t_ms)
{
    *l = (link_t){0};
    l->last_rx_ms = t_ms;
    l->armed_cmd = CMD_NONE;
}

void link_rx(link_t *l, uint64_t t_ms)
{
    l->last_rx_ms = t_ms;
    l->has_seen_pi = true;
}

bool link_step(link_t *l, const cfg_t *cfg, uint64_t t_ms)
{
    bool was = l->pi_ok;

    l->pi_ok = l->has_seen_pi &&
               t_ms - l->last_rx_ms <=
                   (uint64_t)cfg_get(cfg, PARAM_PI_SILENT_S) * 1000u;
    return l->pi_ok != was;
}

uint8_t link_gate(link_t *l, uint64_t t_ms, uint8_t cmd, uint8_t key)
{
    bool armed;

    if (cmd == CMD_ARM) {
        /* Only actuator commands are armable; ARM never reaches the
         * sequencer, exactly as on the Pi. */
        if (key != CMD_RELEASE)
            return ACK_INVALID;
        l->armed_cmd = CMD_RELEASE;
        l->armed_until_ms = t_ms + LINK_ARM_WINDOW_MS;
        return ACK_OK;
    }

    if (cmd == CMD_RELEASE) {
        armed = l->armed_cmd == CMD_RELEASE && t_ms <= l->armed_until_ms;
        l->armed_cmd = CMD_NONE; /* one ARM authorises one execute */
        if (!armed)
            return ACK_NOT_ARMED;
    }

    return LINK_PASS;
}
