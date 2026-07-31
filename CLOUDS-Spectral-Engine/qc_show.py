"""Live QC capture: one clean lit spectrum through the full UI (real EURECA Duo).

Turns floor lamp 1 on, runs the Engine offscreen against the real camera with
averaging + the median glitch-cleaner, saves output/qc_live_spectrum.png, then
turns the lamp off. Demonstrates a clean live spectrum on the 5 m cable.

    python qc_show.py
"""
import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets

import clouds_spectral

HERE = os.path.dirname(os.path.abspath(__file__))
LAMP = os.path.join(HERE, "ha_lamp.py")
PY = sys.executable


def lamp(*a, targets=None):
    env = dict(os.environ)
    if targets:
        env["CLOUDS_HA_TARGETS"] = targets
    subprocess.run([PY, LAMP, *map(str, a)], capture_output=True, text=True, env=env)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = clouds_spectral.Engine(mock=False)
win.show()
for _ in range(4):
    app.processEvents()
win._connect()
app.processEvents()
if not win.connected:
    print("camera not connected:", win.hint.text())
    sys.exit(1)
print("connected:", win.info.summary())

try:
    lamp("ct", "2200", "100", targets="light.floor_lamp_1")
    time.sleep(2.0)
    win.sp_avg.setValue(8)                         # median cleaner over 8 frames
    win.sp_exp.setValue(60)
    win._single_shot()
    app.processEvents()
    peak = float(win.last_proc["m"].max())
    if win._last_sat > 0.05:
        win.sp_exp.setValue(20)
    elif peak < 3000:
        win.sp_exp.setValue(150)
    win._single_shot()
    app.processEvents()
    print(f"exp {win.exposure_ms:g} ms x{win.navg} | raw glitch {win._last_glitch*100:.1f}% "
          f"| meas peak {win.last_proc['m'].max():.0f} @ {win._peak_nm:.0f} nm "
          f"| sat {win._last_sat*100:.1f}%")
    os.makedirs("output", exist_ok=True)
    win.grab().save("output/qc_live_spectrum.png")
    print("saved output/qc_live_spectrum.png")
finally:
    lamp("off")
    try:
        win.driver.close()
    except Exception:
        pass
print("lamp off, done")
