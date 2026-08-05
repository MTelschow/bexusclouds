"""Headless QC of the CLOUDS Spectral Engine panel - no GPU, no hardware.

QT_QPA_PLATFORM=offscreen + the mock driver; drive every control and grab a
panel screenshot. Run:

    $env:PYTHONIOENCODING='utf-8'; python -u verify_qt.py     (must end "VERIFY OK")
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import csv
import glob as _glob
import sys

import numpy as np
from PyQt5 import QtCore, QtWidgets


def _qt_msg(mode, ctx, msg):
    print(f"QT[{mode}]: {msg}", flush=True)


QtCore.qInstallMessageHandler(_qt_msg)
import clouds_spectral

FAILS = []


def check(n, c, d=""):
    ok = bool(c)
    print(f"[{'OK ' if ok else 'FAIL'}] {n}" + (f"  -- {d}" if d else ""))
    if not ok:
        FAILS.append(n)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = clouds_spectral.Engine(mock=True)
win.show()
for _ in range(8):
    app.processEvents()

check("futura family", bool(win.futura), win.futura)
_logo_pm = win.logo_label.pixmap()
check("CLOUDS logo loaded", _logo_pm is not None and not _logo_pm.isNull())
check("starts disconnected", not win.connected)

win._connect()
app.processEvents()
check("connects to mock", win.connected and win.info.mock, win.info.summary())

win.sp_exp.setValue(5)
win._single()
app.processEvents()
check("frame acquired", win.last_frame is not None and win.last_frame.shape == (2048,))
check("short exposure not clipping", win._last_sat < 0.5, f"sat={win._last_sat:.3f}")

win.sp_exp.setValue(0.05)
app.processEvents()
check("sub-ms integration (0.05 ms = 50 us)", abs(win.exposure_ms - 0.05) < 1e-6, str(win.exposure_ms))

win.sp_exp.setValue(1000)
app.processEvents()
check("exposure set 1000 ms", abs(win.exposure_ms - 1000) < 1e-6, str(win.exposure_ms))
win._single()
app.processEvents()
check("long exposure clips a channel", win._last_sat > 0.0, f"sat={win._last_sat:.3f}")
check("stats flag CLIPPING", "CLIPPING" in win.stats.text())

for label, idx in (("transmission", 1), ("absorbance", 2), ("counts", 0)):
    win.view_combo.setCurrentIndex(idx)
    app.processEvents()
    check(f"view -> {label}", win.view == label, win.view)

win.axis_combo.setCurrentIndex(1)
app.processEvents()
check("axis -> pixel", win.axis == "pixel")
win.axis_combo.setCurrentIndex(0)
app.processEvents()

win._capture_dark()
app.processEvents()
check("dark captured", win.dark is not None and win.dark.shape == (2048,))
win.chk_dark.setChecked(True)
win._single()
app.processEvents()
check("dark subtract on", win.subtract_dark_flag)

win.sp_avg.setValue(8)
app.processEvents()
check("averaging set to 8", win.navg == 8)

win.chk_clean.setChecked(False)
app.processEvents()
check("glitch filter toggles to raw", not win.clean)
win.chk_clean.setChecked(True)
app.processEvents()
check("glitch filter back on", win.clean)

win._render_plot()
_g = win._geom
_cx = int((_g["bbox"][0] + _g["bbox"][2]) / 2 * _g["pmw"])
_cy = int((1 - (_g["bbox"][1] + _g["bbox"][3]) / 2) * _g["pmh"])
win._cursor_readout(QtCore.QPoint(_cx, _cy))
check("cursor readout shows nm + counts", "nm" in win.cursor_lbl.text() and "meas" in win.cursor_lbl.text())

check("peak marker default on", win.show_peak)
win.chk_peak.setChecked(False); app.processEvents()
check("peak marker toggles off", not win.show_peak)
win.chk_peak.setChecked(True); app.processEvents()
check("peak marker back on", win.show_peak)

# interactive wavelength calibration dialog
dlg = clouds_spectral._CalibrationDialog(win)
mcal = win.cal.by_role("measurement")
f110 = float(mcal.pixel_to_nm(110))
dlg.table.setRowCount(0)
for pxv in (20, 110, 200):
    dlg._add_row(float(mcal.pixel_to_nm(pxv)), f"p{pxv}")
for _row, pxv in enumerate((20, 110, 200)):
    dlg.table.setItem(_row, 2, QtWidgets.QTableWidgetItem(f"{pxv}.0"))
dlg.ch_combo.setCurrentText("measurement")
dlg._fit(); app.processEvents()
check("calibration refit reproduces factory", abs(float(win.cal.by_role("measurement").pixel_to_nm(110)) - f110) < 0.5)
check("calibration shows RMS residual", "RMS" in dlg.result.text())
dlg.table.setCurrentCell(0, 0)
dlg._arm()
check("arming sets the plot-click callback", win._cal_cb is not None)
dlg._on_click(f110)
check("plot click marks a pixel", bool(dlg.table.item(0, 2).text()))
dlg._reset(); app.processEvents()
check("calibration reset restores factory", win.cal.by_role("measurement").pixel_window == (0, 235))

# flat-field / stored reference (clear the stale long-exposure dark first)
win.chk_dark.setChecked(False)
win.sp_exp.setValue(5); win._single(); app.processEvents()
win._capture_reference(); app.processEvents()
check("reference captured + flat on", win.reference_proc is not None and win.flat)
win._single(); app.processEvents()
_refm = np.asarray(win.reference_proc["m"], dtype=float)
_md = clouds_spectral.P.reference_ratio(win.last_proc["m"], _refm)
_sel = _md[_refm > 100]
check("flat-field baseline ~1 vs same light",
      _sel.size > 0 and abs(float(np.median(_sel)) - 1.0) < 0.15,
      f"{float(np.median(_sel)) if _sel.size else float('nan'):.3f}")
win._clear_reference(); app.processEvents()
check("reference cleared", win.reference_proc is None and not win.flat)
# smoothing toggle + mean/sigma stats
win.smooth_combo.setCurrentIndex(1); app.processEvents()
check("savgol smoothing on", win.smooth_win > 0 and win.smooth_mode == "savgol")
win.smooth_combo.setCurrentIndex(0); app.processEvents()
check("smoothing off", win.smooth_win == 0)
win._single(); app.processEvents()
check("stats show mean + sd", "mean" in win.stats.text() and "sd" in win.stats.text())
# log scale + spectral-region zoom + fps/frame counter
win.yscale_combo.setCurrentIndex(1); app.processEvents()
check("y log scale on", win.yscale == "log")
win.yscale_combo.setCurrentIndex(0); app.processEvents()
win.sp_xlo.setValue(600); win.sp_xhi.setValue(700); app.processEvents()
check("zoom window 600-700 nm", win.x_lo == 600 and win.x_hi == 700)
win._zoom_full(); app.processEvents()
check("zoom reset to full", win.x_lo is None and win.x_hi is None)
win._start()
for _ in range(3):
    win._tick_once(); app.processEvents()
win._stop()
check("fps + frame counter", win._frame_n > 0 and "fps" in win.stats.text())
# offset modes + sqrt scale
win.chk_dark.setChecked(False)
win.offset_combo.setCurrentIndex(1); win._single(); app.processEvents()
check("offset subtract-minimum -> baseline 0", win.offset_mode == "minimum" and float(np.min(win.last_proc["m"])) < 1.0)
win.offset_combo.setCurrentIndex(2); win._single(); app.processEvents()
check("offset dark-pixels mode (on-chip)", win.offset_mode == "darkpixels" and win._dark_value is not None)
win.offset_combo.setCurrentIndex(0); app.processEvents()
win.yscale_combo.setCurrentIndex(2); app.processEvents()
check("sqrt y-scale renders", win.yscale == "sqrt")
win.yscale_combo.setCurrentIndex(0); app.processEvents()
# auto-exposure: start saturated, expect it to back off into range
win.sp_exp.setValue(1000); app.processEvents()
win._auto_expose(); app.processEvents()
check("auto-exposure converges below saturation", 0.01 < win.exposure_ms < 300 and win._last_sat < 0.5,
      f"{win.exposure_ms} ms, sat {win._last_sat:.2f}")

# ---- continuous auto-exposure tracking (the servo: follow a changing scene) ----
win.chk_dark.setChecked(False); win.chk_flat.setChecked(False)
win.reference_proc = None; win.flat = False
_orig_shape = win.driver._shape.copy()
_sat = win.cal.saturation_count


def _settle(n=12):
    for _ in range(n):
        win._tick_once(); app.processEvents()


# snap-then-track: toggle on while live -> snaps into band and holds it
# timer stopped so only these explicit _tick_once() calls drive frames - live
# ticks now run on a worker thread and would otherwise land asynchronously,
# out of step with this section's tick-by-tick accounting (_esc, _ch, ...).
win.sp_exp.setValue(10); win._start(); win.timer.stop(); app.processEvents()
win.chk_track.setChecked(True); app.processEvents()
_settle(8)
_frac = win._last_peak / _sat
check("tracking: converges into band on a static scene", 0.56 <= _frac <= 0.84, f"frac={_frac:.3f}")
# dead-beat / no hunting: same scene, exposure must not churn
_e0 = win.exposure_ms; _ch = 0
for _ in range(20):
    _b = win.exposure_ms; win._tick_once(); app.processEvents()
    if abs(win.exposure_ms - _b) > 1e-6:
        _ch += 1
check("tracking: no hunting on a steady scene", _ch <= 1, f"{_ch} exposure changes / 20 ticks")
# bright -> dark 10x: exposure rises, peak climbs back into band
win.driver._shape = _orig_shape / 10.0
_settle(10)
_frac = win._last_peak / _sat
check("tracking: recovers from 10x dimming", 0.50 <= _frac <= 0.85 and win.exposure_ms > _e0,
      f"frac={_frac:.3f}, exp={win.exposure_ms} ms")
# worst case: parked high, then a big brightening into deep saturation -> escape fast
win.driver._shape = _orig_shape * 0.02
_settle(14)                                   # servo drives toward the 1000 ms rail
win.driver._shape = _orig_shape * 2.0         # ~100x brighter than it was parked for
_esc = None
for _i in range(10):
    win._tick_once(); app.processEvents()
    if win._last_sat < 0.01 and _esc is None:
        _esc = _i + 1
_settle(8)
_frac = win._last_peak / _sat
check("tracking: escapes deep saturation in <=4 ticks + lands in band",
      _esc is not None and _esc <= 4 and 0.50 <= _frac <= 0.85, f"escaped@{_esc}, frac={_frac:.3f}")
win.driver._shape = _orig_shape; _settle(8)
# glitch immunity: a 1-px spike (high peak, NO multi-pixel saturation) must not trigger a cut
win._oob_count = 0; _e_before = win.exposure_ms
win._last_peak = _sat * 0.99; win._last_sat = 0.0
win._track_exposure()
check("tracking: ignores a 1-px glitch (no saturated fraction)", abs(win.exposure_ms - _e_before) < 1e-6,
      f"exp {_e_before}->{win.exposure_ms}")
# rail honesty: too dim to reach band even at 1000 ms -> pin + say so
win.driver._shape = _orig_shape * 0.001
_settle(14)
check("tracking: rail-honest when the scene is too dim", win.exposure_ms >= 999 and "dim" in win._track_msg,
      f"exp={win.exposure_ms} ms, msg={win._track_msg!r}")
win.driver._shape = _orig_shape; _settle(6)
# manual slider drag hands control back (tracking auto-disables)
check("tracking is on before the manual drag", win._track)
win.sp_exp.setValue(7.0); app.processEvents()     # simulate a user drag -> _on_exposure fires
check("tracking: a manual slider drag disables tracking", not win._track and not win.chk_track.isChecked())
win._stop(); win.driver._shape = _orig_shape; app.processEvents()

# single-channel support: swap to a 1-channel calibration and exercise the no-reference path
win.chk_dark.setChecked(False); win.chk_flat.setChecked(False); win.reference_proc = None
win.cal = clouds_spectral.Calibration.load(os.path.join(clouds_spectral.HERE, "calibration_single.json"))
win.sp_exp.setValue(5); win._single(); app.processEvents()
check("single-channel: no reference channel", win._ref() is None and win.last_proc.get("r") is None)
check("single-channel: measurement renders", win.last_proc["m"].size > 0 and win._geom is not None)
win.view_combo.setCurrentIndex(1); win._single(); app.processEvents()       # transmission -> graceful fallback
check("single-channel: ratio view falls back without crash", win._geom is not None)
win.view_combo.setCurrentIndex(0); app.processEvents()
_sg = win._geom
win._cursor_readout(QtCore.QPoint(int((_sg["bbox"][0] + _sg["bbox"][2]) / 2 * _sg["pmw"]),
                                  int((1 - (_sg["bbox"][1] + _sg["bbox"][3]) / 2) * _sg["pmh"])))
check("single-channel: cursor shows ref --", "--" in win.cursor_lbl.text())
# single-channel export + session logging must NOT crash (regression for the KeyError bug)
_sc_before = set(_glob.glob("output/clouds_spectrum_*.csv"))
win._export(); app.processEvents()
_sc_new = sorted(set(_glob.glob("output/clouds_spectrum_*.csv")) - _sc_before)
_sc_ok = bool(_sc_new) and os.path.exists(_sc_new[-1][:-4] + ".pdf")
if _sc_ok:
    with open(_sc_new[-1], newline="", encoding="utf-8") as _f:
        _rows = [r for r in csv.reader(_f) if r and r[0] and r[0][0] != "#"]
    _hdr = next((r for r in _rows if r[0] == "wavelength_nm"), None)
    _data = _rows[_rows.index(_hdr) + 1:] if _hdr else []
    _sc_ok = bool(_data) and all(r[2] == "" for r in _data)        # reference column blank
check("single-channel: export CSV+PDF without crash, blank reference column", _sc_ok)
_lg_before = set(_glob.glob("output/session_*.csv"))
win.chk_log.setChecked(True); win._single(); win._single(); app.processEvents()
_lg_new = sorted(set(_glob.glob("output/session_*.csv")) - _lg_before)
_lg_ok = False
if _lg_new:
    with open(_lg_new[-1], newline="", encoding="utf-8") as _f:
        _lrows = list(csv.reader(_f))
    _lg_ok = len(_lrows) >= 3 and all(r[5] == "" for r in _lrows[1:])   # >=2 data rows, ref_peak blank
check("single-channel: session logging writes rows with blank reference", _lg_ok and win.logger is not None,
      f"{len(_lrows) - 1 if _lg_new else 0} rows")
win.chk_log.setChecked(False)
win.cal = clouds_spectral.Calibration.load(); app.processEvents()           # restore the Duo

# --edu wiring: kind selection + its per-instrument default calibration.
# Wiring only, no acquisition - the mock driver emits 2048-px Duo frames, which
# a 3648-px calibration has no business slicing.
check("kind: default is std", win.kind == "std")
_edu = clouds_spectral.Engine(mock=True, kind="edu")
check("kind: --edu is honoured", _edu.kind == "edu")
check("kind: --edu stays on the mock driver", type(_edu.driver) is type(win.driver))
check("kind: --edu loads the 3648-px single-channel calibration",
      _edu.cal.n_pixels == 3648 and _edu.cal.by_role_optional("reference") is None,
      f"{_edu.cal.n_pixels}px, {len(_edu.cal.channels)} channel(s)")
check("kind: the Duo default is untouched",
      win.cal.n_pixels == 2048 and win.cal.by_role_optional("reference") is not None)
os.environ["CLOUDS_CALIBRATION"] = os.path.join(clouds_spectral.HERE, "calibration.json")
check("kind: an explicit CLOUDS_CALIBRATION overrides the --edu default",
      clouds_spectral._default_calibration("edu") is None)
del os.environ["CLOUDS_CALIBRATION"]
_edu.driver.close(); _edu.close(); _edu.deleteLater(); app.processEvents()

win._start()
app.processEvents()
check("running", win.running and win.timer.isActive())
for _ in range(5):
    win._tick_once()
    app.processEvents()
win._stop()
check("stopped", not win.running and not win.timer.isActive())

win._start()
app.processEvents()
win._single_shot()
app.processEvents()
check("Single button freezes live + captures", (not win.running) and win.last_frame is not None)

os.makedirs("output", exist_ok=True)
win.grab().save("output/qt_panel.png")
print("device:", win.lbl_device.text().replace("\n", " | "))
print("hint  :", repr(win.hint.text()))
print("stats :", win.stats.text().replace("\n", " | "))

win._export()
app.processEvents()
check("UI export writes csv+pdf",
      bool(_glob.glob("output/clouds_spectrum_*.csv")) and bool(_glob.glob("output/clouds_spectrum_*.pdf")))
win.chk_log.setChecked(True)
win._single()
win._single()
app.processEvents()
win.chk_log.setChecked(False)
app.processEvents()
check("UI session log written", bool(_glob.glob("output/session_*.csv")))

if "--live" in sys.argv:
    print("\n-- live hardware through the full UI (real EURECA Duo) --")
    lwin = clouds_spectral.Engine(mock=False)
    lwin.show()
    for _ in range(4):
        app.processEvents()
    lwin._connect()
    app.processEvents()
    check("live UI connects", lwin.connected and (lwin.info is not None) and not lwin.info.mock,
          lwin.info.summary() if lwin.info else "no info")
    lwin.sp_exp.setValue(3)
    for _ in range(3):
        lwin._single()
        app.processEvents()
    ok_frame = lwin.last_frame is not None and lwin.last_frame.shape == (2048,)
    check("live UI acquires a frame", ok_frame,
          f"meas max={int(lwin.last_proc['m'].max()) if lwin.last_proc else -1}")
    lwin.grab().save("output/qt_panel_live.png")
    lwin._stop()
    try:
        lwin.driver.close()
    except Exception:
        pass

print()
if FAILS:
    print(f"VERIFY_QT FAILED: {FAILS}")
    sys.exit(1)
print("VERIFY OK")
