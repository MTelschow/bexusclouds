"""CLOUDS Spectral Engine - ground-test / bench software for the EURECA Duo.

Qt control panel + live dual-trace spectrum view (measurement Ch1 / reference
Ch2 on one detector). Adopts the CLOUDS design language from the Raytracing
Engine (docs/UI_STYLE.md). Talks only to spectro.driver.SpectrometerDriver, so
``--mock`` runs the whole UI with no hardware.

    python clouds_spectral.py            # real EURECA Duo on this machine
    python clouds_spectral.py --edu      # real EURECA e9u_LSMD_EDU (single channel)
    python clouds_spectral.py --mock     # synthetic Duo
    python clouds_spectral.py --net 192.168.100.10
                                        # Duo on the flight Pi, live over the
                                        # cable (run spectro.net_server there)
"""
from __future__ import annotations

import os
import sys
import threading

import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from PyQt5 import QtCore, QtGui, QtWidgets

from spectro.calibration import Calibration, subtract_dark
from spectro.driver import DriverError, open_driver, resolve_kind
from spectro import processing as P

HERE = os.path.dirname(os.path.abspath(__file__))
NAVY = "#01386a"
VERSION = "0.1.0"

# Default frame averaging. Tuned for the CURRENT bench cable: a ~5 m passive USB run
# corrupts ~7% of pixels/frame to a fixed glitch code, and the median only fully
# rejects that once it has a quorum. Measured (docs/DEVLOG.md): flat-region noise is
# ~2860 ct at navg 4 but collapses to ~9 ct (read-noise floor) at navg 8 - a ~900x
# drop. So 8 is the right default HERE. On a healthy short cable the glitch is gone
# and the normal default of 4 (or less) is fine - revert this one number.
NAVG_DEFAULT = 8
C_MEAS = NAVY
C_REF = "#4d8fd1"
C_TRANS = "#1D9E75"
C_ABS = "#b0413e"

# Per-kind default calibration. The EDU board is single-fibre / 3648 px, so the
# Duo's two-window calibration.json would slice a phantom reference channel out
# of it. An explicit CLOUDS_CALIBRATION (or the Calibrate dialog's Load...)
# still wins - Calibration.load(None) reads the env var first.
_CAL_BY_KIND = {"edu": "calibration_edu.json"}


def _default_calibration(kind: str) -> str | None:
    name = _CAL_BY_KIND.get(kind)
    if not name or os.environ.get("CLOUDS_CALIBRATION"):
        return None                       # None -> env var, else calibration.json
    path = os.path.join(HERE, name)
    return path if os.path.exists(path) else None


# --------------------------------------------------------------------- widgets
def _wl_rgb(nm):
    """Approximate sRGB for a wavelength [nm]; dim gray outside the visible."""
    if nm < 380:
        return (90, 60, 110)
    if nm > 780:
        return (96, 88, 84)
    if nm < 440:
        r, g, b = -(nm - 440) / 60.0, 0.0, 1.0
    elif nm < 490:
        r, g, b = 0.0, (nm - 440) / 50.0, 1.0
    elif nm < 510:
        r, g, b = 0.0, 1.0, -(nm - 510) / 20.0
    elif nm < 580:
        r, g, b = (nm - 510) / 70.0, 1.0, 0.0
    elif nm < 645:
        r, g, b = 1.0, -(nm - 645) / 65.0, 0.0
    else:
        r, g, b = 1.0, 0.0, 0.0
    if nm < 420:
        f = 0.3 + 0.7 * (nm - 380) / 40.0
    elif nm > 700:
        f = 0.3 + 0.7 * (780 - nm) / 80.0
    else:
        f = 1.0
    return tuple(int(255 * (c * f) ** 0.8) for c in (r, g, b))


class _OverlayFrame(QtWidgets.QFrame):
    """Rounded overlay box that never leaves unpainted corners (the corner
    pixels are filled with the scene background colour)."""

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor("#e9eef4"))
        path = QtGui.QPainterPath()
        path.addRoundedRect(0.5, 0.5, self.width() - 1.0, self.height() - 1.0, 8, 8)
        p.fillPath(path, QtGui.QColor("#eef3f8"))
        p.setPen(QtGui.QPen(QtGui.QColor("#d3dde6"), 1))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawPath(path)
        p.end()


class _AcquisitionWorker(QtCore.QThread):
    """Runs one tick's blocking driver I/O off the GUI thread.

    Against the local/exclusive driver, ``grab()`` returns in milliseconds and
    this is overkill. Against ``--net`` in bench-stream mode it blocks for up
    to a second per call, paced to the FSW's cadence (bench_stream.py's
    ``wait_for_new``); calling that straight from the 60 ms QTimer slot froze
    the whole window between frames.
    """
    done = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.done.emit(result)


def _fig_to_pixmap(fig):
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    w, h = canvas.get_width_height()
    data = bytes(canvas.buffer_rgba())          # keep alive until the pixmap owns a copy
    img = QtGui.QImage(data, w, h, QtGui.QImage.Format_RGBA8888)
    return QtGui.QPixmap.fromImage(img.copy())


# ----------------------------------------------------------------------- engine
class Engine(QtWidgets.QMainWindow):
    def __init__(self, mock=False, kind=None, host=None):
        super().__init__()
        self.setWindowTitle("CLOUDS Spectral Engine")
        ico = os.path.join(HERE, "assets", "clouds.ico")
        if os.path.exists(ico):
            self.setWindowIcon(QtGui.QIcon(ico))
        screen = QtWidgets.QApplication.primaryScreen()
        max_h = screen.availableGeometry().height() if screen else 920
        self.resize(1420, min(920, max_h))
        self.futura = self._load_futura()

        self.kind = resolve_kind(kind)
        self.cal = Calibration.load(_default_calibration(self.kind))
        extra = {"host": host} if self.kind == "net" else {}
        self.driver = open_driver(mock=mock, kind=self.kind, **extra)
        self.mock = mock
        self.connected = False
        self.info = None
        self.running = False
        self._driver_lock = threading.RLock()   # serializes driver I/O vs. the live-tick worker
        self._acq_worker = None

        # acquisition state
        self.exposure_ms = 10.0
        # NAVG_DEFAULT's median rejects a physical bench-cable glitch that has no
        # counterpart over the network - on "net" each grab() already paces to the
        # FSW's own cadence (bench_stream.py), so multiplying it by navg only adds
        # multi-second delay for no noise benefit.
        self.navg = 1 if self.kind == "net" else NAVG_DEFAULT
        self.clean = True           # glitch filter (median + spike despike); off = raw sensor data
        self.axis = "nm"            # "nm" | "pixel"
        self.view = "counts"        # "counts" | "transmission" | "absorbance"
        self.show_peak = True       # vertical peak marker + readout on the spectrum
        self.dark = None
        self.subtract_dark_flag = False
        self.reference_proc = None      # captured no-sample baseline (per channel)
        self.flat = False               # divide by the stored reference (flat-field)
        self.smooth_win = 0             # smoothing window (0 = off)
        self.smooth_mode = "savgol"
        self.yscale = "linear"          # linear | log
        self.x_lo = None                # zoom window in nm (None = full range)
        self.x_hi = None
        self._frame_n = 0
        self._fps = 0.0
        self._t_prev = None
        self.offset_mode = "none"       # none | minimum | darkpixels
        self._dark_value = None
        self._last_fc = None
        self._dropped = 0
        self._applied_us = None
        self.last_frame = None
        self.last_proc = None
        self._geom = None           # plot axes geometry, for mapping cursor -> data
        self._cal_cb = None         # plot-click callback while calibrating
        self._last_sat = 0.0
        self._last_glitch = 0.0
        self._last_peak = 0.0           # brightest channel, despiked, raw counts (for tracking)
        self._peak_nm = 550.0
        self._track = False             # continuous auto-exposure servo (follows a changing scene)
        self._track_msg = ""            # transient too-dim / too-bright note from the servo
        self._oob_count = 0             # consecutive out-of-band ticks (servo persistence gate)
        self.logger = None

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._tick_live)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        lay = QtWidgets.QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_view(), 1)
        lay.addWidget(self._build_panel(), 0)
        self._render_plot()
        self._update_stats()
        self._set_hint("press Connect, then Run")

    # ----------------------------------------------------------- branding bits
    def _load_futura(self):
        path = os.path.join(HERE, "assets", "Futura-Bold.ttf")
        if os.path.exists(path):
            fid = QtGui.QFontDatabase.addApplicationFont(path)
            fams = QtGui.QFontDatabase.applicationFontFamilies(fid)
            if fams:
                return fams[0]
        for cand in ("Futura", "Century Gothic"):
            if cand in QtGui.QFontDatabase().families():
                return cand
        return "Arial"

    def _logo_pixmap(self, width):
        """Crisp CLOUDS wordmark: render the SVG via QtSvg (vector); PNG fallback."""
        svg = os.path.join(HERE, "assets", "clouds_logo.svg")
        if os.path.exists(svg):
            try:
                from PyQt5 import QtSvg
                r = QtSvg.QSvgRenderer(svg)
                if r.isValid():
                    sz = r.defaultSize()
                    dpr = 2.0                       # render at 2x for HiDPI crispness
                    h = max(1, round(width * sz.height() / sz.width()))
                    pm = QtGui.QPixmap(round(width * dpr), round(h * dpr))
                    pm.fill(QtCore.Qt.transparent)
                    painter = QtGui.QPainter(pm)
                    r.render(painter)
                    painter.end()
                    pm.setDevicePixelRatio(dpr)
                    return pm
            except Exception:
                pass
        png = os.path.join(HERE, "assets", "clouds_logo.png")
        if os.path.exists(png):
            pm = QtGui.QPixmap(png)
            if not pm.isNull():
                return pm.scaledToWidth(width, QtCore.Qt.SmoothTransformation)
        return QtGui.QPixmap()

    def _heading(self, txt):
        lab = QtWidgets.QLabel(txt.upper())
        lab.setStyleSheet("color:#8a97a3; font-size:10px; letter-spacing:3px;")
        return lab

    # --------------------------------------------------------------- left view
    def _build_view(self):
        view = QtWidgets.QWidget()
        view.setStyleSheet("background:#eef3f8;")
        self._view = view
        self.plot = QtWidgets.QLabel(view)
        self.plot.setAlignment(QtCore.Qt.AlignCenter)
        self.plot.setStyleSheet("background:transparent;")
        v = QtWidgets.QVBoxLayout(view)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.plot)

        # floating stats card (top-left), engine style
        self.stats_box = _OverlayFrame(view)
        sb = QtWidgets.QVBoxLayout(self.stats_box)
        sb.setContentsMargins(12, 8, 12, 10)
        sb.setSpacing(4)
        cap = QtWidgets.QLabel("LIVE")
        cap.setStyleSheet("color:#8a97a3; font-size:9px; letter-spacing:2px;"
                          "border:0; background:transparent;")
        sb.addWidget(cap)
        self.stats = QtWidgets.QLabel("")
        self.stats.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.stats.setStyleSheet(
            f"color:{NAVY}; font-family:Consolas,monospace; font-size:12px;"
            "font-weight:bold; border:0; background:transparent;")
        sb.addWidget(self.stats)
        self.stats_box.move(16, 16)

        # cursor readout card (top-right), updates on hover over the spectrum
        self.cursor_box = _OverlayFrame(view)
        cb = QtWidgets.QVBoxLayout(self.cursor_box)
        cb.setContentsMargins(12, 8, 12, 10)
        cb.setSpacing(4)
        ccap = QtWidgets.QLabel("CURSOR")
        ccap.setStyleSheet("color:#8a97a3; font-size:9px; letter-spacing:2px;"
                           "border:0; background:transparent;")
        cb.addWidget(ccap)
        self.cursor_lbl = QtWidgets.QLabel("hover the spectrum")
        self.cursor_lbl.setStyleSheet(
            f"color:{NAVY}; font-family:Consolas,monospace; font-size:12px;"
            "font-weight:bold; border:0; background:transparent;")
        cb.addWidget(self.cursor_lbl)
        self.cursor_box.adjustSize()
        self.cursor_box.hide()
        self.plot.setMouseTracking(True)
        self.plot.installEventFilter(self)

        view.installEventFilter(self)
        return view

    def eventFilter(self, obj, ev):
        if obj is getattr(self, "_view", None) and ev.type() == QtCore.QEvent.Resize:
            self.stats_box.adjustSize()
            self.stats_box.move(16, 16)
            self._render_plot()
        elif obj is getattr(self, "plot", None):
            if ev.type() == QtCore.QEvent.MouseMove:
                self._cursor_readout(ev.pos())
            elif ev.type() == QtCore.QEvent.Leave:
                self.cursor_box.hide()
            elif ev.type() == QtCore.QEvent.MouseButtonPress and self._cal_cb is not None:
                dx = self._data_x_at(ev.pos())
                if dx is not None:
                    self._cal_cb(dx)
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------- the sidebar
    def _build_panel(self):
        panel = QtWidgets.QWidget()
        panel.setStyleSheet("background:#ffffff;")
        v = QtWidgets.QVBoxLayout(panel)
        v.setContentsMargins(20, 20, 20, 18)
        v.setSpacing(12)

        logo = QtWidgets.QLabel()
        logo.setStyleSheet("background:transparent;")
        pm = self._logo_pixmap(250)
        if not pm.isNull():
            logo.setPixmap(pm)
        else:                                   # text fallback if no asset is present
            tf = QtGui.QFont(self.futura, 30)
            tf.setBold(True)
            logo.setText("CLOUDS")
            logo.setFont(tf)
            logo.setStyleSheet(f"color:{NAVY}; background:transparent;")
        self.logo_label = logo
        sub = QtWidgets.QLabel(f"Spectral Engine   v{VERSION}")
        sub.setStyleSheet("color:#5a6b7a; font-size:13px;")
        v.addWidget(logo)
        v.addWidget(sub)
        rule = QtWidgets.QFrame()
        rule.setFrameShape(QtWidgets.QFrame.HLine)
        rule.setStyleSheet("color:#dde3e9;")
        v.addWidget(rule)

        # --- Device ---
        v.addWidget(self._heading("Device"))
        self.btn_connect = QtWidgets.QPushButton("Connect")
        self.btn_connect.setStyleSheet(self._primary_btn())
        self.btn_connect.clicked.connect(self._toggle_connect)
        v.addWidget(self.btn_connect)
        self.lbl_device = QtWidgets.QLabel("not connected")
        self.lbl_device.setWordWrap(True)
        self.lbl_device.setStyleSheet("color:#5a6b7a; font-size:11px;")
        v.addWidget(self.lbl_device)

        # --- Acquisition ---
        v.addWidget(self._heading("Acquisition"))
        row, self.sl_exp, self.sp_exp = self._log_slider_row(
            "Integration  [ms]", 0.01, 1000, self.exposure_ms, self._on_exposure)
        v.addWidget(row)
        row, self.sl_avg, self.sp_avg = self._lin_slider_row(
            "Averaging  [frames]", 1, 64, self.navg, self._on_navg)
        v.addWidget(row)
        self.chk_clean = QtWidgets.QCheckBox("glitch filter  (median + despike)")
        self.chk_clean.setStyleSheet(self._checkbox_style())
        self.chk_clean.setChecked(True)
        self.chk_clean.setToolTip("Removes USB-cable transfer glitches (not real signal).\n"
                                  "Uncheck to see / export RAW sensor data.")
        self.chk_clean.toggled.connect(self._on_clean)
        v.addWidget(self.chk_clean)
        run = QtWidgets.QHBoxLayout()
        self.btn_run = QtWidgets.QPushButton("Run")
        self.btn_run.setStyleSheet(self._primary_btn())
        self.btn_run.clicked.connect(self._toggle_run)
        self.btn_single = QtWidgets.QPushButton("Single")
        self.btn_single.setStyleSheet(self._flat_btn())
        self.btn_single.clicked.connect(self._single_shot)
        self.btn_auto = QtWidgets.QPushButton("Auto")
        self.btn_auto.setStyleSheet(self._flat_btn())
        self.btn_auto.setToolTip("Auto-set the integration time to ~70% of full scale\n"
                                 "(brightest of both channels, without saturating).")
        self.btn_auto.clicked.connect(self._auto_expose)
        run.addWidget(self.btn_run)
        run.addWidget(self.btn_single)
        run.addWidget(self.btn_auto)
        v.addLayout(run)
        self.chk_track = QtWidgets.QCheckBox("auto integration time  (continuous)")
        self.chk_track.setStyleSheet(self._checkbox_style())
        self.chk_track.setToolTip("On by default. While live, keeps adjusting the integration time every\n"
                                  "frame from the recent measurements so the brightest channel's peak\n"
                                  "stays between 60-80% of full scale - for scenes whose brightness\n"
                                  "changes, e.g. sweeping the fibre around the room.\n"
                                  "Dragging the integration slider hands control back to you.")
        self.chk_track.toggled.connect(self._on_track)
        self.chk_track.setChecked(True)             # auto integration time is on by default
        v.addWidget(self.chk_track)

        # --- Dark frame ---
        v.addWidget(self._heading("Dark frame"))
        dk = QtWidgets.QHBoxLayout()
        self.btn_dark = QtWidgets.QPushButton("Capture dark")
        self.btn_dark.setStyleSheet(self._flat_btn())
        self.btn_dark.clicked.connect(self._capture_dark)
        self.btn_dark_clear = QtWidgets.QPushButton("Clear")
        self.btn_dark_clear.setStyleSheet(self._flat_btn())
        self.btn_dark_clear.clicked.connect(self._clear_dark)
        dk.addWidget(self.btn_dark)
        dk.addWidget(self.btn_dark_clear)
        v.addLayout(dk)
        self.chk_dark = QtWidgets.QCheckBox("subtract dark")
        self.chk_dark.setStyleSheet(self._checkbox_style())
        self.chk_dark.toggled.connect(self._on_dark_toggle)
        v.addWidget(self.chk_dark)
        self.offset_combo = QtWidgets.QComboBox()
        self.offset_combo.setStyleSheet(self._combo_style())
        self.offset_combo.addItems(["offset: none", "subtract minimum", "subtract dark pixels"])
        self.offset_combo.setToolTip("Extra per-frame baseline: the signal minimum, or the\n"
                                     "on-chip optical-black (dark-pixel) level read from the sensor.")
        self.offset_combo.currentIndexChanged.connect(self._on_offset)
        v.addWidget(self.offset_combo)

        # --- Reference (flat-field / 100% line) ---
        v.addWidget(self._heading("Reference"))
        rf = QtWidgets.QHBoxLayout()
        self.btn_ref = QtWidgets.QPushButton("Capture reference")
        self.btn_ref.setStyleSheet(self._flat_btn())
        self.btn_ref.clicked.connect(self._capture_reference)
        self.btn_ref_clear = QtWidgets.QPushButton("Clear")
        self.btn_ref_clear.setStyleSheet(self._flat_btn())
        self.btn_ref_clear.clicked.connect(self._clear_reference)
        rf.addWidget(self.btn_ref); rf.addWidget(self.btn_ref_clear)
        v.addLayout(rf)
        self.chk_flat = QtWidgets.QCheckBox("divide by reference (flat-field)")
        self.chk_flat.setStyleSheet(self._checkbox_style())
        self.chk_flat.setToolTip("Capture a no-sample baseline, then show signal / reference.\n"
                                 "The no-sample line reads ~1.0; a sample shows as the dip.")
        self.chk_flat.toggled.connect(self._on_flat)
        v.addWidget(self.chk_flat)

        # --- View ---
        v.addWidget(self._heading("View"))
        self.view_combo = QtWidgets.QComboBox()
        self.view_combo.setStyleSheet(self._combo_style())
        self.view_combo.addItems(["Counts  (both channels)",
                                  "Transmission  (meas / ref)",
                                  "Absorbance  (-log10)"])
        self.view_combo.currentIndexChanged.connect(self._on_view)
        v.addWidget(self.view_combo)
        self.axis_combo = QtWidgets.QComboBox()
        self.axis_combo.setStyleSheet(self._combo_style())
        self.axis_combo.addItems(["x-axis: wavelength (nm)", "x-axis: pixel"])
        self.axis_combo.currentIndexChanged.connect(self._on_axis)
        v.addWidget(self.axis_combo)
        self.chk_peak = QtWidgets.QCheckBox("peak marker")
        self.chk_peak.setStyleSheet(self._checkbox_style())
        self.chk_peak.setChecked(True)
        self.chk_peak.setToolTip("Vertical line + readout at each channel's spectral peak.")
        self.chk_peak.toggled.connect(self._on_peak)
        v.addWidget(self.chk_peak)
        srow = QtWidgets.QHBoxLayout()
        self.smooth_combo = QtWidgets.QComboBox()
        self.smooth_combo.setStyleSheet(self._combo_style())
        self.smooth_combo.addItems(["smooth: off", "Savitzky-Golay", "boxcar"])
        self.smooth_combo.currentIndexChanged.connect(self._on_smooth)
        self.sp_smooth = QtWidgets.QSpinBox()
        self.sp_smooth.setRange(3, 51); self.sp_smooth.setSingleStep(2)
        self.sp_smooth.setValue(9); self.sp_smooth.setPrefix("win ")
        self.sp_smooth.valueChanged.connect(self._on_smooth)
        srow.addWidget(self.smooth_combo, 1); srow.addWidget(self.sp_smooth)
        v.addLayout(srow)
        zrow = QtWidgets.QHBoxLayout()
        self.yscale_combo = QtWidgets.QComboBox()
        self.yscale_combo.setStyleSheet(self._combo_style())
        self.yscale_combo.addItems(["y: linear", "y: log", "y: sqrt"])
        self.yscale_combo.currentIndexChanged.connect(self._on_yscale)
        self.sp_xlo = QtWidgets.QDoubleSpinBox(); self.sp_xlo.setRange(300, 1100)
        self.sp_xlo.setDecimals(0); self.sp_xlo.setValue(350); self.sp_xlo.setPrefix("lo ")
        self.sp_xhi = QtWidgets.QDoubleSpinBox(); self.sp_xhi.setRange(300, 1100)
        self.sp_xhi.setDecimals(0); self.sp_xhi.setValue(850); self.sp_xhi.setPrefix("hi ")
        self.sp_xlo.valueChanged.connect(self._on_zoom); self.sp_xhi.valueChanged.connect(self._on_zoom)
        btn_full = QtWidgets.QPushButton("full"); btn_full.setStyleSheet(self._flat_btn())
        btn_full.clicked.connect(self._zoom_full)
        zrow.addWidget(self.yscale_combo); zrow.addWidget(self.sp_xlo)
        zrow.addWidget(self.sp_xhi); zrow.addWidget(btn_full)
        v.addLayout(zrow)

        # --- Calibration ---
        v.addWidget(self._heading("Calibration"))
        self.btn_cal = QtWidgets.QPushButton("Calibrate wavelength...")
        self.btn_cal.setStyleSheet(self._flat_btn())
        self.btn_cal.clicked.connect(self._open_calibration)
        v.addWidget(self.btn_cal)

        # --- Export ---
        v.addWidget(self._heading("Export"))
        self.btn_export = QtWidgets.QPushButton("Export CSV + PDF")
        self.btn_export.setStyleSheet(self._flat_btn())
        self.btn_export.clicked.connect(self._export)
        v.addWidget(self.btn_export)
        self.chk_log = QtWidgets.QCheckBox("log session to CSV")
        self.chk_log.setStyleSheet(self._checkbox_style())
        self.chk_log.toggled.connect(self._on_log_toggle)
        v.addWidget(self.chk_log)

        v.addStretch(1)
        self.hint = QtWidgets.QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#b25e00; font-size:11px; font-style:italic;")
        v.addWidget(self.hint)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(410)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        return scroll

    # ---------------------------------------------------------- control styles
    def _primary_btn(self):
        return (f"QPushButton{{background:{NAVY}; color:#ffffff; font-weight:bold;"
                "border:0; border-radius:6px; padding:7px 12px;}"
                "QPushButton:hover{background:#024a8c;}"
                "QPushButton:disabled{background:#9fb3c6;}")

    def _flat_btn(self):
        return ("QPushButton{background:#eef1f4; color:#33414d; border:0;"
                "border-radius:5px; padding:6px 10px;}"
                "QPushButton:hover{background:#e2e8ee;}"
                "QPushButton:disabled{color:#aebccb;}")

    def _checkbox_style(self):
        """Same native-rendering gap as combo boxes (see _combo_style) - the
        label text silently fails to draw on recent macOS without this."""
        return ("QCheckBox{color:#33414d; spacing:8px;}"
                "QCheckBox::indicator{width:15px; height:15px; border:1px solid #c3cfd9;"
                "border-radius:3px; background:#ffffff;}"
                "QCheckBox::indicator:hover{border-color:#8fa3b3;}"
                f"QCheckBox::indicator:checked{{background:{NAVY}; border-color:{NAVY};}}")

    def _combo_style(self):
        """PyQt5's native macOS combo box renders blank text on recent macOS
        (Qt5 is EOL, untested past ~macOS 13) - style it explicitly like the
        buttons above instead of relying on Cocoa/Aqua drawing."""
        return (f"QComboBox{{background:#eef1f4; color:#33414d; border:1px solid #d3dde6;"
                "border-radius:5px; padding:5px 24px 5px 8px;}"
                "QComboBox:hover{background:#e2e8ee;}"
                "QComboBox::drop-down{border:0; width:22px;}"
                "QComboBox::down-arrow{image:none; width:0; height:0;"
                "border-left:4px solid transparent; border-right:4px solid transparent;"
                "border-top:5px solid #5a6b7a; margin-right:8px;}"
                f"QComboBox QAbstractItemView{{background:#ffffff; color:#33414d;"
                f"selection-background-color:{NAVY}; selection-color:#ffffff;"
                "border:1px solid #d3dde6; outline:0;}")

    def _slider_style(self):
        """Same native-rendering gap as combo boxes (see _combo_style) - the
        groove/handle silently fail to draw on recent macOS without this."""
        return (f"QSlider::groove:horizontal{{height:4px; background:#dde3e9; border-radius:2px;}}"
                f"QSlider::sub-page:horizontal{{background:{NAVY}; border-radius:2px;}}"
                f"QSlider::handle:horizontal{{background:#ffffff; border:2px solid {NAVY};"
                "width:14px; height:14px; margin:-6px 0; border-radius:7px;}"
                "QSlider::handle:horizontal:hover{background:#eef3f8;}")

    # ----------------------------------------------------------- slider rows
    def _lin_slider_row(self, label, lo, hi, val, cb):
        w = QtWidgets.QWidget()
        g = QtWidgets.QVBoxLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(2)
        top = QtWidgets.QHBoxLayout()
        lab = QtWidgets.QLabel(label)
        lab.setStyleSheet("color:#33414d; font-size:13px;")
        sp = QtWidgets.QSpinBox()
        sp.setRange(lo, hi)
        sp.setValue(val)
        sp.setFixedWidth(84)
        top.addWidget(lab)
        top.addStretch(1)
        top.addWidget(sp)
        sl = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(val)
        sl.setStyleSheet(self._slider_style())
        g.addLayout(top)
        g.addWidget(sl)
        guard = {"busy": False}

        def from_slider(value):
            if guard["busy"]:
                return
            guard["busy"] = True
            sp.setValue(value)
            guard["busy"] = False
            cb(value)

        def from_spin(value):
            if guard["busy"]:
                return
            guard["busy"] = True
            sl.setValue(value)
            guard["busy"] = False
            cb(value)

        sl.valueChanged.connect(from_slider)
        sp.valueChanged.connect(from_spin)
        return w, sl, sp

    def _log_slider_row(self, label, lo, hi, val, cb, decimals=2):
        """Logarithmic slider over [lo, hi] with an exact (float) spin box.

        Used for integration time; lo can be sub-ms (0.01 ms = 10 us) to match the
        EURECA range.
        """
        import math
        STEPS = 600
        lg_lo, lg_hi = math.log10(lo), math.log10(hi)
        w = QtWidgets.QWidget()
        g = QtWidgets.QVBoxLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(2)
        top = QtWidgets.QHBoxLayout()
        lab = QtWidgets.QLabel(label)
        lab.setStyleSheet("color:#33414d; font-size:13px;")
        sp = QtWidgets.QDoubleSpinBox()
        sp.setDecimals(decimals)
        sp.setRange(lo, hi)
        sp.setValue(val)
        sp.setFixedWidth(90)
        top.addWidget(lab)
        top.addStretch(1)
        top.addWidget(sp)
        sl = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        sl.setRange(0, STEPS)
        sl.setStyleSheet(self._slider_style())

        def to_val(pos):
            v = 10.0 ** (lg_lo + (lg_hi - lg_lo) * pos / STEPS)
            return float(min(max(v, lo), hi))

        def to_pos(v):
            v = min(max(float(v), lo), hi)
            return int(round((math.log10(v) - lg_lo) / (lg_hi - lg_lo) * STEPS))

        sl.setValue(to_pos(val))
        g.addLayout(top)
        g.addWidget(sl)
        guard = {"busy": False}

        def from_slider(pos):
            if guard["busy"]:
                return
            guard["busy"] = True
            v = to_val(pos)
            sp.setValue(v)
            guard["busy"] = False
            cb(v)

        def from_spin(v):
            if guard["busy"]:
                return
            guard["busy"] = True
            sl.setValue(to_pos(v))
            guard["busy"] = False
            cb(v)

        sl.valueChanged.connect(from_slider)
        sp.valueChanged.connect(from_spin)
        return w, sl, sp

    # -------------------------------------------------------------- callbacks
    def _on_exposure(self, v):
        self.exposure_ms = float(v)
        if self._track:                     # a manual slider drag takes back control
            self.chk_track.setChecked(False)
        if self.connected and not self.running:
            self._single()

    def _on_track(self, on):
        self._track = bool(on)
        self._track_msg = ""
        self._oob_count = 0
        if on and self.connected:
            if not self.running:
                self._start()               # tracking only does anything live
            self._auto_expose()             # snap from cold once, then the servo tracks smoothly
        self._set_hint("auto integration time ON - holding 60-80% full scale"
                       if on else "auto integration time off")

    def _on_navg(self, v):
        self.navg = int(v)
        if self.connected and not self.running:
            self._single()

    def _on_clean(self, on):
        self.clean = bool(on)
        if self.connected and not self.running:
            self._single()
        self._set_hint("glitch filter ON" if on else "glitch filter OFF - RAW sensor data")

    def _on_view(self, idx):
        self.view = ("counts", "transmission", "absorbance")[idx]
        self._render_plot()

    def _on_axis(self, idx):
        self.axis = "nm" if idx == 0 else "pixel"
        self._render_plot()

    def _on_peak(self, on):
        self.show_peak = bool(on)
        self._render_plot()

    def _open_calibration(self):
        self._cal_dialog = _CalibrationDialog(self)
        self._cal_dialog.show()

    def _on_dark_toggle(self, on):
        self.subtract_dark_flag = bool(on)
        if self.dark is None and on:
            self._set_hint("no dark captured yet - press Capture dark")
        self._process()
        self._render_plot()
        self._update_stats()

    def _capture_reference(self):
        if not self.connected:
            self._set_hint("connect first")
            return
        try:
            self._apply_exposure_if_changed()
            n = max(16, self.navg)
            with self._driver_lock:
                frame = P.average_frames([self.driver.grab() for _ in range(n)], method="median", clean=self.clean)
        except (DriverError, OSError) as e:
            self._on_driver_error(e)
            return
        m = self.cal.by_role("measurement")
        r = self._ref()
        use_dark = self.dark if (self.subtract_dark_flag and self.dark is not None) else None
        fr = subtract_dark(frame, use_dark)
        ref = {"m": m.slice(fr).copy()}
        if r is not None:
            ref["r"] = r.slice(fr).copy()
        self.reference_proc = ref
        self.chk_flat.setChecked(True)
        self._set_hint(f"reference captured ({n} frames) - flat-field on")
        if not self.running:
            self._single()

    def _clear_reference(self):
        self.reference_proc = None
        self.chk_flat.setChecked(False)
        self._set_hint("reference cleared")

    def _on_flat(self, on):
        self.flat = bool(on)
        if on and self.reference_proc is None:
            self._set_hint("capture a reference first")
        self._render_plot()

    def _on_smooth(self, *_):
        idx = self.smooth_combo.currentIndex()
        self.smooth_mode = ("off", "savgol", "boxcar")[idx]
        self.smooth_win = 0 if idx == 0 else int(self.sp_smooth.value())
        self._render_plot()

    def _on_yscale(self, idx):
        self.yscale = ("linear", "log", "sqrt")[idx]
        self._render_plot()

    def _on_offset(self, idx):
        self.offset_mode = ("none", "minimum", "darkpixels")[idx]
        self._process()
        self._render_plot()
        self._update_stats()

    def _on_zoom(self, *_):
        lo, hi = float(self.sp_xlo.value()), float(self.sp_xhi.value())
        self.x_lo, self.x_hi = (min(lo, hi), max(lo, hi)) if hi > lo + 1 else (None, None)
        self._render_plot()

    def _zoom_full(self):
        self.x_lo = self.x_hi = None
        self._render_plot()

    # ------------------------------------------------------------ connection
    def _disconnect_ui(self, hint: str) -> None:
        """Tear down to 'not connected', for a manual Disconnect click or a
        driver error that leaves the link unusable."""
        self._stop()
        try:
            self.driver.close()
        except Exception:
            pass
        self.connected = False
        self.info = None
        self.btn_connect.setText("Connect")
        self.lbl_device.setText("not connected")
        self._set_hint(hint)

    def _on_driver_error(self, exc) -> None:
        """A synchronous driver call (single-shot / auto-expose / dark or
        reference capture) failed outside the live-tick worker. PyQt5 aborts
        the process on an unhandled exception in a slot, so this must never
        propagate - drop the link cleanly and let the operator reconnect."""
        self._disconnect_ui(f"link lost ({exc}) - press Connect to retry"[:160])

    def _toggle_connect(self):
        if self.connected:
            self._disconnect_ui("disconnected")
        else:
            self._connect()

    def _connect(self):
        try:
            self.info = self.driver.connect()
            self.connected = True
            self._applied_us = None
            self.btn_connect.setText("Disconnect")
            inst = self.cal.instrument
            model = (self.info.model if (self.info.model and "-" in self.info.model)
                     else inst.get("board", self.info.model or "e9u_LSMD"))
            serial = self.info.serial or inst.get("serials", {}).get("eureca", "?")
            port = self.info.com_port or ("MOCK" if self.info.mock else "")
            self.lbl_device.setText(
                f"{model}  SN {serial}\n{inst.get('detector', '')}  "
                f"{self.info.pixels}px  {port}".strip())
            self._set_hint("connected - press Run for live, or Single")
            if self._track:                 # auto integration time is on by default: snap now
                self._auto_expose()
        except DriverError as e:
            self.connected = False
            self.lbl_device.setText("connection failed")
            self._set_hint(str(e).split('\n')[0])
            try:
                self.driver.close()        # release a half-opened device
            except Exception:
                pass

    def closeEvent(self, ev):
        """Tear down cleanly when the window closes: stop the live timer, let
        any in-flight tick finish, and release the camera so a queued tick
        can't touch a closing USB device."""
        try:
            self._stop()
            self.timer.stop()
            if self._acq_worker is not None:
                self._acq_worker.wait()
            if self.connected:
                self.driver.close()
        except Exception:
            pass
        super().closeEvent(ev)

    # ------------------------------------------------------------ acquisition
    def _toggle_run(self):
        self._stop() if self.running else self._start()

    def _start(self):
        if not self.connected:
            self._set_hint("connect first")
            return
        self.running = True
        self.btn_run.setText("Stop")
        self.timer.start()
        self._set_hint("running - live")

    def _stop(self):
        self.running = False
        self.btn_run.setText("Run")
        self.timer.stop()

    def _single(self):
        """Internal one-frame refresh (parameter changes, dark capture)."""
        if not self.connected:
            self._set_hint("connect first")
            return
        self._tick_once()

    def _single_shot(self):
        """Single button: freeze any live run and capture exactly one frame."""
        if not self.connected:
            self._set_hint("connect first")
            return
        was_running = self.running
        if was_running:
            self._stop()                         # so the captured frame stays on screen
        self._tick_once()
        if self.connected:                       # _tick_once may have dropped the link
            self._set_hint("single frame captured" + (" - live stopped" if was_running else ""))

    def _auto_expose(self, target=0.70, lo_ms=0.02, hi_ms=1000.0, iters=8):
        """Hunt the integration time so the brightest channel peaks near `target` of
        full scale, without saturating. Uses a GLITCH-DESPIKED peak (so a stray spike
        can't stop it early) and a PROPORTIONAL jump (signal ~ linear in exposure), so
        it converges in a couple of steps and from any starting exposure. A candidate
        in the sweet spot is CONFIRMED with a second probe (conservative min) before it
        is accepted, so a brief flicker on a fluctuating source - e.g. daylight through
        the shutter - can't stop the hunt early."""
        if not self.connected:
            self._set_hint("connect first")
            return
        sat = self.cal.saturation_count
        tgt = sat * target

        def probe(exp_ms):
            with self._driver_lock:
                self.driver.set_times_us(int(round(exp_ms * 1000)))
                for _ in range(2):
                    self.driver.grab()                              # let the new timing settle
                frame = P.average_frames([self.driver.grab() for _ in range(7)], method="median")
            return max(P.robust_peak(ch.slice(frame)) for ch in self.cal.channels)

        exp, pk = min(max(self.exposure_ms, lo_ms), hi_ms), 0.0
        try:
            for _ in range(iters):
                pk = probe(exp)
                if sat * 0.60 <= pk <= sat * 0.80:                  # candidate -> confirm it holds
                    pk = min(pk, probe(exp))                        # a flicker won't survive the min
                    if sat * 0.60 <= pk <= sat * 0.80:              # same band -> accept; else keep hunting
                        break
                new = exp * 0.5 if pk >= sat * 0.97 else exp * min(max(tgt / max(pk, 1.0), 0.2), 8.0)
                new = min(max(new, lo_ms), hi_ms)
                if abs(new - exp) < 1e-4:                           # clamped at a rail -> best we can do
                    exp = new
                    break
                exp = new
        except (DriverError, OSError) as e:
            self._on_driver_error(e)
            return
        self.exposure_ms = round(exp, 3)
        self.sp_exp.blockSignals(True); self.sp_exp.setValue(self.exposure_ms); self.sp_exp.blockSignals(False)
        self._applied_us = None
        ok = sat * 0.45 <= pk <= sat * 0.97
        self._set_hint(f"auto exposure -> {self.exposure_ms:g} ms ({pk / sat * 100:.0f}% FS)"
                       + ("" if ok else " - source too dim/bright for the target"))
        if not self.running:
            self._single()

    def _track_exposure(self, lo_ms=0.02, hi_ms=1000.0):
        """Continuous auto-exposure servo - one nudge per live frame so the brightest
        channel stays in a comfortable band as the scene changes (sweep the fibre around
        the room). Log-proportional (signal is linear in integration time) so a static
        scene corrects in ~1 step and the loop is provably non-oscillatory; a symmetric
        deadband stops a steady scene from jittering; the step is slew-limited so the
        trace does not flick; true clipping uses a saturated-fraction-scaled, slew-exempt
        cut because clipped data is unrecoverable. Favours robustness over hitting 70%."""
        if not self._track:                         # toggled off between the call and here
            return
        sat = self.cal.saturation_count
        frac = self._last_peak / sat if sat else 0.0
        satf = self._last_sat                       # multi-pixel saturated fraction, [0,1]
        self._track_msg = ""
        BAND_LO, BAND_HI, TARGET = 0.60, 0.80, 0.70     # band symmetric in log around 0.70

        def apply(new):
            new = min(max(new, lo_ms), hi_ms)
            if abs(new - self.exposure_ms) < 1e-4:
                return False
            self.exposure_ms = round(new, 3)
            self.sp_exp.blockSignals(True); self.sp_exp.setValue(self.exposure_ms); self.sp_exp.blockSignals(False)
            return True

        # 1. true clipping: frac is pinned and useless -> scale the cut by HOW MANY pixels
        #    clip (slew-exempt; a white frame has no flicker quality to protect).
        if satf > 0.0 and frac >= 0.95:
            self._oob_count = 0
            factor = 0.06 if satf >= 0.20 else (0.20 if satf >= 0.02 else 0.50)
            if not apply(self.exposure_ms * factor):
                self._track_msg = "(scene too bright)"      # railed at the floor, still clipping
            return

        # 2. steady scene inside the band -> leave it alone
        if BAND_LO <= frac <= BAND_HI:
            self._oob_count = 0
            return

        # 3. out of band: slew-clamped log-proportional correction
        factor = min(max(TARGET / max(frac, 1e-3), 0.25), 4.0)
        on_rail = factor >= 4.0 or factor <= 0.25       # a big move -> act now, do not wait
        self._oob_count += 1
        if not on_rail and self._oob_count < 2:          # small move must persist 2 ticks (kills noise)
            return
        self._oob_count = 0
        if not apply(self.exposure_ms * factor):         # clamped at a rail -> say why
            if self.exposure_ms >= hi_ms and frac < BAND_LO:
                self._track_msg = "(scene too dim @ 1000 ms)"
            elif self.exposure_ms <= lo_ms and frac > BAND_HI:
                self._track_msg = "(scene too bright @ floor)"

    def _apply_exposure_if_changed(self):
        with self._driver_lock:
            us = int(round(self.exposure_ms * 1000))
            if us != self._applied_us:
                self.driver.set_times_us(us)
                self._applied_us = us
                for _ in range(2):          # let the new timing settle
                    self.driver.grab()

    def _acquire_frame(self):
        """Blocking driver I/O for one tick. Runs on the GUI thread for a
        single-shot capture, or inside _AcquisitionWorker for the live loop -
        the lock keeps the two from touching the driver at once."""
        with self._driver_lock:
            self._apply_exposure_if_changed()
            frames = [self.driver.grab() for _ in range(max(1, self.navg))]
            glitch = P.glitch_fraction(frames)
            dark_value = self.driver.dark_value()
            fc = self.driver.frame_counter()
            last_frame = P.average_frames(frames, method="median", clean=self.clean)
        return len(frames), glitch, dark_value, fc, last_frame

    def _finish_tick(self, payload):
        n_frames, glitch, dark_value, fc, last_frame = payload
        self._last_glitch = glitch
        self._dark_value = dark_value
        if fc is not None and self._last_fc is not None:
            adv = fc - self._last_fc
            if 0 <= adv < n_frames:
                self._dropped += n_frames - adv          # got stale/duplicate frames
        self._last_fc = fc
        self.last_frame = last_frame
        self._process()
        self._render_plot()
        self._update_stats()
        if self.logger is not None:
            try:
                self.logger.log(self.cal, self.last_frame, self.exposure_ms,
                                self.navg, self._last_sat)
            except (IOError, OSError) as e:
                self._set_hint(f"session log write failed: {e}")
            except Exception as e:                  # a logic error - surface it, do not log junk
                self._set_hint(f"logging stopped (error: {str(e)[:60]})")
                try:
                    self.logger.close()
                except Exception:
                    pass
                self.logger = None
                self.chk_log.blockSignals(True); self.chk_log.setChecked(False); self.chk_log.blockSignals(False)
        if self._track and self.running:
            self._track_exposure()          # nudge integration time for the NEXT frame

    def _begin_tick(self):
        import time as _time
        self._frame_n += 1
        now = _time.monotonic()
        if self._t_prev is not None and now > self._t_prev:
            self._fps = 1.0 / (now - self._t_prev)
        self._t_prev = now

    def _tick_once(self):
        """Synchronous single-frame capture for button-triggered actions."""
        if not self.connected:
            return
        self._begin_tick()
        try:
            payload = self._acquire_frame()
        except (DriverError, OSError) as e:
            self._on_driver_error(e)
            return
        self._finish_tick(payload)

    def _tick_live(self):
        """QTimer-driven live loop: the actual grab() runs off the GUI thread
        so a slow (net) link stalls only the acquisition, never the window."""
        if not self.connected:
            return
        if self._acq_worker is not None:
            return                              # previous tick's grab still in flight
        self._begin_tick()
        w = _AcquisitionWorker(self._acquire_frame, self)
        w.done.connect(self._finish_tick)
        w.failed.connect(self._on_driver_error)
        w.finished.connect(self._on_worker_finished)
        self._acq_worker = w
        w.start()

    def _on_worker_finished(self):
        w, self._acq_worker = self._acq_worker, None
        w.deleteLater()

    def _ref(self):
        """The reference channel, or None on a single-channel instrument."""
        for ch in self.cal.channels:
            if ch.role == "reference":
                return ch
        return None

    def _process(self):
        if self.last_frame is None:
            return
        m = self.cal.by_role("measurement")
        r = self._ref()
        use_dark = self.dark if (self.subtract_dark_flag and self.dark is not None) else None
        fr = subtract_dark(self.last_frame, use_dark)
        if self.offset_mode == "darkpixels" and self._dark_value is not None:
            fr = np.clip(fr - self._dark_value, 0.0, None)
        mc = m.slice(fr)
        if self.offset_mode == "minimum" and mc.size:
            mc = np.clip(mc - mc.min(), 0.0, None)
        rc = None
        if r is not None:
            rc = r.slice(fr)
            if self.offset_mode == "minimum" and rc.size:
                rc = np.clip(rc - rc.min(), 0.0, None)
        self.last_proc = {"m": mc, "r": rc}
        sat = self.cal.saturation_count
        sats = [P.saturated_fraction(m.slice(self.last_frame), sat)]
        if r is not None:
            sats.append(P.saturated_fraction(r.slice(self.last_frame), sat))
        self._last_sat = max(sats)
        # brightest channel peak in raw counts, glitch-ROBUST (what auto-exposure + the
        # tracking servo target): despike + short boxcar so a dense-cable glitch artifact
        # cannot masquerade as signal at low exposure.
        self._last_peak = max(P.robust_peak(ch.slice(self.last_frame))
                              for ch in self.cal.channels)
        if mc.size:
            self._peak_nm = float(m.wavelengths[P.robust_peak_index(mc)])

    # ------------------------------------------------------------ dark frame
    def _capture_dark(self):
        if not self.connected:
            self._set_hint("connect first")
            return
        try:
            self._apply_exposure_if_changed()
            n = max(8, self.navg)
            with self._driver_lock:
                self.dark = P.average_frames([self.driver.grab() for _ in range(n)], clean=self.clean)
        except (DriverError, OSError) as e:
            self._on_driver_error(e)
            return
        self.chk_dark.setChecked(True)
        self._set_hint(f"dark captured ({n} frames @ {self.exposure_ms:g} ms)")
        if not self.running:
            self._single()

    def _clear_dark(self):
        self.dark = None
        self.chk_dark.setChecked(False)
        self._set_hint("dark cleared")

    # ------------------------------------------------------------- rendering
    def _render_plot(self):
        view = getattr(self, "_view", None)
        if view is None:
            return
        w = max(420, view.width())
        h = max(280, view.height())
        dpi = 105
        fig = Figure(figsize=(w / dpi, h / dpi), dpi=dpi)
        fig.patch.set_facecolor("#eef3f8")
        if self.axis == "nm":
            gs = fig.add_gridspec(2, 1, height_ratios=[20, 1.5], hspace=0.06,
                                  left=0.10, right=0.97, top=0.92, bottom=0.17)
            ax = fig.add_subplot(gs[0])
            bar = fig.add_subplot(gs[1])
        else:
            ax = fig.add_axes([0.10, 0.12, 0.87, 0.80])
            bar = None
        ax.set_facecolor("#ffffff")
        ax.grid(alpha=0.15)
        for sp in ax.spines.values():
            sp.set_color("#d3dde6")
        ax.tick_params(colors="#5a6b7a", labelsize=7)
        ax.set_title("CLOUDS Spectral Engine", color=NAVY, fontsize=11, fontweight="bold")

        m = self.cal.by_role("measurement")
        r = self._ref()
        nm_lo = m.range_nm[0] if r is None else min(m.range_nm[0], r.range_nm[0])
        nm_hi = m.range_nm[1] if r is None else max(m.range_nm[1], r.range_nm[1])

        if self.last_proc is not None:
            mc = self.last_proc["m"]
            rc = self.last_proc.get("r")
            has_ref = r is not None and rc is not None
            if self.view == "counts" or not has_ref:
                mx = m.wavelengths if self.axis == "nm" else m.pixels
                flat = self.flat and self.reference_proc is not None
                md = P.reference_ratio(mc, self.reference_proc["m"]) if flat else mc
                if self.smooth_win:
                    md = P.smooth(md, self.smooth_win, self.smooth_mode)
                ax.plot(mx, md, color=C_MEAS, lw=1.3, label="measurement  Ch1")
                rd = None
                if has_ref:
                    rx = r.wavelengths if self.axis == "nm" else r.pixels
                    rd = (P.reference_ratio(rc, self.reference_proc["r"])
                          if flat and self.reference_proc.get("r") is not None else rc)
                    if self.smooth_win:
                        rd = P.smooth(rd, self.smooth_win, self.smooth_mode)
                    ax.plot(rx, rd, color=C_REF, lw=1.3, label="reference  Ch2")
                if flat:
                    ax.set_ylabel("signal / reference", color="#5a6b7a", fontsize=8)
                    top = float(np.nanmax(md)) if md.size and np.isfinite(md).any() else 1.5
                    ax.set_ylim(0, max(1.5, top * 1.1))
                    ax.axhline(1.0, color="#8a97a3", lw=0.8, ls="--", alpha=0.7)
                else:
                    ax.set_ylabel("counts (16-bit)", color="#5a6b7a", fontsize=8)
                    ax.set_ylim(0, 65535)
                    ax.axhline(self.cal.saturation_count, color="#FF2A2A", lw=0.7, ls="--", alpha=0.6)
                    if self.yscale == "log":
                        ax.set_yscale("log"); ax.set_ylim(10, 65535)
                    elif self.yscale == "sqrt":
                        ax.set_yscale("function", functions=(
                            lambda v: np.sqrt(np.clip(v, 0, None)), np.square))
                ax.legend(loc="upper right", fontsize=7, framealpha=0.9)
                if self.show_peak:
                    self._draw_peak(ax, mx, md, m.wavelengths, C_MEAS)
                    if has_ref:
                        self._draw_peak(ax, rx, rd, r.wavelengths, C_REF, minor=True)
            else:
                grid = P.common_grid(m.wavelengths, r.wavelengths, 256)
                mi = P.resample(m.wavelengths, mc, grid)
                ri = P.resample(r.wavelengths, rc, grid)
                yv = P.transmission(mi, ri) if self.view == "transmission" else P.absorbance(mi, ri)
                if self.smooth_win:
                    yv = P.smooth(yv, self.smooth_win, self.smooth_mode)
                if self.view == "transmission":
                    ax.plot(grid, yv, color=C_TRANS, lw=1.5)
                    ax.set_ylabel("transmission  meas / ref", color="#5a6b7a", fontsize=8)
                    ax.set_ylim(bottom=0)
                else:
                    ax.plot(grid, yv, color=C_ABS, lw=1.5)
                    ax.set_ylabel("absorbance  -log10(meas/ref)", color="#5a6b7a", fontsize=8)
        if self.axis == "nm":
            zlo = self.x_lo if self.x_lo is not None else nm_lo
            zhi = self.x_hi if self.x_hi is not None else nm_hi
            ax.set_xlim(zlo, zhi)
            ax.tick_params(labelbottom=False)            # nm numbers sit under the strip
            for edge in (380.0, 780.0):                  # UV | VIS | IR boundaries
                if nm_lo < edge < nm_hi:
                    ax.axvline(edge, color="#c4d0db", lw=0.8, ls=":", zorder=0)
        else:
            ax.set_xlabel("pixel", color="#5a6b7a", fontsize=8)

        if bar is not None:
            n = 512
            xs = np.linspace(nm_lo, nm_hi, n)
            rgb = np.array([_wl_rgb(x) for x in xs], dtype=float).reshape(1, n, 3) / 255.0
            bar.imshow(rgb, extent=[nm_lo, nm_hi, 0, 1], aspect="auto")
            blo = self.x_lo if self.x_lo is not None else nm_lo
            bhi = self.x_hi if self.x_hi is not None else nm_hi
            bar.set_xlim(blo, bhi)
            bar.set_yticks([])
            step = 100 if (bhi - blo) > 250 else 50
            bar.set_xticks([t for t in range(300, int(bhi) + 1, step) if blo <= t <= bhi])
            bar.tick_params(colors="#5a6b7a", labelsize=7)
            bar.set_xlabel("wavelength (nm)", color="#5a6b7a", fontsize=8)
            for sp in bar.spines.values():
                sp.set_color("#d3dde6")
            # UV / VIS / IR band labels on the strip (matches the Raytracing Engine)
            for lo, hi, lab, col in ((300, 380, "UV", "#ffffff"),
                                     (380, 780, "VIS", NAVY),
                                     (780, 1000, "IR", "#ffffff")):
                c0, c1 = max(lo, nm_lo), min(hi, nm_hi)
                if c1 - c0 > 18:                         # label only if the band is wide enough
                    bar.text((c0 + c1) / 2, 0.5, lab, ha="center", va="center",
                             color=col, fontsize=7, fontweight="bold")

        pm = _fig_to_pixmap(fig)
        self.plot.setPixmap(pm)
        xlo, xhi = ax.get_xlim()
        self._geom = {"bbox": tuple(ax.get_position().extents), "xlo": xlo, "xhi": xhi,
                      "pmw": pm.width(), "pmh": pm.height(), "axis": self.axis}

    def _draw_peak(self, ax, x, y, wl, color, minor=False):
        if not len(y):
            return
        i = P.robust_peak_index(y)                        # despike + boxcar: real line, not a glitch
        xpk, ypk = float(x[i]), float(y[i])
        ax.axvline(xpk, color=color, lw=0.9, ls=(0, (4, 3)), alpha=0.55 if minor else 0.9, zorder=1)
        ax.plot([xpk], [ypk], marker="v", color=color, ms=6, zorder=5)
        if not minor:
            ax.annotate(f"{wl[i]:.1f} nm\n{ypk:.0f} ct", xy=(xpk, ypk),
                        xytext=(5, -2), textcoords="offset points", fontsize=7.5,
                        color=color, fontweight="bold", va="top", ha="left",
                        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=color, lw=0.6, alpha=0.85))

    def _data_x_at(self, pos):
        """Map a mouse position over the plot to a data x (nm or pixel), or None."""
        g = self._geom
        if g is None:
            return None
        offx = max(0, (self.plot.width() - g["pmw"]) // 2)
        offy = max(0, (self.plot.height() - g["pmh"]) // 2)
        mx, my = pos.x() - offx, pos.y() - offy
        if not (0 <= mx < g["pmw"] and 0 <= my < g["pmh"]):
            return None
        fx = mx / g["pmw"]
        x0, _y0, x1, _y1 = g["bbox"]
        if not (x0 <= fx <= x1):
            return None
        return g["xlo"] + (fx - x0) / (x1 - x0) * (g["xhi"] - g["xlo"])

    def _peak_pixel_near(self, data_x, channel, half=8):
        """Refine a click near a channel to its local peak pixel (parabolic sub-pixel)."""
        if self.last_frame is None:
            return None
        lo, hi = channel.pixel_window
        if self._geom and self._geom["axis"] == "pixel":
            p0 = int(round(data_x))
        else:
            p0 = lo + int(np.argmin(np.abs(channel.wavelengths - data_x)))
        a = max(lo, p0 - half)
        b = min(hi, p0 + half)
        seg = np.asarray(self.last_frame, dtype=float)[a:b + 1]
        if seg.size < 3:
            return None
        k = int(np.argmax(seg))
        pk = a + k
        if 0 < k < seg.size - 1:
            denom = seg[k - 1] - 2 * seg[k] + seg[k + 1]
            if denom != 0:
                pk = a + k + 0.5 * (seg[k - 1] - seg[k + 1]) / denom
        return float(pk)

    def _cursor_readout(self, pos):
        g = self._geom
        if g is None or self.last_proc is None:
            self.cursor_box.hide()
            return
        dx = self._data_x_at(pos)
        if dx is None:
            self.cursor_box.hide()
            return
        m = self.cal.by_role("measurement")
        r = self._ref()
        rproc = self.last_proc.get("r")
        if g["axis"] == "nm":
            mi = int(np.argmin(np.abs(m.wavelengths - dx)))
            px = m.pixel_window[0] + mi
            nm_here = float(m.wavelengths[mi])
            mc = float(self.last_proc["m"][mi])
            rc = None
            if r is not None and rproc is not None:
                rc = float(rproc[int(np.argmin(np.abs(r.wavelengths - dx)))])
        else:
            px = int(round(dx))
            nm_here = float(m.pixel_to_nm(px))
            mw = m.pixel_window
            mc = float(self.last_proc["m"][px - mw[0]]) if mw[0] <= px <= mw[1] else None
            rc = None
            if r is not None and rproc is not None and r.pixel_window[0] <= px <= r.pixel_window[1]:
                rc = float(rproc[px - r.pixel_window[0]])
        ms = f"{mc:7.0f}" if mc is not None else "     --"
        rs = f"{rc:7.0f}" if rc is not None else "     --"
        self.cursor_lbl.setText(f"px {px:4d}\n{nm_here:6.1f} nm\nmeas {ms}\nref  {rs}")
        self.cursor_box.adjustSize()
        self.cursor_box.move(max(20, self._view.width() - self.cursor_box.width() - 16), 16)
        self.cursor_box.show()
        self.cursor_box.raise_()

    def _update_stats(self):
        if self.last_proc is None:
            self.stats.setText("no data")
        else:
            m = self.cal.by_role("measurement")
            r = self._ref()
            mc = self.last_proc["m"]; rc = self.last_proc.get("r")
            mi = P.robust_peak_index(mc) if mc.size else 0      # glitch-robust peak readout
            m_nm = float(m.wavelengths[mi]) if mc.size else 0.0
            m_pk = float(mc[mi]) if mc.size else 0.0
            if r is not None and rc is not None and rc.size:
                ri = P.robust_peak_index(rc)
                ref_line = f"ref   {float(rc[ri]):6.0f} @ {float(r.wavelengths[ri]):5.1f} nm\n"
            else:
                ref_line = "ref     --  single channel\n"
            sat = self._last_sat * 100.0
            clip = "  CLIPPING" if self._last_sat > 0.001 else ""
            glitch = self._last_glitch * 100.0
            gl = f"\nUSB   {glitch:4.1f} % glitch" if glitch > 0.2 else ""
            self.stats.setText(
                f"meas  {m_pk:6.0f} @ {m_nm:5.1f} nm\n"
                + ref_line +
                f"mean  {float(np.mean(mc)):6.0f}   sd {float(np.std(mc)):5.0f}\n"
                f"sat   {sat:5.1f} %{clip}\n"
                f"exp   {self.exposure_ms:g} ms  x{self.navg}"
                + ("  TRACK" + (" " + self._track_msg if self._track_msg else "") if self._track else "")
                + f"{gl}\n"
                f"fps   {self._fps:4.1f}   frame #{self._frame_n}"
                + (f"  drop {self._dropped}" if self._dropped else ""))
        self.stats_box.adjustSize()
        self.stats_box.move(16, 16)
        self.stats_box.raise_()

    def _set_hint(self, txt):
        if hasattr(self, "hint"):
            self.hint.setText(txt)

    def _export(self):
        if self.last_frame is None:
            self._set_hint("acquire a frame first (press Single or Run)")
            return
        from spectro import export as EX
        os.makedirs("output", exist_ok=True)
        ts = EX.timestamp()
        meta = {
            "timestamp": ts,
            "instrument": f"{self.cal.instrument.get('product', '')} SN "
                          f"{self.cal.instrument.get('serials', {}).get('eureca', '')}",
            "exposure_ms": self.exposure_ms,
            "averaging": self.navg,
            "dark_subtracted": bool(self.subtract_dark_flag and self.dark is not None),
            "glitch_filtered": bool(self.clean),
        }
        use_dark = self.dark if (self.subtract_dark_flag and self.dark is not None) else None
        frame = subtract_dark(self.last_frame, use_dark)
        base = os.path.join("output", f"clouds_spectrum_{ts}")
        EX.write_spectrum_csv(base + ".csv", self.cal, frame, meta)
        pdfp = EX.write_pdf_report(base + ".pdf", self.cal, frame, meta)
        self._set_hint(f"exported clouds_spectrum_{ts}.csv + .pdf  ->  output/")
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            try:
                os.startfile(os.path.abspath(pdfp))     # open the report for the user
            except Exception:
                pass

    def _on_log_toggle(self, on):
        from spectro import export as EX
        if on:
            os.makedirs("output", exist_ok=True)
            self.logger = EX.SessionLogger(
                os.path.join("output", f"session_{EX.timestamp()}.csv"))
            self._set_hint("logging session to CSV ...")
        elif self.logger is not None:
            n, path = self.logger.count, self.logger.path
            self.logger.close()
            self.logger = None
            self._set_hint(f"logged {n} rows  ->  {os.path.basename(path)}")


class _CalibrationDialog(QtWidgets.QDialog):
    """Interactive pixel->nm recalibration: mark known lines, fit, save/load."""

    PRESETS = {
        "CCFL Hg/Ar": [(435.83, "Hg 436"), (546.07, "Hg 546"), (696.54, "Ar 697"),
                       (763.51, "Ar 764"), (810.37, "Ar 810")],
        "Hg pen lamp": [(435.83, "Hg 436"), (546.07, "Hg 546"), (578.01, "Hg 578"),
                        (696.54, "Ar 697")],
        "Lasers (B/G/R)": [(405.0, "405 nm"), (532.0, "532 nm"), (650.0, "650 nm")],
        "Custom": [],
    }

    def __init__(self, engine):
        super().__init__(engine)
        self.engine = engine
        self._armed = None
        self.setWindowTitle("Wavelength calibration")
        self.resize(380, 440)
        lay = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QHBoxLayout()
        self.ch_combo = QtWidgets.QComboBox(); self.ch_combo.addItems(["measurement", "reference"])
        self.ch_combo.setStyleSheet(engine._combo_style())
        self.preset = QtWidgets.QComboBox(); self.preset.addItems(list(self.PRESETS))
        self.preset.setStyleSheet(engine._combo_style())
        self.preset.currentTextChanged.connect(self._fill)
        top.addWidget(QtWidgets.QLabel("channel")); top.addWidget(self.ch_combo, 1)
        top.addWidget(QtWidgets.QLabel("source")); top.addWidget(self.preset, 1)
        lay.addLayout(top)

        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["nm", "line", "pixel"])
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)

        mk = QtWidgets.QHBoxLayout()
        b_mark = QtWidgets.QPushButton("Pick peak for selected line"); b_mark.clicked.connect(self._arm)
        b_add = QtWidgets.QPushButton("+ line"); b_add.clicked.connect(lambda: self._add_row(0.0, "custom"))
        mk.addWidget(b_mark, 1); mk.addWidget(b_add)
        lay.addLayout(mk)

        self.status = QtWidgets.QLabel("pick a source, select a line, then click its peak on the spectrum")
        self.status.setWordWrap(True); self.status.setStyleSheet("color:#5a6b7a; font-size:11px;")
        lay.addWidget(self.status)
        self.result = QtWidgets.QLabel(""); self.result.setStyleSheet(
            f"color:{NAVY}; font-family:Consolas,monospace; font-size:11px;")
        lay.addWidget(self.result)

        bb = QtWidgets.QHBoxLayout()
        for txt, fn in (("Fit & apply", self._fit), ("Save...", self._save),
                        ("Load...", self._load), ("Reset", self._reset)):
            b = QtWidgets.QPushButton(txt); b.clicked.connect(fn); bb.addWidget(b)
        lay.addLayout(bb)
        self._fill(self.preset.currentText())

    def _fill(self, name):
        self.table.setRowCount(0)
        for wl, lab in self.PRESETS.get(name, []):
            self._add_row(wl, lab)

    def _add_row(self, wl, lab):
        row = self.table.rowCount(); self.table.insertRow(row)
        self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(f"{wl:.2f}"))
        self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(lab))
        self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(""))

    def _arm(self):
        row = self.table.currentRow()
        if row < 0:
            self.status.setText("select a line row first"); return
        self._armed = row
        self.engine._cal_cb = self._on_click
        item = self.table.item(row, 1)
        self.status.setText(f"click the peak for {item.text() if item else 'line'} on the spectrum ...")

    def _on_click(self, data_x):
        if self._armed is None:
            return
        ch = self.engine.cal.by_role(self.ch_combo.currentText())
        px = self.engine._peak_pixel_near(data_x, ch)
        self.engine._cal_cb = None
        if px is None:
            self.status.setText("no frame / out of range - acquire a frame and retry"); return
        self.table.setItem(self._armed, 2, QtWidgets.QTableWidgetItem(f"{px:.2f}"))
        self.status.setText(f"marked pixel {px:.2f} - pick the next line, or Fit & apply")
        self._armed = None

    def _pairs(self):
        pts = []
        for row in range(self.table.rowCount()):
            wi, pi = self.table.item(row, 0), self.table.item(row, 2)
            if wi and pi and pi.text().strip():
                try:
                    pts.append((float(pi.text()), float(wi.text())))
                except ValueError:
                    pass
        return pts

    def _fit(self):
        pts = self._pairs()
        if len(pts) < 2:
            self.status.setText("mark at least 2 lines first"); return
        px = np.array([p[0] for p in pts]); wl = np.array([p[1] for p in pts])
        deg = 2 if len(pts) >= 3 else 1
        co = np.polyfit(px, wl, deg)
        a, b, c = (0.0, co[0], co[1]) if deg == 1 else (co[0], co[1], co[2])
        rms = float(np.sqrt(np.mean((wl - np.polyval(co, px)) ** 2)))
        self.engine.cal.set_poly(self.ch_combo.currentText(), a, b, c)
        self.engine._render_plot()
        self.result.setText(f"{'quadratic' if deg == 2 else 'linear'} fit, {len(pts)} pts\n"
                            f"a={a:.3e}  b={b:.4f}  c={c:.2f}\nRMS residual {rms:.2f} nm")
        self.status.setText("applied to the live plot - Save... to keep it")

    def _save(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save calibration", os.path.join(HERE, "calibration_user.json"), "JSON (*.json)")
        if path:
            self.engine.cal.save(path)
            self.status.setText(f"saved {os.path.basename(path)}")

    def _load(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load calibration", HERE, "JSON (*.json)")
        if path:
            self.engine.cal = Calibration.load(path)
            self.engine._render_plot()
            self.status.setText(f"loaded {os.path.basename(path)}")

    def _reset(self):
        # back to this instrument's factory file, not always the Duo's
        self.engine.cal = Calibration.load(
            _default_calibration(getattr(self.engine, "kind", "std")))
        self.engine._render_plot()
        self.result.setText("")
        self.status.setText("reset to the factory calibration")

    def closeEvent(self, ev):
        self.engine._cal_cb = None
        super().closeEvent(ev)


def main():
    mock = "--mock" in sys.argv
    kind = "edu" if "--edu" in sys.argv else None
    # --net HOST[:PORT]: detector on another machine running spectro.net_server
    host = None
    if "--net" in sys.argv:
        i = sys.argv.index("--net")
        if i + 1 >= len(sys.argv):
            raise SystemExit("--net needs HOST[:PORT], e.g. --net 192.168.100.10")
        host, kind = sys.argv[i + 1], "net"
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CLOUDS.SpectralEngine")
        except Exception:
            pass
    print("[CLOUDS] starting the Spectral Engine ...")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    ico = os.path.join(HERE, "assets", "clouds.ico")
    if os.path.exists(ico):
        app.setWindowIcon(QtGui.QIcon(ico))
    win = Engine(mock=mock, kind=kind, host=host)
    win.show()
    win._connect()
    if win.connected:
        win._start()
    print("[CLOUDS] ready - window open.")
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
