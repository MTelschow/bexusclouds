/* Dispersion motor encoder: speed and stall from a quadrature count.
 *
 * Portable and unit-tested natively - the count comes from hw/ (a PIO state
 * machine on the carrier, hw/quadrature_encoder.pio), and everything done
 * with it lives here. The encoder is a Faulhaber IE3-1024L on the motor
 * shaft, no gearhead, so motor rpm is output rpm (hw/board.h PIN_ENC_A).
 *
 * Two outputs, both consumed once per HK packet:
 *
 *   - motor_enc_take_rpm(): the MEAN speed since the previous packet, from
 *     the count delta over the elapsed time. Not a snapshot - a 5 s pulse is
 *     a handful of 1 Hz packets, and the mean says what the shaft did over
 *     the whole second, which is what a speed-vs-duty plot wants.
 *
 *   - motor_enc_take_stalled(): whether a drive was on and the shaft was
 *     not turning, judged over short windows every loop pass and latched
 *     until the packet takes it (the same latch-and-consume rule as
 *     HKV_MEMBRANE_CYCLING). A FLAG ONLY: nothing on the MCU acts on it.
 */
#ifndef CLOUDS_MOTOR_ENC_H
#define CLOUDS_MOTOR_ENC_H

#include <stdbool.h>
#include <stdint.h>

/* IE3-1024L: 1024 lines per revolution, decoded x4 (every edge of A and B)
 * by the PIO counter. Datasheet DE_IE3-1024L_DFF, "Impulse pro Umdrehung". */
#define MOTOR_ENC_LINES 1024
/* x1: hw/quadrature_encoder.pio counts one edge of one channel per line, the
 * only decode the receiver-less wiring supports (board.h PIN_ENC_A). */
#define MOTOR_ENC_COUNTS_PER_REV MOTOR_ENC_LINES

/* Stall judgement. A drive gets STALL_GRACE_MS to spin up before the shaft
 * is held to anything; after that, any STALL_WINDOW_MS window with the drive
 * on and |speed| under STALL_RPM_MIN latches a stall. PRELIMINARY: chosen
 * without the motor's own curve - the floor is well under any speed the
 * 20 % duty minimum should produce, and the grace far longer than a small
 * DC motor's mechanical time constant. Tune against a bench run. */
#define MOTOR_ENC_STALL_GRACE_MS 500u
#define MOTOR_ENC_STALL_WINDOW_MS 100u
#define MOTOR_ENC_STALL_RPM_MIN 100

typedef struct {
    bool primed;              /* first sample seen */
    int32_t win_count;        /* count at the start of the stall window */
    uint64_t win_ms;
    int32_t hk_count;         /* count at the previous HK take */
    uint64_t hk_ms;
    bool driving;             /* drive state at the previous service */
    uint64_t drive_since_ms;  /* when the current drive started */
    bool stalled;             /* latched, consumed by take_stalled */
} motor_enc_t;

void motor_enc_init(motor_enc_t *m);

/* rpm for a count delta over dt_ms, rounded toward zero and saturated to
 * +-INT16_MAX (the wire field is an i16; the encoder's own 430 kHz limit is
 * ~25 000 rpm, so saturation means a counter fault, not a fast motor).
 * 0 for dt_ms == 0. Signed: the sign is the direction. */
int16_t motor_enc_rpm(int32_t dcount, uint32_t dt_ms);

/* Every loop pass: the raw count (wraps freely - only differences are used)
 * and whether the motor drive is on right now. */
void motor_enc_service(motor_enc_t *m, int32_t count, bool driving,
                       uint64_t now_ms);

/* Once per HK packet. Mean rpm since the previous take (0 on the first). */
int16_t motor_enc_take_rpm(motor_enc_t *m, int32_t count, uint64_t now_ms);

/* Once per HK packet. True if a stall was seen since the previous take. */
bool motor_enc_take_stalled(motor_enc_t *m);

#endif
