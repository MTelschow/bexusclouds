"""GSE PyQt5 dashboard (G-01..G-04, G-07): live HK, quick-look spectrum,
command panel with arm/execute + flight-mode interlock toggle, and direct
drives for the dispersion actuators (membrane solenoid, CaCO3 motor).

Styling is NOT the bench app's design language yet (docs/UI_STYLE.md): the
sidebar is stock Qt on the host palette while the plot is dark `#12141a`, so
the window reads as two half-themed halves. The traces are two fixed colours,
not the bench app's wavelength ramp, and there is no branding or spectrum bar.
Worth settling before roll-out; the doc's panel background is `#ffffff`, so
the plot is the half that is off-language. GUI-only module
- everything testable lives in receiver/commander/session_log.
"""
from __future__ import annotations

import numpy as np
from PyQt5 import QtCore, QtWidgets
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from clouds_link.commands import Command, Param
from clouds_link.frames import AckResult, event_name, severity_name
from clouds_link.hk import Housekeeping
from spectro.calibration import Calibration

from .commander import CommandError, InterlockError
from .monitor import _fmt_hk

_HK_FIELDS = [
    ("State", lambda h: h.state_name),
    ("Mission t", lambda h: f"{h.mission_t_s} s"),
    ("Fired", lambda h: f"{h.fired:02b}"),
    ("p ambient", lambda h: f"{h.p_amb_pa / 100:.1f} hPa"),
    ("p chamber", lambda h: f"{h.p_ch_pa / 100:.1f} hPa"),
    ("T1 / T2", lambda h: f"{h.temp1_cc / 100:.1f} / {h.temp2_cc / 100:.1f} C"),
    ("RH1 / RH2", lambda h: f"{h.rh1_cpct / 100:.1f} / {h.rh2_cpct / 100:.1f} %"),
    ("Membrane", lambda h: f"{h.membrane_duty} %"),
    ("Driving", lambda h: h.actuator_text),
    ("Link", lambda h: h.link_text),
    # Named, not the raw mask: most of these bits are permanently set on this
    # hardware, so this row is the list of what has no source.
    ("Errors", lambda h: h.error_text),
]


def _expand_buttons(box: QtWidgets.QGroupBox, cols: int,
                    uniform: bool = False) -> None:
    """Let every button fill its cell. A QPushButton is horizontally
    `Minimum` by default, so it sits at its text width inside a wider cell -
    which is why one short label used to render as a stunted button next to
    its neighbours.

    Equal stretch is not enough on its own: it splits only the *spare* width,
    on top of each column's own minimum, so a wide label ("ARM + RELEASE 1")
    still pushes its column out and the grid comes back ragged in a second
    way. `uniform` pins every column to the widest button's hint first, which
    is what actually makes a block of command buttons one size.
    """
    lay = box.layout()
    buttons = box.findChildren(QtWidgets.QPushButton)
    widest = max((b.sizeHint().width() for b in buttons), default=0)
    for col in range(cols):
        lay.setColumnStretch(col, 1)
        if uniform:
            lay.setColumnMinimumWidth(col, widest)
    for btn in buttons:
        btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                          QtWidgets.QSizePolicy.Fixed)


def _section(text: str, top: bool = False) -> QtWidgets.QLabel:
    """Section header inside a group box (docs/UI_STYLE.md: `#8a97a3`).
    Without it a heading is indistinguishable from a widget's own label."""
    lab = QtWidgets.QLabel(text)
    lab.setStyleSheet("color: #8a97a3; font-weight: bold; font-size: 11px;"
                      + ("margin-top: 8px;" if top else ""))
    return lab


class GseWindow(QtWidgets.QMainWindow):
    """Poll-based UI: reads receiver state on a 500 ms timer, so telemetry
    callbacks never touch Qt from the wrong thread."""

    def __init__(self, receiver, commander, session):
        super().__init__()
        self._rx = receiver
        self._cmd = commander
        self._session = session
        self._cal = Calibration.load()
        self.setWindowTitle("CLOUDS GSE")
        self.resize(1100, 700)
        self._build()
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(500)

    # -- layout ---------------------------------------------------------------

    def _build(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)

        left = QtWidgets.QVBoxLayout()
        root.addLayout(left, 0)

        self._state_banner = QtWidgets.QLabel("NO TELEMETRY")
        self._state_banner.setStyleSheet(
            "font-size: 20px; font-weight: bold; padding: 8px;")
        left.addWidget(self._state_banner)

        form = QtWidgets.QFormLayout()
        self._hk_labels = {}
        for name, _ in _HK_FIELDS:
            lab = QtWidgets.QLabel("-")
            self._hk_labels[name] = lab
            form.addRow(name, lab)
        # Not "Link": the HK row above already carries that name for the
        # MCU's own link flags, and two rows with one label is unreadable.
        self._link_label = QtWidgets.QLabel("-")
        form.addRow("Downlink", self._link_label)
        left.addLayout(form)

        left.addWidget(self._command_panel())
        left.addWidget(self._actuator_panel())
        self._event_list = QtWidgets.QListWidget()
        left.addWidget(self._event_list, 1)

        fig = Figure(facecolor="#12141a")
        self._canvas = FigureCanvasQTAgg(fig)
        self._ax = fig.add_subplot(111)
        root.addWidget(self._canvas, 1)

    def _command_panel(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Commands")
        lay = QtWidgets.QGridLayout(box)
        self._flight_mode = QtWidgets.QCheckBox("Flight mode (disables "
                                                "ground interlock S.10)")
        self._flight_mode.toggled.connect(self._toggle_flight_mode)
        lay.addWidget(self._flight_mode, 0, 0, 1, 3)
        simple = [("PING", Command.PING), ("START", Command.START),
                  ("HOLD", Command.HOLD), ("RESUME", Command.RESUME),
                  ("ABORT", Command.ABORT)]
        # Plain grid cells, one column each: `_expand_buttons(uniform=True)`
        # pins all three columns to the widest button, so a short label no
        # longer renders as a stunted button and a part-filled row does not
        # stretch its two buttons wider than the full row above it.
        for i, (label, cmd) in enumerate(simple):
            btn = QtWidgets.QPushButton(label)
            btn.clicked.connect(lambda _, c=cmd: self._send(c))
            lay.addWidget(btn, 1 + i // 3, i % 3)
        for n in (1, 2):
            btn = QtWidgets.QPushButton(f"ARM + RELEASE {n}")
            btn.setStyleSheet("color: #ff6b5e; font-weight: bold;")
            btn.clicked.connect(lambda _, v=n: self._release(v))
            lay.addWidget(btn, 3, n - 1)
        self._cmd_status = QtWidgets.QLabel("-")
        lay.addWidget(self._cmd_status, 4, 0, 1, 3)
        _expand_buttons(box, 3, uniform=True)
        return box

    def _actuator_panel(self) -> QtWidgets.QGroupBox:
        """Direct drives for the dispersion hardware (M-07).

        Separate from the Commands box on purpose: these move hardware
        without an arm/execute handshake, because neither drive is
        irreversible - the membrane stops on Stop and the motor pulse is
        bounded on the MCU - and running them is how the mechanism is
        exercised on the bench. The MCU still refuses both in TERMINATION and
        SAFE, so nothing here can restart an aborted experiment.
        """
        box = QtWidgets.QGroupBox("Actuators")
        lay = QtWidgets.QGridLayout(box)

        lay.addWidget(_section("Membrane solenoid"), 0, 0, 1, 4)
        self._duty = QtWidgets.QSpinBox()
        self._duty.setRange(5, 100)          # PARAM_MEMBRANE_DUTY limits
        self._duty.setValue(60)
        self._duty.setSuffix(" %")
        self._duty.setToolTip("Drive duty cycle (MEMBRANE key)")
        lay.addWidget(self._duty, 1, 0)
        self._hz = QtWidgets.QSpinBox()
        self._hz.setRange(1, 400)            # PARAM_MEMBRANE_HZ limits
        self._hz.setValue(2)
        self._hz.setSuffix(" Hz")
        self._hz.setToolTip("Drive frequency, sent as SET_PARAM MEMBRANE_HZ "
                            "before the drive starts")
        lay.addWidget(self._hz, 1, 1)
        start = QtWidgets.QPushButton("Drive")
        start.setStyleSheet("color: #e8821e; font-weight: bold;")
        start.clicked.connect(self._membrane_start)
        lay.addWidget(start, 1, 2)
        stop = QtWidgets.QPushButton("Stop")
        stop.clicked.connect(self._membrane_stop)
        lay.addWidget(stop, 1, 3)

        lay.addWidget(_section("CaCO₃ dispersion motor", top=True),
                      2, 0, 1, 4)
        motor = QtWidgets.QPushButton("Run one pulse")
        motor.setStyleSheet("color: #e8821e; font-weight: bold;")
        motor.setToolTip("One forward pulse, timed on the MCU (5 s) and not "
                         "interruptible from here")
        motor.clicked.connect(self._disperse)
        lay.addWidget(motor, 3, 0, 1, 2)
        # Own row, like the Commands box: beside the button it reads as part
        # of the button's label.
        self._act_status = QtWidgets.QLabel("-")
        lay.addWidget(self._act_status, 4, 0, 1, 4)
        _expand_buttons(box, 4)
        return box

    # -- commands -------------------------------------------------------------

    def _toggle_flight_mode(self, on: bool) -> None:
        if self._cmd:
            self._cmd.flight_mode = on

    def _send(self, cmd: Command) -> None:
        if self._cmd is None:
            self._cmd_status.setText("no command link")
            return
        try:
            r = self._cmd.send(cmd)
            self._cmd_status.setText(f"{cmd.name} -> {r.name}")
        except (InterlockError, CommandError) as e:
            self._cmd_status.setText(str(e))

    def _release(self, valve: int) -> None:
        if self._cmd is None:
            self._cmd_status.setText("no command link")
            return
        # Interlock first, dialog second. Asking "arm and fire valve 1?" and
        # then refusing the Yes teaches the operator that the confirmation
        # means nothing, and on the pad that is every single press.
        if not self._cmd.flight_mode:
            self._cmd_status.setText(
                "RELEASE is interlocked on ground (S.10); "
                "enable flight mode to send it")
            return
        ok = QtWidgets.QMessageBox.question(
            self, "Confirm release",
            f"Arm and fire pinch valve {valve}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if ok != QtWidgets.QMessageBox.Yes:
            return
        try:
            r = self._cmd.release(valve)
            self._cmd_status.setText(f"RELEASE {valve} -> {r.name}")
        except (InterlockError, CommandError) as e:
            self._cmd_status.setText(str(e))

    # -- actuators ------------------------------------------------------------

    def _membrane_start(self) -> None:
        """Frequency first, then the drive: PARAM_MEMBRANE_HZ is read when the
        drive starts, so setting it afterwards would leave the solenoid
        running at the old rate while the panel showed the new one."""
        if self._cmd is None:
            self._act_status.setText("no command link")
            return
        try:
            r = self._cmd.set_param(int(Param.MEMBRANE_HZ), self._hz.value())
            if r != AckResult.OK:
                self._act_status.setText(f"MEMBRANE_HZ -> {r.name}, "
                                         f"not driving")
                return
            r = self._cmd.membrane(self._duty.value())
            self._act_status.setText(
                f"membrane {self._duty.value()} % @ {self._hz.value()} Hz "
                f"-> {r.name}")
        except (InterlockError, CommandError, ValueError) as e:
            self._act_status.setText(str(e))

    def _membrane_stop(self) -> None:
        if self._cmd is None:
            self._act_status.setText("no command link")
            return
        try:
            r = self._cmd.membrane(0)
            self._act_status.setText(f"membrane off -> {r.name}")
        except (InterlockError, CommandError, ValueError) as e:
            self._act_status.setText(str(e))

    def _disperse(self) -> None:
        if self._cmd is None:
            self._act_status.setText("no command link")
            return
        try:
            r = self._cmd.disperse()
            self._act_status.setText(f"disperse -> {r.name}")
        except (InterlockError, CommandError) as e:
            self._act_status.setText(str(e))

    # -- refresh --------------------------------------------------------------

    def _refresh(self) -> None:
        h: Housekeeping | None = self._rx.last_hk
        age = self._rx.hk_age_s()
        if h is not None:
            self._state_banner.setText(h.state_name)
            stale = age is not None and age > 5.0
            self._state_banner.setStyleSheet(
                "font-size: 20px; font-weight: bold; padding: 8px;"
                + ("background: #7a2c20;" if stale else "background: #1f6f43;"))
            for name, fmt in _HK_FIELDS:
                self._hk_labels[name].setText(fmt(h))
        if self._cmd is None:
            cmd_link = "no command link (--listen-only)"
        elif self._cmd.connected:
            rtt = self._cmd.last_rtt_s
            cmd_link = f"cmd up ({rtt * 1000:.0f} ms)" if rtt is not None else "cmd up"
        else:
            cmd_link = "cmd DOWN - retrying"
        self._link_label.setText(
            f"rx {self._rx.gaps.received}  lost {self._rx.gaps.lost}  "
            f"hk age {'-' if age is None else f'{age:.1f} s'}  |  {cmd_link}")
        while self._event_list.count() < len(self._rx.events):
            ev = self._rx.events[self._event_list.count()]
            self._event_list.addItem(
                f"[{severity_name(ev['severity'])}] "
                f"{event_name(ev['code'])}: {ev['text']}")
        self._plot()

    def _plot(self) -> None:
        self._ax.clear()
        self._ax.set_facecolor("#12141a")
        colors = {0: "#59c9ff", 1: "#ffb84d"}
        names = {0: "measurement", 1: "reference"}
        roles = {0: "measurement", 1: "reference"}
        for chan, ql in sorted(self._rx.quicklook.items()):
            ch = self._cal.by_role_optional(roles.get(chan, "measurement"))
            counts = np.asarray(ql["counts"], dtype=float)
            if ch is not None and counts.size:
                lo, _ = ch.pixel_window
                px = lo + np.arange(counts.size) * ql["bin"] + ql["bin"] / 2
                x = ch.pixel_to_nm(px)
                self._ax.plot(x, counts, color=colors.get(chan, "w"),
                              label=f"{names.get(chan, chan)} "
                                    f"(bin {ql['bin']}x)")
        self._ax.set_xlabel("wavelength / nm", color="#aab")
        self._ax.set_ylabel("counts", color="#aab")
        self._ax.tick_params(colors="#aab")
        if self._rx.quicklook:
            self._ax.legend(facecolor="#12141a", labelcolor="#aab")
        self._canvas.draw_idle()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._session.export_summary(
            self._session.hk_path.replace("_hk.csv", "_summary.json"),
            self._rx.gaps)
        event.accept()


def run_gui(receiver, commander, session) -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    receiver._cb["hk"] = session.log_hk
    receiver._cb["ev"] = session.log_event
    receiver._cb["ql"] = session.log_quicklook
    win = GseWindow(receiver, commander, session)
    win.show()
    return app.exec_()
