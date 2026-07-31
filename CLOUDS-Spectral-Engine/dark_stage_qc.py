"""Dark-stage colour-QC (ground-test bench) -- user-authorized one-off.

Snapshots every Living Room light's exact state (and saves it to disk), switches
them ALL off for a dark stage, then floods the GU10 spots through
RED/GREEN/BLUE/WHITE and captures the EURECA Duo at each with paired dark-
subtraction. With ambient gone, this isolates the spots' contribution. A
try/finally ALWAYS restores every light to its snapshot, even on crash.

    python dark_stage_qc.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from spectro.driver import open_driver
from spectro.calibration import Calibration

HERE = os.path.dirname(os.path.abspath(__file__))
HA = os.environ.get("CLOUDS_HA_BASE", "http://homeassistant.local:8123")

# Living Room lights (physical entities; excludes the 'living_room' group).
LR_LIGHTS = [
    "light.bed_1", "light.bed_2",
    "light.floor_lamp_1", "light.floor_lamp_2", "light.floor_lamp_3",
    "light.main_desk_1", "light.main_desk_2",
    "light.spot_1", "light.spot_2", "light.spot_3", "light.spot_4",
]
SPOTS = ["light.spot_1", "light.spot_2", "light.spot_3", "light.spot_4",
         "light.main_desk_1", "light.main_desk_2"]
EXP_MS = 400
NAVG = 6
COLORS = [("RED", [255, 0, 0], "#d62728"), ("GREEN", [0, 255, 0], "#1d9e75"),
          ("BLUE", [0, 0, 255], "#1f77b4"), ("WHITE", None, "#999999")]
BANDS = [("blue", 384, 500), ("green", 500, 600), ("red", 600, 750), ("nir", 750, 851)]


def _tok():
    p = os.path.join(os.path.expanduser("~"), ".clouds_ha_token")
    with open(p, encoding="utf-8") as f:
        return f.read().strip()


def ha(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(HA + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + _tok())
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def svc(domain, service, **data):
    return ha("POST", f"/api/services/{domain}/{service}", data)


def snapshot(entities):
    snap = {}
    for e in entities:
        st, body = ha("GET", f"/api/states/{e}")
        if st == 200:
            j = json.loads(body)
            a = j.get("attributes", {})
            snap[e] = {"on": j["state"] == "on", "brightness": a.get("brightness"),
                       "color_mode": a.get("color_mode"),
                       "color_temp_kelvin": a.get("color_temp_kelvin"),
                       "xy_color": a.get("xy_color"), "rgb_color": a.get("rgb_color")}
    return snap


def restore(snap):
    for e, s in snap.items():
        if not s["on"]:
            svc("light", "turn_off", entity_id=e)
            continue
        p = {"entity_id": e}
        if s["brightness"]:
            p["brightness"] = int(s["brightness"])
        if s["color_mode"] == "color_temp" and s["color_temp_kelvin"]:
            p["color_temp_kelvin"] = int(s["color_temp_kelvin"])
        elif s["xy_color"]:
            p["xy_color"] = s["xy_color"]
        elif s["rgb_color"]:
            p["rgb_color"] = s["rgb_color"]
        svc("light", "turn_on", **p)


def grab_avg(drv, ms, navg=NAVG):
    drv.set_times_us(int(ms * 1000))
    return np.mean([drv.grab(discard=2 if i == 0 else 0) for i in range(navg)], axis=0)


def main():
    cal = Calibration.load()
    drv = open_driver(mock=False)
    print("camera:", drv.connect().summary())
    m = cal.by_role("measurement")
    nm = m.wavelengths

    snap = snapshot(LR_LIGHTS)
    os.makedirs(os.path.join(HERE, "output"), exist_ok=True)
    with open(os.path.join(HERE, "output", "room_snapshot.json"), "w") as f:
        json.dump(snap, f, indent=2)
    on_now = [e for e, s in snap.items() if s["on"]]
    print(f"snapshot saved ({len(snap)} lights; currently on: {on_now or 'none'})")

    diffs = {}
    try:
        print("dark stage: switching all Living Room lights off")
        svc("light", "turn_off", entity_id=LR_LIGHTS)
        time.sleep(2.2)
        for name, rgb, _c in COLORS:
            svc("light", "turn_off", entity_id=SPOTS)
            time.sleep(1.6)
            dark = grab_avg(drv, EXP_MS)
            if rgb is None:
                svc("light", "turn_on", entity_id=SPOTS, brightness_pct=100, color_temp_kelvin=4000)
            else:
                svc("light", "turn_on", entity_id=SPOTS, brightness_pct=100, rgb_color=rgb)
            time.sleep(1.8)
            lit = grab_avg(drv, EXP_MS)
            diffs[name] = m.slice(lit) - m.slice(dark)
            print(f" captured {name}")
    finally:
        print("restoring room from snapshot ...")
        restore(snap)
        drv.close()
        print("room restored.")

    if len(diffs) < len(COLORS):
        print("incomplete; aborting analysis")
        return

    print(f"\nDARK STAGE | exp {EXP_MS} ms x{NAVG} | (lit - off), measurement channel")
    hdr = f"{'colour':6} | " + " ".join(f"{b[0]:>8}" for b in BANDS) + f" | {'peak@nm':>9}"
    print(hdr)
    print("-" * len(hdr))
    for name, _, _c in COLORS:
        d = diffs[name]
        row = f"{name:6} | "
        for _b, lo, hi in BANDS:
            mask = (nm >= lo) & (nm < hi)
            row += f"{d[mask].sum():8.0f} "
        pk = int(np.argmax(d))
        row += f"| {nm[pk]:8.1f}"
        print(row)

    fig = Figure(figsize=(8.4, 4.6), dpi=120)
    fig.patch.set_facecolor("white")
    ax = fig.add_subplot(111)
    for name, _, col in COLORS:
        ax.plot(nm, diffs[name], lw=1.3, color=col, label=name)
    ax.axhline(0, color="#cccccc", lw=0.6)
    ax.set_title("Dark stage: Living Room spots by colour (lit - off), measurement", color="#01386a")
    ax.set_xlabel("wavelength (nm)")
    ax.set_ylabel("counts difference")
    ax.grid(alpha=0.15)
    ax.legend(fontsize=8)
    out = os.path.join(HERE, "output", "dark_stage_qc.png")
    FigureCanvasAgg(fig).print_png(out)
    print("plot:", out)


if __name__ == "__main__":
    main()
