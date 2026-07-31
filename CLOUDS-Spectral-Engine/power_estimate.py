"""Optical-power sensitivity measurement for the EURECA Duo (ground-test bench).

Goal: turn raw ADC counts into an absolute optical-power figure so we can answer
"how many watts of light input does the spectrometer need?".

Method (all on the real hardware, driven by a controllable Hue source):
  1. discover which Hue light actually couples into the fibre.
  2. mask the comb / hot reference pixels (they are not light-responsive).
  3. PHOTON-TRANSFER CURVE: at a fixed bright setting, sweep integration time;
     for each level capture a stack of frames and compute the per-pixel temporal
     mean and variance. For shot-noise-limited signal  var[counts] = mean/g,  so
     the slope of (variance vs mean) gives the conversion gain g  [e-/count]
     PURELY FROM MEASUREMENT -- no datasheet guess for the gain.
  4. DARK / NOISE FLOOR vs exposure (source off) -> the detection limit.
  5. SOURCE RESPONSE vs brightness (the controllable "turn it up/down" vector).

Saves per-level per-pixel mean/variance to output/power_estimate.npz; the
radiometry (counts -> electrons -> photons -> watts) is done in analyze_power.py
so the math can be re-run without re-measuring.

ALWAYS leaves the room OFF (try/finally): nobody home, night.

    python power_estimate.py run            # auto-pick source, full campaign
    python power_estimate.py run light.floor_lamp_1
    python power_estimate.py source         # just identify the coupled bulb
"""
import json
import os
import subprocess
import sys
import time

import numpy as np

from spectro.driver import open_driver
from spectro.calibration import Calibration

HERE = os.path.dirname(os.path.abspath(__file__))
LAMP = os.path.join(HERE, "ha_lamp.py")
OUT = os.path.join(HERE, "output")
PY = sys.executable

# Hue lights that might be the one aimed at the fibre (color-temp capable).
CANDIDATES = ["light.floor_lamp_1", "light.floor_lamp_3", "light.main_desk_1",
              "light.spot_1", "light.spot_3"]
WARM = ("ct", "2200", "100")          # warm white, full -> strong red through the caps
SAT = 65520                           # 12-bit << 4 saturation
MASK_THR = 8000                       # dark counts above this => comb / hot pixel
SETTLE = 1.8                          # seconds for a Hue change to take effect


def lamp(*a, targets=None):
    env = dict(os.environ)
    if targets:
        env["CLOUDS_HA_TARGETS"] = targets
    subprocess.run([PY, LAMP, *map(str, a)], capture_output=True, text=True, env=env)


def stack(drv, exp_us, m, settle=3):
    """Return an (m, 2048) float array of consecutive frames at exp_us."""
    drv.set_times_us(int(exp_us))
    for _ in range(settle):
        drv.grab(discard=0)
    return np.array([drv.grab(discard=0) for _ in range(m)], dtype=np.float64)


def comb_mask(dark_mean):
    """True = usable (light-responsive) pixel; False = comb/hot/reference."""
    return dark_mean < MASK_THR


def chan_peak(frame, ch, good):
    s = ch.slice(frame)
    g = ch.slice(good)
    return float(s[g].max()) if g.any() else float(s.max())


def auto_expose(drv, ch, good, target=0.80, lo_us=1000, hi_us=300000):
    exp = 8000.0
    for _ in range(9):
        f = stack(drv, exp, 4).mean(axis=0)
        pk = chan_peak(f, ch, good)
        if pk >= SAT * 0.92:
            exp = max(lo_us, exp / 1.8)
        elif pk < SAT * target * 0.7:
            exp = min(hi_us, exp * 1.7)
        else:
            break
        exp = min(max(exp, lo_us), hi_us)
    return float(min(max(exp, lo_us), hi_us))


def discover(drv, ch):
    """Find the Hue entity that most increases the in-channel signal."""
    lamp("off")
    time.sleep(SETTLE)
    dark = stack(drv, 50000, 6).mean(axis=0)
    good = comb_mask(dark)
    base = chan_peak(dark, ch, good)
    results = []
    for ent in CANDIDATES:
        lamp(*WARM, targets=ent)
        time.sleep(SETTLE)
        f = stack(drv, 50000, 6).mean(axis=0)
        sig = chan_peak(f, ch, good) - base
        results.append((ent, sig))
        print(f"  {ent:20} delta-peak = {sig:9.0f} counts @50ms")
        lamp("off", targets=ent)
        time.sleep(1.0)
    results.sort(key=lambda r: r[1], reverse=True)
    return results[0][0], results


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "run"
    cal = Calibration.load()
    ch = cal.by_role("measurement")
    drv = open_driver(mock=False)
    print("camera:", drv.connect().summary())

    try:
        if cmd == "source":
            best, res = discover(drv, ch)
            print(f"\nbest-coupled source: {best}")
            return

        source = args[1] if len(args) > 1 else None
        if source is None:
            print("discovering coupled source ...")
            source, _ = discover(drv, ch)
        print(f"source = {source}")

        # --- baseline dark + pixel mask ---
        lamp("off")
        time.sleep(SETTLE)
        dark2 = stack(drv, 2000, 20)
        good = comb_mask(dark2.mean(axis=0))
        print(f"usable (non-comb) pixels: {int(good.sum())}/2048")

        # --- find an exposure that nearly fills the well under the source ---
        lamp(*WARM, targets=source)
        time.sleep(SETTLE)
        t_hi = auto_expose(drv, ch, good)
        print(f"top exposure t_hi = {t_hi/1000:.2f} ms")
        exps = np.unique(np.linspace(max(1000.0, t_hi / 12.0), t_hi, 8).astype(int))

        # --- PHOTON TRANSFER: keep the FULL frame stacks so flicker (common-mode
        #     source ripple) can be divided out offline before taking the variance ---
        M = 50
        light_frames = []
        for i, e in enumerate(exps):
            s = stack(drv, e, M)
            light_frames.append(s.astype(np.float32))
            print(f"  light  {e/1000:7.2f} ms  peak={chan_peak(s.mean(0), ch, good):8.0f}")

        # --- matching DARK stacks (source off), same exposures ---
        lamp("off")
        time.sleep(SETTLE)
        dark_frames = []
        for i, e in enumerate(exps):
            s = stack(drv, e, M)
            dark_frames.append(s.astype(np.float32))
            gm = s.mean(0)[good].mean()
            print(f"  dark   {e/1000:7.2f} ms  floor-mean={gm:7.1f} "
                  f"px-std~{np.median(s.std(0, ddof=1)[good]):6.2f}")

        # --- brightness response at a mid exposure (the control vector) ---
        t_mid = int(exps[len(exps) // 2])
        bri_levels = [0, 10, 25, 50, 75, 100]
        bmean = np.zeros((len(bri_levels), 2048))
        for i, b in enumerate(bri_levels):
            if b == 0:
                lamp("off")
            else:
                lamp("ct", "2200", str(b), targets=source)
            time.sleep(SETTLE)
            bmean[i] = stack(drv, t_mid, 12).mean(axis=0)
            print(f"  bri {b:3d}%  peak={chan_peak(bmean[i], ch, good):8.0f} @ {t_mid/1000:.1f} ms")

    finally:
        lamp("off")
        drv.close()
        print("room OFF, device closed.")

    os.makedirs(OUT, exist_ok=True)
    npz = os.path.join(OUT, "power_estimate.npz")
    np.savez_compressed(
        npz,
        exposures_us=exps,
        light_frames=np.array(light_frames, dtype=np.float32),   # (L, M, 2048)
        dark_frames=np.array(dark_frames, dtype=np.float32),
        good=good,
        bri_levels=np.array(bri_levels), bri_mean=bmean, t_mid_us=t_mid,
        wavelengths=ch.wavelengths, ch_window=np.array(ch.slice(np.arange(2048))),
        source=source, sat=SAT, M=M)
    print("saved:", npz)


if __name__ == "__main__":
    main()
