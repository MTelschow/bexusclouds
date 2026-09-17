"""Flight half of the operator sidebar: housekeeping, commanding, actuators,
events (G-01..G-04, G-07).

This is the old GSE dashboard's sidebar, restyled into the bench app's design
language and folded into the one window. The logic is unchanged where it was
load-bearing; what changed is that it no longer lives in a separate
application, so an operator watching the trace and an operator commanding the
experiment are the same person at the same window.

The data path is untouched: everything here reads a `clouds_gse.Receiver`
(UDP downlink) and writes through a `clouds_gse.Commander` (TCP uplink with
the ground interlock). Nothing in this file talks to a detector, and nothing
in the instrument half talks to the link.

**Every slot in here is guarded.** PyQt5 aborts the process on an unhandled
exception in a slot, and "no command link" is a normal state (--listen-only,
or a Pi that has not come up yet), not an error.
"""
from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from clouds_link.commands import Command, Param
from clouds_link.frames import AckResult, event_name, severity_name
from clouds_link.hk import (HB_SENSE_A_PER_V, RAIL_I2C_ADDR, RAIL_NAMES,
                            RAIL_SHUNT_MOHM, HkErrors, Housekeeping)
from clouds_gse.commander import CommandError, InterlockError

from . import style
from .sections import Section, group_label

#: State rows: where the sequence is and what the experiment is doing. The
#: sensor readings are a separate section (SENSOR_FIELDS) because they answer
#: a different question and most of them have no source on this carrier.
HK_FIELDS = [
    ("State", lambda h: h.state_name),
    ("Mission t", lambda h: f"{h.mission_t_s} s"),
    ("Uptime", lambda h: f"{h.uptime_s} s"),
    ("Fired", lambda h: f"{h.fired:02b}"),
    # Commanded duty plus the sensed plunger position from the GP30 switch:
    # the pair is what shows a drive that moves nothing, or a switch that
    # says pulled with the drive off. `pushed`/`pulled` is omitted when the
    # MCU build cannot read the switch (HKE_NO_MEMBRANE_SENSE).
    ("Membrane", lambda h: h.membrane_text),
    ("Driving", lambda h: h.actuator_text),
    ("Link", lambda h: h.link_text),
    # Named, not the raw mask: most of these bits are permanently set on this
    # carrier, so the row is the list of what has no source.
    ("Errors", lambda h: h.error_text),
]


def _held(h) -> str:
    """`p_amb_pa` is the one field the MCU deliberately holds rather than
    zeroes on a failed read, because a 0 Pa reads as a 100 kPa fall and trips
    launch detection. A held value is real data, just old - so it is shown,
    and labelled."""
    return "  (held, stale)" if h.error_flags & HkErrors.P_AMB_STALE else ""


def _rail_row(i: int):
    """Formatter for one INA226 rail: bus voltage and the current through its
    shunt.

    Returns the sentinel's meaning rather than numbers when the monitor did
    not answer, because **0.00 V is a real reading** for a rail whose supply
    is absent - V_in does exactly that on a USB-powered bench - and a dead
    monitor and a dead rail are different faults to chase. The same goes for
    the current: 0.000 A is what an idle rail reads.

    A rail the carrier has no monitor on says so in its own words. The 24 V
    rail is that today: "no monitor" would send an operator looking for a
    fault that is really an unpopulated footprint.

    Amps are shown to mA, which is where the hardware's resolution runs out
    (2.5 uV/LSB over 10 mOhm is 0.25 mA), and volts to 10 mV. A negative
    current is printed as it comes, not clamped: it means the rail is pushing
    back into the supply, and hiding the sign hides that.

    Both numbers are right-aligned in a fixed width. The rows are rendered in
    the monospaced face, so that makes the rails a column an operator can scan
    down instead of differently indented sentences - 24.06 and 5.09 do not
    otherwise start at the same pixel.
    """
    def fmt(h):
        if RAIL_I2C_ADDR[i] is None:
            return "not fitted"
        a = h.rail_a(i)
        if a is None:
            return "no monitor"
        return f"{h.rail_mv[i] / 1000:5.2f} V   {a:+6.3f} A"
    return fmt


#: One row per sensor reading in the 56-byte housekeeping packet: the label, the
#: part that produces it, how to render it, and the `HkErrors` bit that means
#: **this number has no sensor behind it**.
#:
#: That last column is the point of this table. The MCU fills a field with
#: zeros whenever it has no reading for it - the IMU vectors through the
#: BNO055's 650 ms boot, after a bus glitch, and permanently if its bring-up
#: fails. Rendered as numbers those zeros are indistinguishable from readings:
#: 0 mg is a plausible acceleration. So a row whose flag is set says what is
#: wrong instead of showing the number, and the number is not quietly turned
#: into something prettier.
#:
#: Two groups of rows that used to sit here are gone with their parts: the
#: chamber pressure and second humidity channel with the Keller 23SY pair
#: (their HK fields went too), and `T1 / T2` with the **STLM20 pair, which is
#: not populated and is not coming**. A row that can only ever say "not
#: populated" is telling the operator about a part that is not part of the
#: experiment; `HKE_NO_TEMP` still rides in `error_flags`, so the Errors row
#: declares the two wire fields as unsourced without giving them a readout
#: that looks like a sensor.
SENSOR_FIELDS = [
    ("Ambient p", "BME280",
     lambda h: f"{h.p_amb_pa / 100:.1f} hPa{_held(h)}", HkErrors.BME280_FAIL),
    ("Ambient T", "BME280",
     lambda h: f"{h.bme_temp_cc / 100:.1f} C", HkErrors.BME280_FAIL),
    ("Ambient RH", "BME280",
     lambda h: f"{h.rh1_cpct / 100:.1f} %", HkErrors.BME280_FAIL),
    ("Accel", "BNO055",
     lambda h: "  ".join(f"{v:+d}" for v in h.accel_mg) + " mg",
     HkErrors.IMU_FAIL),
    # gyro_ddps is deci-dps on the wire, like every other scaled HK integer.
    # Printed raw it reads as a rate ten times the real one, which nothing on
    # screen would contradict.
    ("Gyro", "BNO055",
     lambda h: "  ".join(f"{v / 10:+.1f}" for v in h.gyro_ddps) + " dps",
     HkErrors.IMU_FAIL),
] + [
    # One row per rail rather than one packed line, so an operator can see at
    # a glance which rail is off. `None` for the flag: HKE_RAIL_FAIL says only
    # that *some* rail failed, so which one is unreadable is carried by the
    # field itself, as RAIL_MV_INVALID - see _rail_row.
    (f"Rail {name}",
     f"INA226 0x{addr:02X}" if addr is not None else "INA226 not fitted",
     _rail_row(i), None)
    for i, (name, addr) in enumerate(zip(RAIL_NAMES, RAIL_I2C_ADDR))
] + [
    # The push-pull solenoid's own current, from the ACT_HB_SENS net on GP46.
    # Volts at the pin until the sense gain is measured (HB_SENSE_A_PER_V),
    # amps after; `-` when the MCU build has no GP46. `None` for the flag:
    # the field carries its own sentinel, like the rails.
    ("Solenoid I", "ADC GP46", lambda h: h.hb_sense_text, None),
]

#: What to say in place of a number, per unsourced flag. "no source" rather
#: than "sensor failed": on this carrier these parts were never fitted, and an
#: operator reading "failed" would go looking for a fault to clear.
UNSOURCED_TEXT = {
    HkErrors.BME280_FAIL: "no read",
    HkErrors.IMU_FAIL: "no data",
}

#: Older than this and the state banner goes red - the numbers on screen are
#: no longer telling you about now.
STALE_HK_S = 5.0


class FlightPanel(QtCore.QObject):
    """The flight sections and the slots that keep them fed.

    It builds sections and owns their update logic; it does **not** lay them
    out. The sidebar packs every section - both halves - into one column flow
    (`sections.SectionFlow`), so a container of its own here would pin the
    flight group into a single column and defeat that. `sections` is the
    ordered list the sidebar consumes.
    """

    def __init__(self, receiver, commander, session, parent=None):
        super().__init__(parent)
        self._rx = receiver
        self._cmd = commander
        self._session = session

        # Order is the operator's working order, not the data's: the sections
        # they steer the experiment with come first, and the housekeeping
        # grid - long, and read rather than acted on - sits below them.
        self.sec_sensors = Section("Sensors")
        self._build_sensors(self.sec_sensors)

        self.sec_cmd = Section("Commands")
        self._build_commands(self.sec_cmd)

        self.sec_act = Section("Actuators")
        self._build_actuators(self.sec_act)

        self.sec_events = Section("Events")
        self._build_events(self.sec_events)

        self.sec_hk = Section("Housekeeping")
        self._build_hk(self.sec_hk)

        self.sections = [self.sec_sensors, self.sec_cmd, self.sec_act,
                         self.sec_events, self.sec_hk]

    # -- lifecycle -----------------------------------------------------------

    def rebind(self, receiver, commander, session) -> None:
        """Point the sections at a new receiver / commander / session (the
        window's Restart) and put every readout back to its startup text.

        The widgets are kept, not rebuilt: the sidebar has already laid them
        out, and the operator's fold state is theirs to keep. But everything
        the widgets *show* came from the old receiver - the event list in
        particular is filled by index against `receiver.events`, so left as
        it is it would sit on the old count and show nothing new until the
        fresh receiver had caught up with it.

        The interlock checkbox is the operator's setting, not the link's, so
        it survives and is pushed onto the new commander rather than reset.
        """
        self._rx = receiver
        self._cmd = commander
        self._session = session
        self._on_flight_mode(self.chk_flight_mode.isChecked())

        self.banner.setText("NO TELEMETRY")
        self._set_banner_style(None)
        for lab in self._hk_labels.values():
            lab.setText("-")
        for lab in self._sensor_labels.values():
            lab.setText("-")
            lab.setStyleSheet("")
        self.lbl_downlink.setText("-")
        self.lbl_cmd_status.setText("-")
        self.lbl_act_status.setText("-")
        self.event_list.clear()

    # -- layout --------------------------------------------------------------

    def _build_hk(self, sec: Section) -> None:
        self.banner = QtWidgets.QLabel("NO TELEMETRY")
        self.banner.setAlignment(QtCore.Qt.AlignCenter)
        self._set_banner_style(None)
        sec.add(self.banner)

        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(2)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)
        self._hk_labels: dict[str, QtWidgets.QLabel] = {}
        for name, _ in HK_FIELDS:
            val = QtWidgets.QLabel("-")
            val.setStyleSheet(f"color:{style.NAVY}; font-family:{style.MONO};"
                              "font-size:11px; font-weight:bold;")
            val.setWordWrap(True)
            key = QtWidgets.QLabel(name)
            key.setStyleSheet(f"color:{style.MUTED}; font-size:11px;")
            self._hk_labels[name] = val
            form.addRow(key, val)
        # Not a second row called "Link": the HK row above carries that name
        # for the MCU's own link flags, and two rows with one label is
        # unreadable. This one is the ground station's own view of the stream.
        self.lbl_downlink = QtWidgets.QLabel("-")
        self.lbl_downlink.setWordWrap(True)
        self.lbl_downlink.setStyleSheet(
            f"color:{style.MUTED}; font-family:{style.MONO}; font-size:11px;")
        dl = QtWidgets.QLabel("Downlink")
        dl.setStyleSheet(f"color:{style.MUTED}; font-size:11px;")
        form.addRow(dl, self.lbl_downlink)
        sec.add(form)

    def _build_sensors(self, sec: Section) -> None:
        """Every sensor reading the housekeeping packet carries, with the part
        that produces it named next to it.

        The part name is not decoration: `Accel` looks like instrument data
        until you know it comes from a BNO055 whose sub-sensor IDs read 0x00.
        An operator who can see which part a number came from can see which
        numbers to believe.
        """
        # Three columns on one line - reading, part, value - rather than the
        # two-line label this used to be. Nine rows at two lines each is
        # ~270 px of a sidebar column, and the sidebar now has to fit its
        # open sections on screen without scrolling (`sections.SectionFlow`);
        # one line a row buys that back without dropping the part name, which
        # is the column that makes the readings judgeable.
        grid = QtWidgets.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        self._sensor_labels: dict[str, QtWidgets.QLabel] = {}
        for row, (name, part, _fmt, _flag) in enumerate(SENSOR_FIELDS):
            key = QtWidgets.QLabel(name)
            key.setStyleSheet(f"color:{style.MUTED}; font-size:11px;")
            src = QtWidgets.QLabel(part)
            src.setStyleSheet(f"color:{style.SECTION}; font-size:10px;")
            val = QtWidgets.QLabel("-")
            val.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self._sensor_labels[name] = val
            grid.addWidget(key, row, 0)
            grid.addWidget(src, row, 1)
            grid.addWidget(val, row, 2)
        grid.setColumnStretch(2, 1)
        sec.add(grid)

        # The shunt resistances are named on screen because they are the one
        # number in the current reading that is not measured: the MCU
        # downlinks raw shunt voltage and the amps above are Ohm's law applied
        # here. If a value is wrong, every current on this panel is wrong by
        # the same factor, and an operator has to be able to see which
        # assumption to doubt.
        shunts = ", ".join(f"{n} {r:g}" for n, r
                           in zip(RAIL_NAMES, RAIL_SHUNT_MOHM))
        hb = ("solenoid sense gain not yet measured - pin volts shown"
              if HB_SENSE_A_PER_V is None
              else f"solenoid sense {HB_SENSE_A_PER_V:g} A/V")
        note = QtWidgets.QLabel(f"current derived: shunt voltage over "
                                f"{shunts} mΩ; {hb}")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{style.SECTION}; font-size:10px;"
                           "font-style:italic;")
        sec.add(note)

    def _build_commands(self, sec: Section) -> None:
        # A QCheckBox does not wrap, and a sidebar column is 340 px: keep the
        # label short and put the requirement in the tooltip.
        self.chk_flight_mode = QtWidgets.QCheckBox("Flight mode")
        self.chk_flight_mode.setStyleSheet(style.checkbox_style())
        self.chk_flight_mode.setToolTip(
            "Disables the ground interlock (S.10) so RELEASE and START can be "
            "sent. The Pi re-checks it against fresh housekeeping regardless.")
        self.chk_flight_mode.toggled.connect(self._on_flight_mode)
        sec.add(self.chk_flight_mode)

        grid = QtWidgets.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        simple = [("PING", Command.PING), ("START", Command.START),
                  ("HOLD", Command.HOLD), ("RESUME", Command.RESUME),
                  ("ABORT", Command.ABORT)]
        # Six columns so the grid can hold two different button widths without
        # going ragged: the short commands span 2 (three per row), the release
        # pair spans 3 (two per row). Equal column stretch then makes every
        # button in a row the same width.
        #
        # Pinning columns to the widest button's own hint is what NOT to do
        # here, even though it does produce equal widths: 3 x "ARM + RELEASE 1"
        # is ~470 px inside a 340 px sidebar column whose horizontal scrollbar
        # is off, so the far column is silently clipped - and it drags the
        # rest of the sidebar off the edge with it. Spanning spreads a long
        # label across columns instead of widening one.
        self._cmd_buttons: list[QtWidgets.QPushButton] = []
        for i, (label, cmd) in enumerate(simple):
            btn = QtWidgets.QPushButton(label)
            btn.setStyleSheet(style.flat_btn())
            btn.clicked.connect(lambda _, c=cmd: self._send(c))
            grid.addWidget(btn, i // 3, (i % 3) * 2, 1, 2)
            self._cmd_buttons.append(btn)
        for n in (1, 2):
            btn = QtWidgets.QPushButton(f"ARM + RELEASE {n}")
            btn.setStyleSheet(style.danger_btn())
            btn.clicked.connect(lambda _, v=n: self._release(v))
            grid.addWidget(btn, 2, (n - 1) * 3, 1, 3)
            self._cmd_buttons.append(btn)
        for col in range(6):
            grid.setColumnStretch(col, 1)
        for btn in self._cmd_buttons:
            btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                              QtWidgets.QSizePolicy.Fixed)
        sec.add(grid)

        self.lbl_cmd_status = QtWidgets.QLabel("-")
        self.lbl_cmd_status.setWordWrap(True)
        self.lbl_cmd_status.setStyleSheet(
            f"color:{style.MUTED}; font-size:11px;")
        sec.add(self.lbl_cmd_status)

    def _build_actuators(self, sec: Section) -> None:
        """Direct drives for the dispersion hardware (M-07).

        Kept as its own section rather than sitting among the Commands: these
        move hardware with no arm/execute handshake, because neither drive is
        irreversible - the membrane stops on Stop and the motor pulse is
        bounded on the MCU - and running them is how the mechanism gets
        exercised on the bench. The MCU still refuses both in TERMINATION and
        SAFE, so nothing here can restart an aborted experiment.
        """
        sec.add(group_label("Membrane solenoid"))
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.sp_duty = QtWidgets.QSpinBox()
        self.sp_duty.setRange(5, 100)        # PARAM_MEMBRANE_DUTY limits
        self.sp_duty.setValue(60)
        self.sp_duty.setSuffix(" %")
        self.sp_duty.setStyleSheet(style.spin_style())
        self.sp_duty.setToolTip("Drive duty cycle (MEMBRANE key)")
        row.addWidget(self.sp_duty, 1)
        self.sp_hz = QtWidgets.QSpinBox()
        self.sp_hz.setRange(1, 400)          # PARAM_MEMBRANE_HZ limits
        self.sp_hz.setValue(2)
        self.sp_hz.setSuffix(" Hz")
        self.sp_hz.setStyleSheet(style.spin_style())
        self.sp_hz.setToolTip("Drive frequency, sent as SET_PARAM MEMBRANE_HZ "
                              "before the drive starts")
        row.addWidget(self.sp_hz, 1)
        sec.add(row)

        row2 = QtWidgets.QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(6)
        self.btn_drive = QtWidgets.QPushButton("Drive")
        self.btn_drive.setStyleSheet(style.primary_btn())
        self.btn_drive.clicked.connect(self._membrane_start)
        row2.addWidget(self.btn_drive, 1)
        self.btn_stop = QtWidgets.QPushButton("Stop")
        self.btn_stop.setStyleSheet(style.flat_btn())
        self.btn_stop.clicked.connect(self._membrane_stop)
        row2.addWidget(self.btn_stop, 1)
        sec.add(row2)

        sec.add(group_label("CaCO₃ dispersion motor"))
        self.btn_pulse = QtWidgets.QPushButton("Run one pulse")
        self.btn_pulse.setStyleSheet(style.primary_btn())
        self.btn_pulse.setToolTip("One forward pulse, timed on the MCU (5 s) "
                                  "and not interruptible from here")
        self.btn_pulse.clicked.connect(self._disperse)
        sec.add(self.btn_pulse)

        self.lbl_act_status = QtWidgets.QLabel("-")
        self.lbl_act_status.setWordWrap(True)
        self.lbl_act_status.setStyleSheet(
            f"color:{style.MUTED}; font-size:11px;")
        sec.add(self.lbl_act_status)

    def _build_events(self, sec: Section) -> None:
        self.event_list = QtWidgets.QListWidget()
        self.event_list.setStyleSheet(style.list_style())
        # Fixed, not a minimum: a list widget's own hint is ~250 px, and the
        # sidebar spends that height on sections the operator is reading
        # rather than on empty rows. Six or so events are visible and the
        # rest scroll, which is what a log does.
        self.event_list.setFixedHeight(140)
        sec.add(self.event_list)

    # -- commands ------------------------------------------------------------

    def _on_flight_mode(self, on: bool) -> None:
        if self._cmd is not None:
            self._cmd.flight_mode = on

    def _send(self, cmd: Command) -> None:
        if self._cmd is None:
            self.lbl_cmd_status.setText("no command link")
            return
        try:
            r = self._cmd.send(cmd)
            self.lbl_cmd_status.setText(f"{cmd.name} -> {r.name}")
        except (InterlockError, CommandError) as e:
            self.lbl_cmd_status.setText(str(e))

    def _release(self, valve: int) -> None:
        if self._cmd is None:
            self.lbl_cmd_status.setText("no command link")
            return
        # Interlock first, dialog second. Asking "arm and fire valve 1?" and
        # then refusing the Yes teaches the operator that the confirmation
        # means nothing - and on the pad that is every single press.
        if not self._cmd.flight_mode:
            self.lbl_cmd_status.setText(
                "RELEASE is interlocked on ground (S.10); "
                "enable flight mode to send it")
            return
        ok = QtWidgets.QMessageBox.question(
            self.sec_cmd, "Confirm release",
            f"Arm and fire pinch valve {valve}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if ok != QtWidgets.QMessageBox.Yes:
            return
        try:
            r = self._cmd.release(valve)
            self.lbl_cmd_status.setText(f"RELEASE {valve} -> {r.name}")
        except (InterlockError, CommandError) as e:
            self.lbl_cmd_status.setText(str(e))

    # -- actuators -----------------------------------------------------------

    def _membrane_start(self) -> None:
        """Frequency first, then the drive: PARAM_MEMBRANE_HZ is read when the
        drive starts, so setting it afterwards would leave the solenoid
        running at the old rate while the panel showed the new one."""
        if self._cmd is None:
            self.lbl_act_status.setText("no command link")
            return
        try:
            r = self._cmd.set_param(int(Param.MEMBRANE_HZ), self.sp_hz.value())
            if r != AckResult.OK:
                self.lbl_act_status.setText(
                    f"MEMBRANE_HZ -> {r.name}, not driving")
                return
            r = self._cmd.membrane(self.sp_duty.value())
            self.lbl_act_status.setText(
                f"membrane {self.sp_duty.value()} % @ {self.sp_hz.value()} Hz "
                f"-> {r.name}")
        except (InterlockError, CommandError, ValueError) as e:
            self.lbl_act_status.setText(str(e))

    def _membrane_stop(self) -> None:
        if self._cmd is None:
            self.lbl_act_status.setText("no command link")
            return
        try:
            r = self._cmd.membrane(0)
            self.lbl_act_status.setText(f"membrane off -> {r.name}")
        except (InterlockError, CommandError, ValueError) as e:
            self.lbl_act_status.setText(str(e))

    def _disperse(self) -> None:
        if self._cmd is None:
            self.lbl_act_status.setText("no command link")
            return
        try:
            r = self._cmd.disperse()
            self.lbl_act_status.setText(f"disperse -> {r.name}")
        except (InterlockError, CommandError) as e:
            self.lbl_act_status.setText(str(e))

    # -- refresh -------------------------------------------------------------

    def _set_banner_style(self, state_ok: bool | None) -> None:
        bg = {True: "#1f6f43", False: "#7a2c20", None: style.GRAY}[state_ok]
        self.banner.setStyleSheet(
            "font-size:16px; font-weight:bold; padding:7px;"
            f"color:#ffffff; background:{bg}; border-radius:5px;")

    def _refresh_sensors(self, h: Housekeeping) -> None:
        """A reading, or what is wrong with it - never a number the hardware
        did not produce."""
        for name, _part, fmt, flag in SENSOR_FIELDS:
            lab = self._sensor_labels[name]
            # flag None: the row decides for itself whether it has a reading
            # (the rails do, from their own sentinel).
            if flag is not None and h.error_flags & flag:
                lab.setText(UNSOURCED_TEXT.get(flag, "no source"))
                lab.setStyleSheet(f"color:{style.GRAY}; "
                                  f"font-family:{style.MONO};"
                                  "font-size:11px; font-style:italic;")
            else:
                lab.setText(fmt(h))
                lab.setStyleSheet(f"color:{style.NAVY}; "
                                  f"font-family:{style.MONO};"
                                  "font-size:11px; font-weight:bold;")

    def refresh(self) -> None:
        """Poll the receiver. Called from the window's timer, so telemetry
        threads never touch Qt."""
        h: Housekeeping | None = self._rx.last_hk
        age = self._rx.hk_age_s()
        if h is not None:
            self.banner.setText(h.state_name)
            self._set_banner_style(not (age is not None and age > STALE_HK_S))
            for name, fmt in HK_FIELDS:
                self._hk_labels[name].setText(fmt(h))
            self._refresh_sensors(h)

        if self._cmd is None:
            link = "no command link (listen-only)"
        elif self._cmd.connected:
            rtt = self._cmd.last_rtt_s
            link = (f"cmd up ({rtt * 1000:.0f} ms)" if rtt is not None
                    else "cmd up")
        else:
            link = "cmd DOWN - retrying"
        self.lbl_downlink.setText(
            f"rx {self._rx.gaps.received}  lost {self._rx.gaps.lost}  "
            f"hk age {'-' if age is None else f'{age:.1f} s'}\n{link}")

        while self.event_list.count() < len(self._rx.events):
            ev = self._rx.events[self.event_list.count()]
            self.event_list.addItem(
                f"[{severity_name(ev['severity'])}] "
                f"{event_name(ev['code'])}: {ev['text']}")
            self.event_list.scrollToBottom()
