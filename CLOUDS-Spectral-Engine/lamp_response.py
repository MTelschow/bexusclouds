"""Autonomous light-response experiment (ground-test bench).

Captures the EURECA Duo with Floor Lamp 1 OFF, then ON (warm 2200 K, 100 %),
across several exposures, and reports the DARK-SUBTRACTED difference (ON - OFF)
per channel. The subtraction cancels the static baseline + fixed-pattern comb
and isolates the lamp's actual contribution -- telling us whether the lamp
reaches the fibres, which channel it feeds, and how strong it is. Restores the
lamp at the end.

    python lamp_response.py
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
EXPS = [10, 50, 200, 500]   # ms


def lamp(*a):
    subprocess.run([PY, LAMP, *map(str, a)], capture_output=True, text=True)


def lamp_state():
    return subprocess.run([PY, LAMP, "state"], capture_output=True, text=True).stdout.strip()


def grab_avg(drv, ms, navg=6):
    drv.set_times_us(int(ms * 1000))
    return np.mean([drv.grab(discard=2 if i == 0 else 0) for i in range(navg)], axis=0)


def main():
    cal = Calibration.load()
    drv = open_driver(mock=False)
    print("camera:", drv.connect().summary())
    print("original lamp:", lamp_state())
    m = cal.by_role("measurement")
    r = cal.by_role("reference")
    sat = cal.saturation_count

    print("\ncapturing DARK (lamp OFF) ...")
    lamp("off")
    time.sleep(1.6)
    dark = {e: grab_avg(drv, e) for e in EXPS}

    print("capturing LIT (warm 2200 K, 100 %) ...")
    lamp("ct", 2200, 100)
    time.sleep(1.6)
    lit = {e: grab_avg(drv, e) for e in EXPS}

    lamp("ct", 2200, 100)
    time.sleep(0.8)
    print("restored:", lamp_state())
    drv.close()

    print(f"\n{'exp':>5} | {'channel':<13} {'dark_mn':>8} {'lit_mn':>8} {'(ON-OFF)sum':>12} "
          f"{'max':>7} {'@nm':>6} {'litSat':>6}")
    print("-" * 78)
    for e in EXPS:
        for ch in (m, r):
            d = ch.slice(dark[e]).astype(float)
            l = ch.slice(lit[e]).astype(float)
            diff = l - d
            pk = int(np.argmax(diff))
            print(f"{e:5d} | {ch.name + '/' + ch.role:<13} {d.mean():8.0f} {l.mean():8.0f} "
                  f"{diff.sum():12.0f} {diff.max():7.0f} {ch.wavelengths[pk]:6.1f} "
                  f"{np.mean(l >= sat) * 100:5.1f}%")

    os.makedirs(os.path.join(HERE, "output"), exist_ok=True)
    fig = Figure(figsize=(8.2, 4.6), dpi=120)
    fig.patch.set_facecolor("white")
    ax = fig.add_subplot(111)
    for e in EXPS:
        ax.plot(m.wavelengths, m.slice(lit[e]).astype(float) - m.slice(dark[e]).astype(float),
                lw=1.1, label=f"{e} ms")
    ax.set_title("Floor Lamp 1  (ON - OFF), measurement channel", color="#01386a")
    ax.set_xlabel("wavelength (nm)")
    ax.set_ylabel("counts difference (lamp signal)")
    ax.grid(alpha=0.15)
    ax.legend(fontsize=8, title="exposure")
    out = os.path.join(HERE, "output", "lamp_diff.png")
    FigureCanvasAgg(fig).print_png(out)
    print("plot:", out)


if __name__ == "__main__":
    main()
