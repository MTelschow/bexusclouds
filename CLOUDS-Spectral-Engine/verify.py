"""Headless self-checks for CLOUDS Spectral Engine - no hardware required.

Batch 1: calibration math against the factory INSION numbers + channel slicing.
(Driver/mock checks are added alongside the driver layer.)

Run:  python verify.py        (must end "VERIFY OK")
"""
import os
import sys

import numpy as np

from spectro.calibration import Calibration, subtract_dark
from spectro.driver import open_driver

FAILS = []


def check(name, cond, detail=""):
    ok = bool(cond)
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def approx(a, b, tol):
    return abs(float(a) - float(b)) <= tol


cal = Calibration.load()
print(f"source   : {cal.source[:68]}...")
print(f"detector : {cal.instrument.get('detector')} | pixels {cal.n_pixels} | sat {cal.saturation_count}\n")

ch1 = cal.channel("Ch1")
ch2 = cal.channel("Ch2")

check("two channels", len(cal.channels) == 2)
check("Ch1 role = measurement", ch1.role == "measurement", ch1.role)
check("Ch2 role = reference", ch2.role == "reference", ch2.role)
check("detector is 2048 px", cal.n_pixels == 2048)

# pixel->nm against the factory endpoints
check("Ch1 px0   ~ 383.6 nm", approx(ch1.pixel_to_nm(0), 383.6101, 0.01), f"{float(ch1.pixel_to_nm(0)):.3f}")
check("Ch1 px234 ~ 850 nm", approx(ch1.pixel_to_nm(234), 850.0, 1.0), f"{float(ch1.pixel_to_nm(234)):.3f}")
check("Ch2 px1516 ~ 350 nm", approx(ch2.pixel_to_nm(1516), 350.0, 2.0), f"{float(ch2.pixel_to_nm(1516)):.3f}")
check("Ch2 px1766 ~ 850 nm", approx(ch2.pixel_to_nm(1766), 850.0, 2.0), f"{float(ch2.pixel_to_nm(1766)):.3f}")

# wavelength arrays: monotonic, right length
check("Ch1 wavelengths increasing", bool(np.all(np.diff(ch1.wavelengths) > 0)))
check("Ch2 wavelengths increasing", bool(np.all(np.diff(ch2.wavelengths) > 0)))
check("Ch1 len matches window", len(ch1.wavelengths) == ch1.pixel_window[1] - ch1.pixel_window[0] + 1)

# channel slicing out of a full 2048-px frame
frame = np.zeros(cal.n_pixels, dtype=np.uint16)
frame[ch1.pixel_window[0]:ch1.pixel_window[1] + 1] = 1000
frame[ch2.pixel_window[0]:ch2.pixel_window[1] + 1] = 2000
check("Ch1 slice picks its window", bool(np.all(ch1.slice(frame) == 1000)))
check("Ch2 slice picks its window", bool(np.all(ch2.slice(frame) == 2000)))
check("windows disjoint", ch1.pixel_window[1] < ch2.pixel_window[0])

# dark subtraction clips at zero
f = np.array([100, 50, 10], dtype=np.float64)
d = np.array([20, 60, 5], dtype=np.float64)
check("dark subtract clips >= 0", np.array_equal(subtract_dark(f, d), [80, 0, 5]))
check("dark None passthrough", np.array_equal(subtract_dark(f, None), f))

# interactive recalibration: refit a channel from marked (pixel, nm) points + save/load
cal2 = Calibration.load()
m0 = cal2.channel("Ch1")
ppx = np.array([20.0, 110.0, 200.0]); pnm = m0.pixel_to_nm(ppx)
co = np.polyfit(ppx, pnm, 2)
cal2.set_poly("measurement", co[0], co[1], co[2])
check("set_poly reproduces factory on exact points",
      abs(float(cal2.by_role("measurement").pixel_to_nm(110)) - float(m0.pixel_to_nm(110))) < 0.1)
os.makedirs("output", exist_ok=True)
cal2.save("output/_cal_rt.json")
cal3 = Calibration.load("output/_cal_rt.json")
check("calibration save/load round-trips",
      cal3.by_role("measurement").pixel_window == (0, 235)
      and abs(float(cal3.by_role("measurement").pixel_to_nm(110)) - float(m0.pixel_to_nm(110))) < 0.1)

# ---- driver layer (mock; hardware-free) ----
drv = open_driver(mock=True)
info = drv.connect()
check("mock connects", info.mock and info.pixels == 2048, info.summary())
drv.set_times_us(1000)                                   # 1 ms -> unsaturated
short = drv.grab()
check("frame is 2048 x uint16", short.shape == (2048,) and short.dtype == np.uint16)
check("short frame below saturation", short.max() < cal.saturation_count, f"max={int(short.max())}")
drv.set_times_us(1_000_000)                              # 1 s -> channels saturate
long_fr = drv.grab()
check("long frame saturates", long_fr.max() >= cal.saturation_count, f"max={int(long_fr.max())}")
check("Ch1 window carries signal", int(ch1.slice(long_fr).max()) >= cal.saturation_count)
check("Ch2 window carries signal", int(ch2.slice(long_fr).max()) >= cal.saturation_count)
frames = np.stack([drv.grab() for _ in range(16)]).astype(np.float64)
avg = frames.mean(axis=0)
gap = np.arange(300, 1500)
noncomb = gap[gap % 37 != 0]                             # dark pixels between the two windows
err_one = float(np.abs(frames[0][noncomb] - 1500).mean())
err_avg = float(np.abs(avg[noncomb] - 1500).mean())
check("averaging reduces noise", err_avg < err_one, f"{err_avg:.2f} < {err_one:.2f}")
_fc0 = drv.frame_counter()
drv.grab(); drv.grab()
check("driver frame_counter advances", (drv.frame_counter() - _fc0) >= 2, f"{drv.frame_counter() - _fc0}")
check("driver dark_value present", drv.dark_value() is not None, str(drv.dark_value()))
drv.close()

# ---- processing (dual-beam ratio views) ----
from spectro import processing as P
check("transmission halves", np.allclose(P.transmission(np.array([50., 100.]), np.array([100., 100.])), [0.5, 1.0]))
check("absorbance of 0.1 = 1.0", abs(float(P.absorbance(np.array([10.]), np.array([100.]))[0]) - 1.0) < 1e-9)
g = P.common_grid(np.array([384., 850.]), np.array([350., 850.]), 64)
check("common grid is the overlap", g[0] >= 383.9 and g[-1] <= 850.1, f"{g[0]:.1f}..{g[-1]:.1f}")
check("resample is linear interp", abs(float(P.resample([0., 10.], [0., 100.], [5.])[0]) - 50.0) < 1e-9)

# robust frame combine rejects the USB transfer-glitch code (~33514)
gframes = np.full((8, 6), 1500.0); gframes[2, 3] = 33514; gframes[5, 3] = 33520
check("median combine rejects ~33514 glitch", abs(P.average_frames(gframes, method="median")[3] - 1500.0) < 1.0)
check("glitch_fraction counts the code", abs(P.glitch_fraction(gframes) - 2.0 / 48.0) < 1e-9)
gsingle = np.full(6, 1500.0); gsingle[3] = 33514
check("single-frame despike interpolates", abs(P.average_frames(gsingle)[3] - 1500.0) < 1.0)
allbad = np.full((4, 5), 1500.0); allbad[:, 2] = 33514
check("all-glitched pixel interpolated", abs(P.average_frames(allbad)[2] - 1500.0) < 1.0)
spk = np.full(7, 1500.0); spk[3] = 35000.0        # ABOVE the old value band -> caught by the spike test
check("value-agnostic spike removed", abs(P.average_frames(spk)[3] - 1500.0) < 1.0, f"{P.average_frames(spk)[3]:.0f}")
spk2 = np.full(9, 1500.0); spk2[4] = 34000.0; spk2[5] = 34000.0   # 2-pixel-wide persistent glitch
_c2 = P.average_frames(spk2)
check("2-pixel-wide spike removed", abs(_c2[4] - 1500.0) < 1.0 and abs(_c2[5] - 1500.0) < 1.0, f"{_c2[4]:.0f},{_c2[5]:.0f}")

# robust_peak: the exposure-control peak. A real spectral line is >=3.7 px FWHM and
# survives; a glitch CLUSTER that slips past despike is diluted by the boxcar so it
# cannot masquerade as signal (full protection pairs this with a 7-frame odd median).
_xs = np.arange(60)
_line = 1500.0 + 3000.0 * np.exp(-0.5 * ((_xs - 20) / 2.5) ** 2)    # real ~6 px line, peak ~4500
_with_glitch = _line.copy(); _with_glitch[40:43] = 26000.0          # 3-px residual glitch cluster
_rp = P.robust_peak(_with_glitch); _plain = float(P._despike(_with_glitch).max())
check("robust_peak dilutes a surviving glitch cluster vs plain max", _rp < _plain * 0.75,
      f"robust {_rp:.0f} < 0.75 x plain {_plain:.0f}")
check("robust_peak preserves a real >=5 px line", P.robust_peak(_line) > 3800,
      f"{P.robust_peak(_line):.0f}")
# robust_peak_index marks the real line, not a glitch spike, at a sane exposure
_idxsig = 1500.0 + 20000.0 * np.exp(-0.5 * ((_xs - 20) / 2.5) ** 2)   # strong line at px 20
_idxsig[45] = 50000.0; _idxsig[46] = 50000.0                         # tall 2-px glitch
check("robust_peak_index finds the real line past a glitch spike",
      abs(P.robust_peak_index(_idxsig) - 20) <= 2, str(P.robust_peak_index(_idxsig)))

# smoothing: reduces noise, preserves peak position; reference-ratio (flat-field)
_x = np.linspace(0, 50, 200)
_clean = 1000.0 * np.exp(-0.5 * ((_x - 25) / 2.0) ** 2)
_noisy = _clean + np.random.default_rng(0).normal(0, 30, _x.size)
_sm = P.smooth(_noisy, 9, "savgol")
check("savgol reduces noise", float(np.std(_sm - _clean)) < float(np.std(_noisy - _clean)))
check("savgol keeps peak position", abs(int(np.argmax(_sm)) - int(np.argmax(_clean))) <= 1)
check("smooth window 0 is a no-op", np.array_equal(P.smooth(_noisy, 0), _noisy))
_ref = np.array([5000.0, 8000.0, 3000.0])
check("reference_ratio of self is 1.0", np.allclose(P.reference_ratio(_ref, _ref), 1.0))
check("reference_ratio halves at 50%", np.allclose(P.reference_ratio(_ref / 2, _ref), 0.5))
peak = 1500.0 + 30000.0 * np.exp(-0.5 * ((np.arange(40) - 20) / 1.8) ** 2)   # real ~4px-FWHM line
check("real broad peak preserved", abs(P.average_frames(peak)[20] - peak[20]) < 1.0, f"{P.average_frames(peak)[20]:.0f}/{peak[20]:.0f}")

# FILTER SAFETY: a line at the instrument's OWN resolution must pass through untouched,
# and raw mode (clean=False) must keep absolutely everything.
_m = cal.by_role("measurement")
_disp = (_m.range_nm[1] - _m.range_nm[0]) / (_m.pixel_window[1] - _m.pixel_window[0])
_res = _m.fwhm_nm / _disp
_xx = np.arange(120); _sig = _res / 2.3548
_line = 1500.0 + 50000.0 * np.exp(-0.5 * ((_xx - 60) / _sig) ** 2)
_ret = (P.average_frames(_line)[60] - 1500.0) / (_line[60] - 1500.0)
check(f"instrument-resolution line ({_res:.1f}px) preserved >99%", _ret > 0.99, f"{_ret*100:.2f}%")
_spk = np.full(120, 1500.0); _spk[60] = 45000.0
check("raw mode (clean=False) keeps everything", abs(P.average_frames(_spk, clean=False)[60] - 45000.0) < 1.0)

# ---- export (csv + branded pdf, hardware-free) ----
from spectro import export as EX
os.makedirs("output", exist_ok=True)
exp_meta = {"timestamp": "verify", "exposure_ms": 50, "averaging": 1, "dark_subtracted": False}
drv2 = open_driver(mock=True)
drv2.connect()
drv2.set_times_us(50_000)
exp_frame = drv2.grab()
drv2.close()
EX.write_spectrum_csv("output/_verify.csv", cal, exp_frame, exp_meta)
EX.write_pdf_report("output/_verify.pdf", cal, exp_frame, exp_meta)
check("csv exported", os.path.getsize("output/_verify.csv") > 200)
check("pdf exported", os.path.getsize("output/_verify.pdf") > 2000)
logger = EX.SessionLogger("output/_verify_log.csv")
for _ in range(3):
    logger.log(cal, exp_frame, 50, 1, 0.0)
logger.close()
check("session log has rows", logger.count == 3 and os.path.getsize("output/_verify_log.csv") > 50)

if "--live" in sys.argv:
    print("\n-- live hardware smoke (EurecaDriver on the real COM port) --")
    live = open_driver(mock=False)
    li = live.connect()
    check("live connects", (not li.mock) and li.pixels == 2048, li.summary())
    live.set_times_us(2000)
    fr = live.grab(discard=2)
    check("live frame 2048 x uint16", fr.shape == (2048,) and fr.dtype == np.uint16, f"max={int(fr.max())}")
    # the real USB stream carries the ~33514 transfer glitch; the cleaner must remove it
    live.set_times_us(20000)
    raw = np.stack([live.grab() for _ in range(12)]).astype(np.float64)
    gf = P.glitch_fraction(raw)
    comb = P.average_frames(raw, method="median")
    comb_gl = float(P._glitch_mask(comb).mean())
    print(f"   live raw glitch = {gf*100:.1f}% / frame  ->  after median combine = {comb_gl*100:.2f}%")
    check("median combine clears the USB glitch", comb_gl < 0.005, f"{comb_gl*100:.2f}% remain")
    live.close()

print()
if FAILS:
    print(f"VERIFY FAILED: {len(FAILS)} check(s) -> {FAILS}")
    sys.exit(1)
print("VERIFY OK")
