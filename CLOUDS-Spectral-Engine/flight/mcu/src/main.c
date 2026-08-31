/* CLOUDS FSW-MCU main loop (RP2350).
 *
 * 1 Hz: read sensors -> log redundantly -> emit HK over UART -> step the
 * sequencer. Every iteration: poll UART commands, service the timed
 * actuator drives, kick the watchdog. Nothing in the loop blocks longer
 * than one 10 ms pass, so the 2 s watchdog only ever bites on a real hang.
 * The Pi is a peer, never a dependency (S.7): this loop is complete with
 * the UART unplugged.
 */
#include <string.h>

#include "pico/stdlib.h"

#include "core/config.h"
#include "core/frame.h"
#include "core/link.h"
#include "core/sequencer.h"
#include "hw/hw.h"
#include "hw/uart_io.h"

#define HK_PERIOD_MS 1000u
/* Frames handled per loop pass. Every command is answered with a blocking
 * ACK write (~2 ms at 115200), so an unbounded drain lets a flood of uplink
 * frames - a stuck Pi, a noisy line - hold the loop past the 2 s watchdog.
 * Eight per 10 ms pass is 800/s, far above any real command rate, and the
 * rest simply wait in the UART FIFO for the next pass. */
#define MAX_FRAMES_PER_PASS 8u

static cfg_t cfg;
static sequencer_t seq;
static link_t pi_link;
/* One sequence counter per packet type - a shared one makes every interleaved
 * packet of another type look lost to the GSE gap tracker. */
static uint16_t hk_seq_no;
static uint16_t ev_seq_no;
static uint16_t ack_seq_no;

static void send_event(uint8_t code, const char *msg)
{
    uint8_t payload[2 + 64];
    uint16_t plen = event_pack(code, 1, msg, payload, sizeof payload);
    uint32_t wall = hw_wall_s();

    if (plen)
        uart_io_send(PKT_EVENT, ev_seq_no++, wall, 0, payload, plen);
    hw_log_event(code, msg, wall);
}

/* Every command frame is answered, whoever decided the outcome: the arm gate,
 * the sequencer, or a failed parse. Without this the Pi can only tell ground
 * that it managed to write to the UART. */
static void send_ack(uint16_t cmd_seq, uint8_t cmd, uint8_t result)
{
    uint8_t payload[ACK_SIZE];

    ack_pack(cmd_seq, cmd, result, payload);
    uart_io_send(PKT_ACK, ack_seq_no++, hw_wall_s(), 0, payload, ACK_SIZE);
}

static void send_hk(uint64_t t_ms)
{
    hk_t hk;
    uint8_t payload[HK_SIZE];
    uint32_t wall = hw_wall_s();

    memset(&hk, 0, sizeof hk);
    hw_read_sensors(&hk);
    hk.state = (uint8_t)seq.state;
    hk.fired = seq.fired;
    hk.flags = (uint8_t)((seq.autonomy.autonomous_latched
                              ? MCUF_AUTONOMOUS_LATCHED
                              : 0) |
                         (seq.autonomy.has_seen_cmd &&
                                  !seq.autonomy.autonomous_latched
                              ? MCUF_LINK_OK
                              : 0) |
                         (pi_link.pi_ok ? MCUF_PI_OK : 0) |
                         (seq.seal_verified ? MCUF_SEAL_VERIFIED : 0) |
                         (seq.hold ? MCUF_HOLD : 0));
    hk.uptime_s = (uint32_t)(t_ms / 1000u);
    hk.mission_t_s = seq_mission_t_s(&seq, wall);

    hw_log_hk(&hk, wall); /* storage copy first (O.3), then downlink */
    hk_pack(&hk, payload);
    uart_io_send(PKT_HK, hk_seq_no++, wall, 0, payload, HK_SIZE);

    /* step the sequence with the same sensor sweep */
    seq_step(&seq, t_ms, wall, hk.p_amb_pa, hk.p_ch_pa);
}

static void handle_command(uint64_t t_ms, const frame_view_t *view)
{
    uint8_t cmd, key, result;
    int32_t value;

    if (!cmd_unpack(view, &cmd, &key, &value)) {
        send_ack(view->seq, CMD_NONE, ACK_INVALID);
        return;
    }
    /* Any valid command means the ground link lives, including ARM, which
     * the gate answers itself and never passes to the sequencer (O.2). */
    seq_note_ground_cmd(&seq, t_ms);
    result = link_gate(&pi_link, t_ms, cmd, key); /* S.8, defence in depth */
    if (result == LINK_PASS)
        result = seq_command(&seq, t_ms, hw_wall_s(), cmd, key, value, &cfg);
    send_ack(view->seq, cmd, result);
}

static void poll_commands(uint64_t t_ms)
{
    frame_view_t view;
    uint32_t ts_s;
    uint16_t ts_ms;
    unsigned handled = 0;

    while (handled++ < MAX_FRAMES_PER_PASS && uart_io_poll(&view)) {
        /* Any valid frame proves the Pi is alive - liveness is about the peer
         * on the UART, not about what it happened to send (M-13). */
        link_rx(&pi_link, t_ms);
        if (view.type == PKT_CMD)
            handle_command(t_ms, &view);
        else if (view.type == PKT_TIMESYNC &&
                 timesync_unpack(&view, &ts_s, &ts_ms))
            hw_timesync(ts_s, ts_ms); /* S.4 */
    }
}

/* The Pi is a peer, never a dependency (S.7): losing it clears MCUF_PI_OK and
 * raises one event, and changes nothing about the sequence. */
static void check_pi_link(uint64_t t_ms)
{
    if (!link_step(&pi_link, &cfg, t_ms))
        return;
    if (pi_link.pi_ok)
        send_event(EV_PI_LINK_OK, "pi link up");
    else
        send_event(EV_PI_LINK_LOST, "pi silent");
}

/* Sequencer events go to both the SD log and the downlink. */
static void event_shim(void *ctx, uint8_t code, const char *msg)
{
    (void)ctx;
    send_event(code, msg);
}

int main(void)
{
    seq_persist_t restored;
    bool have_restore;
    uint64_t next_hk_ms = 0;
    static seq_ops_t ops;

    /* Registers the USB stdio driver, which is what carries the picotool
     * reset interface; without this call the driver is compiled and then
     * discarded by the linker. UART stdio is off (see CMakeLists) so nothing
     * here can write into the HK stream on GP0/GP1. Does not wait for a host
     * to connect. */
    stdio_init_all();

    hw_init();
    uart_io_init();

    ops = hw_seq_ops;
    ops.event = event_shim;

    cfg_defaults(&cfg);
    link_init(&pi_link, hw_monotonic_ms());
    ops.ctx = &cfg; /* ops_membrane reads PARAM_MEMBRANE_HZ from here */
    have_restore = hw_restore_persist(&restored); /* S.3 brownout resume */
    seq_init(&seq, &cfg, &ops, have_restore ? &restored : NULL,
             hw_monotonic_ms(), hw_wall_s());

    hw_watchdog_enable(); /* after init: a hung boot must not loop forever */

    for (;;) {
        uint64_t now = hw_monotonic_ms();

        hw_watchdog_kick();
        poll_commands(now);
        if (now >= next_hk_ms) {
            check_pi_link(now); /* before send_hk: MCUF_PI_OK must be current */
            send_hk(now);
            next_hk_ms = now + HK_PERIOD_MS;
        }
        /* Start/end valve drives here, after the step that requested them:
         * the 5 s pulse outlives the 2 s watchdog, so it is timed across
         * loop passes instead of slept through (S.9). */
        hw_actuators_service(hw_monotonic_ms());
        sleep_ms(10);
    }
}
