"""Whole-room QC (ground-test bench).

Floods the entire Living Room (all its Hue lights, via the scoped ha_lamp.py
whose default target is the whole room) across brightness + colour-temperature
and captures the EURECA Duo at each, dark-subtracting vs OFF. The whole room is
far brighter than the individual spots, so even through the red covers this is
the strongest, cleanest changing-light QC vector available right now.

ALWAYS leaves the room OFF (try/finally), as required (nobody home, night).

    python room_qc.py
"""
import os
import subprocess
import sys
import time

import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from spectro.driver import open_driver
from spectro.calibration import Calibration

HERE = os.path.dirname(os.path.abspath(__file__))
LAMP = os.path.join(HERE, "ha_lamp.py")
PY = sys.executable
NAVG = 6
BANDS = [("blue", 384, 500), ("green", 500, 600), ("red", 600, 750), ("nir", 750, 851)]

EXP_MS = 40
STATES = [
    ("OFF",       ("off",)),
    ("WARM 30%",  ("ct", 2200, 30)),
    ("WARM 60%",  ("ct", 2200, 60)),
    ("WARM 100%", ("ct", 2200, 100)),
    ("COOL 100%", ("ct", 6500, 100)),
]


def lamp(*a):
    subprocess.run([PY, LAMP, *map(str, a)], capture_output=True, text=True)


def grab_avg(drv, ms, navg=NAVG):
    drv.set_times_us(int(ms * 1000))
    return np.mean([drv.grab(discard=2 if i == 0 else 0) for i in range(navg)], axis=0)


def auto_expose(drv, cal, target=45000.0, lo=0.5, hi=60.0):
    exp = 5.0
    for _ in range(8):
        f = grab_avg(drv, exp, navg=3)
        pk = max(float(ch.slice(f).max()) for ch in cal.channels)
        if pk >= cal.saturation_count * 0.92:
            exp = max(lo, exp / 2.0)
        elif pk < target * 0.4:
            exp = min(hi, exp * 1.7)
        else:
            break
    return round(exp, 3)


def main():
    cal = Calibration.load()
    drv = open_driver(mock=False)
    print("camera:", drv.connect().summary())
    m = cal.by_role("measurement")
    nm = m.wavelengths
    sat = cal.saturation_count

    frames = {}
    exp = EXP_MS
    try:
        print(f"fixed exposure {exp} ms (whole-room warm brightness sweep)")
        for name, cmd in STATES:
            lamp(*cmd)
            time.sleep(2.0)
            frames[name] = grab_avg(drv, exp)
            clip = max(np.mean(ch.slice(frames[name]) >= sat) for ch in cal.channels) * 100
            print(f" captured {name:11} (clip {clip:.1f}%)")
    finally:
        lamp("off")                       # leave the room OFF
        drv.close()
        print("room switched OFF.")

    if len(frames) < len(STATES):
        print("incomplete; aborting analysis")
        return

    off = frames["OFF"]
    print(f"\nWHOLE ROOM | exp {exp} ms x{NAVG} | (state - OFF), measurement channel")
    hdr = f"{'state':11} | " + " ".join(f"{b[0]:>9}" for b in BANDS) + f" | {'peak@nm':>9}"
    print(hdr)
    print("-" * len(hdr))
    for name, _ in STATES:
        if name == "OFF":
            continue
        d = m.slice(frames[name]) - m.slice(off)
        row = f"{name:11} | "
        for _b, lo, hi in BANDS:
            mask = (nm >= lo) & (nm < hi)
            row += f"{d[mask].sum():9.0f} "
        pk = int(np.argmax(d))
        row += f"| {nm[pk]:8.1f}"
        print(row)

    os.makedirs(os.path.join(HERE, "output"), exist_ok=True)
    fig = Figure(figsize=(8.4, 4.6), dpi=120)
    fig.patch.set_facecolor("white")
    ax = fig.add_subplot(111)
    cols = {"WHITE 30%": "#bbbbbb", "WHITE 100%": "#666666",
            "WARM 2200K": "#d8861e", "COOL 6500K": "#4d8fd1"}
    for name, _ in STATES:
        if name == "OFF":
            continue
        ax.plot(nm, m.slice(frames[name]) - m.slice(off), lw=1.3,
                color=cols.get(name, "#333"), label=name)
    ax.set_title("Whole Living Room (state - OFF), measurement channel", color="#01386a")
    ax.set_xlabel("wavelength (nm)")
    ax.set_ylabel("counts difference")
    ax.grid(alpha=0.15)
    ax.legend(fontsize=8)
    out = os.path.join(HERE, "output", "room_qc.png")
    FigureCanvasAgg(fig).print_png(out)
    print("plot:", out)


if __name__ == "__main__":
    main()
