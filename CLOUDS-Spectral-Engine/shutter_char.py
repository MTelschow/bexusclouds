"""Daylight / roller-shutter characterization (bench LEARNING experiment).

Uses cover.rolladen as a controllable DAYLIGHT source (red caps still on, so red/NIR
biased) to learn three things, none of which change the software:
  1. signal & spectrum vs shutter opening %  (is daylight a usable controllable source?)
  2. the daylight spectrum SHAPE + a look for solar/atmospheric features (e.g. the
     O2 A-band ~760 nm) -- daylight is the real flight source (sunlight).
  3. RE-ATTEMPT the photon-transfer GAIN measurement that the Hue bulb's flicker blocked:
     daylight is steady, so per-stack shot noise should be clean -> a measured gain to
     cross-check the firmware's 1.36 e-/count.

ALWAYS restores the shutter to as-found and leaves the lamp off (user is away).

    python shutter_char.py
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

import numpy as np

from spectro.driver import open_driver
from spectro.calibration import Calibration

HERE = os.path.dirname(os.path.abspath(__file__))
COVER = os.path.join(HERE, "ha_cover.py")
LAMP = os.path.join(HERE, "ha_lamp.py")
PY = sys.executable
HA = "http://homeassistant.local:8123"
SAT = 65520


def _tok():
    with open(os.path.join(os.path.expanduser("~"), ".clouds_ha_token"), encoding="utf-8") as f:
        return f.read().strip()


def ha_pos():
    req = urllib.request.Request(f"{HA}/api/states/cover.rolladen")
    req.add_header("Authorization", "Bearer " + _tok())
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode()).get("attributes", {}).get("current_position")


def cover(*a):
    subprocess.run([PY, COVER, *map(str, a)], capture_output=True, text=True)


def lamp(*a):
    subprocess.run([PY, LAMP, *map(str, a)], capture_output=True, text=True)


def move_to(pos, timeout=70):
    cover("position", int(pos))
    t0 = time.monotonic()
    cur = ha_pos()
    while time.monotonic() - t0 < timeout:
        time.sleep(2.5)
        cur = ha_pos()
        if cur is not None and abs(cur - pos) <= 3:
            break
    time.sleep(2.5)                                   # mechanical settle
    return cur


def grab_med(drv, ms, navg=8):
    drv.set_times_us(int(ms * 1000))
    return np.median([drv.grab(discard=2 if i == 0 else 0) for i in range(navg)], axis=0)


def auto_expose(drv, ch, target=0.55, lo=0.05, hi=200.0):
    exp = 10.0
    for _ in range(10):
        pk = float(ch.slice(grab_med(drv, exp, 4)).max())
        if pk >= SAT * 0.92:
            exp = max(lo, exp / 2.0)
        elif pk < SAT * target * 0.6:
            exp = min(hi, exp * 1.7)
        else:
            break
        exp = min(max(exp, lo), hi)
    return round(exp, 3)


def main():
    cal = Calibration.load()
    ch = cal.by_role("measurement")
    nm = ch.wavelengths
    drv = open_driver(mock=False)
    print("camera:", drv.connect().summary())
    snap = ha_pos()
    print(f"shutter as-found position = {snap}%")

    positions = [25, 50, 75, 100]
    try:
        lamp("off")
        time.sleep(1.5)
        print("closing shutter for a dark/closed reference ...")
        move_to(0)
        dark = grab_med(drv, 50.0, 8)
        print(f"  closed-room dark peak (meas chan) = {ch.slice(dark).max():.0f}")

        spec = {}
        for p in positions:
            print(f"opening to {p}% ...")
            cur = move_to(p)
            exp = auto_expose(drv, ch)
            f = grab_med(drv, exp, 8)
            s = ch.slice(f)
            spec[p] = (f.astype(np.float32), exp, cur)
            print(f"  {p:3d}% (real {cur}) exp {exp:g} ms  peak {s.max():.0f} @ {nm[int(np.argmax(s))]:.0f} nm")

        # --- photon transfer on STEADY daylight (the Hue flicker blocked this) ---
        ptc_pos = 100
        move_to(ptc_pos)
        t_hi = auto_expose(drv, ch, target=0.72)
        if t_hi <= 0.06 and float(ch.slice(grab_med(drv, t_hi, 4)).max()) >= SAT * 0.95:
            ptc_pos = 40                                  # too bright wide open -> stop down
            move_to(ptc_pos)
            t_hi = auto_expose(drv, ch, target=0.72)
        exps = np.unique(np.linspace(max(0.1, t_hi / 10.0), t_hi, 8).round(3))
        M = 40
        frames = []
        drift = []
        print(f"daylight PTC at {ptc_pos}% open, t_hi {t_hi:g} ms:")
        for e in exps:
            drv.set_times_us(int(e * 1000))
            for _ in range(3):
                drv.grab()
            s = np.array([drv.grab() for _ in range(M)], dtype=np.float32)
            frames.append(s)
            gm = s.mean(axis=1)
            drift.append(float(gm.std() / gm.mean() * 100))
            print(f"  {e:6.2f} ms  peak {ch.slice(s.mean(0)).max():.0f}  intra-stack drift {drift[-1]:.2f}%")

        os.makedirs(os.path.join(HERE, "output"), exist_ok=True)
        np.savez_compressed(
            os.path.join(HERE, "output", "shutter_char.npz"),
            positions=np.array(positions),
            spectra=np.array([spec[p][0] for p in positions]),
            spectra_exp=np.array([spec[p][1] for p in positions]),
            spectra_cur=np.array([spec[p][2] for p in positions]),
            dark=dark.astype(np.float32),
            ptc_pos=ptc_pos, ptc_exps=exps, ptc_frames=np.array(frames, dtype=np.float32),
            ptc_drift=np.array(drift), wavelengths=nm,
            ch_window=np.array(ch.slice(np.arange(2048))), sat=SAT)
        print("saved output/shutter_char.npz")
    finally:
        if snap is not None:
            print(f"restoring shutter to {snap}% ...")
            move_to(int(snap))
        lamp("off")
        drv.close()
        print("shutter restored, lamp off, device closed.")


if __name__ == "__main__":
    main()
