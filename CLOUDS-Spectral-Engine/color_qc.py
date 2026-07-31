"""Colour-QC experiment (ground-test bench).

Floods the Living Room Hue GU10 colour spots through RED / GREEN / BLUE / WHITE
and captures the EURECA Duo (optical covers on, indirect room light) at each.
Each colour is paired with its own fresh OFF capture and dark-subtracted
(lit - off), which cancels slow baseline drift and isolates the spots. Results
are reported band-resolved (blue/green/red/nir) -- a changing-light vector to
QC and develop the software against, NOT a calibration.

Floor lamp 1 is off during the run; a try/finally always restores the room
(spots -> off, floor lamp 1 -> warm 2200 K 100 %).

    python color_qc.py
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
EXP_MS = 400
NAVG = 6

COLORS = [
    ("RED",   ("rgb", 255, 0, 0), "#d62728"),
    ("GREEN", ("rgb", 0, 255, 0), "#1d9e75"),
    ("BLUE",  ("rgb", 0, 0, 255), "#1f77b4"),
    ("WHITE", ("white", 100),     "#999999"),
]
BANDS = [("blue", 384, 500), ("green", 500, 600), ("red", 600, 750), ("nir", 750, 851)]


def lamp(*a, targets=None):
    env = dict(os.environ)
    if targets:
        env["CLOUDS_HA_TARGETS"] = targets
    subprocess.run([PY, LAMP, *map(str, a)], capture_output=True, text=True, env=env)


def restore():
    lamp("off")
    lamp("ct", 2200, 100, targets="light.floor_lamp_1")


def grab_avg(drv, ms, navg=NAVG):
    drv.set_times_us(int(ms * 1000))
    return np.mean([drv.grab(discard=2 if i == 0 else 0) for i in range(navg)], axis=0)


def main():
    cal = Calibration.load()
    drv = open_driver(mock=False)
    print("camera:", drv.connect().summary())
    m = cal.by_role("measurement")
    nm = m.wavelengths

    diffs = {}
    clips = {}
    try:
        lamp("off", targets="light.floor_lamp_1")
        time.sleep(1.2)
        for name, cmd, _ in COLORS:
            lamp("off")
            time.sleep(1.7)
            dark = grab_avg(drv, EXP_MS)
            lamp(*cmd)
            time.sleep(1.7)
            lit = grab_avg(drv, EXP_MS)
            diffs[name] = m.slice(lit) - m.slice(dark)
            clips[name] = float(np.mean(m.slice(lit) >= cal.saturation_count) * 100)
            print(f"captured {name}  (clip {clips[name]:.1f}%)")
    finally:
        restore()
        drv.close()
        print("restored: spots off, floor lamp 1 -> warm 2200 K 100 %")

    if len(diffs) < len(COLORS):
        print("incomplete; aborting analysis")
        return

    print(f"\nexposure {EXP_MS} ms x{NAVG}, paired dark-subtraction | measurement channel")
    header = f"{'colour':6} | " + " ".join(f"{b[0]:>8}" for b in BANDS) + f" | {'peak@nm':>9}"
    print(header)
    print("-" * len(header))
    for name, _, _c in COLORS:
        d = diffs[name]
        row = f"{name:6} | "
        for _bn, lo, hi in BANDS:
            mask = (nm >= lo) & (nm < hi)
            row += f"{d[mask].sum():8.0f} "
        pk = int(np.argmax(d))
        row += f"| {nm[pk]:8.1f}"
        print(row)

    os.makedirs(os.path.join(HERE, "output"), exist_ok=True)
    fig = Figure(figsize=(8.4, 4.6), dpi=120)
    fig.patch.set_facecolor("white")
    ax = fig.add_subplot(111)
    for name, _, col in COLORS:
        ax.plot(nm, diffs[name], lw=1.3, color=col, label=name)
    ax.axhline(0, color="#cccccc", lw=0.6)
    ax.set_title("Living Room spots by colour  (lit - off), measurement channel", color="#01386a")
    ax.set_xlabel("wavelength (nm)")
    ax.set_ylabel("counts difference")
    ax.grid(alpha=0.15)
    ax.legend(fontsize=8)
    out = os.path.join(HERE, "output", "color_qc.png")
    FigureCanvasAgg(fig).print_png(out)
    print("plot:", out)


if __name__ == "__main__":
    main()
