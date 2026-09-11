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

import numpy as np
from PyQt5 import QtCore, QtWidgets


def _qt_msg(mode, ctx, msg):
    print(f"QT[{mode}]: {msg}", flush=True)


QtCore.qInstallMessageHandler(_qt_msg)
from clouds_ui import window as clouds_ui_window

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

_mcu = {"duty": 0, "valves": 0, "hz": 0, "log": []}


def _forward(cmd, key, value):
    """Stands in for the RP2350: its own acceptance rules are tested in
    flight/mcu/test, so this only acks and reflects the drive into HK."""
    _mcu["log"].append((int(cmd), key, value))
    if cmd == _Cmd.MEMBRANE:
        _mcu["duty"] = key
    elif cmd == _Cmd.DISPERSE:
        _mcu["valves"] = int(_hk.ValveStatus.DISPERSE)
    elif cmd == _Cmd.SET_PARAM and key == _Param.MEMBRANE_HZ:
        _mcu["hz"] = value
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
    _gse.sp_hz.setValue(3)
    _gse._membrane_start()
    check("flight: membrane drive reaches the link",
          _mcu["log"] == [(int(_Cmd.SET_PARAM), int(_Param.MEMBRANE_HZ), 3),
                          (int(_Cmd.MEMBRANE), 70, 0)], str(_mcu["log"]))
    check("flight: frequency is set before the drive starts", _mcu["hz"] == 3)
    _mcu["log"].clear()
    _gse._membrane_stop()
    check("flight: Stop commands duty 0",
          _mcu["log"] == [(int(_Cmd.MEMBRANE), 0, 0)] and _mcu["duty"] == 0,
          str(_mcu["log"]))
    _mcu["log"].clear()
    _gse._disperse()
    check("flight: motor button asks for one pulse",
          _mcu["log"] == [(int(_Cmd.DISPERSE), 1, 0)], str(_mcu["log"]))

    # housekeeping feedback: without it a 5 s pulse is invisible to ground
    import socket as _socket
    _tx = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    _tx.sendto(_Frame(type=_Pkt.HK,
                      payload=_hk.Housekeeping(state=_hk.SeqState.STANDBY,
                                               membrane_duty=70,
                                               valve_status=_mcu["valves"]
                                               ).pack(),
                      seq=0).stamp().encode(), ("127.0.0.1", _rx.port))
    for _ in range(60):
        app.processEvents()
        QtCore.QThread.msleep(5)
    _gse.refresh()
    app.processEvents()
    check("flight: renders the commanded drive",
          _gse._hk_labels["Membrane"].text() == "70 %"
          and _gse._hk_labels["Driving"].text() == "DISPERSE",
          f'{_gse._hk_labels["Membrane"].text()} / '
          f'{_gse._hk_labels["Driving"].text()}')
    _tx.close()

    # A raising slot aborts the whole process under PyQt5, so the listen-only
    # path must report instead of raise.
    _gse._cmd = None
    _gse._membrane_start()
    _gse._membrane_stop()
    _gse._disperse()
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
    # Keller 23SY pair, and the STLM20 pair that was never populated. A row
    # that can only ever say "not populated" sends an operator looking for a
    # part to fit; HKE_NO_TEMP in the Errors row is the honest declaration.
    check("flight: rows for parts that are off the design are gone",
          not any(n.startswith("Chamber") or n.startswith("T1")
                  for n, _p, _f, _fg in _fl.SENSOR_FIELDS),
          str([n for n, _p, _f, _fg in _fl.SENSOR_FIELDS]))
    check("flight: HKE_NO_TEMP is still declared in the Errors row",
          "NO_TEMP" in _unsourced.error_text, _unsourced.error_text)
    check("flight: the BME280 readings are shown, being real",
          _texts["Ambient T"] == "34.2 C"
          and _texts["Ambient p"].startswith("992.5 hPa")
          and _texts["Ambient RH"] == "29.9 %",
          f'{_texts["Ambient T"]} / {_texts["Ambient p"]} / '
          f'{_texts["Ambient RH"]}')

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
                           rh1_cpct=3050, accel_mg=(1, -2, 981),
                           gyro_ddps=(0, 1, -1),
                           rail_mv=(24062, _hk.RAIL_MV_INVALID, 5095, 3297),
                           shunt_raw=(514, 0, -40, 6667), error_flags=0)
    _gse._refresh_sensors(_ok)
    check("flight: a fully sourced packet renders every sensor row",
          all(any(c.isdigit() for c in _gse._sensor_labels[n].text())
              for n, _p, _f, _fg in _fl.SENSOR_FIELDS
              if n != "Rail 24 V"),
          str({n: _gse._sensor_labels[n].text()
               for n, _p, _f, _fg in _fl.SENSOR_FIELDS}))

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
finally:
    _commander.close()
    _server.stop()
    _rx.stop()


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
