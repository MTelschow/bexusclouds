"""CLOUDS Spectral Engine - ground-test / bench software for the EURECA Duo.

Qt control panel + live dual-trace spectrum view (measurement Ch1 / reference
Ch2 on one detector). Adopts the CLOUDS design language from the Raytracing
Engine (docs/UI_STYLE.md). Talks only to spectro.driver.SpectrometerDriver.

    python -m clouds_ui                  # the EURECA Duo on this machine
    python -m clouds_ui --net 192.168.100.10
                                        # Duo on the flight Pi, live over the
                                        # cable (run spectro.net_server there)
    python -m clouds_ui --mock           # synthetic detector, for demo and
                                        # for the hardware-free checks

Unless ``mock`` is set, what this window draws from the detector is real
light. ``mock=True`` also serves the hardware-free checks (verify_qt.py,
tests/), and wherever it is set the window says so: in the title bar, in the
plot's source banner, and on the device line. It additionally refuses to
write or clear the stored dark frame, which is shared with real sessions.
"""
from __future__ import annotations

import os
import sys
import threading

import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure

from PyQt5 import QtCore, QtGui, QtWidgets

from spectro import dark as darkstore
from spectro.calibration import Calibration, subtract_dark
from spectro.driver import DriverError, open_driver, resolve_kind
from spectro import processing as P

from . import style
from . import timeline
from .flight import FlightPanel
from .sections import Section, SectionFlow, group_label
from .timeline import TimelineBuffer, TimelineView, fig_to_pixmap

# Repo root, not this package: assets/, calibration*.json and the Calibrate
# dialog's file pickers all live one level up now that the window moved into
# clouds_ui/.
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAVY = "#01386a"
# Readout font stack. Platform-native mono first: naming a font Qt cannot resolve
# (Consolas on macOS/Linux) makes it scan every installed family to build the alias
# table - ~100 ms at startup, logged as "qt.qpa.fonts: Populating font family aliases".
MONO = "Menlo,DejaVu Sans Mono,Consolas,monospace"
VERSION = "0.1.0"
RECONNECT_INTERVAL_MS = 3000   # auto-retry cadence after a driver/link error
#: The spectrum pane's floor on the horizontal splitter. The operator sets the
#: split, but not to the point where the trace stops being a trace.
MIN_PLOT_W = 420

#: Sections that start expanded, in either kind of session, and the order they
#: sit in at the top of the sidebar (`_build_panel` + `FlightPanel.sections`
#: build them in this order). These are what an operator steers the experiment
#: with and watches it answer on; everything else is set once and then left
#: alone. Titles are upper-case to match `Section.title_key`.
DEFAULT_OPEN = ("SPECTRUM SOURCE", "SENSORS", "COMMANDS", "ACTUATORS",
                "EVENTS")

#: Sections that start folded whichever half was asked for. Each is either
#: long (Timeline's two dozen series toggles, the View block) or set once and
#: forgotten (Device, Dark frame, Reference, Calibration, Export) - on screen
#: at startup they cost the sections above them the height they are read in.
#: Folding is display only, so a folded Timeline keeps recording.
DEFAULT_CLOSED = ("TIMELINE", "DEVICE", "ACQUISITION", "DARK FRAME",
                  "REFERENCE", "VIEW", "CALIBRATION", "EXPORT")

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


#: Both plots in the view render a matplotlib figure into a QLabel; the helper
#: lives with the timeline so there is one copy of it.
_fig_to_pixmap = fig_to_pixmap


# ----------------------------------------------------------------------- engine
class CloudsWindow(QtWidgets.QMainWindow):
    """The one operator interface: instrument on the left of the sidebar's
    order of business, flight above it, one spectrum view serving both.

    Two independent data paths meet here and are kept apart on purpose:

    * the **detector** through ``spectro.driver`` - continuous, every pixel in
      the channel window, and the only path that can *change* the hardware
      (exposure). Bench only: reaching it from the ground depends on the Pi's
      ``--bench-stream``, which is off in flight.
    * the **downlink** through ``clouds_gse.Receiver`` - 1 Hz, mean-binned to
      ~30 points per channel by the 2 kbit/s budget, plus housekeeping,
      events and the command uplink. The only path that exists in flight.

    Which one the spectrum shows is the operator's explicit choice
    (``self.source``) and never changes by itself, because the failure this
    guards against is reading a binned 1 Hz quick-look as a live instrument
    view. The plot says which source it is drawing, always.
    """

    def __init__(self, mock=False, kind=None, host=None,
                 receiver=None, commander=None, session=None,
                 source="detector", persist_dark=True,
                 mock_stack=None, link_factory=None):
        super().__init__()
        # The title is the one label that is on screen even when the window is
        # behind something else or in a screenshot someone later argues from,
        # so the simulation is named there first.
        self.setWindowTitle("CLOUDS Spectral Engine"
                            + ("  -  MOCK: SIMULATED DATA, NO HARDWARE"
                               if mock else ""))
        ico = os.path.join(HERE, "assets", "clouds.ico")
        if os.path.exists(ico):
            self.setWindowIcon(QtGui.QIcon(ico))
        screen = QtWidgets.QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        max_w = avail.width() if avail else 1720
        max_h = avail.height() if avail else 920
        # Wider than the old 1420: the sidebar packs its open sections into
        # columns rather than a scrolling strip (`SectionFlow`), and on a
        # laptop-height screen that is two columns. Asking for the width they
        # need up front is what keeps the spectrum from paying for them.
        self.resize(min(1720, max_w), min(980, max_h))
        self.futura = self._load_futura()

        self.kind = resolve_kind(kind)
        # One instrument family, one factory file: Calibration.load(None) reads
        # CLOUDS_CALIBRATION if it is set, else calibration.json.
        self.cal = Calibration.load()
        self.host = host            # only meaningful for kind="net"
        extra = {"host": host} if self.kind == "net" else {}
        self.driver = open_driver(mock=mock, kind=self.kind, **extra)
        self.mock = mock
        # The stored dark frame is shared with every later session, so a
        # synthetic one must not be able to reach a real measurement. The
        # hardware-free checks (verify_qt.py) still exercise the store - they
        # are the only thing that can - which is why this is its own switch
        # and not simply `not mock`: `python -m clouds_ui --mock` turns it off.
        self._persist_dark = persist_dark
        self.connected = False
        self.info = None
        self.running = False
        self._driver_lock = threading.RLock()   # serializes driver I/O vs. the live-tick worker
        self._acq_worker = None
        self._resume_on_reconnect = False   # was live when the link dropped -> resume on reconnect
        self._ever_connected = False        # has the detector ever answered this session
        self._reconnect_worker = None
        self._auto_worker = None        # exposure hunt, off the GUI thread (see _auto_expose)
        self._auto_resume = False       # was live when the hunt took the detector over
        self._reconnect_timer = QtCore.QTimer(self)
        self._reconnect_timer.setInterval(RECONNECT_INTERVAL_MS)
        self._reconnect_timer.timeout.connect(self._try_reconnect)

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
        self._dark_meta = None      # DarkFrame the counts came from, or None
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

        # --- flight half (downlink + uplink). All three may be None: the
        # instrument-only bench case, where the flight sections are built but
        # report "no telemetry" / "no command link" rather than being hidden.
        # Hiding them would make the one UI silently become two again.
        self.rx = receiver
        self.commander = commander
        self.session = session
        #: The simulated flight chain under --mock (clouds_ui.mock_stack), or
        #: None. Owned here so that Restart can stop and re-create it with
        #: the receiver it downlinks to.
        self.mock_stack = mock_stack
        #: Zero-argument callable returning an object with `receiver`,
        #: `commander`, `session` and `mock_stack` attributes (main.Links).
        #: Restart uses it to build the flight half again from the flags the
        #: session started with; None means Restart can only re-open the
        #: detector and the flight half stays as it is (there is none, or the
        #: caller built it by hand, as verify_qt.py does).
        self._link_factory = link_factory
        self._restarting = False
        #: "detector" | "downlink" - what the spectrum view is drawing.
        self.source = source
        self._src_bin = None        # quick-look bin factor, for the x axis
        self._src_exp_ms = None     # exposure the downlinked frame was taken at

        # Housekeeping history for the timeline under the spectrum. Filled
        # from the flight tick, not from the receiver's thread: the receiver
        # must never touch Qt, and the buffer is read by the render slot.
        self.tl_buf = TimelineBuffer()
        self._tl_last_t = 0.0       # last HK arrival recorded, to sample once per packet

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._tick_live)
        # Flight refresh is its own, slower timer: housekeeping arrives at
        # 1 Hz, so polling it on the 60 ms acquisition tick would be 16x of
        # nothing. Poll-based on purpose - the receiver's thread must never
        # touch Qt (the old dashboard's rule, kept).
        self.flight_timer = QtCore.QTimer(self)
        self.flight_timer.setInterval(500)
        self.flight_timer.timeout.connect(self._tick_flight)

        # Horizontal splitter, not a fixed sidebar: how much of the window
        # goes to the trace and how much to the controls is the operator's,
        # and it changes with the job - a calibration pass wants the
        # spectrum, a commanding pass wants the sidebar. The sidebar re-packs
        # into however many columns the width it is dragged to can hold
        # (`_reflow_panel`), so widening it turns into columns rather than
        # into empty space.
        central = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        central.setChildrenCollapsible(False)
        central.setHandleWidth(4)
        central.setStyleSheet(
            f"QSplitter::handle{{background:{style.BORDER};}}"
            f"QSplitter::handle:hover{{background:{NAVY};}}")
        self.setCentralWidget(central)
        view = self._build_view()
        view.setMinimumWidth(MIN_PLOT_W)
        central.addWidget(view)
        central.addWidget(self._build_panel())
        central.setStretchFactor(0, 1)      # extra width goes to the trace
        central.setStretchFactor(1, 0)
        central.splitterMoved.connect(lambda *_: self._reflow_panel())
        self._h_split = central
        # Two columns to start where the window is wide enough for them,
        # which is the layout the default sections were sized against; one
        # otherwise, and the operator can drag for the second.
        want = self._panel_width_for(2)
        if self.width() - want < MIN_PLOT_W:
            want = self._panel_width_for(1)
        central.setSizes([max(MIN_PLOT_W, self.width() - want), want])
        self._update_source_banner()
        self._render_plot()
        self._update_stats()
        if self.rx is not None:
            self.flight_timer.start()
        self._set_hint("press Connect, then Run" if self.source == "detector"
                       else "waiting for the downlink")
        self._restore_stored_dark()

    def fold_for(self, flight: bool) -> None:
        """Set which sections are on screen at startup.

        `DEFAULT_OPEN` is expanded and `DEFAULT_CLOSED` folded in either kind
        of session; only the housekeeping grid follows the half that was
        asked for. Both halves stay built and live either way - folding is
        display only - so a bench session can open Commands without a
        restart, and a flight session can still look at the instrument
        sections to read what the settings were. What this decides is only
        what is on screen first.
        """
        flight_secs = set(self.flight.sections)
        with self.flow.held():
            self._fold_sections(flight, flight_secs)
        self._reflow_panel()

    def _fold_sections(self, flight: bool, flight_secs) -> None:
        for sec in self._sections:
            if sec.title_key in DEFAULT_OPEN:
                # The group at the top of the sidebar: what the operator
                # steers the experiment and the plot with, in either kind of
                # session. Open regardless of which half was asked for -
                # these are the sections you look for first.
                sec.set_open(True)
            elif sec.title_key in DEFAULT_CLOSED:
                sec.set_open(False)
            else:
                # What is left - the housekeeping grid - follows the half
                # that was asked for.
                sec.set_open(sec in flight_secs if flight
                             else sec not in flight_secs)

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
        """The left half: spectrum on top, housekeeping history below.

        A vertical `QSplitter`, not a fixed split, because the two halves are
        wanted in different proportions at different times - a calibration
        pass is all spectrum, an ascent is all timeline - and either can be
        dragged shut without a restart or a menu.

        `self._view` stays the **spectrum pane**, not the splitter: the stats,
        cursor and source-banner cards are children of it and are positioned
        against its geometry, and the resize handler re-renders the spectrum
        from its size. Pointing it at the container would float those cards
        over the timeline and size the figure to both halves.
        """
        split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        split.setStyleSheet(
            f"QSplitter::handle{{background:{style.BORDER}; height:3px;}}"
            f"QSplitter::handle:hover{{background:{NAVY};}}")
        split.setChildrenCollapsible(True)

        view = QtWidgets.QWidget()
        view.setStyleSheet("background:#eef3f8;")
        view.setMinimumHeight(220)
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
        cap = self.stats_cap = QtWidgets.QLabel("LIVE")
        cap.setStyleSheet("color:#8a97a3; font-size:9px; letter-spacing:2px;"
                          "border:0; background:transparent;")
        sb.addWidget(cap)
        self.stats = QtWidgets.QLabel("")
        self.stats.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.stats.setStyleSheet(
            f"color:{NAVY}; font-family:{MONO}; font-size:12px;"
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
            f"color:{NAVY}; font-family:{MONO}; font-size:12px;"
            "font-weight:bold; border:0; background:transparent;")
        cb.addWidget(self.cursor_lbl)
        self.cursor_box.adjustSize()
        self.cursor_box.hide()
        self.plot.setMouseTracking(True)
        self.plot.installEventFilter(self)

        # Which source the plot is drawing, stated in the plot. Top-centre so
        # it is not something you have to go looking for in the sidebar.
        self.src_banner = QtWidgets.QLabel(view)
        self.src_banner.setAlignment(QtCore.Qt.AlignCenter)

        view.installEventFilter(self)

        # --- housekeeping over time, under the spectrum --------------------
        self.timeline = TimelineView(self.tl_buf)
        if self.rx is None:
            self.timeline.set_note("no downlink in this session")
        split.addWidget(view)
        split.addWidget(self.timeline)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([560, 300])
        return split

    def eventFilter(self, obj, ev):
        if obj is getattr(self, "_view", None) and ev.type() == QtCore.QEvent.Resize:
            self.stats_box.adjustSize()
            self.stats_box.move(16, 16)
            self._place_source_banner()
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
        """One sidebar for both halves.

        Flight sits above Instrument because that is the order of an
        operator's attention in flight, and each group is a collapsible
        `Section` so the whole thing fits a laptop screen: keep open the two
        or three you are working with, fold the rest. Folding is display only
        - a folded section keeps updating (see sections.Section).
        """
        panel = QtWidgets.QWidget()
        panel.setStyleSheet(f"background:{style.PANEL_BG};")
        outer = QtWidgets.QVBoxLayout(panel)
        outer.setContentsMargins(16, 14, 16, 12)
        outer.setSpacing(10)
        self._sections: list[Section] = []
        # Everything in the sidebar goes into the flow, which decides how many
        # columns it all needs for the height on offer - including the
        # wordmark, which is a flow item rather than a header above it. A
        # header would be ~100 px the columns never get to use, and on a
        # 1440x870 screen that is the difference between fitting and not.
        # `outer` carries only the hint line, which spans the full width
        # because it is the panel's status line, not one column's.
        self.flow = SectionFlow()

        def sec(title, open_=True):
            """Start a new collapsible section and return its body layout, so
            the group-building code below stays plain `v.addWidget` calls."""
            s_ = Section(title, open_=open_)
            self._sections.append(s_)
            self.flow.add(s_)
            return s_.body

        brand = QtWidgets.QWidget()
        head = QtWidgets.QVBoxLayout(brand)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        self.flow.add(brand)
        outer.addWidget(self.flow, 0, QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        v = head

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
        # Restart sits in the header, not in Device or in a flight section,
        # because it is the one control that acts on both halves: the
        # detector link and the downlink, uplink, session log and (mock)
        # flight chain all come back as if the app had just been launched -
        # with the window, its layout and the operator's settings intact.
        self.btn_restart = QtWidgets.QPushButton("Restart")
        self.btn_restart.setStyleSheet(self._flat_btn())
        self.btn_restart.setToolTip(
            "Restart everything without closing the window: reopen the "
            "detector, and bring the downlink receiver, the command link and "
            "the session log up again as a fresh session. Exposure, dark, "
            "reference, view and zoom are kept; the housekeeping timeline "
            "and event list start over with the new session.")
        self.btn_restart.clicked.connect(lambda: self.restart())
        ver = QtWidgets.QHBoxLayout()
        ver.setContentsMargins(0, 0, 0, 0)
        ver.setSpacing(8)
        ver.addWidget(sub, 1)
        ver.addWidget(self.btn_restart, 0)
        v.addWidget(logo)
        v.addLayout(ver)
        rule = QtWidgets.QFrame()
        rule.setFrameShape(QtWidgets.QFrame.HLine)
        rule.setStyleSheet("color:#dde3e9;")
        v.addWidget(rule)

        # --- Source: what the spectrum view is drawing ---------------------
        # Top of the sidebar because it governs the whole plot, and explicit
        # because the two sources are different measurements of different
        # fidelity that would otherwise look alike.
        v = sec("Spectrum source")
        self.rb_detector = QtWidgets.QRadioButton("Detector  -  continuous, "
                                                  "full resolution")
        self.rb_downlink = QtWidgets.QRadioButton("Downlink  -  1 Hz, binned")
        for rb in (self.rb_detector, self.rb_downlink):
            rb.setStyleSheet(style.radio_style())
            v.addWidget(rb)
        self.rb_detector.setChecked(self.source == "detector")
        self.rb_downlink.setChecked(self.source == "downlink")
        self.rb_detector.toggled.connect(
            lambda on: self._on_source("detector") if on else None)
        self.rb_downlink.toggled.connect(
            lambda on: self._on_source("downlink") if on else None)
        if self.rx is None:
            self.rb_downlink.setEnabled(False)
            self.rb_downlink.setToolTip("No downlink receiver in this session")

        # --- Timeline: which housekeeping series the lower plot draws ------
        self._build_timeline_section(sec("Timeline"))

        # --- Flight: housekeeping, commanding, actuators, events -----------
        self.flight = FlightPanel(self.rx, self.commander, self.session)
        self._sections.extend(self.flight.sections)
        for s_ in self.flight.sections:
            self.flow.add(s_)

        # --- Device ---
        v = sec("Device")
        self.btn_connect = QtWidgets.QPushButton("Connect")
        self.btn_connect.setStyleSheet(self._primary_btn())
        self.btn_connect.clicked.connect(self._toggle_connect)
        v.addWidget(self.btn_connect)
        self.lbl_conn_error = QtWidgets.QLabel("")
        self.lbl_conn_error.setWordWrap(True)
        self.lbl_conn_error.setStyleSheet("color:#b3261e; font-size:11px; font-weight:bold;")
        v.addWidget(self.lbl_conn_error)
        self.lbl_device = QtWidgets.QLabel("not connected")
        self.lbl_device.setWordWrap(True)
        self.lbl_device.setStyleSheet("color:#5a6b7a; font-size:11px;")
        v.addWidget(self.lbl_device)

        # --- Acquisition ---
        v = sec("Acquisition")
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
        # The lambda is load-bearing: `clicked` carries a `checked` bool, and
        # PyQt5 binds it to the first parameter of any slot that will take one -
        # so a direct connect called _auto_expose(target=False). tgt then came
        # out 0, the proportional step clamped to its 0.2 floor every iteration,
        # and the hunt could only ever DIVIDE the exposure: it ran all `iters`
        # probes down to the 0.02 ms rail and returned a black spectrum, unless
        # the very first probe happened to land in the band.
        self.btn_auto.clicked.connect(lambda: self._auto_expose())
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
                                  "The integration controls are greyed while this is on - uncheck\n"
                                  "it to set the integration time by hand.")
        self.chk_track.toggled.connect(self._on_track)
        self.chk_track.setChecked(True)             # auto integration time is on by default
        v.addWidget(self.chk_track)

        # --- Dark frame ---
        v = sec("Dark frame")
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
        # What is actually being subtracted, and whether it applies at the
        # current exposure. A dark is invisible in the trace once it works, so
        # the only way to know a stale one is in play is to say so.
        self.lbl_dark = QtWidgets.QLabel("no dark - press Capture dark")
        self.lbl_dark.setStyleSheet(
            f"color:#6b7784; font-family:{MONO}; font-size:10px;")
        self.lbl_dark.setWordWrap(True)
        self.lbl_dark.setToolTip(
            "A captured dark is saved as the default and loaded on the next "
            "start, together with the exposure it was taken at.\n"
            "Clear removes both.")
        v.addWidget(self.lbl_dark)
        self.offset_combo = QtWidgets.QComboBox()
        self.offset_combo.setStyleSheet(self._combo_style())
        self.offset_combo.addItems(["offset: none", "subtract minimum", "subtract dark pixels"])
        self.offset_combo.setToolTip("Extra per-frame baseline: the signal minimum, or the\n"
                                     "on-chip optical-black (dark-pixel) level read from the sensor.")
        self.offset_combo.currentIndexChanged.connect(self._on_offset)
        v.addWidget(self.offset_combo)

        # --- Reference (flat-field / 100% line) ---
        v = sec("Reference", open_=False)
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
        v = sec("View")
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
        v = sec("Calibration", open_=False)
        self.btn_cal = QtWidgets.QPushButton("Calibrate wavelength...")
        self.btn_cal.setStyleSheet(self._flat_btn())
        self.btn_cal.clicked.connect(self._open_calibration)
        v.addWidget(self.btn_cal)

        # --- Export ---
        v = sec("Export")
        self.btn_export = QtWidgets.QPushButton("Export CSV + PDF")
        self.btn_export.setStyleSheet(self._flat_btn())
        self.btn_export.clicked.connect(self._export)
        v.addWidget(self.btn_export)
        self.chk_log = QtWidgets.QCheckBox("log session to CSV")
        self.chk_log.setStyleSheet(self._checkbox_style())
        self.chk_log.toggled.connect(self._on_log_toggle)
        v.addWidget(self.chk_log)

        outer.addStretch(1)
        self.hint = QtWidgets.QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color:{style.HINT}; font-size:11px;"
                                "font-style:italic;")
        outer.addWidget(self.hint)

        # The scroll area is the fallback, not the layout: the flow packs the
        # open sections into the height that is there, and only a window
        # shorter than three columns can hold makes a scrollbar appear.
        # Horizontal scrolling stays off - a clipped sidebar is a bug, and
        # the flow sizes itself to whole columns so it cannot want one.
        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        # One column is the floor - narrower clips the command grid - and
        # MAX_COLS the ceiling, so dragging the handle out past the widest
        # useful sidebar gives the width back to the trace instead of
        # stretching three columns of air.
        scroll.setMinimumWidth(self._panel_width_for(1))
        scroll.setMaximumWidth(self._panel_width_for(SectionFlow.MAX_COLS))
        self._panel_scroll = scroll
        self._panel_chrome = 14 + 12        # outer margins, for the budget
        self._reflow_panel()
        return scroll

    def _panel_width_for(self, cols: int) -> int:
        """Sidebar width that holds `cols` columns: the columns, the gaps
        between them, the panel's own margins and the vertical scrollbar's
        width - which is reserved whether or not the bar is showing, so that
        one appearing cannot change the column count and make it vanish
        again."""
        sb = self._panel_scroll.verticalScrollBar() if hasattr(
            self, "_panel_scroll") else None
        pad = sb.sizeHint().width() if sb is not None else 16
        return (cols * SectionFlow.COL_W + (cols - 1) * SectionFlow.GAP
                + 2 * 16 + pad)

    #: Height the sidebar needs beyond its sections: wordmark, subtitle, rule,
    #: the hint line, and the spacing between those and the flow.
    _PANEL_HEAD_H = 120

    def _reflow_panel(self) -> None:
        """Re-pack the sidebar for the space it currently has.

        Driven from the window's resize and the splitter's handle rather than
        from the panel, because the panel is as tall as its content and so
        can report neither the height it has nor the width it was given.

        Nothing here sets the sidebar's width - that is the operator's, via
        the splitter. What this decides is how many columns to spend it on.
        """
        if not hasattr(self, "flow") or not hasattr(self, "_panel_scroll"):
            return
        avail_h = self._panel_scroll.viewport().height() or self.height()
        panel = self._panel_scroll.widget()
        # What the sidebar spends on things that are not sections - wordmark,
        # subtitle, rule, hint, margins - measured rather than guessed, so a
        # longer hint line does not quietly push the last section off screen.
        chrome = panel.sizeHint().height() - self.flow.sizeHint().height()
        if chrome <= 0:
            chrome = self._PANEL_HEAD_H + self._panel_chrome
        budget = max(200, avail_h - chrome)
        # The scrollbar's width is reserved whether or not it is showing: a
        # bar that appears would otherwise narrow the sidebar by its own
        # width, drop a column, make the content fit, and vanish again.
        sb = self._panel_scroll.verticalScrollBar()
        pad = sb.sizeHint().width() if sb is not None else 16
        width = max(SectionFlow.COL_W,
                    self._panel_scroll.width() - 2 * 16 - pad)
        self.flow.relayout(budget, width)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._reflow_panel()

    def _build_timeline_section(self, v):
        """Which housekeeping series the lower plot draws, and over how long.

        The toggles live in the sidebar rather than under the plot because
        there are two dozen of them: a strip of checkboxes wide enough to
        hold that would cost the timeline the height it exists for. They are
        grouped by the part that produces them, the same way the Sensors
        section is, so "which of these can I believe" has one answer in both
        places.

        A part the carrier does not have gets a disabled box that says so,
        not a missing row: an operator looking for a rail current needs to
        find out that the monitor is unpopulated, and an absent checkbox
        teaches them nothing.
        """
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        lab = QtWidgets.QLabel("Span")
        lab.setStyleSheet(f"color:{style.TEXT}; font-size:11px;")
        row.addWidget(lab)
        self.cmb_tl_window = QtWidgets.QComboBox()
        self.cmb_tl_window.setStyleSheet(self._combo_style())
        for name, _secs in timeline.WINDOWS:
            self.cmb_tl_window.addItem(name)
        self.cmb_tl_window.setCurrentIndex(1)            # 5 min
        self.cmb_tl_window.currentIndexChanged.connect(self._on_tl_window)
        row.addWidget(self.cmb_tl_window, 1)
        btn = QtWidgets.QPushButton("Clear")
        btn.setStyleSheet(self._flat_btn())
        btn.setToolTip("Discard the recorded history. The session log on disk "
                       "is not touched.")
        btn.clicked.connect(self._clear_timeline)
        row.addWidget(btn)
        v.addLayout(row)

        self._tl_boxes: dict[str, QtWidgets.QCheckBox] = {}
        for group, members in timeline.GROUPS:
            v.addWidget(group_label(group))
            grid = QtWidgets.QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(2)
            for i, s in enumerate(members):
                box = QtWidgets.QCheckBox(s.label)
                box.setStyleSheet(self._checkbox_style())
                box.setChecked(s.key in timeline.DEFAULT_KEYS)
                if not s.fitted:
                    box.setEnabled(False)
                    box.setToolTip("No part fitted on this carrier - there is "
                                   "no reading to plot.")
                else:
                    box.setToolTip(f"{s.label} [{s.unit}] from {s.group}")
                box.toggled.connect(self._on_tl_series)
                self._tl_boxes[s.key] = box
                grid.addWidget(box, i // 2, i % 2)
            v.addLayout(grid)

        note = QtWidgets.QLabel(
            "1 Hz from the downlink. Series sharing a unit share an axis; a "
            "gap is a reading that does not exist, never a zero.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{style.SECTION}; font-size:10px;"
                           "font-style:italic;")
        v.addWidget(note)

    # ------------------------------------------------------------- timeline
    def _on_tl_series(self, *_):
        self.timeline.set_selection([k for k, b in self._tl_boxes.items()
                                     if b.isChecked()])

    def _on_tl_window(self, idx):
        self.timeline.set_window(timeline.WINDOWS[idx][1])

    def _clear_timeline(self):
        self.tl_buf.clear()
        self._tl_last_t = 0.0
        self.timeline.refresh()

    def _sample_timeline(self):
        """Record one point per housekeeping packet.

        Keyed on the receiver's `last_hk_time`, not on this timer: the flight
        tick runs at 2 Hz against a 1 Hz stream, so polling blind would record
        every packet twice and halve the real span of the buffer. A repeated
        timestamp means no new packet arrived, which is exactly the case a
        dropout must be allowed to show as a gap.
        """
        hk = getattr(self.rx, "last_hk", None)
        t = getattr(self.rx, "last_hk_time", 0.0)
        if hk is None or t <= self._tl_last_t:
            return
        self._tl_last_t = t
        self.tl_buf.append(t, hk)
        self.timeline.refresh()

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
        # The servo and the auto hunt set the exposure from code, and they have
        # to move BOTH widgets (see _show_exposure) - the spin box alone leaves
        # the slider parked at a stale position that contradicts it.
        sl.to_pos = to_pos
        return w, sl, sp

    # ------------------------------------------------------- programmatic set
    def _show_exposure(self, ms):
        """Put `ms` on the integration widgets without re-entering `_on_exposure`.

        Both of them: the spin box and the log slider are two views of one
        value, and every code path that moved only the spin box (auto hunt,
        tracking servo, stored-dark restore) left the slider showing the
        exposure from before - which then looked like the slider was wrong,
        and a drag from that stale position jumped the exposure."""
        for wdg, val in ((self.sp_exp, ms), (self.sl_exp, self.sl_exp.to_pos(ms))):
            wdg.blockSignals(True)
            wdg.setValue(val)
            wdg.blockSignals(False)

    def _set_exposure_enabled(self, on):
        """Grey the integration controls while something else owns the exposure.

        While `auto integration time` is on the servo rewrites the exposure
        every frame, so a manual value survives at most one frame - a live
        control that does nothing is worse than a greyed one."""
        for wdg in (self.sl_exp, self.sp_exp):
            wdg.setEnabled(bool(on))

    # -------------------------------------------------------------- callbacks
    def _on_exposure(self, v):
        self.exposure_ms = float(v)
        if self._track:                     # belt and braces: the controls are
            self.chk_track.setChecked(False)   # greyed while tracking, and the
                                            # servo's own writes go through
                                            # _show_exposure with signals blocked
        if self.dark is not None and not self._dark_exposure_ok():
            self._set_hint(f"dark is for {self._dark_meta.exposure_ms:g} ms - held back "
                           f"at {self.exposure_ms:g} ms; recapture to use it here")
        self._update_dark_label()
        if self.connected and not self.running:
            self._single()

    def _on_track(self, on):
        self._track = bool(on)
        self._track_msg = ""
        self._oob_count = 0
        self._set_exposure_enabled(not self._track)
        self._set_hint("auto integration time ON - holding 60-80% full scale"
                       if on else "auto integration time off")
        if on and self.connected:
            if not self.running:
                self._start()               # tracking only does anything live
            # Snap from cold once, then the servo tracks smoothly. The hint goes
            # up first because this now returns immediately - the hunt runs on a
            # worker and posts its own progress and result.
            self._auto_expose()

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
        elif on and not self._dark_exposure_ok():
            self._set_hint(f"dark was taken at {self._dark_meta.exposure_ms:g} ms - "
                           f"not subtracted at {self.exposure_ms:g} ms; recapture it")
        self._update_dark_label()
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
        fr = subtract_dark(frame, self._dark_in_use())
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
    def _disconnect_ui(self, hint: str, error: str = "") -> None:
        """Tear down to 'not connected', for a manual Disconnect click or a
        driver error that leaves the link unusable. `error`, if given, stays
        posted under the Connect button until the next successful connect -
        the bottom hint line gets overwritten by whatever the operator does
        next, so it alone isn't a reliable place to notice a dropped link."""
        self._stop()
        # _stop() only stops the QTimer - a live tick already handed to
        # _AcquisitionWorker is still inside grab(). close() nulls the vendor
        # library handle and the pixel-buffer pointer, so closing under that
        # thread is a ctypes call into a stopped camera: a segfault with no
        # Python traceback. closeEvent() waits on the worker for exactly this
        # reason; here the (re-entrant) driver lock does the same job without
        # blocking on a hunt that may have seconds left to run.
        try:
            with self._driver_lock:
                self.driver.close()
        except Exception:
            pass
        self.connected = False
        self.info = None
        self.btn_connect.setText("Connect")
        self.lbl_device.setText("not connected")
        self.lbl_conn_error.setText(error)
        self._set_hint(hint)
        self._update_source_banner()

    def _on_driver_error(self, exc) -> None:
        """A synchronous driver call (single-shot / auto-expose / dark or
        reference capture) failed outside the live-tick worker. PyQt5 aborts
        the process on an unhandled exception in a slot, so this must never
        propagate - drop the link cleanly and let the operator reconnect."""
        self._resume_on_reconnect = self.running
        retry_s = RECONNECT_INTERVAL_MS // 1000
        self._disconnect_ui(f"link lost - retrying every {retry_s}s ...",
                            error=f"Link lost: {exc}"[:200])
        self._reconnect_timer.start()

    def _toggle_connect(self):
        if self.connected:
            self._resume_on_reconnect = False   # deliberate disconnect - don't auto-resume later
            self._reconnect_timer.stop()
            self._disconnect_ui("disconnected")
        else:
            self._connect()

    def _on_connected(self, info) -> None:
        """Shared by a manual Connect click and a successful background retry."""
        self._reconnect_timer.stop()
        self.info = info
        self.connected = True
        self._applied_us = None
        self.btn_connect.setText("Disconnect")
        self.lbl_conn_error.setText("")
        inst = self.cal.instrument
        model = (self.info.model if (self.info.model and "-" in self.info.model)
                 else inst.get("board", self.info.model or "e9u_LSMD"))
        serial = self.info.serial or inst.get("serials", {}).get("eureca", "?")
        port = self.info.com_port or ("MOCK" if self.info.mock else "")
        self.lbl_device.setText(
            f"{model}  SN {serial}\n{inst.get('detector', '')}  "
            f"{self.info.pixels}px  {port}".strip())
        # The banner names the detector's state, so it follows it.
        self._update_source_banner()
        if self._resume_on_reconnect:
            # was live when the link died (Ethernet or USB pull, either can
            # crash/drop the far end), or is the startup path's standing
            # intent to be live - resume without waiting for the operator to
            # notice and press Run again.
            first = not self._ever_connected
            self._resume_on_reconnect = False
            self._start()
            self._set_hint("connected - live" if first
                           else "reconnected - live resumed")
        else:
            self._set_hint("connected - press Run for live, or Single")
        self._ever_connected = True
        # No eager _auto_expose() snap here: it hunts over several blocking
        # driver round-trips (settle grabs + a 7-frame average per probe,
        # up to 8 iterations) - fine for a manual toggle, but over --net or
        # slow hardware it would stall startup for seconds. The continuous
        # servo (_track_exposure) converges gradually once live instead.

    def start_detector(self) -> None:
        """Startup path: connect and go live, and keep trying if the detector
        is not there yet.

        The detector can be seconds behind the window at start - the Pi's
        --bench-stream comes up with the flight app, and a USB Duo can lose
        the first ``search_for_camera`` after a replug. Every *later* driver
        error arms the 3 s retry; the one at startup did not, so a transient
        left the instrument half dead for the whole session with only a label
        to say so, and restarting the app was the operator's fix. Same retry
        here, with live remembered as the intent so the attempt that gets
        through starts it.
        """
        self._resume_on_reconnect = True
        self._connect(retry=True)

    def _connect(self, retry: bool = False):
        # A manual click takes over from any auto-retry in flight - but if it
        # fails, hand the retry back rather than dropping it: a click that
        # came a second too early must not disarm the loop that would have
        # got there on its own.
        was_retrying = self._reconnect_timer.isActive()
        self._reconnect_timer.stop()
        try:
            with self._driver_lock:
                info = self.driver.connect()
        except DriverError as e:
            self.connected = False
            msg = str(e).split('\n')[0]
            self.lbl_device.setText("connection failed")
            self.lbl_conn_error.setText(msg[:200])
            try:
                self.driver.close()        # release a half-opened device
            except Exception:
                pass
            if retry or was_retrying:
                retry_s = RECONNECT_INTERVAL_MS // 1000
                self._set_hint(f"{msg[:80]} - retrying every {retry_s}s ...")
                self._reconnect_timer.start()
            else:
                self._resume_on_reconnect = False
                self._set_hint(msg)
            # The window is launched from a terminal and the reason is
            # otherwise a small red label in the sidebar.
            print(f"[CLOUDS] detector: {msg}")
            return
        self._on_connected(info)

    # -- background auto-retry (started by _on_driver_error) -----------------

    def _try_reconnect(self):
        if self.connected or self._reconnect_worker is not None:
            return   # already up, or a previous attempt is still in flight

        def attempt():
            with self._driver_lock:
                return self.driver.connect()

        w = _AcquisitionWorker(attempt, self)
        w.done.connect(self._on_reconnect_done)
        w.failed.connect(self._on_reconnect_failed)
        w.finished.connect(self._on_reconnect_worker_finished)
        self._reconnect_worker = w
        w.start()

    def _on_reconnect_worker_finished(self):
        w, self._reconnect_worker = self._reconnect_worker, None
        w.deleteLater()

    def _on_reconnect_done(self, info):
        self._on_connected(info)

    def _on_reconnect_failed(self, msg):
        retry_s = RECONNECT_INTERVAL_MS // 1000
        self.lbl_conn_error.setText(f"Link lost: {msg}"[:200])
        self._set_hint(f"link down, retrying every {retry_s}s ({str(msg)[:80]})")

    def closeEvent(self, ev):
        """Tear down cleanly when the window closes: stop the live timer, let
        any in-flight tick finish, and release the camera so a queued tick
        can't touch a closing USB device."""
        try:
            self._stop()
            self.timer.stop()
            self._reconnect_timer.stop()
            self.flight_timer.stop()
            if self._acq_worker is not None:
                self._acq_worker.wait()
            if self._auto_worker is not None:
                self._auto_worker.wait()
            if self._reconnect_worker is not None:
                self._reconnect_worker.wait()
            if self.connected:
                self.driver.close()
        except Exception:
            pass
        self.close_links()
        super().closeEvent(ev)

    def close_links(self) -> None:
        """Shut the flight half down: command link, mock chain, receiver,
        then the session log. Shared by closeEvent and Restart, and safe to
        call twice - everything is set to None once closed.

        The order is the data's: the receiver's thread writes into the
        session log from its callbacks, so the log closes only after the
        receiver has stopped, or a packet landing in between hits a closed
        file from the receiver's thread. The summary is written here because
        it needs the receiver's gap counters, which die with the receiver.
        """
        rx, cmd, session, stack = (self.rx, self.commander, self.session,
                                   self.mock_stack)
        self.rx = self.commander = self.session = self.mock_stack = None
        gaps = rx.gaps if rx is not None else None
        for step in ((lambda: cmd.close()) if cmd is not None else None,
                     (lambda: stack.stop()) if stack is not None else None,
                     (lambda: rx.stop()) if rx is not None else None):
            if step is None:
                continue
            try:
                step()
            except Exception:
                pass
        if session is not None:
            try:
                session.export_summary(
                    session.hk_path.replace("_hk.csv", "_summary.json"), gaps)
            except Exception:
                pass
            try:
                session.close()
            except Exception:
                pass

    def restart(self) -> None:
        """Restart everything the window talks to, without closing the window.

        The detector driver is closed and re-opened; the downlink receiver,
        the command link, the session log and the mock flight chain are torn
        down and built again from the session's own flags (`link_factory`);
        then the startup sequence runs as `main` ran it. What the operator
        set - exposure, averaging, dark, reference, view, axis, zoom, fold
        state, the interlock checkbox - is kept, because none of it belonged
        to a connection. What the connections produced - housekeeping,
        events, the timeline, the gap counters, the session file - starts
        over, and the old session is closed with its summary like any other.

        Why not re-exec the process: the window is the thing the operator
        does not want to lose. Re-plugging the cable or power-cycling the
        Pi is what this is for, and the software following that should not
        cost the layout and the last ten minutes of context on screen.

        Runs on the GUI thread and blocks it while in-flight workers finish
        (the same wait closeEvent does); the hint says so first. Their
        finished slots still fire when the event loop is pumped below, so
        the instrument half is torn down only after they have run, against
        the driver and state they expect - `_restarting` keeps those slots
        from starting the live loop again in between.
        """
        if self._restarting:
            return
        self._restarting = True
        self.btn_restart.setEnabled(False)
        self._set_hint("restarting ...")
        QtWidgets.QApplication.processEvents()
        try:
            # -- instrument half down -----------------------------------------
            # was_connected also covers a link that dropped and is mid-retry:
            # that operator wants the detector back just as much.
            was_connected = self.connected or self._reconnect_timer.isActive()
            self._reconnect_timer.stop()
            self._resume_on_reconnect = False
            self._stop()
            for w in (self._acq_worker, self._auto_worker, self._reconnect_worker):
                if w is not None:
                    w.wait()
            for _ in range(50):
                if (self._acq_worker is None and self._auto_worker is None
                        and self._reconnect_worker is None):
                    break
                QtWidgets.QApplication.processEvents()
            self._auto_resume = False
            self._stop()
            self._disconnect_ui("restarting ...")
            extra = {"host": self.host} if self.kind == "net" else {}
            self.driver = open_driver(mock=self.mock, kind=self.kind, **extra)

            # -- flight half down, then up --------------------------------------
            link_error = ""
            if self._link_factory is not None:
                self.close_links()
                try:
                    links = self._link_factory()
                except Exception as e:      # e.g. the UDP port taken meanwhile
                    link_error = str(e).split("\n")[0]
                else:
                    self.rx = links.receiver
                    self.commander = links.commander
                    self.session = links.session
                    self.mock_stack = links.mock_stack
            self.flight.rebind(self.rx, self.commander, self.session)
            self.rb_downlink.setEnabled(self.rx is not None)
            self.rb_downlink.setToolTip(
                "" if self.rx is not None else "No downlink receiver in this session")
            self.timeline.set_note("waiting for housekeeping" if self.rx is not None
                                   else "no downlink in this session")
            self._clear_timeline()
            self._src_bin = self._src_exp_ms = None
            if self.source == "downlink":
                self.last_proc = None        # the old link's frame, not this one's
                self._frame_n = 0
                self._render_plot()
                self._update_stats()
            self._update_source_banner()
            if self.rx is not None:
                self.flight_timer.start()

            # -- and up again, the way main() starts ----------------------------
            self._restarting = False
            if was_connected or self.source == "detector":
                self._connect()
                if self.connected:
                    self._start()
            if link_error:
                self._set_hint(f"restarted, but no downlink: {link_error}")
            elif self.connected:
                self._set_hint("restarted - live" if self.running
                               else "restarted - connected")
            elif not (was_connected or self.source == "detector"):
                self._set_hint("restarted" + (" - waiting for the downlink"
                                              if self.rx is not None else ""))
            # else: _connect() posted why the detector did not come back
        finally:
            self._restarting = False
            self.btn_restart.setEnabled(True)

    # ------------------------------------------------------------ acquisition
    def _toggle_run(self):
        self._stop() if self.running else self._start()

    def _start(self):
        if self._restarting:
            return          # a worker slot draining mid-restart (see restart)
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
        """Internal one-frame refresh (parameter changes, dark capture).

        `_tick_once` grabs on the GUI thread, so it waits on the driver lock.
        During an exposure hunt that lock is held a probe at a time - over
        ``--net`` seconds at a stretch - and a slider nudge would freeze the
        window for as long. The hunt ends with its own refresh, so skipping is
        not a lost frame."""
        if not self.connected:
            self._set_hint("connect first")
            return
        if self._auto_worker is not None or self._restarting:
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

    #: Frames a probe grabs per exposure candidate: discards that let the new
    #: timing settle, then a median stack. Every one of them is a full driver
    #: round-trip, so this number times `_AUTO_ITERS` times two (the confirm
    #: probe) is what the hunt can cost - see `_auto_expose`.
    _AUTO_SETTLE = 2
    _AUTO_STACK = 3

    def _auto_expose(self, target=0.70, lo_ms=0.02, hi_ms=1000.0, iters=8,
                     budget_s=15.0):
        """Hunt the integration time so the brightest channel peaks near `target` of
        full scale, without saturating. Uses a GLITCH-DESPIKED peak (so a stray spike
        can't stop it early) and a PROPORTIONAL jump (signal ~ linear in exposure), so
        it converges in a couple of steps and from any starting exposure. A candidate
        in the sweet spot is CONFIRMED with a second probe (conservative min) before it
        is accepted, so a brief flicker on a fluctuating source - e.g. daylight through
        the shutter - can't stop the hunt early.

        **The hunt runs off the GUI thread**, for the reason `_AcquisitionWorker`
        exists at all. It is not one driver call but up to `iters` x 2 probes of
        `_AUTO_SETTLE + _AUTO_STACK` grabs each, and over ``--net`` against the
        FSW's ``--bench-stream`` every grab is paced to the flight cadence of
        1 Hz - so on the GUI thread this froze the window for minutes and macOS
        showed the app as hung. `budget_s` bounds it on top of `iters`: a scene
        that needs more probes than that gets the best exposure found so far and
        is told, rather than holding the detector indefinitely.

        The live loop is paused for the duration - the `_track_exposure` servo
        would otherwise be steering the same exposure from the other direction -
        and resumed when the hunt lands."""
        if not self.connected:
            self._set_hint("connect first")
            return
        if self._auto_worker is not None:
            return                          # a hunt is already in flight
        self._auto_resume = self.running
        if self.running:
            self._stop()
        # Run is greyed too, and honestly: the live loop is already stopped, so
        # there is nothing for Stop to stop, and letting it restart mid-hunt puts
        # the servo and the hunt on the same exposure through the same lock.
        for b in (self.btn_auto, self.btn_single, self.btn_run):
            b.setEnabled(False)
        self._set_exposure_enabled(False)   # the hunt owns the exposure until it lands
        self._set_hint("auto exposure - hunting ...")
        sat = self.cal.saturation_count
        tgt = sat * float(target)
        settle, stack = self._AUTO_SETTLE, self._AUTO_STACK

        def hunt():
            """Runs on `_AcquisitionWorker`: driver + calibration only, no widgets."""
            import time as _time

            def probe(exp_ms):
                with self._driver_lock:
                    self.driver.set_times_us(int(round(exp_ms * 1000)))
                    for _ in range(settle):
                        self.driver.grab()                          # let the new timing settle
                    frame = P.average_frames([self.driver.grab() for _ in range(stack)],
                                             method="median")
                return max(P.robust_peak(ch.slice(frame)) for ch in self.cal.channels)

            deadline = _time.monotonic() + budget_s
            exp, pk, spent = min(max(self.exposure_ms, lo_ms), hi_ms), 0.0, False
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
                if _time.monotonic() >= deadline:
                    spent = True
                    break
            return exp, pk, spent

        w = _AcquisitionWorker(hunt, self)
        w.done.connect(self._on_auto_done)
        w.failed.connect(self._on_auto_failed)
        w.finished.connect(self._on_auto_worker_finished)
        self._auto_worker = w
        w.start()

    def _on_auto_done(self, payload):
        exp, pk, spent = payload
        sat = self.cal.saturation_count
        self.exposure_ms = round(exp, 3)
        self._show_exposure(self.exposure_ms)
        self._applied_us = None
        if spent:
            note = " - stopped at the time budget"
        elif sat * 0.45 <= pk <= sat * 0.97:
            note = ""
        else:
            note = " - source too dim/bright for the target"
        self._set_hint(f"auto exposure -> {self.exposure_ms:g} ms "
                       f"({pk / sat * 100:.0f}% FS){note}")

    def _on_auto_failed(self, msg):
        self._on_driver_error(msg)
        # The hunt had already paused the live loop, so `running` was False by
        # the time the link dropped and _on_driver_error read it. Carry the
        # operator's actual intent across instead, or a hunt that hits an
        # unplugged cable comes back connected but stopped.
        self._resume_on_reconnect = self._auto_resume
        self._auto_resume = False

    def _on_auto_worker_finished(self):
        w, self._auto_worker = self._auto_worker, None
        w.deleteLater()
        for b in (self.btn_auto, self.btn_single, self.btn_run):
            b.setEnabled(True)
        self._set_exposure_enabled(not self._track)
        resume, self._auto_resume = self._auto_resume, False
        if not self.connected:
            return
        if resume:
            hint = self.hint.text()     # _start()'s "running - live" would bury the result
            self._start()
            self._set_hint(hint)
        elif not self.running:
            self._single()              # show the frame the new exposure produces

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
            self._show_exposure(self.exposure_ms)
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

    # ---------------------------------------------------------- flight half
    def _tick_flight(self):
        """Poll the downlink for housekeeping, events, and - only when the
        operator has put the spectrum on the downlink - the quick-look trace.

        Broad `except` on purpose: this is a QTimer slot, and PyQt5 aborts the
        whole process on an unhandled exception in one. Losing the window is
        strictly worse than a hint saying the refresh failed, and the flight
        half must never be able to take the instrument half down with it.
        """
        if self.rx is None:
            return
        try:
            self.flight.refresh()
            self._sample_timeline()
            if self.source == "downlink":
                self._take_downlink_frame()
        except Exception as e:                          # noqa: BLE001 - see above
            self._set_hint(f"downlink refresh failed: {e}")

    def _take_downlink_frame(self):
        """Turn the latest quick-look into the same `last_proc` the detector
        path produces, so one renderer draws both.

        The counts are already the flight-scaled 16-bit values the MCU sent;
        there is no dark subtraction, averaging or glitch filter to apply,
        because none of that happened on the Pi. The instrument controls that
        imply otherwise are ignored in this source rather than silently
        pretending to work.
        """
        ql = getattr(self.rx, "quicklook", None)
        if not ql:
            return
        r = self._ref()
        proc, head = {}, None
        for chan, payload in sorted(ql.items()):
            counts = np.asarray(payload["counts"], dtype=float)
            if not counts.size:
                continue
            if chan == 0:
                proc["m"] = counts
            elif chan == 1 and r is not None:
                proc["r"] = counts
            head = payload
        if "m" not in proc or head is None:
            return
        if head["bin"] != self._src_bin:
            # The banner quotes the binning, so it cannot be written once at
            # switch time - until the first quick-look lands there is nothing
            # to quote, and it must stop saying "waiting" when one does.
            self._src_bin = head["bin"]
            self._update_source_banner()
        self._src_exp_ms = head["exposure_ms"]
        # Saturation is worth having here too: the bench quick-look clips flat
        # at saturation_count and the old dashboard gave no sign of it, so a
        # clipped downlink looked like a real spectrum with a plateau.
        allc = np.concatenate([v for v in proc.values()])
        self._last_sat = (float(np.count_nonzero(
            allc >= self.cal.saturation_count)) / allc.size) if allc.size else 0.0
        self._last_glitch = 0.0
        self.last_proc = proc
        self._frame_n += 1
        self._render_plot()
        self._update_stats()

    def _on_source(self, name):
        """Switch what the spectrum view draws. Explicit only - nothing in the
        app calls this on a link state change, because a plot that silently
        becomes a different measurement is how a binned 1 Hz quick-look gets
        read as a live instrument trace."""
        if name == self.source:
            return
        self.source = name
        self.last_proc = None                # never mix the two on one axis
        self._last_sat = self._last_glitch = 0.0
        self._src_bin = self._src_exp_ms = None
        self._frame_n = 0
        self._update_source_banner()
        if name == "downlink":
            self._take_downlink_frame()
            self._set_hint("spectrum follows the downlink - 1 Hz, binned")
        else:
            self._set_hint("spectrum follows the detector"
                           + ("" if self.connected else " - press Connect"))
        self._render_plot()
        self._update_stats()

    def _update_source_banner(self):
        """Say which source the plot is drawing, in the plot. The whole reason
        the old two-app split was documented as a trap is that people could
        not tell these apart by looking."""
        if self.source == "downlink":
            b = self._src_bin
            txt = "MOCK DOWNLINK" if self.mock else "DOWNLINK"
            det = (f"1 Hz  mean-binned {b}x  -  not an instrument view"
                   if b else "1 Hz  binned  -  waiting for a quick-look")
            col, bg = ("#7b1fa2", "#f5e9fa") if self.mock \
                else ("#8a4b00", "#fdf1e2")
        elif self.mock:
            # Not a shade of the detector banner: a simulated trace has to be
            # unmistakable at a glance, including in a screenshot with no
            # command line next to it.
            txt = "MOCK DETECTOR"
            det = ("synthetic spectrum - no instrument, no light"
                   if self.connected else "not connected")
            col, bg = "#7b1fa2", "#f5e9fa"
        else:
            txt = "DETECTOR"
            det = (f"continuous  full resolution  {self.kind}"
                   if self.connected else "not connected")
            col, bg = NAVY, "#e8f0f8"
        self.src_banner.setText(f"  {txt}   {det}  ")
        self.src_banner.setStyleSheet(
            f"color:{col}; background:{bg}; border:1px solid {col};"
            "border-radius:4px; font-size:10px; font-weight:bold;"
            "letter-spacing:1px; padding:3px 6px;")
        self.src_banner.adjustSize()
        self._place_source_banner()

    def _place_source_banner(self):
        view = getattr(self, "_view", None)
        if view is None or not hasattr(self, "src_banner"):
            return
        self.src_banner.move(max(16, (view.width() - self.src_banner.width()) // 2), 14)
        self.src_banner.raise_()

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
        fr = subtract_dark(self.last_frame, self._dark_in_use())
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
    def _dark_in_use(self):
        """The dark to subtract right now, or ``None``.

        A dark is only valid at the exposure it was taken at - dark current
        scales with integration time - so an exposure change withholds it
        instead of subtracting the wrong pedestal off every frame. The
        withholding is visible: the checkbox stays on and the Dark frame
        section says why, because silently not subtracting is its own lie.
        """
        if not self.subtract_dark_flag or self.dark is None:
            return None
        if self._dark_meta is not None and not self._dark_meta.matches_exposure(
                int(round(self.exposure_ms * 1000))):
            return None
        return self.dark

    def _dark_exposure_ok(self) -> bool:
        return (self.dark is None or self._dark_meta is None
                or self._dark_meta.matches_exposure(
                    int(round(self.exposure_ms * 1000))))

    def _update_dark_label(self):
        if not hasattr(self, "lbl_dark"):
            return
        if self.dark is None:
            self.lbl_dark.setText("no dark - press Capture dark")
        elif not self._dark_exposure_ok():
            self.lbl_dark.setText(
                f"held back: dark is {self._dark_meta.exposure_ms:g} ms, "
                f"exposure is {self.exposure_ms:g} ms")
        elif self._dark_meta is not None:
            self.lbl_dark.setText(self._dark_meta.summary())
        else:
            self.lbl_dark.setText(f"dark @ {self.exposure_ms:g} ms")

    def _restore_stored_dark(self):
        """Load the dark captured in an earlier session, if there is one.

        The exposure comes back with it and the auto-integration servo is
        switched off, because those three are one setting: a dark is only
        valid at its own exposure, and a servo that moves the exposure would
        invalidate the thing we just restored within a frame or two. The
        operator gets both back exactly as they left them, and either control
        overrides it in one click.
        """
        try:
            stored = darkstore.load(pixels=self.driver.PIXELS)
        except darkstore.DarkError as e:
            self._set_hint(str(e))
            return
        if stored is None:
            return
        self.dark = stored.counts
        self._dark_meta = stored
        self.exposure_ms = round(stored.exposure_ms, 3)
        if hasattr(self, "sp_exp"):
            self._show_exposure(self.exposure_ms)
        if hasattr(self, "chk_track") and self.chk_track.isChecked():
            self.chk_track.blockSignals(True)
            self.chk_track.setChecked(False)
            self.chk_track.blockSignals(False)
            self._track = False
            self._set_exposure_enabled(True)
        self.chk_dark.setChecked(True)
        self._update_dark_label()
        self._set_hint(f"stored dark loaded ({stored.summary()}) - exposure "
                       f"set to {self.exposure_ms:g} ms, auto integration off")

    def _capture_dark(self):
        if not self.connected:
            self._set_hint("connect first")
            return
        if self._auto_worker is not None:
            # Grabs on the GUI thread, and the hunt owns the driver lock a probe
            # at a time. Waiting it out would freeze the window; the exposure is
            # also still moving, and a dark is only valid at one exposure.
            self._set_hint("auto exposure is running - capture the dark when it lands")
            return
        try:
            self._apply_exposure_if_changed()
            n = max(8, self.navg)
            with self._driver_lock:
                self.dark = P.average_frames([self.driver.grab() for _ in range(n)], clean=self.clean)
        except (DriverError, OSError) as e:
            self._on_driver_error(e)
            return
        info = self.info
        meta = darkstore.DarkFrame(
            counts=self.dark, exposure_us=int(round(self.exposure_ms * 1000)),
            navg=n, clean=self.clean,
            model=getattr(info, "model", "") or "",
            serial=getattr(info, "serial", "") or "",
            source="mock" if self.mock
            else (self.kind if self.kind != "net"
                  else f"net {self.host or ''}".strip()))
        self._dark_meta = meta
        self.chk_dark.setChecked(True)
        # Persisted on capture, not behind a second "save" click: the capture
        # needs a darkened bench, so the expensive half is already done and
        # nobody wants to redo it after a restart. Clear removes it again.
        #
        # Except with persistence off (--mock): the stored default is loaded
        # by whatever runs next, and a synthetic dark subtracted from real
        # light is a wrong measurement nobody would think to suspect. The mock
        # may use its own dark for the session; it may not leave one behind.
        if not self._persist_dark:
            saved = " - not stored: a mock dark must not reach a real session"
        else:
            try:
                path = darkstore.save(meta)
                saved = f", saved as the default ({os.path.basename(path)})"
            except OSError as e:
                saved = f" - could not save it as the default: {e}"
        self._update_dark_label()
        self._set_hint(f"dark captured ({n} frames @ {self.exposure_ms:g} ms){saved}")
        if not self.running:
            self._single()

    def _clear_dark(self):
        self.dark = None
        self._dark_meta = None
        self.chk_dark.setChecked(False)
        # The stored default goes with it. Leaving it on disk would resurrect
        # a dark the operator just dropped on the next start, which is the
        # kind of surprise a default must never spring. With persistence off
        # the file on disk belongs to a real bench session this one never
        # touched, so clearing a simulated dark must not delete it.
        removed = darkstore.clear() if self._persist_dark else False
        self._update_dark_label()
        self._set_hint("dark cleared (stored default removed)" if removed
                       else "dark cleared")

    # ------------------------------------------------------------- rendering
    # ------------------------------------------------- what the x axis means
    # The two sources give a channel's counts on different grids: the detector
    # returns every pixel in the channel's window, the downlink returns that
    # window mean-binned to ~30 points. So a trace's x values follow the trace
    # length rather than the calibration's full pixel array - line them up
    # with `m.wavelengths` and a 29-point quick-look plots against 236 nm of
    # axis compressed into the first 29 pixels.

    def _trace_px(self, ch, n):
        """Pixel centres for an n-point trace on channel `ch`."""
        lo, hi = ch.pixel_window
        if n >= (hi - lo + 1):                    # full resolution: as calibrated
            return ch.pixels
        b = self._src_bin or 1                    # binned: centre of each bin
        return lo + np.arange(n) * b + (b - 1) / 2.0

    def _trace_nm(self, ch, n):
        lo, hi = ch.pixel_window
        if n >= (hi - lo + 1):
            return ch.wavelengths
        return ch.pixel_to_nm(self._trace_px(ch, n))

    def _trace_sample(self, ch, data, px):
        """Counts on an n-point trace of `ch` at detector pixel `px`, or None
        when the pixel is outside the channel window."""
        if data is None or not data.size:
            return None
        lo, hi = ch.pixel_window
        if not (lo <= px <= hi):
            return None
        i = int(np.argmin(np.abs(self._trace_px(ch, data.size) - px)))
        return float(data[i])

    def _trace_x(self, ch, n):
        """x values for an n-point trace, in whichever axis is selected."""
        return self._trace_nm(ch, n) if self.axis == "nm" \
            else self._trace_px(ch, n)

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
                mx = self._trace_x(m, mc.size)
                flat = self.flat and self.reference_proc is not None
                md = P.reference_ratio(mc, self.reference_proc["m"]) if flat else mc
                if self.smooth_win:
                    md = P.smooth(md, self.smooth_win, self.smooth_mode)
                ax.plot(mx, md, color=C_MEAS, lw=1.3, label="measurement  Ch1")
                rd = None
                if has_ref:
                    rx = self._trace_x(r, rc.size)
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
                    self._draw_peak(ax, mx, md, self._trace_nm(m, md.size),
                                    C_MEAS)
                    if has_ref:
                        self._draw_peak(ax, rx, rd,
                                        self._trace_nm(r, rd.size), C_REF,
                                        minor=True)
            else:
                mnm = self._trace_nm(m, mc.size)
                rnm = self._trace_nm(r, rc.size)
                grid = P.common_grid(mnm, rnm, 256)
                mi = P.resample(mnm, mc, grid)
                ri = P.resample(rnm, rc, grid)
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
        mproc = self.last_proc["m"]
        rproc = self.last_proc.get("r")
        if mproc is None or not mproc.size:
            self.cursor_box.hide()
            return
        # Index each trace on its own grid. On the downlink a channel is ~30
        # binned points, so a pixel offset into the channel window names the
        # wrong sample and, past the 30th pixel, no sample at all.
        if g["axis"] == "nm":
            mx = self._trace_nm(m, mproc.size)
            mi = int(np.argmin(np.abs(mx - dx)))
            px = int(round(float(self._trace_px(m, mproc.size)[mi])))
            nm_here = float(mx[mi])
            mc = float(mproc[mi])
            rc = None
            if r is not None and rproc is not None and rproc.size:
                rx = self._trace_nm(r, rproc.size)
                rc = float(rproc[int(np.argmin(np.abs(rx - dx)))])
        else:
            px = int(round(dx))
            # A channel's calibration only describes its own window; the dark
            # gap between the two is not a wavelength, and extrapolating Ch1
            # across it printed confident nonsense (px 1833 as 3945 nm).
            nm_here = None
            for ch in (m, r):
                if ch is not None and ch.pixel_window[0] <= px <= ch.pixel_window[1]:
                    nm_here = float(ch.pixel_to_nm(px))
                    break
            mc = self._trace_sample(m, mproc, px)
            rc = self._trace_sample(r, rproc, px) if r is not None else None
        ms = f"{mc:7.0f}" if mc is not None else "     --"
        rs = f"{rc:7.0f}" if rc is not None else "     --"
        nms = f"{nm_here:6.1f} nm" if nm_here is not None else "     -- nm"
        self.cursor_lbl.setText(f"px {px:4d}\n{nms}\nmeas {ms}\nref  {rs}")
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
            # Index the trace's own wavelength grid: on the downlink a channel
            # is ~30 binned points, so m.wavelengths[mi] would name a
            # wavelength from the wrong end of the window.
            m_nm = float(self._trace_nm(m, mc.size)[mi]) if mc.size else 0.0
            m_pk = float(mc[mi]) if mc.size else 0.0
            if r is not None and rc is not None and rc.size:
                ri = P.robust_peak_index(rc)
                r_nm = float(self._trace_nm(r, rc.size)[ri])
                ref_line = f"ref   {float(rc[ri]):6.0f} @ {r_nm:5.1f} nm\n"
            else:
                ref_line = "ref     --  single channel\n"
            sat = self._last_sat * 100.0
            clip = "  CLIPPING" if self._last_sat > 0.001 else ""
            head = (f"meas  {m_pk:6.0f} @ {m_nm:5.1f} nm\n"
                    + ref_line
                    + f"mean  {float(np.mean(mc)):6.0f}   "
                      f"sd {float(np.std(mc)):5.0f}\n"
                    + f"sat   {sat:5.1f} %{clip}\n")
            if self.source == "downlink":
                # None of the acquisition controls applied to this frame - it
                # was taken on the Pi and binned for the budget - so reporting
                # this window's exposure and averaging here would be a lie.
                age = self.rx.hk_age_s() if self.rx is not None else None
                self.stats.setText(
                    head
                    + f"exp   {self._src_exp_ms or 0:g} ms  on the Pi\n"
                    + f"bin   {self._src_bin or 0}x  mean\n"
                    + f"hk    {'-' if age is None else f'{age:.1f} s'} old"
                      f"   packet #{self._frame_n}")
            else:
                glitch = self._last_glitch * 100.0
                gl = f"\nUSB   {glitch:4.1f} % glitch" if glitch > 0.2 else ""
                self.stats.setText(
                    head
                    + f"exp   {self.exposure_ms:g} ms  x{self.navg}"
                    + ("  TRACK" + (" " + self._track_msg
                                    if self._track_msg else "")
                       if self._track else "")
                    + f"{gl}\n"
                    + f"fps   {self._fps:4.1f}   frame #{self._frame_n}"
                    + (f"  drop {self._dropped}" if self._dropped else ""))
        if hasattr(self, "stats_cap"):
            self.stats_cap.setText("LIVE" if self.source == "detector"
                                   else "QUICK-LOOK")
        self.stats_box.adjustSize()
        self.stats_box.move(16, 16)
        self.stats_box.raise_()

    def _set_hint(self, txt):
        if hasattr(self, "hint"):
            self.hint.setText(txt)
            # The hint spans the sidebar and wraps: a long one is two or three
            # lines, which is height the columns no longer have. Re-pack, or a
            # hint could be what pushes the last section out of view.
            self._reflow_panel()

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
            "dark_subtracted": self._dark_in_use() is not None,
            "glitch_filtered": bool(self.clean),
        }
        frame = subtract_dark(self.last_frame, self._dark_in_use())
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
            f"color:{NAVY}; font-family:{MONO}; font-size:11px;")
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
        # back to the factory file (CLOUDS_CALIBRATION, else calibration.json)
        self.engine.cal = Calibration.load()
        self.engine._render_plot()
        self.result.setText("")
        self.status.setText("reset to the factory calibration")

    def closeEvent(self, ev):
        self.engine._cal_cb = None
        super().closeEvent(ev)
