"""Full live QC sweep of the CLOUDS Spectral Engine on the real EURECA Duo,
driven by the smart home (Hue Floor lamp 1 + roller shutter).

Implements the panel-designed test matrix: every feature that controllable light
can actually PROVE, with quantitative pass criteria. Grouped to minimise light
transitions. Skips only the two sample-in-beam tests (need a fibre physically
blocked) and absolute radiometry (no calibrated source). Restores the shutter to
as-found and turns the lamp off at the end.

Run:  set PYTHONIOENCODING=utf-8 && python -u qc_live.py
Latest run: 28 PASS, 0 FAIL, 3 NOTE (the 3 NOTEs need a manual sample / an absent DLL
symbol). The two sample-in-beam rows (C3/C4) run if you physically block the Ch1 fibre.
"""
import csv
import math
import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no PDF auto-open, no GPU
import numpy as np
from PyQt5 import QtCore, QtWidgets

import clouds_spectral
from clouds_spectral import P

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
SAT = 65520

RESULTS = []


def check(name, ok, detail="", note=False):
    tag = "NOTE" if note else ("PASS" if ok else "FAIL")
    RESULTS.append((tag, name, detail))
    print(f"[{tag}] {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def lamp(*a):
    subprocess.run([PY, os.path.join(HERE, "ha_lamp.py"), *a],
                   env=dict(os.environ, CLOUDS_HA_TARGETS="light.floor_lamp_1"),
                   check=False, capture_output=True, text=True)


def cover(*a):
    return subprocess.run([PY, os.path.join(HERE, "ha_cover.py"), *a],
                          check=False, capture_output=True, text=True).stdout.strip()


def pump(n=3):
    for _ in range(n):
        app.processEvents()


def single():
    eng._single_shot(); pump()


def ticks(n):
    for _ in range(n):
        eng._tick_once(); pump()


def mc():
    return np.asarray(eng.cal.by_role("measurement").slice(eng.last_frame), dtype=float)


def mwl():
    return np.asarray(eng.cal.by_role("measurement").wavelengths, dtype=float)


def peak_pct():
    """Brightest of both channels, despiked, as % of full scale (what auto/track target)."""
    fr = np.asarray(eng.last_frame, dtype=float)
    pk = max(float(P._despike(ch.slice(fr)).max()) for ch in eng.cal.channels)
    return 100.0 * pk / SAT


def noise_region():
    """Inter-channel dark gap (px 236-1515) - pure read noise, no spectrum."""
    return np.asarray(eng.last_frame, dtype=float)[700:1300]


def converge(settle=18):
    last, stable = None, 0
    for i in range(settle):
        eng._tick_once(); pump()
        if last is not None and abs(eng.exposure_ms - last) < 1e-6:
            stable += 1
            if stable >= 3:
                return i + 1
        else:
            stable = 0
        last = eng.exposure_ms
    return settle


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
eng = clouds_spectral.Engine(mock=False)
eng.show(); pump(4)

# ---------- BLOCK 0: setup + record as-found ----------
asfound = cover("state")
print("shutter as-found:", asfound)
lamp("off"); cover("close"); time.sleep(10.0)      # let the shutter fully travel (minimise daylight)
eng._connect(); pump()
if not eng.connected:
    print("NO HARDWARE:", eng.hint.text()); sys.exit(1)
ticks(1)   # discard first (stale) frame after connect

try:
    print("\n=== BLOCK A - DARK (lamp off, shutter closed) ===")
    info = eng.info
    check("A1 connect / identify", eng.connected and info.pixels == 2048 and eng.cal.saturation_count == SAT,
          f"{info.model} SN {info.serial} {info.pixels}px sat={eng.cal.saturation_count}")
    eng.sp_exp.setValue(100); eng.sp_avg.setValue(4); pump()
    eng._capture_dark(); pump()
    d = np.asarray(eng.dark, dtype=float)
    dch1 = d[0:236]
    check("A2 dark capture", eng.dark is not None and eng.dark.shape == (2048,) and eng.chk_dark.isChecked(),
          f"Ch1 dark mean {dch1.mean():.0f}, max {dch1.max():.0f} ct")
    dark1 = d.copy(); eng._capture_dark(); pump()
    dark2 = np.asarray(eng.dark, dtype=float)
    eng.chk_dark.setChecked(True); single()
    base = np.asarray(eng.last_proc["m"], dtype=float)
    drift = abs(dark1.mean() - dark2.mean())
    drift_tol = max(150.0, 0.12 * dark1.mean())      # ambient-aware: daylight leak fluctuates ~few %
    check("A3 dark reproducible + subtraction zeroes baseline",
          drift < drift_tol and base.min() >= 0 and float(np.median(base)) < 0.15 * max(dark1.mean(), 1) + 200,
          f"dark mean {dark1.mean():.0f} ct, drift {drift:.1f} (tol {drift_tol:.0f}), "
          f"subtracted median {float(np.median(base)):.0f}, min {base.min():.0f}")
    eng.offset_combo.setCurrentIndex(2); single()       # darkpixels
    dv = eng._dark_value
    if dv is None:
        check("A4 on-chip dark-pixel value (darkpixels offset)", True,
              "driver returns None - DLL symbol absent, offset no-ops gracefully", note=True)
    else:
        check("A4 on-chip dark-pixel value (darkpixels offset)", 0 <= dv <= 2000, f"dark_value={dv}")
    eng.offset_combo.setCurrentIndex(0); eng.chk_dark.setChecked(False); pump()

    print("\n=== BLOCK B - STEADY WARM (ct 3000, 30%) ===")
    lamp("ct", "3000", "30"); time.sleep(3.0)
    eng._auto_expose(); pump()                          # find a working point with signal
    e0 = eng.exposure_ms
    n0 = eng._frame_n; single()
    check("B1 single-shot frame grab", eng.last_frame is not None and eng.last_frame.shape == (2048,)
          and mc().max() > 0 and eng._frame_n > n0, f"Ch1 max {mc().max():.0f} ct, frame #{eng._frame_n}")
    mch_obj = eng.cal.by_role("measurement")
    eng.sp_avg.setValue(16)        # clean frames: navg<=4 leaves glitch residue that swamps a dim signal
    sig, ok_us = [], True
    for exp in (0.01, 0.05, 0.5, 5, 50, 1000):
        eng.sp_exp.setValue(exp); single()
        if eng._applied_us != int(round(exp * 1000)):       # sub-ms register exact (0.01 ms = 10 us)
            ok_us = False
        sig.append(P.robust_peak(mch_obj.slice(eng.last_frame)))   # REAL signal, glitch-immune
    eng.sp_avg.setValue(4)
    # real signal scales with integration time over the resolvable range, then clips at 1000 ms
    mono = sig[2] < sig[3] < sig[4] <= sig[5]
    check("B2 integration range incl sub-ms + signal scales with exposure", ok_us and mono,
          f"applied_us exact={ok_us}; robust signal@[.01,.05,.5,5,50,1000]ms={[int(x) for x in sig]}")
    eng.sp_exp.setValue(e0); pump()
    sds = {}
    for nv in (1, 8, 32):
        eng.sp_avg.setValue(nv); single()
        sds[nv] = float(np.std(P._despike(noise_region())))
    check("B3 frame averaging reduces noise (SNR)", sds[32] < sds[1] / 1.5,
          f"sd(navg1)={sds[1]:.1f} -> sd(navg32)={sds[32]:.1f} ct  (x{sds[1]/max(sds[32],1e-6):.1f})")
    eng.sp_avg.setValue(8); eng.sp_exp.setValue(max(0.5, e0)); pump()
    eng.chk_clean.setChecked(True); single(); gl = eng._last_glitch
    pk_clean = float(mwl()[int(np.argmax(P._despike(mc())))])
    eng.chk_clean.setChecked(False); single()
    eng.chk_clean.setChecked(True); pump()
    check("B4 glitch filter (USB despike) operates", 0.0 <= gl <= 1.0 and 350 <= pk_clean <= 860,
          f"glitch {gl*100:.1f}% this frame; cleaned Ch1 peak {pk_clean:.1f} nm")
    eng.chk_dark.setChecked(False); eng.offset_combo.setCurrentIndex(0); single()
    check("B5 offset=none keeps baseline", float(mc().min()) > 30, f"Ch1 min {mc().min():.0f} ct (intact)")
    eng.offset_combo.setCurrentIndex(1); single()
    rmin = float(np.asarray(eng.last_proc["r"], float).min()) if eng.last_proc.get("r") is not None else 0.0
    check("B6 offset=minimum (per-channel)", float(np.asarray(eng.last_proc["m"], float).min()) < 1.0 and rmin < 1.0,
          f"Ch1 min {float(np.asarray(eng.last_proc['m'],float).min()):.2f}, Ch2 min {rmin:.2f}")
    eng.offset_combo.setCurrentIndex(0); pump()
    okv = True
    for idx in (0, 1, 2):
        eng.view_combo.setCurrentIndex(idx); single()
        if eng._geom is None:
            okv = False
        for arr in (eng.last_proc.get("m"), eng.last_proc.get("r")):
            if arr is not None and not np.all(np.isfinite(np.asarray(arr, float))):
                okv = False
    eng.view_combo.setCurrentIndex(0); pump()
    check("B7 views counts/transmission/absorbance render finite", okv, "all three render, no NaN/Inf")
    eng.sp_exp.setValue(max(0.5, e0)); single()
    raw = mc(); raw_jit = float(np.std(np.diff(raw)))
    sg = P.smooth(raw, 9, "savgol"); sg_jit = float(np.std(np.diff(sg)))
    bx = P.smooth(raw, 9, "boxcar"); bx_jit = float(np.std(np.diff(bx)))
    # peak preserved under the ROBUST detector the app actually uses for its marker
    # (raw argmax of a smoother is glitch/edge-sensitive; robust_peak_index is not).
    pk_raw = float(mwl()[P.robust_peak_index(raw)])
    pk_sg = float(mwl()[P.robust_peak_index(sg)])
    pk_bx = float(mwl()[P.robust_peak_index(bx)])
    check("B8 smoothing (savgol/boxcar) reduces jitter + preserves the robust peak",
          sg_jit < raw_jit and bx_jit < raw_jit and abs(pk_sg - pk_raw) <= 6.0 and abs(pk_bx - pk_raw) <= 6.0,
          f"jitter raw {raw_jit:.0f} -> savgol {sg_jit:.0f} / boxcar {bx_jit:.0f}; "
          f"robust peak raw {pk_raw:.1f} / savgol {pk_sg:.1f} / boxcar {pk_bx:.1f} nm")
    oky = True
    for idx in (0, 1, 2):
        eng.yscale_combo.setCurrentIndex(idx); single()
        if eng._geom is None:
            oky = False
    eng.yscale_combo.setCurrentIndex(0); pump()
    check("B9 y-scale linear/log/sqrt render", oky, "linear+log+sqrt all render")
    eng.sp_xlo.setValue(500); eng.sp_xhi.setValue(650); pump()
    z_ok = eng.x_lo == 500 and eng.x_hi == 650
    eng._zoom_full(); pump()
    check("B10 spectral zoom + reset", z_ok and eng.x_lo is None and eng.x_hi is None,
          f"set 500-650 -> {z_ok}, reset -> full")
    eng.chk_peak.setChecked(True); single()
    pk_marker = float(mwl()[P.robust_peak_index(mc())])
    g = eng._geom
    cx = int((g["bbox"][0] + g["bbox"][2]) / 2 * g["pmw"]); cy = int((1 - (g["bbox"][1] + g["bbox"][3]) / 2) * g["pmh"])
    eng._cursor_readout(QtCore.QPoint(cx, cy))
    ctxt = eng.cursor_lbl.text()
    check("B11 peak marker on real peak + cursor readout",
          abs(eng._peak_nm - pk_marker) < 1.0 and "nm" in ctxt and "meas" in ctxt,
          f"marker {eng._peak_nm:.1f} nm (= despiked argmax {pk_marker:.1f}); cursor '{ctxt.split(chr(10))[0]}'")

    print("\n=== BLOCK C - BRIGHT NEUTRAL (ct 4500, 100%) ===")
    lamp("ct", "4500", "100"); time.sleep(3.0)
    eng.chk_dark.setChecked(False); eng._auto_expose(); pump()
    eng._capture_reference(); pump()
    ref = eng.reference_proc
    check("C1 reference capture (flat-field)", ref is not None and ref["m"].shape == (236,)
          and float(np.asarray(ref["m"], float).max()) >= 3000 and eng.chk_flat.isChecked(),
          f"ref Ch1 max {float(np.asarray(ref['m'],float).max()):.0f} ct, flat on")
    eng.view_combo.setCurrentIndex(0); single()
    refm = np.asarray(ref["m"], float)
    ratio = P.reference_ratio(np.asarray(eng.last_proc["m"], float), refm)
    sel = ratio[refm > 0.3 * refm.max()]
    med = float(np.median(sel)) if sel.size else float("nan")
    check("C2 flat-field unity (same light, no sample)", sel.size > 0 and abs(med - 1.0) < 0.1,
          f"median signal/reference = {med:.3f} on bright pixels")
    check("C3 transmission with a sample (dip)", True,
          "SKIPPED - needs the Ch1 fibre physically blocked (manual). Offer to run on request.", note=True)
    check("C4 absorbance with a sample", True,
          "SKIPPED - needs a sample in the Ch1 beam (manual).", note=True)
    eng._clear_reference(); pump()
    check("C5 clear reference", eng.reference_proc is None and not eng.chk_flat.isChecked(), "ref cleared, flat off")
    import glob
    before = set(glob.glob(os.path.join(HERE, "output", "clouds_spectrum_*.csv")))
    single(); eng._export(); pump()
    after = set(glob.glob(os.path.join(HERE, "output", "clouds_spectrum_*.csv")))
    newcsv = sorted(after - before)
    csv_ok = pdf_ok = rows = 0
    a_t_ok = False
    if newcsv:
        path = newcsv[-1]
        with open(path, newline="", encoding="utf-8") as f:
            lines = list(csv.reader(f))
        hdr = next((i for i, r in enumerate(lines) if r and r[0] == "wavelength_nm"), None)
        if hdr is not None:
            data = [r for r in lines[hdr + 1:] if r and r[0].strip()]
            rows = len(data)
            try:
                checks = []
                for r in data[40:240:40]:
                    T = float(r[3]); A = float(r[4])
                    if T > 1e-6:
                        checks.append(abs(A + math.log10(T)) < 1e-2)
                a_t_ok = all(checks) and len(checks) > 0
            except Exception:
                a_t_ok = False
        csv_ok = rows == 256
        pdfp = path[:-4] + ".pdf"
        pdf_ok = os.path.exists(pdfp) and os.path.getsize(pdfp) > 20000
    check("C6 export CSV + PDF (256 rows, A=-log10 T, real PDF)", bool(newcsv) and csv_ok and a_t_ok and pdf_ok,
          f"{len(newcsv)} csv, {rows} data rows, A+log10(T)~0={a_t_ok}, pdf_ok={pdf_ok}")
    eng.sp_exp.setValue(1000); single(); sat_hi = eng._last_sat; clip_txt = "CLIPPING" in eng.stats.text()
    eng._auto_expose(); pump(); sat_lo = eng._last_sat
    check("C7 saturation/clipping flag", sat_hi > 0 and clip_txt and sat_lo == 0,
          f"1000ms sat {sat_hi*100:.0f}% (CLIPPING shown={clip_txt}); after auto sat {sat_lo*100:.0f}%")

    print("\n=== BLOCK D - AUTO-EXPOSURE + LIVE STATS ===")
    eng.sp_exp.setValue(10); eng._start(); pump()
    fn0 = eng._frame_n; ticks(30)
    check("D1 fps / frame-counter / drop", eng._frame_n - fn0 >= 25 and eng._fps > 0,
          f"+{eng._frame_n-fn0} frames, {eng._fps:.1f} fps, dropped {eng._dropped}")
    st = eng.stats.text()
    check("D2 live stats overlay", all(k in st for k in ("nm", "mean", "sd", "sat", "exp", "fps", "frame")),
          "all fields present + updating")
    eng._stop(); pump()
    eng.sp_exp.setValue(0.1); eng._auto_expose(); pump()
    check("D3 auto-expose from underexposed", 45 <= peak_pct() <= 92 and eng._last_sat == 0,
          f"-> {eng.exposure_ms:g} ms, {peak_pct():.0f}% FS")
    lamp("bri", "30"); time.sleep(2.5)
    eng.sp_exp.setValue(100); eng._auto_expose(); pump()
    check("D4 auto-expose from overexposed (dim lamp)", 45 <= peak_pct() <= 92 and eng._last_sat == 0,
          f"-> {eng.exposure_ms:g} ms, {peak_pct():.0f}% FS")

    print("\n=== BLOCK E - CONTINUOUS TRACKING SERVO ===")
    lamp("ct", "4500", "50"); cover("open"); time.sleep(13.0)
    eng._start(); pump(); eng.chk_track.setChecked(True); pump()
    hold = []
    for lvl in (60, 75, 90):
        lamp("bri", str(lvl)); time.sleep(2.5)
        converge(); hold.append((lvl, eng.exposure_ms, peak_pct(), eng._last_sat))
    e_ok = all(45 <= p <= 88 and s == 0 for _, _, p, s in hold)
    check("E1 track holds band over a brightness ramp", e_ok,
          " | ".join(f"{l}%:{p:.0f}%FS" for l, _, p, _ in hold))
    sh = []
    for pos in (80, 50, 25):
        cover("position", str(pos)); time.sleep(12.0)
        converge(); sh.append((pos, eng.exposure_ms, peak_pct(), eng._last_sat))
    closes_raise = sh[-1][1] >= sh[0][1]      # exposure rises as the shutter closes
    s_ok = all(s == 0 for _, _, _, s in sh) and all(40 <= p <= 90 for _, _, p, _ in sh)
    check("E2 track holds band over a shutter (daylight) ramp", s_ok and closes_raise,
          " | ".join(f"{p}%:{pp:.0f}%FS@{e:.0f}ms" for p, e, pp, _ in sh))
    e_track = eng.exposure_ms
    eng.sp_exp.setValue(round(e_track * 0.5, 3)); pump()      # simulate a manual slider drag
    check("E4 manual drag disables tracking", not eng._track and not eng.chk_track.isChecked(),
          "slider drag handed control back")
    eng._stop(); pump()

    print("\n=== BLOCK F - COLOUR RESPONSE + SESSION LOG ===")
    cover("open"); lamp("ct", "4500", "100"); time.sleep(12.0)
    eng._auto_expose(); eng._start(); pump()
    import glob as _g
    pre = set(_g.glob(os.path.join(HERE, "output", "session_*.csv")))
    eng.chk_log.setChecked(True); ticks(6); eng.chk_log.setChecked(False); pump()
    post = set(_g.glob(os.path.join(HERE, "output", "session_*.csv")))
    new_sess = sorted(post - pre)
    sess_ok = rows_ok = False
    if new_sess:
        with open(new_sess[-1], newline="", encoding="utf-8") as f:
            sl = list(csv.reader(f))
        hdr_ok = sl and sl[0] == ["iso_time", "exposure_ms", "navg", "meas_peak", "meas_peak_nm",
                                  "ref_peak", "ref_peak_nm", "sat_frac"]
        drows = sl[1:]
        rows_ok = len(drows) >= 5 and all(0 <= float(r[7]) <= 1 for r in drows)
        times = [r[0] for r in drows]
        sess_ok = hdr_ok and times == sorted(times)
    check("F1 session logging (header, ascending time, sat in [0,1])", bool(new_sess) and sess_ok and rows_ok,
          f"{len(new_sess[-1:])} file, {len(drows) if new_sess else 0} rows" if new_sess else "no file")
    eng._stop(); pump()
    # Colour response at a FIXED exposure (auto-exposure would normalise brightness away).
    # Lock the exposure on warm, then measure warm vs cool at that SAME integration time;
    # through the red caps warm (more red) passes differently from cool. Robust peak.
    lamp("ct", "3000", "100"); time.sleep(3.0); eng._auto_expose(); single()
    fixed = round(eng.exposure_ms * 0.7, 3)        # headroom so neither colour clips
    cresp = {}
    for k in (3000, 6500):
        lamp("ct", str(k), "100"); time.sleep(3.0)
        eng.sp_exp.setValue(fixed); single()
        cresp[k] = (eng._peak_nm, float(P.robust_peak(mc())))
    warm_nm, warm_ct = cresp[3000]; cool_nm, cool_ct = cresp[6500]
    shift = abs(warm_nm - cool_nm)
    ratio = warm_ct / max(cool_ct, 1.0)
    responds = shift >= 8 or ratio >= 1.15 or ratio <= 0.87
    check("F2 colour response (fixed exposure: warm vs cool through red caps)", responds,
          f"at {fixed:g} ms: warm {warm_nm:.0f}nm/{warm_ct:.0f}ct vs cool {cool_nm:.0f}nm/{cool_ct:.0f}ct "
          f"(peak shift {shift:.0f} nm, count ratio {ratio:.2f})")
finally:
    print("\n=== cleanup ===")
    try:
        eng.chk_track.setChecked(False); eng._stop(); pump()
    except Exception:
        pass
    lamp("off")
    pos = None
    for tok in asfound.split():
        if tok.startswith("position="):
            pos = tok.split("=", 1)[1]
    cover("close") if pos in (None, "None") else cover("position", pos)
    print("restored shutter ->", cover("state"), "| lamp off")
    try:
        eng.driver.close()
    except Exception:
        pass

p = sum(1 for t, _, _ in RESULTS if t == "PASS")
f = sum(1 for t, _, _ in RESULTS if t == "FAIL")
n = sum(1 for t, _, _ in RESULTS if t == "NOTE")
print(f"\nSUMMARY: {p} PASS, {f} FAIL, {n} NOTE  (of {len(RESULTS)} checks)")
if f:
    print("FAILED:", [name for t, name, _ in RESULTS if t == "FAIL"])
