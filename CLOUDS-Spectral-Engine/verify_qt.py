"""Headless QC of the CLOUDS Spectral Engine panel - no GPU, no hardware.

QT_QPA_PLATFORM=offscreen + the mock driver; drive every control and grab a
panel screenshot. Run:

    $env:PYTHONIOENCODING='utf-8'; python -u verify_qt.py     (must end "VERIFY OK")
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Capture now persists the dark as the operator's default. A QC run must never
# overwrite the one on the bench, so point the store at a scratch file before
# clouds_ui is imported.
os.makedirs("output", exist_ok=True)
os.environ["CLOUDS_DARK"] = os.path.join("output", "verify_dark.npz")
import csv
import glob as _glob
import sys
import time

import numpy as np
from PyQt5 import QtCore, QtTest, QtWidgets


def _qt_msg(mode, ctx, msg):
    print(f"QT[{mode}]: {msg}", flush=True)


QtCore.qInstallMessageHandler(_qt_msg)
from clouds_ui import window as clouds_ui_window
from clouds_ui import style as _style

FAILS = []


def check(n, c, d=""):
    ok = bool(c)
    print(f"[{'OK ' if ok else 'FAIL'}] {n}" + (f"  -- {d}" if d else ""))
    if not ok:
        FAILS.append(n)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = clouds_ui_window.CloudsWindow(mock=True)
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

# A detector that is not up at startup must not be a dead session. Every
# *later* driver error arms the 3 s retry; the one at startup did not, so a
# Pi whose --bench-stream was a second behind the window, or a Duo that lost
# its first search_for_camera, left the instrument half dead with the flight
# half running - which reads as "the spectrum just doesn't show" and got
# fixed by restarting the app. Own window on a closed port: refused at once.
import socket as _socket
_probe = _socket.socket(); _probe.bind(("127.0.0.1", 0))
_dead_port = _probe.getsockname()[1]; _probe.close()
_cold = clouds_ui_window.CloudsWindow(kind="net", host=f"127.0.0.1:{_dead_port}")
_cold.start_detector()
app.processEvents()
check("startup with no detector arms the retry",
      not _cold.connected and _cold._reconnect_timer.isActive()
      and _cold._resume_on_reconnect,
      "connect refused -> retrying, live still the standing intent")
check("a manual Connect click does not disarm that retry",
      (_cold._connect() or True) and _cold._reconnect_timer.isActive())
_cold.close()

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

# The dark survives a restart: capture writes it, a fresh window loads it back
# together with the exposure it was taken at - and refuses to apply it at any
# other exposure, because dark current scales with integration time.
from spectro import dark as _darkstore                                     # noqa: E402

_dpath = _darkstore.default_path()
check("dark: captured dark is stored as the default", os.path.isfile(_dpath),
      os.path.basename(_dpath))
_stored = _darkstore.load(_dpath, pixels=2048)
check("dark: the store keeps the exposure it was taken at",
      _stored is not None and _stored.exposure_us == int(round(win.exposure_ms * 1000)),
      _stored.summary() if _stored else "-")

_dwin = clouds_ui_window.CloudsWindow(mock=True)
app.processEvents()
check("dark: a fresh window restores it", _dwin.dark is not None
      and np.allclose(np.asarray(_dwin.dark, dtype=float),
                      np.asarray(win.dark, dtype=float), atol=1e-3))
check("dark: the exposure comes back with it",
      abs(_dwin.exposure_ms - win.exposure_ms) < 1e-3,
      f"{_dwin.exposure_ms:g} ms")
check("dark: subtraction is on and the servo is off",
      _dwin.chk_dark.isChecked() and not _dwin.chk_track.isChecked())
check("dark: the panel names what is subtracted",
      "ms" in _dwin.lbl_dark.text() and "mean" in _dwin.lbl_dark.text(),
      _dwin.lbl_dark.text())
_dwin.sp_exp.setValue(_dwin.exposure_ms / 4)   # down: 4x up can hit the 1000 ms rail
app.processEvents()
check("dark: a different exposure withholds it rather than subtracting it",
      _dwin.dark is not None and _dwin._dark_in_use() is None)
check("dark: and the panel says it is held back",
      "held back" in _dwin.lbl_dark.text(), _dwin.lbl_dark.text())
_dwin.sp_exp.setValue(win.exposure_ms)
app.processEvents()
check("dark: back at its own exposure it applies again",
      _dwin._dark_in_use() is not None)
_dwin._clear_dark()
app.processEvents()
check("dark: Clear drops the stored default too",
      _dwin.dark is None and not os.path.isfile(_dpath))
_dwin.driver.close(); _dwin.close(); _dwin.deleteLater(); app.processEvents()

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
dlg = clouds_ui_window._CalibrationDialog(win)
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
_md = clouds_ui_window.P.reference_ratio(win.last_proc["m"], _refm)
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
def _wait_auto(timeout_s=30.0):
    """Drain the event loop until the exposure hunt has landed.

    The hunt runs on _AcquisitionWorker (over --net every probe is paced to the
    FSW's 1 Hz, and on the GUI thread that froze the window for minutes), so
    _auto_expose returns before the exposure has moved. Without this the checks
    below read the spinbox mid-hunt.
    """
    import time as _t
    t0 = _t.monotonic()
    while win._auto_worker is not None and _t.monotonic() - t0 < timeout_s:
        app.processEvents(); _t.sleep(0.005)
    app.processEvents()


win.sp_exp.setValue(1000); app.processEvents()
win._auto_expose(); _wait_auto()
check("auto-exposure converges below saturation", 0.01 < win.exposure_ms < 300 and win._last_sat < 0.5,
      f"{win.exposure_ms} ms, sat {win._last_sat:.2f}")
# the Auto button's own path: `clicked` carries a checked bool and PyQt5 binds
# it to the first slot parameter, which once made this _auto_expose(target=False)
# - the hunt could then only divide and always ended at the 0.02 ms rail.
win.sp_exp.setValue(1000); app.processEvents()
win.btn_auto.click(); _wait_auto()
check("Auto button does not pass its checked flag as the target",
      0.01 < win.exposure_ms < 300 and win._last_sat < 0.5,
      f"{win.exposure_ms} ms, sat {win._last_sat:.2f}")
# ... and the hunt must not hold the GUI thread while it does it. The mock
# driver returns instantly, so slow it to something like the --net case, where
# every grab is paced to the FSW's 1 Hz and the old synchronous hunt froze the
# window for minutes.
_real_grab = win.driver.grab


def _slow_grab(*a, **kw):
    import time as _t
    _t.sleep(0.05)
    return _real_grab(*a, **kw)


win.driver.grab = _slow_grab
win.sp_exp.setValue(1000); app.processEvents()
_t0, _spins = time.monotonic(), 0
win._auto_expose()
while win._auto_worker is not None and time.monotonic() - _t0 < 30.0:
    app.processEvents(); _spins += 1; time.sleep(0.001)
win.driver.grab = _real_grab
app.processEvents()
check("auto-exposure hunt leaves the GUI thread free", _spins > 50,
      f"{_spins} event-loop turns while the hunt ran")

# The hunt owns the detector for its whole run: unchecking `auto integration
# time` mid-hunt must NOT hand the controls back, or a value typed there is
# overwritten by the hunt's result seconds later.
win.driver.grab = _slow_grab
win.chk_track.blockSignals(True); win.chk_track.setChecked(True); win.chk_track.blockSignals(False)
win._track = True
win._auto_expose()
app.processEvents()
win.chk_track.setChecked(False)          # operator takes over mid-hunt
app.processEvents()
check("auto-exposure: unchecking auto mid-hunt does not free the controls",
      not win.sl_exp.isEnabled() and not win.sp_exp.isEnabled()
      and win.lbl_exp.text().endswith("busy"), repr(win.lbl_exp.text()))
_wait_auto()
win.driver.grab = _real_grab
app.processEvents()
check("auto-exposure: the controls come back when the hunt lands",
      win.sl_exp.isEnabled() and win.sp_exp.isEnabled()
      and win.lbl_exp.text() == win._EXP_LABEL, repr(win.lbl_exp.text()))

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
# the toggle snaps with a hunt first; wait it out, then re-stop the timer the
# hunt's resume restarted, so only the explicit _tick_once() calls drive frames
win.chk_track.setChecked(True); _wait_auto(); win.timer.stop(); app.processEvents()
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
# The integration controls must be visibly, not just functionally, handed over:
# while the servo owns the exposure they are disabled AND say who has them.
check("tracking off: the integration controls are live",
      win.sl_exp.isEnabled() and win.sp_exp.isEnabled()
      and win.lbl_exp.text() == win._EXP_LABEL, repr(win.lbl_exp.text()))
win.chk_track.setChecked(True); _wait_auto(); win.timer.stop(); app.processEvents()
check("tracking on: the integration controls are greyed and labelled",
      not win.sl_exp.isEnabled() and not win.sp_exp.isEnabled()
      and win.lbl_exp.text().endswith("auto") and "uncheck" in win.lbl_exp.toolTip(),
      repr(win.lbl_exp.text()))
check("tracking on: the disabled slider is drawn as disabled",
      ":disabled" in win.sl_exp.styleSheet())
# slider and spin box are two views of ONE value: what the servo set must be
# what the spin box prints, and the slider must sit at that position.
win.chk_track.setChecked(False); app.processEvents()
for _ms in (0.01, 0.023, 7.0, 123.456, 1000.0):
    win._show_exposure(_ms)
    check(f"integration {_ms:g} ms: slider and spin agree",
          abs(float(win.sp_exp.value()) - _ms) < 10 ** -win.sp_exp.decimals()
          and win.sl_exp.value() == win.sl_exp.to_pos(_ms),
          f"spin={win.sp_exp.value()} pos={win.sl_exp.value()}")
# a slider step must hand the driver exactly the number on screen (it used to
# pass the unrounded value while the spin box showed the rounded one)
win.sl_exp.setValue(win.sl_exp.value() - 40); app.processEvents()
check("integration: a slider move sets the exposure the spin box shows",
      abs(win.exposure_ms - float(win.sp_exp.value())) < 1e-9,
      f"exp={win.exposure_ms} spin={win.sp_exp.value()}")
# ... and the handle must sit where that number is. In the bottom decade the
# spin box has fewer distinct values than the slider has steps, so without the
# snap the handle parks up to two steps off the value it printed.
_off = []
for _pos in range(0, 121, 3):
    win.sl_exp.setValue(_pos)
    win.sl_exp.sliderReleased.emit()        # a drag ends in a release
    app.processEvents()
    if win.sl_exp.value() != win.sl_exp.to_pos(win.sp_exp.value()):
        _off.append(_pos)
check("integration: the handle sits at the value it shows, decade by decade",
      not _off, f"{len(_off)} positions disagree, first {_off[:3]}")
# one arrow click is ~10%, at both ends of the five-decade range
win._show_exposure(0.01)
check("integration: the spin step follows the decade (low end)",
      abs(win.sp_exp.singleStep() - 0.001) < 1e-9, str(win.sp_exp.singleStep()))
win._show_exposure(1000.0)
check("integration: the spin step follows the decade (high end)",
      abs(win.sp_exp.singleStep() - 100.0) < 1e-9, str(win.sp_exp.singleStep()))
win.sp_exp.setValue(7.0); app.processEvents()
win._stop(); win.driver._shape = _orig_shape; app.processEvents()

# single-channel support: swap to a 1-channel calibration and exercise the no-reference path
win.chk_dark.setChecked(False); win.chk_flat.setChecked(False); win.reference_proc = None
win.cal = clouds_ui_window.Calibration.load(os.path.join(clouds_ui_window.HERE, "calibration_single.json"))
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
win.cal = clouds_ui_window.Calibration.load(); app.processEvents()           # restore the Duo

# Kind wiring. One instrument family is left ("std", plus "net" for the same
# Duo reached over the cable), so the window must default to the Duo and reject
# a kind that no longer exists instead of quietly opening the wrong detector.
check("kind: default is std", win.kind == "std")
check("kind: the Duo calibration is what it loaded",
      win.cal.n_pixels == 2048 and win.cal.by_role_optional("reference") is not None,
      f"{win.cal.n_pixels}px, {len(win.cal.channels)} channel(s)")
try:
    clouds_ui_window.CloudsWindow(mock=True, kind="edu")
    _kind_rejected = False
except ValueError:
    _kind_rejected = True
check("kind: the retired EDU board is refused, not silently the Duo",
      _kind_rejected)

# Where a bare `python -m clouds_ui` looks for the detector. macOS has no
# EURECA vendor library at all, so "this machine" is not a place the detector
# can be - the default has to be the cable, or the app fails into a reconnect
# loop against a driver that cannot exist.
from clouds_ui import main as clouds_ui_main                                # noqa: E402

_bare = clouds_ui_main._parse([])
if sys.platform == "darwin":
    check("args: a bare run goes to the bench Pi on macOS",
          _bare.net == clouds_ui_main.BENCH_PI, _bare.net)
    check("args: the detector and the command link agree by default",
          _bare.net == _bare.experiment, f"{_bare.net} / {_bare.experiment}")
    os.environ["CLOUDS_SPECTRO_HOST"] = "10.9.8.7"
    check("args: CLOUDS_SPECTRO_HOST moves the default",
          clouds_ui_main._default_net() == "10.9.8.7")
    del os.environ["CLOUDS_SPECTRO_HOST"]
else:
    check("args: a bare run opens the local detector off macOS",
          _bare.net is None, repr(_bare.net))
check("args: --net always wins",
      clouds_ui_main._parse(["--net", "1.2.3.4"]).net == "1.2.3.4")

# --mock is the one way a spectrum on this screen is not real light, so the
# window has to say so where nobody can miss it - and it must not be able to
# leave a synthetic dark behind for the next real session to subtract.
check("args: --mock opens no detector anywhere",
      clouds_ui_main._parse(["--mock"]).net is None)
try:
    clouds_ui_main._parse(["--mock", "--net", "1.2.3.4"])
    _contradiction_refused = False
except SystemExit:
    _contradiction_refused = True
check("args: --mock and --net are refused together", _contradiction_refused)

_mwin = clouds_ui_window.CloudsWindow(mock=True, persist_dark=False)
_mwin._connect()
app.processEvents()
check("mock: the title names the simulation", "MOCK" in _mwin.windowTitle(),
      _mwin.windowTitle())
check("mock: the plot banner names it too", "MOCK" in _mwin.src_banner.text(),
      _mwin.src_banner.text().strip())
_mwin.source = "downlink"
_mwin._update_source_banner()
check("mock: and on the downlink source as well",
      "MOCK" in _mwin.src_banner.text(), _mwin.src_banner.text().strip())
_mwin.source = "detector"
_mwin._update_source_banner()

_before = open(_dpath, "rb").read() if os.path.isfile(_dpath) else None
_mwin.sp_exp.setValue(7)
_mwin._capture_dark()
app.processEvents()
_after = open(_dpath, "rb").read() if os.path.isfile(_dpath) else None
check("mock: a simulated dark is used but never stored",
      _mwin.dark is not None and _after == _before)
_mwin._clear_dark()
check("mock: clearing it leaves the real stored dark alone",
      os.path.isfile(_dpath) == (_before is not None))
_mwin.close()

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

# -- flight half: the actuator controls move real hardware -------------------
# The bench panel above only reads a detector; the GSE panel energizes the
# membrane solenoid and the dispersion motor. A slot that is not wired means
# an operator presses Stop and nothing happens, so the wiring is checked here
# rather than trusted.
print("\n-- flight half of the merged window (offscreen) --")
for _extra in ("gse", os.path.join("flight", "pi")):
    _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), _extra)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from clouds_link import hk as _hk
from clouds_link.commands import Command as _Cmd, Param as _Param
from clouds_link.frames import AckResult as _Ack, Frame as _Frame, \
    PacketType as _Pkt, pack_event as _pack_event
from clouds_fsw.command_server import CommandServer as _CmdServer, \
    CommandState as _CmdState
from clouds_gse.commander import Commander as _Commander
from clouds_gse.receiver import Receiver as _Receiver
from clouds_gse.session_log import SessionLog as _SessionLog

_mcu = {"duty": 0, "valves": 0, "hz": 0, "motor_duty": 100, "log": [],
        "motor_run": False}


def _forward(cmd, key, value):
    """Stands in for the RP2350: its own acceptance rules are tested in
    flight/mcu/test, so this only acks and reflects the drive into HK."""
    _mcu["log"].append((int(cmd), key, value))
    if cmd == _Cmd.MEMBRANE:
        _mcu["duty"] = key
    elif cmd == _Cmd.DISPERSE:
        # key = DisperseKey: 1 pulse, 2 run (held), 0 stop (both)
        _mcu["motor_run"] = key == 2
        _mcu["valves"] = int(_hk.ValveStatus.DISPERSE) if key else 0
    elif cmd == _Cmd.SET_PARAM and key == _Param.MEMBRANE_MHZ:
        _mcu["hz"] = value
    elif cmd == _Cmd.SET_PARAM and key == _Param.DISPERSE_DUTY:
        _mcu["motor_duty"] = value
    return _Ack.OK


_server = _CmdServer("127.0.0.1", 0, forward=_forward, state=_CmdState())
_server.start()
_rx = _Receiver(bind="127.0.0.1", port=0)
_rx.start()
_commander = _Commander("127.0.0.1", _server.port, timeout=2.0)
# The merged window in its flight shape. Instantiated with mock=True so this
# section never reaches for a detector: what is under test here is the flight
# half and the source switch, not acquisition.
_win = clouds_ui_window.CloudsWindow(
    mock=True, receiver=_rx, commander=_commander,
    session=_SessionLog("output", stamp="verify_gse"), source="downlink")
_win.resize(1420, 900)
_win.fold_for(flight=True)
_gse = _win.flight
_win.show()
app.processEvents()
try:
    _gse.sp_duty.setValue(70)
    _gse.sp_hz.setValue(0.5)   # tenths of a hertz must reach the MCU as mHz
    _gse._membrane_start()
    check("flight: membrane drive reaches the link",
          _mcu["log"] == [(int(_Cmd.SET_PARAM), int(_Param.MEMBRANE_MHZ), 500),
                          (int(_Cmd.MEMBRANE), 70, 0)], str(_mcu["log"]))
    check("flight: frequency is set before the drive starts", _mcu["hz"] == 500)
    _mcu["log"].clear()
    _gse._membrane_stop()
    check("flight: Stop commands duty 0",
          _mcu["log"] == [(int(_Cmd.MEMBRANE), 0, 0)] and _mcu["duty"] == 0,
          str(_mcu["log"]))
    _mcu["log"].clear()
    _gse.sl_motor.setValue(40)
    _gse._disperse()
    check("flight: motor button sets the speed, then asks for one pulse",
          _mcu["log"] == [(int(_Cmd.SET_PARAM), int(_Param.DISPERSE_DUTY), 40),
                          (int(_Cmd.DISPERSE), 1, 0)]
          and _mcu["motor_duty"] == 40, str(_mcu["log"]))
    check("flight: the speed slider shows its value",
          _gse.lbl_motor_speed.text() == "40 %", _gse.lbl_motor_speed.text())
    # Start/Stop: a run the operator holds, its speed re-sent live on slider
    # release while it runs and not otherwise, ended by Stop.
    _mcu["log"].clear()
    _gse.sl_motor.setValue(60)
    _gse._on_motor_speed_released()
    check("flight: an idle motor takes no speed on slider release",
          _mcu["log"] == [], str(_mcu["log"]))
    _gse._motor_start()
    check("flight: Start sets the speed, then asks for a run",
          _mcu["log"] == [(int(_Cmd.SET_PARAM), int(_Param.DISPERSE_DUTY), 60),
                          (int(_Cmd.DISPERSE), 2, 0)]
          and _mcu["motor_run"] and _gse._motor_running, str(_mcu["log"]))
    _mcu["log"].clear()
    _gse.sl_motor.setValue(30)
    _gse._on_motor_speed_released()
    check("flight: a running motor takes the new speed on slider release",
          _mcu["log"] == [(int(_Cmd.SET_PARAM), int(_Param.DISPERSE_DUTY), 30)]
          and _mcu["motor_duty"] == 30, str(_mcu["log"]))
    # The release is only one of the ways the handle moves. Arrow keys, the
    # wheel and a click on the groove emit no `sliderReleased` at all, so a
    # panel that listened for that alone showed a speed the motor was not
    # turning at. Drive the key the way the operator does, through the widget.
    _mcu["log"].clear()
    QtTest.QTest.keyClick(_gse.sl_motor, QtCore.Qt.Key_Left)
    check("flight: a running motor takes a speed dialled by keyboard",
          _mcu["log"] == [(int(_Cmd.SET_PARAM), int(_Param.DISPERSE_DUTY), 29)]
          and _mcu["motor_duty"] == 29 and _gse.lbl_motor_speed.text() == "29 %",
          f'{_mcu["log"]} / {_gse.lbl_motor_speed.text()}')
    # ...and the same value is not sent twice: a release after the keyboard
    # already pushed it, or a drag that ends where it started, is not a new
    # setting and must not spend a second SET_PARAM.
    _mcu["log"].clear()
    _gse._on_motor_speed_released()
    check("flight: an unchanged speed is not re-sent",
          _mcu["log"] == [], str(_mcu["log"]))
    _mcu["log"].clear()
    _gse._motor_stop()
    check("flight: Stop commands DISPERSE stop",
          _mcu["log"] == [(int(_Cmd.DISPERSE), 0, 0)]
          and not _mcu["motor_run"] and not _gse._motor_running,
          str(_mcu["log"]))
    _mcu["log"].clear()
    _gse.sl_motor.setValue(40)
    _gse._disperse()          # leave the HK stand-in showing a pulse below

    # housekeeping feedback: without it a 5 s pulse is invisible to ground
    import socket as _socket
    _tx = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    # The GP30 position switch rides in the same byte as the drive: it must
    # land in the Membrane row, not in Driving, or a sensed plunger reads as
    # a line the MCU is holding.
    _tx.sendto(_Frame(type=_Pkt.HK,
                      payload=_hk.Housekeeping(state=_hk.SeqState.STANDBY,
                                               membrane_duty=70,
                                               valve_status=_mcu["valves"]
                                               | _hk.ValveStatus.MEMBRANE_PULLED
                                               | _hk.ValveStatus.MEMBRANE_CYCLING
                                               ).pack(),
                      seq=0).stamp().encode(), ("127.0.0.1", _rx.port))
    for _ in range(60):
        app.processEvents()
        QtCore.QThread.msleep(5)
    _gse.refresh()
    app.processEvents()
    check("flight: renders the commanded drive and the sensed plunger",
          _gse._hk_labels["Membrane"].text() == "70 %  pulled, cycling"
          and _gse._hk_labels["Driving"].text() == "DISPERSE",
          f'{_gse._hk_labels["Membrane"].text()} / '
          f'{_gse._hk_labels["Driving"].text()}')
    # The same bits as a light beside the Drive/Stop buttons, and there the
    # colour is a verdict: green because the drive is on and the switch is
    # cycling with it, which is the agreement the light exists to show.
    check("flight: the switch light is green when the plunger follows the drive",
          _gse.lbl_switch.text()
          == "driving 70 % - plunger cycling, switch pressed"
          and _style.GREEN in _gse.dot_switch.styleSheet(),
          f"{_gse.lbl_switch.text()} / {_gse.dot_switch.styleSheet()}")
    # A build that cannot read GP30 says so: grey, and a reason, never a
    # confident "pressed" from an always-clear bit.
    _tx.sendto(_Frame(type=_Pkt.HK,
                      payload=_hk.Housekeeping(
                          state=_hk.SeqState.STANDBY, membrane_duty=70,
                          error_flags=_hk.HkErrors.NO_MEMBRANE_SENSE).pack(),
                      seq=1).stamp().encode(), ("127.0.0.1", _rx.port))
    for _ in range(60):
        app.processEvents()
        QtCore.QThread.msleep(5)
    _gse.refresh()
    app.processEvents()
    check("flight: the switch light goes grey when the MCU cannot read GP30",
          _gse.lbl_switch.text() == "switch: no reading (MCU build without GP30)"
          and _style.GRAY in _gse.dot_switch.styleSheet(),
          f"{_gse.lbl_switch.text()} / {_gse.dot_switch.styleSheet()}")
    # A drive that is on and a plunger that is not moving: the fault the
    # switch exists to show, and the one case that is red. The panel judges
    # against the rate it last had ACKed - the Drive button above left it at
    # 0.5 Hz, too slow to judge - so put it back to the MCU's default first.
    from clouds_ui.flight import MEMBRANE_HZ_DEFAULT as _MHZ_DEF
    _gse._membrane_hz = _MHZ_DEF
    _tx.sendto(_Frame(type=_Pkt.HK,
                      payload=_hk.Housekeeping(state=_hk.SeqState.STANDBY,
                                               membrane_duty=70).pack(),
                      seq=2).stamp().encode(), ("127.0.0.1", _rx.port))
    for _ in range(60):
        app.processEvents()
        QtCore.QThread.msleep(5)
    _gse.refresh()
    app.processEvents()
    check("flight: the switch light is red when the drive moves nothing",
          _gse.lbl_switch.text()
          == "driving 70 % - plunger NOT cycling, switch stuck released"
          and _style.RED in _gse.dot_switch.styleSheet(),
          f"{_gse.lbl_switch.text()} / {_gse.dot_switch.styleSheet()}")
    # Drive off: there is nothing for the switch to agree with, so the light
    # reports the position and stays grey - a resting solenoid is not a fault.
    _tx.sendto(_Frame(type=_Pkt.HK,
                      payload=_hk.Housekeeping(state=_hk.SeqState.STANDBY,
                                               membrane_duty=0).pack(),
                      seq=3).stamp().encode(), ("127.0.0.1", _rx.port))
    for _ in range(60):
        app.processEvents()
        QtCore.QThread.msleep(5)
    _gse.refresh()
    app.processEvents()
    check("flight: the switch light is grey with the solenoid off",
          _gse.lbl_switch.text() == "solenoid off - switch released"
          and _style.GRAY in _gse.dot_switch.styleSheet(),
          f"{_gse.lbl_switch.text()} / {_gse.dot_switch.styleSheet()}")
    # A drive slower than the 1 Hz sample cannot be judged from one packet:
    # grey with the reason, not a red that would blame the sampling on the
    # solenoid. 0.2 Hz: the plunger holds each level for 2.5 s.
    _gse._membrane_hz = 0.2
    _gse.refresh()
    _tx.sendto(_Frame(type=_Pkt.HK,
                      payload=_hk.Housekeeping(state=_hk.SeqState.STANDBY,
                                               membrane_duty=50).pack(),
                      seq=4).stamp().encode(), ("127.0.0.1", _rx.port))
    for _ in range(60):
        app.processEvents()
        QtCore.QThread.msleep(5)
    _gse.refresh()
    app.processEvents()
    check("flight: a drive too slow to sample is grey, not red",
          _gse.lbl_switch.text()
          == ("driving 50 % at 0.2 Hz - too slow to judge from 1 Hz HK, "
              "switch released")
          and _style.GRAY in _gse.dot_switch.styleSheet(),
          f"{_gse.lbl_switch.text()} / {_gse.dot_switch.styleSheet()}")
    _gse._membrane_hz = _MHZ_DEF
    _tx.close()

    # -- Ethernet traffic indicator: the two packets above are on the wire,
    # and the commands earlier in this block went out on the uplink ---------
    _win.traffic.refresh()
    app.processEvents()
    check("traffic: the Down lane counted the telemetry that arrived",
          _win.traffic.lane_down.total == _rx.rx_bytes
          and _win.traffic.lane_down.total > 0,
          f"lane={_win.traffic.lane_down.total} rx={_rx.rx_bytes}")
    check("traffic: the Up lane counted the commands that left",
          _win.traffic.lane_up.total >= _commander.tx_bytes > 0,
          f"lane={_win.traffic.lane_up.total} tx={_commander.tx_bytes}")
    check("traffic: a mock detector is not Ethernet, so the Bench lane is idle",
          _win.traffic.lane_bench.state == "none"
          and _win.traffic._totals["Bench"].text() == "-")
    check("traffic: the far end of the uplink is named",
          _win.traffic.lbl_peer.text() == _commander.peer,
          _win.traffic.lbl_peer.text())
    # A link that has gone silent must not keep showing the last light it had:
    # the lane is polled with a stamp far past SILENT_S rather than by waiting.
    import time as _time
    _win.traffic.lane_down.poll(_time.time() + 3600)
    check("traffic: a silent link goes red, not idle",
          _win.traffic.lane_down.state == "silent"
          and _style.RED in _win.traffic.lane_down.colour)

    # A raising slot aborts the whole process under PyQt5, so the listen-only
    # path must report instead of raise.
    _gse._cmd = None
    _gse._membrane_start()
    _gse._membrane_stop()
    _gse._disperse()
    _gse._motor_start()
    _gse._motor_stop()
    check("flight: actuators survive a missing command link",
          _gse.lbl_act_status.text() == "no command link", _gse.lbl_act_status.text())
    # Pixel regression: every button in the Commands box is one width. Three
    # different widths used to share that box (a full row, a part-filled row,
    # and the release pair), which reads as a broken layout.
    app.processEvents()
    # The command block must fit its 340 px sidebar column, whose horizontal
    # scrollbar is off: pinning its columns to the widest label once pushed
    # the far button (and the rest of the sidebar) off the visible edge.
    _sa = _win.findChild(QtWidgets.QScrollArea)
    check("flight: the sidebar is not clipped horizontally",
          _sa.widget().width() <= _sa.viewport().width(),
          f"contents {_sa.widget().width()} vs viewport "
          f"{_sa.viewport().width()}")
    # The sidebar packs into columns instead of scrolling: with the default
    # sections open it must fit the height of the window, because the failure
    # being fixed is an operator who cannot see the command they sent and the
    # housekeeping that answers it at the same time. Driven with an explicit
    # budget rather than the window's, since the offscreen platform reports an
    # 800x600 screen and the column cap is sized from the real one.
    _budget = 760
    _win.flow.relayout(_budget, 3 * 340 + 2 * 12)
    app.processEvents()
    _colh = _win.flow.column_heights()
    check("sidebar: the open sections fit without scrolling",
          bool(_colh) and max(_colh) <= _budget,
          f"{_win.flow.columns} columns, tallest {max(_colh) if _colh else 0} "
          f"of {_budget} px")
    _placed = [_l.itemAt(_i).widget() for _l in _win.flow._cols
               for _i in range(_l.count())
               if _l.itemAt(_i).widget() is not None]
    check("sidebar: every section is placed exactly once",
          len(_placed) == len(set(map(id, _placed))) == len(_win.flow._items)
          and all(_s in _placed for _s in _win._sections),
          f"{len(_placed)} placed of {len(_win.flow._items)}, columns {_colh}")
    # A tall screen gets one column and gives the width back to the spectrum.
    _win.flow.relayout(4000, 3 * 340 + 2 * 12)
    check("sidebar: a tall window uses one column",
          _win.flow.columns == 1, f"{_win.flow.columns} columns")
    _win._reflow_panel()
    app.processEvents()

    _rows = {}
    for _b in _gse._cmd_buttons:
        _rows.setdefault(_b.y(), []).append(_b.width())
    # Uniform within a row, which is what reads as a tidy block; the release
    # pair is deliberately wider (it spans 3 of 6 columns, not 2).
    check("flight: command buttons are even across each row",
          all(max(r) - min(r) <= 8 for r in _rows.values()),
          str({y: sorted(r) for y, r in _rows.items()}))

    # The release confirmation must not ask about something it will refuse.
    _dialogs = []
    _real_question = QtWidgets.QMessageBox.question
    QtWidgets.QMessageBox.question = staticmethod(
        lambda *a, **k: _dialogs.append(a[2]) or QtWidgets.QMessageBox.Yes)
    try:
        _gse._cmd = _commander
        _commander.flight_mode = False
        _gse._release(1)
        check("flight: checks the interlock before the confirm dialog",
              _dialogs == []
              and "interlock" in _gse.lbl_cmd_status.text().lower(),
              f"{_dialogs} / {_gse.lbl_cmd_status.text()}")
        _commander.flight_mode = True
        _gse._release(1)
        check("flight: still confirms a release it will send",
              len(_dialogs) == 1, str(_dialogs))
    finally:
        QtWidgets.QMessageBox.question = _real_question
        _commander.flight_mode = False

    # Events are named, not numbered: `[1] 12: membrane on` told an operator
    # nothing. EventCode 0x0C is MANUAL_DRIVE.
    _tx2 = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    _tx2.sendto(_Frame(type=_Pkt.EVENT,
                       payload=_pack_event(0x0C, 0, "membrane on"),
                       seq=0).stamp().encode(), ("127.0.0.1", _rx.port))
    for _ in range(60):
        app.processEvents()
        QtCore.QThread.msleep(5)
    _gse.refresh()
    app.processEvents()
    _items = [_gse.event_list.item(i).text()
              for i in range(_gse.event_list.count())]
    check("flight: names event codes", any("MANUAL_DRIVE" in t for t in _items),
          str(_items))
    _tx2.close()

    # A sensor field with no part behind it must never render as a number.
    # Every one of these is zero-filled by the MCU, and "0.0 C" is
    # indistinguishable from a real reading - which is the whole failure this
    # project has already been bitten by.
    import clouds_ui.flight as _fl
    _unsourced = _hk.Housekeeping(
        state=_hk.SeqState.STANDBY, p_amb_pa=99248,
        bme_temp_cc=3422, rh1_cpct=2993,
        error_flags=_hk.HkErrors.IMU_FAIL | _hk.HkErrors.NO_TEMP)
    _gse._refresh_sensors(_unsourced)
    _texts = {n: _gse._sensor_labels[n].text()
              for n, _p, _f, _fg in _fl.SENSOR_FIELDS}
    check("flight: unsourced sensors show no number",
          not any(any(c.isdigit() for c in _texts[n])
                  for n in ("Accel", "Gyro")),
          str(_texts))
    # A part that is not part of the experiment gets no row at all - the
    # STLM20 pair that was never populated. A row that can only ever say
    # "not populated" sends an operator looking for a part to fit;
    # HKE_NO_TEMP in the Errors row is the honest declaration.
    check("flight: rows for parts that are off the design are gone",
          not any(n.startswith("T1") or n.startswith("T2")
                  for n, _p, _f, _fg in _fl.SENSOR_FIELDS),
          str([n for n, _p, _f, _fg in _fl.SENSOR_FIELDS]))
    # The Chamber rows ARE back, and they are not the Keller 23SY rows
    # returning: they come from a second BME280 on SPI_1, a part that
    # answers, so the rule above is not violated by them. The part column
    # has to say which bus, or two identical BME280s are indistinguishable
    # on screen when one of them fails.
    _chm = {n: _p for n, _p, _f, _fg in _fl.SENSOR_FIELDS
            if n.startswith("Chamber")}
    check("flight: the chamber BME280 has its three rows",
          set(_chm) == {"Chamber p", "Chamber T", "Chamber RH"}
          and all("SPI" in v for v in _chm.values()), str(_chm))
    check("flight: HKE_NO_TEMP is still declared in the Errors row",
          "NO_TEMP" in _unsourced.error_text, _unsourced.error_text)
    check("flight: the BME280 readings are shown, being real",
          _texts["Ambient T"] == "34.2 C"
          and _texts["Ambient p"].startswith("992.5 hPa")
          and _texts["Ambient RH"] == "29.9 %",
          f'{_texts["Ambient T"]} / {_texts["Ambient p"]} / '
          f'{_texts["Ambient RH"]}')

    # The chamber part is on its own bus with its own flag, so it must be
    # possible for exactly one of the two BME280s to go unsourced. Ambient
    # keeps its numbers while the chamber rows say so, and the other way
    # round - a shared flag would have made a chamber part that was never
    # fitted look like the ambient sensor failing, which is the one sensor
    # fault that matters in flight.
    _chm_dead = _hk.Housekeeping(
        p_amb_pa=99248, bme_temp_cc=3422, rh1_cpct=2993,
        chm_temp_cc=2450, chm_rh_cpct=3812, chm_p_pa=98765,
        error_flags=_hk.HkErrors.BME280_CHM_FAIL)
    _gse._refresh_sensors(_chm_dead)
    check("flight: a dead chamber part shows no number and spares ambient",
          not any(c.isdigit()
                  for c in _gse._sensor_labels["Chamber p"].text())
          and _gse._sensor_labels["Ambient T"].text() == "34.2 C",
          f'{_gse._sensor_labels["Chamber p"].text()} / '
          f'{_gse._sensor_labels["Ambient T"].text()}')

    _amb_dead = _hk.Housekeeping(
        chm_temp_cc=2450, chm_rh_cpct=3812, chm_p_pa=98765,
        error_flags=_hk.HkErrors.BME280_FAIL)
    _gse._refresh_sensors(_amb_dead)
    check("flight: a live chamber part is read while ambient is dead",
          _gse._sensor_labels["Chamber T"].text() == "24.5 C"
          and _gse._sensor_labels["Chamber p"].text() == "987.6 hPa"
          and _gse._sensor_labels["Chamber RH"].text() == "38.1 %"
          and not any(c.isdigit()
                      for c in _gse._sensor_labels["Ambient T"].text()),
          f'{_gse._sensor_labels["Chamber T"].text()} / '
          f'{_gse._sensor_labels["Chamber p"].text()} / '
          f'{_gse._sensor_labels["Chamber RH"].text()} / '
          f'{_gse._sensor_labels["Ambient T"].text()}')

    # ...and a held ambient pressure is real data, so it is shown - labelled.
    _stale = _hk.Housekeeping(p_amb_pa=99248,
                              error_flags=_hk.HkErrors.P_AMB_STALE)
    _gse._refresh_sensors(_stale)
    check("flight: a held pressure is shown and marked stale",
          "992.5 hPa" in _gse._sensor_labels["Ambient p"].text()
          and "stale" in _gse._sensor_labels["Ambient p"].text(),
          _gse._sensor_labels["Ambient p"].text())

    # With nothing wrong, every row is a number.
    _ok = _hk.Housekeeping(p_amb_pa=99248, bme_temp_cc=2140,
                           chm_p_pa=98765, chm_temp_cc=2450, chm_rh_cpct=3812,
                           rh1_cpct=3050, accel_mg=(1, -2, 981),
                           gyro_ddps=(0, 1, -1),
                           rail_mv=(24062, _hk.RAIL_MV_INVALID, 5095, 3297),
                           shunt_raw=(514, 0, -40, 6667), error_flags=0,
                           hb_sense_raw=1500)
    _gse._refresh_sensors(_ok)
    check("flight: a fully sourced packet renders every sensor row",
          all(any(c.isdigit() for c in _gse._sensor_labels[n].text())
              for n, _p, _f, _fg in _fl.SENSOR_FIELDS
              if n != "Rail 24 V"),
          str({n: _gse._sensor_labels[n].text()
               for n, _p, _f, _fg in _fl.SENSOR_FIELDS}))

    # The dispersion motor's current sense: amps through the DRV8251A IPROPI
    # chain, `-` from a build with no GP46 - and 0 counts is a reading (idle
    # or coasting), not the sentinel.
    check("flight: the motor sense renders amps",
          _gse._sensor_labels["Motor I"].text() == "0.537A",
          _gse._sensor_labels["Motor I"].text())
    _gse._refresh_sensors(_hk.Housekeeping(hb_sense_raw=0))
    check("flight: an idle motor reads 0 A, not no reading",
          _gse._sensor_labels["Motor I"].text() == "0.000A",
          _gse._sensor_labels["Motor I"].text())
    _gse._refresh_sensors(_hk.Housekeeping())
    check("flight: a build without GP46 shows no motor current reading",
          _gse._sensor_labels["Motor I"].text() == "-",
          _gse._sensor_labels["Motor I"].text())

    # A rail with no monitor must not render as 0.00 V: the 24 V bus reads a
    # genuine 0 mV on a USB-powered bench, so a dead monitor and a dead rail
    # have to stay distinguishable.
    _rails = _hk.Housekeeping(rail_mv=(_hk.RAIL_MV_INVALID,
                                       _hk.RAIL_MV_INVALID, 0, 3298),
                              shunt_raw=(0, 0, 0, 6667),
                              error_flags=_hk.HkErrors.RAIL_FAIL)
    _gse._refresh_sensors(_rails)
    check("flight: an unmonitored rail shows no voltage or current",
          _gse._sensor_labels["Rail V_in"].text() == "no monitor",
          _gse._sensor_labels["Rail V_in"].text())
    # A rail with no INA226 on the board is not a fault to chase: it says so
    # in its own words, and never "no monitor", which reads as a dead part.
    check("flight: the unfitted 24 V rail reads as not fitted",
          _gse._sensor_labels["Rail 24 V"].text() == "not fitted",
          _gse._sensor_labels["Rail 24 V"].text())
    check("flight: a rail that is genuinely down still reads 0.00 V",
          _gse._sensor_labels["Rail 5 V"].text() == " 0.00 V   +0.000 A",
          _gse._sensor_labels["Rail 5 V"].text())
    # 6667 counts x 2.5 uV = 16.667 mV over the 3.3 V rail's 50 mOhm shunt
    check("flight: a live rail reads its voltage and its current",
          _gse._sensor_labels["Rail 3.3 V"].text() == " 3.30 V   +0.333 A",
          _gse._sensor_labels["Rail 3.3 V"].text())
    # A rail feeding current back into its supply is real data, and the sign
    # is the only thing that says so.
    _back = _hk.Housekeeping(rail_mv=(24062, _hk.RAIL_MV_INVALID, 5095, 3298),
                             shunt_raw=(-514, 0, 0, 0))
    _gse._refresh_sensors(_back)
    check("flight: a negative rail current keeps its sign",
          _gse._sensor_labels["Rail V_in"].text() == "24.06 V   -0.129 A",
          _gse._sensor_labels["Rail V_in"].text())

    # -- the housekeeping timeline under the spectrum ----------------------
    # The lower half of the view. What is checked here is the split (the
    # overlay cards must still belong to the spectrum pane, not float over
    # the timeline), the sampling rule (one point per packet, not one per
    # tick), and that the Sensors section's "no number without a sensor"
    # rule survives being turned into a line.
    import clouds_ui.timeline as _tl
    check("timeline: the view is split, spectrum over history",
          _win.timeline is not None
          and _win._view is not _win.timeline
          and _win.stats_box.parent() is _win._view
          and _win.timeline.parent() is _win._view.parent(),
          f"pane {_win._view.height()} px / timeline {_win.timeline.height()} px")
    # The flight tick is the only thing that feeds it - the receiver's thread
    # must never touch Qt - so a packet that reached the sidebar must have
    # reached the buffer too.
    check("timeline: the flight tick records housekeeping",
          len(_win.tl_buf) > 0, f"{len(_win.tl_buf)} samples")
    _win._clear_timeline()

    # The flight tick runs at 2 Hz against a 1 Hz stream. Polling it twice
    # for the same packet must record one point: two would halve the real
    # span of every window the operator picks.
    _rx.last_hk = _hk.Housekeeping(p_amb_pa=99248, bme_temp_cc=2140,
                                   rh1_cpct=3050,
                                   rail_mv=(24062, _hk.RAIL_MV_INVALID,
                                            5095, 3298),
                                   shunt_raw=(514, 0, -40, 660))
    _rx.last_hk_time = 5000.0
    _win._sample_timeline()
    _win._sample_timeline()
    check("timeline: one point per packet, not one per tick",
          len(_win.tl_buf) == 1, f"{len(_win.tl_buf)} samples")
    for _i in range(1, 30):
        _rx.last_hk_time = 5000.0 + _i
        _win._sample_timeline()
    _x, _cols = _win.tl_buf.window(["p_amb", "rail_v0"], None)
    check("timeline: records the series it drew",
          _x.size == 30 and abs(_cols["p_amb"][-1] - 992.48) < 0.01
          and abs(_cols["rail_v0"][-1] - 24.062) < 0.001,
          f"{_x.size} pts, p={_cols['p_amb'][-1]:.2f} hPa, "
          f"v={_cols['rail_v0'][-1]:.3f} V")

    # A dropout is a gap. A straight line across a link outage claims ground
    # knows what happened during it.
    _rx.last_hk_time = 5100.0
    _win._sample_timeline()
    _x, _cols = _win.tl_buf.window(["p_amb"], None)
    check("timeline: a dropout breaks the trace",
          _x.size == 32 and np.isnan(_cols["p_amb"][-2])
          and not np.isnan(_cols["p_amb"][-1]),
          f"{_x.size} pts")

    # An unsourced field must not become a line at zero - the same failure
    # the Sensors section guards, one axis further on.
    _rx.last_hk = _hk.Housekeeping(
        accel_mg=(0, 0, 0), gyro_ddps=(0, 0, 0),
        error_flags=_hk.HkErrors.IMU_FAIL)
    _rx.last_hk_time = 5200.0
    _win._sample_timeline()
    _x, _cols = _win.tl_buf.window(["acc_x", "gyr_z"], None)
    check("timeline: an unsourced field is a gap, never a zero",
          all(np.isnan(_cols[k][-1]) for k in ("acc_x", "gyr_z")),
          str({k: float(v[-1]) for k, v in _cols.items()}))
    check("timeline: the STLM20 pair is not offered either",
          not any(k in _win._tl_boxes for k in ("t1", "t2"))
          and not any("STLM20" in s.group for s in _tl.SERIES),
          str(sorted({s.group for s in _tl.SERIES})))

    # A part the carrier does not have cannot be selected at all.
    check("timeline: the unfitted 24 V rail cannot be toggled on",
          not _win._tl_boxes["rail_v1"].isEnabled()
          and not _win._tl_boxes["rail_i1"].isEnabled()
          and _win._tl_boxes["rail_v0"].isEnabled())

    # Toggling a box reaches the plot, and every unit that is selected gets
    # its own axis rather than sharing a scale with amps.
    for _k in ("rh1", "rail_v0", "rail_i0"):
        _win._tl_boxes[_k].setChecked(True)
    app.processEvents()
    _sel = set(_win.timeline.selected)
    _units = {_tl.SERIES_BY_KEY[k].unit for k in _sel}
    check("timeline: the checkboxes drive the plot",
          _sel == {"p_amb", "bme_t", "rh1", "rail_v0", "rail_i0"}
          and _units == {"hPa", "C", "%", "V", "A"},
          f"{sorted(_sel)} over {sorted(_units)}")
    _win._tl_boxes["rh1"].setChecked(False)
    app.processEvents()
    check("timeline: unticking removes the series",
          "rh1" not in _win.timeline.selected)

    for _i in range(len(_tl.WINDOWS)):
        _win.cmb_tl_window.setCurrentIndex(_i)
        app.processEvents()
        if _win.timeline.plot.pixmap() is None:
            break
    check("timeline: every span renders",
          _win.timeline.window_s is _tl.WINDOWS[-1][1]
          and _win.timeline.plot.pixmap() is not None
          and not _win.timeline.plot.pixmap().isNull(),
          f"span {_win.timeline.window_s}")
    _win.cmb_tl_window.setCurrentIndex(1)

    # Nothing selected is a legible state, not a crash or a blank panel.
    _was = list(_win.timeline.selected)
    for _k in _was:
        _win._tl_boxes[_k].setChecked(False)
    app.processEvents()
    check("timeline: an empty selection still draws",
          _win.timeline.selected == []
          and _win.timeline.plot.pixmap() is not None
          and not _win.timeline.plot.pixmap().isNull())
    for _k in _was:
        _win._tl_boxes[_k].setChecked(True)
    app.processEvents()

    _win._clear_timeline()
    check("timeline: Clear drops the history",
          len(_win.tl_buf) == 0 and _win._tl_last_t == 0.0)
    _rx.last_hk_time = 5300.0
    _win._sample_timeline()
    check("timeline: it records again after a clear", len(_win.tl_buf) == 1)

    # Cursor readout on a downlink trace. A quick-look is ~30 binned points
    # per channel, not one per pixel: reading it at a pixel offset into the
    # channel window walked off the end of the array and took the window down
    # with it (IndexError inside an event filter aborts the process).
    _ch1, _ch2 = _win.cal.by_role("measurement"), _win._ref()
    _rx.quicklook = {
        0: {"channel": 0, "bin": 8, "exposure_ms": 5.0,
            "counts": [1000 + 10 * i for i in range(29)]},
        1: {"channel": 1, "bin": 8, "exposure_ms": 5.0,
            "counts": [2000 - 10 * i for i in range(31)]},
    }
    _win.source = "downlink"
    _win._take_downlink_frame()
    app.processEvents()
    check("downlink: a quick-look draws as ~30 binned points per channel",
          _win.last_proc is not None and _win.last_proc["m"].size == 29
          and _win.last_proc["r"].size == 31,
          str(None if _win.last_proc is None
              else {k: v.size for k, v in _win.last_proc.items()}))
    _swept = 0
    for _axis in ("nm", "pixel"):
        _win.axis = _axis
        _win._render_plot()
        app.processEvents()
        for _fx in range(0, _win._view.width(), 7):
            _win._cursor_readout(QtCore.QPoint(_fx, _win._view.height() // 2))
            _swept += 1
    check("downlink: the cursor readout survives the whole plot width",
          _swept > 0 and _win.cursor_lbl.text() != "",
          f"{_swept} positions, last {_win.cursor_lbl.text()!r}")
    _win.axis = "nm"

    _gse.sec_sensors.set_open(True)
    app.processEvents()
    _win.grab().save("output/qt_merged_flight.png")

    # -- Restart: everything live comes back, the window does not go away ---
    # The flight half is rebuilt from a factory, as main() hands the window
    # one; here it hands out a fresh receiver on loopback and a fresh
    # commander to the same command server, so the restart can be watched
    # from both ends.
    class _Links:
        pass

    _rebuilt = []

    def _factory():
        L = _Links()
        L.receiver = _Receiver(bind="127.0.0.1", port=0)
        L.receiver.start()
        L.commander = _Commander("127.0.0.1", _server.port, timeout=2.0)
        L.session = _SessionLog("output", stamp="verify_gse_restart")
        L.mock_stack = None
        _rebuilt.append(L)
        return L

    _win._link_factory = _factory
    _old_rx, _old_cmd, _old_session = _win.rx, _win.commander, _win.session
    _gse._cmd = _old_cmd                    # put the link back the earlier check took away
    _gse.chk_flight_mode.setChecked(True)
    _win.rb_downlink.setChecked(True)
    app.processEvents()
    _win.restart()
    app.processEvents()
    check("restart: the window is still open", _win.isVisible())
    check("restart: the flight half was rebuilt once", len(_rebuilt) == 1)
    check("restart: the window holds the new receiver",
          _win.rx is _rebuilt[0].receiver and _win.rx is not _old_rx)
    check("restart: the flight sections follow the new receiver",
          _gse._rx is _win.rx and _gse._cmd is _win.commander)
    check("restart: the old receiver's socket is closed",
          _old_rx._sock.fileno() == -1)
    check("restart: the old command link is closed", not _old_cmd.connected)
    check("restart: the old session wrote its summary",
          os.path.isfile("output/session_verify_gse_summary.json"))
    check("restart: the new session logs to its own file",
          _win.session.hk_path != _old_session.hk_path)
    check("restart: the event list and readouts start over",
          _gse.event_list.count() == 0 and _gse.banner.text() == "NO TELEMETRY"
          and _gse._hk_labels["Membrane"].text() == "-"
          and _gse.lbl_switch.text() == "switch: no telemetry")
    check("restart: the interlock setting survives and reaches the new link",
          _gse.chk_flight_mode.isChecked() and _win.commander.flight_mode)
    check("restart: the flight tick is running again", _win.flight_timer.isActive())
    check("restart: the traffic counters start over on the new links",
          _win.traffic._rx is _win.rx and _win.traffic._cmd is _win.commander
          and _win.traffic.lane_down.total == 0,
          f"total={_win.traffic.lane_down.total}")
    check("restart: a downlink source stays on the downlink",
          _win.source == "downlink" and _win.rb_downlink.isChecked())
    # New housekeeping lands in the new receiver and is rendered: the proof
    # that the rebuilt chain is wired end to end, not merely swapped in.
    _tx2 = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    _tx2.sendto(_Frame(type=_Pkt.HK,
                       payload=_hk.Housekeeping(state=_hk.SeqState.STANDBY,
                                                membrane_duty=35).pack(),
                       seq=0).stamp().encode(), ("127.0.0.1", _win.rx.port))
    for _ in range(60):
        app.processEvents()
        QtCore.QThread.msleep(5)
    _gse.refresh()
    app.processEvents()
    check("restart: housekeeping flows through the new receiver",
          _gse._hk_labels["Membrane"].text() == "35 %  pushed, not cycling",
          _gse._hk_labels["Membrane"].text())
    check("restart: the switch light judges the new packet",
          _gse.lbl_switch.text()
          == "driving 35 % - plunger NOT cycling, switch stuck released"
          and _style.RED in _gse.dot_switch.styleSheet(),
          f"{_gse.lbl_switch.text()} / {_gse.dot_switch.styleSheet()}")
    _tx2.close()
    check("restart: the button is usable again", _win.btn_restart.isEnabled())
finally:
    _commander.close()
    _server.stop()
    _rx.stop()
    for L in _rebuilt:
        L.commander.close()
        L.receiver.stop()
        L.session.close()


# -- Restart on the bench window: the detector is re-opened and live resumes,
# with the operator's settings intact --------------------------------------
_old_driver = win.driver
win.sp_exp.setValue(7)
win._connect()
app.processEvents()
win.restart()
app.processEvents()
check("restart: a new driver is opened", win.driver is not _old_driver)
check("restart: the detector reconnects and goes live", win.connected and win.running,
      f"connected={win.connected} running={win.running}")
check("restart: the exposure setting is kept", abs(win.exposure_ms - 7) < 1e-6,
      str(win.exposure_ms))
check("restart: no downlink stays no downlink", win.rx is None
      and not win.rb_downlink.isEnabled())
win._stop()
win._single()
app.processEvents()
check("restart: the new driver delivers frames",
      win.last_frame is not None and win.last_frame.shape == (2048,))

if "--live" in sys.argv:
    print("\n-- live hardware through the full UI (real EURECA Duo) --")
    lwin = clouds_ui_window.CloudsWindow(mock=False)
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
