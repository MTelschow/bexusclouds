#include "link.h"

void link_init(link_t *l, uint64_t t_ms)
{
    *l = (link_t){0};
    l->last_rx_ms = t_ms;
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
