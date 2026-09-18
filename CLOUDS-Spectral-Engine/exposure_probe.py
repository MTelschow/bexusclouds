"""Is the integration time what we asked for? Ask the FPGA, not the spectrum.

The vendor library is opened in **async** mode (`e9u_LSMD_start_camera_async`):
no internal frame timer, no external trigger - every frame is triggered over USB
from inside `get_next_frame`. Between two triggers the line is not clocked, so
charge keeps collecting on the photodiodes for the whole idle time. That makes
the *first* frame after a pause carry the pause, not `exposure_us`, and a 1 Hz
live loop with a 10 ms exposure then looks saturated at every setting.

The camera timestamps its own integration window: `CH0_T_STAMP_EXP_START` /
`_STOP`, in the same microseconds as the `CH0_EXP_TIME` register - the vendor's
own `wait_times_us()` spins on exactly that comparison, which is also the
admission that a timing change does not take effect on the next frame.

So for each exposure this measures three things per frame:
  * `hw_us`   - the FPGA's own exposure timestamp difference
  * `b2b`     - peak counts, frames grabbed back to back
  * `idle`    - peak counts for one frame grabbed after a 1.0 s pause
  * `idle+f`  - the same pause, but with the driver's flush frame in front of it

Expect, if the idle-accumulation theory holds: `b2b` scales with the exposure,
`idle` does not (it pins near saturation at every setting), `idle+f` matches
`b2b` again, and `hw_us` on the first frame after a change still reports the
*old* exposure.

The driver's own idle flush is switched **off** inside this probe: it is the
fix, and measuring it away would hide what is being measured. The `idle+f`
column re-applies it by hand, so one run shows both the fault and the fix.

Run it where the vendor library lives - the Pi or the bench PC, not over
``--net``; register access is USB-local. The detector is exclusive, so stop the
FSW / net_server first.

    python exposure_probe.py                 # default sweep
    python exposure_probe.py --exp-ms 5 50 500
"""
from __future__ import annotations

import argparse
import ctypes
import time

import numpy as np

from spectro.calibration import Calibration
from spectro.eureca_driver import EurecaDriver

# e9u_LSMD_defs.h
REG_CH0_CONTROL = 0x00
REG_CH0_EXP_TIME = 0x01
REG_CH0_FRAME_TIME = 0x02
REG_T_STAMP_EXP_STOP = 0x05
REG_T_STAMP_EXP_START = 0x06
BANK_RX, BANK_TX, BANK_SH = 0, 1, 2

DEFAULT_EXP_MS = [1, 2, 5, 10, 20, 50, 100, 200, 500]


def _bind(lib):
    """The register + limit calls the driver does not need, but a probe does."""
    for name, args, rt in (
        ("e9u_LSMD_get_reg32", (ctypes.c_uint, ctypes.c_uint, ctypes.c_uint), ctypes.c_uint),
        ("e9u_LSMD_diff32", (ctypes.c_uint, ctypes.c_uint), ctypes.c_uint),
        ("e9u_LSMD_minimum_frame", (ctypes.c_uint,), ctypes.c_uint),
        ("e9u_LSMD_step_frame", (ctypes.c_uint,), ctypes.c_uint),
        ("e9u_LSMD_minimum_exposure", (ctypes.c_uint,), ctypes.c_uint),
        ("e9u_LSMD_step_exposure", (ctypes.c_uint,), ctypes.c_uint),
    ):
        fn = getattr(lib, name, None)
        if fn is None:
            raise SystemExit(f"vendor library does not export {name}")
        fn.argtypes, fn.restype = args, rt
    return lib


def hw_exposure_us(lib, cam: int) -> int:
    """The FPGA's measured integration window for the frame just read."""
    stop = lib.e9u_LSMD_get_reg32(cam, REG_T_STAMP_EXP_STOP, BANK_SH)
    start = lib.e9u_LSMD_get_reg32(cam, REG_T_STAMP_EXP_START, BANK_SH)
    return int(lib.e9u_LSMD_diff32(stop, start))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp-ms", type=float, nargs="+", default=DEFAULT_EXP_MS)
    ap.add_argument("--frames", type=int, default=6, help="back-to-back frames per exposure")
    ap.add_argument("--idle-s", type=float, default=1.0, help="pause before the idle frame")
    ap.add_argument("--out", default="output/exposure_probe.npz")
    args = ap.parse_args()

    cal = Calibration.load()
    sat = cal.saturation_count

    drv = EurecaDriver()
    info = drv.connect()
    drv._flush_mode = "0"          # measure the camera, not the workaround
    lib, cam = _bind(drv._lib), drv.cam
    print(f"{info.model}  SN {info.serial}  {info.pixels} px  on {info.com_port}")
    print(f"count_shift={drv._count_shift}  saturation={sat}")
    print(f"limits us: exposure min={lib.e9u_LSMD_minimum_exposure(cam)} "
          f"step={lib.e9u_LSMD_step_exposure(cam)}  "
          f"frame min={lib.e9u_LSMD_minimum_frame(cam)} "
          f"step={lib.e9u_LSMD_step_frame(cam)}")
    print("\n(peaks are the max over both calibrated channel windows)\n")
    print(f"{'req_ms':>7} {'reg_exp':>8} {'reg_frm':>8}  {'hw_us per frame':<30} "
          f"{'b2b peak per frame':<30} {'idle':>7} {'idle+f':>7}")

    rows = []
    try:
        for exp_ms in args.exp_ms:
            us = int(round(exp_ms * 1000))
            drv.set_times_us(us)
            reg_exp = int(lib.e9u_LSMD_get_reg32(cam, REG_CH0_EXP_TIME, BANK_TX))
            reg_frm = int(lib.e9u_LSMD_get_reg32(cam, REG_CH0_FRAME_TIME, BANK_TX))

            hw, peaks, frames = [], [], []
            for _ in range(args.frames):                  # back to back, no pause
                f = drv.grab()
                frames.append(f)
                hw.append(hw_exposure_us(lib, cam))
                peaks.append(max(int(ch.slice(f).max()) for ch in cal.channels))

            time.sleep(args.idle_s)                       # the live-loop cadence
            f_idle = drv.grab()
            idle_peak = max(int(ch.slice(f_idle).max()) for ch in cal.channels)
            idle_hw = hw_exposure_us(lib, cam)

            time.sleep(args.idle_s)                       # same pause, flush in front
            f_flushed = drv.grab(discard=1)
            flushed_peak = max(int(ch.slice(f_flushed).max()) for ch in cal.channels)

            print(f"{exp_ms:7.1f} {reg_exp:8d} {reg_frm:8d}  "
                  f"{str(hw):<30.30} {str(peaks):<30.30} {idle_peak:7d} "
                  f"{flushed_peak:7d}")
            rows.append(dict(req_us=us, reg_exp=reg_exp, reg_frm=reg_frm,
                             hw_us=hw, peaks=peaks, idle_peak=idle_peak,
                             idle_hw_us=idle_hw, flushed_peak=flushed_peak,
                             frames=np.array(frames, dtype=np.uint16),
                             idle_frame=f_idle, flushed_frame=f_flushed))
    finally:
        drv.close()

    # linearity of the settled back-to-back frames: peak / exposure should be flat
    print("\nsettled (last back-to-back frame) vs exposure:")
    print(f"{'req_ms':>7} {'hw_ms':>8} {'peak':>7} {'peak/ms':>9}  clip?")
    for r in rows:
        pk, hw_ms = r["peaks"][-1], r["hw_us"][-1] / 1000.0
        print(f"{r['req_us']/1000:7.1f} {hw_ms:8.3f} {pk:7d} "
              f"{pk / max(r['req_us']/1000, 1e-6):9.1f}  {'CLIP' if pk >= sat else ''}")
    print(f"\nidle-frame peak vs exposure, after a {args.idle_s:.1f} s pause "
          f"(flat and high = the pause is being integrated, not the exposure; "
          f"'flushed' is the same pause with one frame thrown away first):")
    print(f"{'req_ms':>7} {'idle':>7} {'flushed':>8} {'settled b2b':>12}")
    for r in rows:
        print(f"{r['req_us']/1000:7.1f} {r['idle_peak']:7d} {r['flushed_peak']:8d} "
              f"{r['peaks'][-1]:12d}")

    np.savez_compressed(
        args.out,
        req_us=np.array([r["req_us"] for r in rows]),
        reg_exp=np.array([r["reg_exp"] for r in rows]),
        reg_frm=np.array([r["reg_frm"] for r in rows]),
        hw_us=np.array([r["hw_us"] for r in rows]),
        peaks=np.array([r["peaks"] for r in rows]),
        idle_peak=np.array([r["idle_peak"] for r in rows]),
        idle_hw_us=np.array([r["idle_hw_us"] for r in rows]),
        flushed_peak=np.array([r["flushed_peak"] for r in rows]),
        frames=np.array([r["frames"] for r in rows]),
        idle_frames=np.array([r["idle_frame"] for r in rows]),
        flushed_frames=np.array([r["flushed_frame"] for r in rows]),
        idle_s=args.idle_s,
    )
    print(f"\nsaved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
