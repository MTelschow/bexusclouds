"""Flight half of the operator sidebar: housekeeping, commanding, actuators,
events (G-01..G-04, G-07).

This is the old GSE dashboard's sidebar, restyled into the bench app's design
language and folded into the one window. The logic is unchanged where it was
load-bearing; what changed is that it no longer lives in a separate
application, so an operator watching the trace and an operator commanding the
experiment are the same person at the same window.

The data path is untouched: everything here reads a `clouds_gse.Receiver`
(UDP downlink) and writes through a `clouds_gse.Commander` (TCP uplink).
Nothing in this file talks to a detector, and nothing in the instrument half
talks to the link.

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
from clouds_gse.commander import CommandError

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
    # Commanded duty plus the GP30 switch: plunger position at the sample and
    # whether it moved in the last second (`cycling`). The row is what shows
    # a drive that moves nothing (`60 %  pushed, not cycling`), or a switch
    # that says pulled with the drive off. Position and motion are omitted
    # when the MCU build cannot read the switch (HKE_NO_MEMBRANE_SENSE).
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


#: One row per sensor reading in the 64-byte housekeeping packet: the label, the
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
#: One group of rows that used to sit here is gone with its part: `T1 / T2`,
#: the **STLM20 pair, which is not populated and is not coming**. A row that
#: can only ever say "not populated" is telling the operator about a part
#: that is not part of the experiment; `HKE_NO_TEMP` still rides in
#: `error_flags`, so the Errors row declares the two wire fields as
#: unsourced without giving them a readout that looks like a sensor.
SENSOR_FIELDS = [
    ("Ambient p", "BME280",
     lambda h: f"{h.p_amb_pa / 100:.1f} hPa{_held(h)}", HkErrors.BME280_FAIL),
    ("Ambient T", "BME280",
     lambda h: f"{h.bme_temp_cc / 100:.1f} C", HkErrors.BME280_FAIL),
    ("Ambient RH", "BME280",
     lambda h: f"{h.rh1_cpct / 100:.1f} %", HkErrors.BME280_FAIL),
    # The chamber BME280, a second part on SPI_1 behind the chip select on
    # GP9. Same three readings, same units, deliberately the same wording -
    # "Ambient"/"Chamber" is the only difference between the two triples, so
    # an operator comparing them is comparing like with like. The part column
    # names the bus as well as the part, because that is the thing that
    # differs: two BME280s that fail for unrelated reasons are only
    # distinguishable on screen if the bus is on screen.
    #
    # No `(held, stale)` on chamber pressure: the MCU zeroes these on a
    # failed read rather than holding them (holding exists to stop a 0 Pa
    # tripping launch detection, and nothing reads the chamber), so the flag
    # column is the whole story here.
    ("Chamber p", "BME280 SPI_1",
     lambda h: f"{h.chm_p_pa / 100:.1f} hPa", HkErrors.BME280_CHM_FAIL),
    ("Chamber T", "BME280 SPI_1",
     lambda h: f"{h.chm_temp_cc / 100:.1f} C", HkErrors.BME280_CHM_FAIL),
    ("Chamber RH", "BME280 SPI_1",
     lambda h: f"{h.chm_rh_cpct / 100:.1f} %", HkErrors.BME280_CHM_FAIL),
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
    # The CaCO3 dispersion motor's own current, from the ACT_HB_SENS net on
    # GP46 - the IPROPI output of its DRV8251A, not the membrane solenoid.
    # Amps via HB_SENSE_A_PER_V; `-` when the MCU build has no GP46. `None`
    # for the flag: the field carries its own sentinel, like the rails.
    ("Motor I", "DRV8251A IPROPI, ADC GP46", lambda h: h.hb_sense_text, None),
]

#: The longest reading any `SENSOR_FIELDS` formatter can produce, used to
#: reserve the value column's width.
#:
#: It is `Ambient p` carrying its held-and-stale suffix: `_held()` appends
#: that to a pressure that is already the widest plain number on the panel.
#: Reserving for the widest *possible* value rather than the widest usual one
#: is the point - the stale case is exactly when an operator most needs to
#: read the row, and a column sized for the happy path would push the suffix
#: out at that moment.
#:
#: A literal rather than a loop over the formatters: several of them need a
#: whole `Housekeeping` to run, and feeding them a synthetic worst-case
#: packet to measure a column is more machinery than a string that the
#: `verify_qt.py` check below keeps honest.
WIDEST_SENSOR_VALUE = "1013.2 hPa  (held, stale)"

#: What to say in place of a number, per unsourced flag. "no source" rather
#: than "sensor failed": on this carrier these parts were never fitted, and an
#: operator reading "failed" would go looking for a fault to clear.
UNSOURCED_TEXT = {
    HkErrors.BME280_FAIL: "no read",
    # "no read" and not "not fitted": this part IS meant to be there, and the
    # likeliest cause on a board where it has never run is the chip select,
    # not the sensor (hw/board.h PIN_BME_CHAMBER_CS).
    HkErrors.BME280_CHM_FAIL: "no read",
    HkErrors.IMU_FAIL: "no data",
}

#: Older than this and the state banner goes red - the numbers on screen are
#: no longer telling you about now.
STALE_HK_S = 5.0

#: The MCU's PARAM_MEMBRANE_MHZ default (core/config.c), in hertz. The panel
#: judges the position switch against the drive it believes is running, and
#: until it has sent a frequency of its own, that is the MCU's default - a
#: release drives the membrane at it with no panel involved.
MEMBRANE_HZ_DEFAULT = 2.0

#: Housekeeping arrives once a second, so an edge is only *expected* inside a
#: packet if the drive's longer phase is shorter than this. Below that rate a
#: clear MEMBRANE_CYCLING bit is the sampling, not a stuck plunger.
HK_PERIOD_MS = 1000.0


class _ElidedLabel(QtWidgets.QLabel):
    """A label that shortens its text with an ellipsis instead of demanding
    the width to show all of it.

    A plain `QLabel` reports its full text width as its minimum, so in a grid
    it pushes the other columns rather than giving way. That is what let the
    sensor grid's part column squeeze the readings out of the row. This one
    keeps the full string for painting decisions and the tooltip, and reports
    a minimum of a few characters, so the column it sits in can be made as
    narrow as the layout needs.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                           QtWidgets.QSizePolicy.Preferred)

    def setText(self, text: str) -> None:       # noqa: N802 - Qt's spelling
        self._full = text
        super().setText(text)
        self._elide()

    def minimumSizeHint(self):                  # noqa: N802 - Qt's spelling
        hint = super().minimumSizeHint()
        # Wide enough to show that something is there, narrow enough never to
        # be the reason a reading is hidden.
        hint.setWidth(self.fontMetrics().boundingRect("...").width())
        return hint

    def resizeEvent(self, ev):                  # noqa: N802 - Qt's spelling
        super().resizeEvent(ev)
        self._elide()

    def _elide(self) -> None:
        super().setText(self.fontMetrics().elidedText(
            self._full, QtCore.Qt.ElideRight, max(0, self.width())))


def membrane_longest_phase_ms(hz: float, duty_pct: int) -> float:
    """How long the membrane drive holds one level, in ms - the same
    arithmetic as `sqwave_start()` in flight/mcu/src/core/sqwave.c, clamps
    included, so the panel expects edges exactly when the MCU produces them.

    It is the *longer* of the two phases: a 95 % duty at 2 Hz rises every
    500 ms but falls for only 25 ms, and it is the long phase that decides
    whether a 1 Hz sample can miss every edge.
    """
    mhz = max(1.0, hz * 1000.0)
    period = max(2.0, 1000000.0 / mhz)
    on = period * duty_pct / 100.0
    on = min(max(on, 1.0), period - 1.0)
    return max(on, period - on)


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
        # The drive frequency the MCU is believed to be running: the last one
        # it ACKed for this panel, else its own default. It is not in
        # housekeeping, and the switch light needs it to know whether a
        # missing edge is a fault or just the 1 Hz sample.
        self._membrane_hz = MEMBRANE_HZ_DEFAULT

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

        """
        self._rx = receiver
        self._cmd = commander
        self._session = session

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
        self._membrane_hz = MEMBRANE_HZ_DEFAULT
        # The run this panel started belonged to the old link. Nothing here
        # stops the motor - only DISPERSE STOP does - but the panel no longer
        # claims to know it is turning, so a slider move does not push a speed
        # for a run it never commanded. Start or Stop re-establishes the fact.
        self._motor_running = False
        self._motor_speed_sent = self.sl_motor.value()
        self._set_switch(None, None, 0, "no telemetry")
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
        # two-line label this used to be. Thirteen rows at two lines each is
        # ~390 px of a sidebar column, and the sidebar has to fit its open
        # sections on screen without scrolling (`sections.SectionFlow`); one
        # line a row buys that back without dropping the part name, which is
        # the column that makes the readings judgeable.
        #
        # THE VALUE COLUMN IS RESERVED, NOT LEFTOVER. It used to be the only
        # stretching column, which meant it got whatever the name and part
        # columns did not want - and those two size to their own longest
        # string with no ceiling. At 340 px (`SectionFlow.COL_W`, the
        # narrowest a sidebar column goes) `DRV8251A IPROPI, ADC GP46` alone
        # is most of the row, so the readings were already living on the
        # remainder; a name one glyph longer took width straight off them,
        # and on a wider font they collapse to nothing. A sensor panel whose
        # numbers vanish because a label got longer is the worst version of
        # this bug, because everything still looks laid out.
        #
        # So the value column gets a floor wide enough for the longest
        # reading any formatter above produces, and the PART column is the
        # one that gives: it stretches, and elides when there is not enough
        # room. Losing the tail of `DRV8251A IPROPI, ADC GP46` costs context
        # that the tooltip still carries; losing the reading costs the
        # measurement.
        grid = QtWidgets.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        self._sensor_labels: dict[str, QtWidgets.QLabel] = {}
        for row, (name, part, _fmt, _flag) in enumerate(SENSOR_FIELDS):
            key = QtWidgets.QLabel(name)
            key.setStyleSheet(f"color:{style.MUTED}; font-size:11px;")
            src = _ElidedLabel(part)
            src.setStyleSheet(f"color:{style.SECTION}; font-size:10px;")
            # The full name stays reachable once the column is too narrow for
            # it - the part is why a reading is believable, so it must not be
            # merely gone.
            src.setToolTip(part)
            val = QtWidgets.QLabel("-")
            val.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self._sensor_labels[name] = val
            grid.addWidget(key, row, 0)
            grid.addWidget(src, row, 1)
            grid.addWidget(val, row, 2)
        # Column 1 absorbs the slack and shrinks; column 2 never goes below
        # what a reading needs. Measured against a real value label rather
        # than guessed, so a different font or platform gets the width it
        # actually needs instead of the width this machine happened to want.
        probe = QtWidgets.QLabel()
        probe.setStyleSheet(f"font-family:{style.MONO}; font-size:11px;"
                            "font-weight:bold;")
        grid.setColumnMinimumWidth(
            2, probe.fontMetrics().boundingRect(WIDEST_SENSOR_VALUE).width())
        grid.setColumnStretch(1, 1)
        sec.add(grid)

        # The shunt resistances are named on screen because they are the one
        # number in the current reading that is not measured: the MCU
        # downlinks raw shunt voltage and the amps above are Ohm's law applied
        # here. If a value is wrong, every current on this panel is wrong by
        # the same factor, and an operator has to be able to see which
        # assumption to doubt.
        shunts = ", ".join(f"{n} {r:g}" for n, r
                           in zip(RAIL_NAMES, RAIL_SHUNT_MOHM))
        hb = ("motor sense gain not set - pin volts shown"
              if HB_SENSE_A_PER_V is None
              else f"motor IPROPI {HB_SENSE_A_PER_V:.3g} A/V "
                   f"(0 in coast, not 0 A)")
        note = QtWidgets.QLabel(f"current derived: shunt voltage over "
                                f"{shunts} mΩ; {hb}")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{style.SECTION}; font-size:10px;"
                           "font-style:italic;")
        sec.add(note)

    def _build_commands(self, sec: Section) -> None:
        # The Flight mode checkbox is gone (2026-09-18): it existed to lift
        # the ground interlock, and START does that job now - it is the one
        # button that starts the experiment, and nothing is held back after
        # it. One control, not two that had to agree.
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
        # here, even though it does produce equal widths: three long labels
        # are ~470 px inside a 340 px sidebar column whose horizontal
        # scrollbar is off, so the far column is silently clipped - and it
        # drags the rest of the sidebar off the edge with it. Spanning
        # spreads a long label across columns instead of widening one.
        self._cmd_buttons: list[QtWidgets.QPushButton] = []
        for i, (label, cmd) in enumerate(simple):
            btn = QtWidgets.QPushButton(label)
            btn.setStyleSheet(style.flat_btn())
            btn.clicked.connect(lambda _, c=cmd: self._send(c))
            grid.addWidget(btn, i // 3, (i % 3) * 2, 1, 2)
            self._cmd_buttons.append(btn)
        for n in (1, 2):
            btn = QtWidgets.QPushButton(f"RELEASE {n}")
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
        irreversible - the membrane stops on Stop, the motor stops on its own
        Stop and its pulse is bounded on the MCU - and running them is how
        the mechanism gets exercised on the bench. The MCU still refuses both
        in TERMINATION and SAFE, so nothing here can restart an aborted
        experiment.
        """
        sec.add(group_label("Membrane solenoid"))
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.sp_duty = QtWidgets.QSpinBox()
        self.sp_duty.setRange(5, 100)        # PARAM_MEMBRANE_DUTY limits
        self.sp_duty.setValue(20)
        self.sp_duty.setSuffix(" %")
        self.sp_duty.setStyleSheet(style.spin_style())
        self.sp_duty.setToolTip("Drive duty cycle (MEMBRANE key)")
        row.addWidget(self.sp_duty, 1)
        # Tenths of a hertz, not whole hertz: the membrane is worked at
        # 0.1..0.9 Hz as well as 2 Hz. The wire carries millihertz
        # (Commander.membrane_hz does the conversion).
        self.sp_hz = QtWidgets.QDoubleSpinBox()
        self.sp_hz.setDecimals(1)
        self.sp_hz.setSingleStep(0.1)
        self.sp_hz.setRange(0.1, 400.0)      # PARAM_MEMBRANE_MHZ limits / 1000
        self.sp_hz.setValue(2.0)
        self.sp_hz.setSuffix(" Hz")
        self.sp_hz.setStyleSheet(style.spin_style())
        self.sp_hz.setToolTip("Drive frequency, 0.1 to 400 Hz in tenths, "
                              "sent as SET_PARAM MEMBRANE_MHZ (millihertz) "
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

        # The GP30 position switch as a light. The Membrane HK row already
        # says `pulled` / `pushed`, but that is one word in a column of text;
        # an operator exercising the solenoid on the bench wants to see at a
        # glance whether the plunger is doing what the drive asks.
        #
        # So the colour is a verdict, not a position: GREEN = the switch
        # agrees with the drive that is running, RED = it does not (a drive
        # is on and the plunger is not moving - the fault this switch exists
        # to show), GREY = no verdict is available. Grey covers the drive
        # being off, no HK yet, stale HK, an MCU build that cannot reach
        # GP30, and a drive too slow for a 1 Hz sample to prove anything -
        # never a confident colour for a judgement the telemetry does not
        # support. The text always says which of those it is.
        sw = QtWidgets.QHBoxLayout()
        sw.setContentsMargins(0, 2, 0, 0)
        sw.setSpacing(6)
        self.dot_switch = QtWidgets.QLabel("●")
        self.dot_switch.setFixedWidth(14)
        self.dot_switch.setAlignment(QtCore.Qt.AlignCenter)
        sw.addWidget(self.dot_switch)
        self.lbl_switch = QtWidgets.QLabel("-")
        self.lbl_switch.setToolTip(
            "Membrane position switch on GP30: pressed by the plunger when "
            "the solenoid actuates, released while it rests (HK "
            "MEMBRANE_PULLED, set = pressed = pulled; MEMBRANE_CYCLING = it "
            "changed state within the last second).\n\n"
            "Green: the switch matches the drive that is running. Red: it "
            "does not. Grey: no verdict - drive off, no or stale HK, a build "
            "without GP30, or a drive too slow for a 1 Hz sample to judge.")
        sw.addWidget(self.lbl_switch, 1)
        sec.add(sw)
        self._set_switch(None, None, 0, "no telemetry")

        sec.add(group_label("CaCO₃ dispersion motor"))
        # Speed is a slider, not a spin box: it is a continuous mechanical
        # setting an operator dials while watching the motor, and the value
        # lives beside it so the panel never shows a handle without a number.
        speed = QtWidgets.QHBoxLayout()
        speed.setContentsMargins(0, 0, 0, 0)
        speed.setSpacing(6)
        speed.addWidget(QtWidgets.QLabel("Speed"))
        self.sl_motor = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sl_motor.setRange(20, 100)      # PARAM_DISPERSE_DUTY limits
        self.sl_motor.setValue(50)
        self.sl_motor.setStyleSheet(style.slider_style())
        self.sl_motor.setToolTip("Motor PWM duty, sent as SET_PARAM "
                                 "DISPERSE_DUTY before a drive starts, and "
                                 "again whenever it is changed while the "
                                 "motor is running")
        #: Set by an accepted Start, cleared by Stop. What the live speed
        #: updates key off; the MCU's own state is in HK.
        self._motor_running = False
        #: The duty the MCU last accepted, so the same value is never sent
        #: twice - a drag that ends where it started is not a new setting.
        self._motor_speed_sent = self.sl_motor.value()
        # Both signals, because neither alone covers the ways a slider moves.
        # `sliderReleased` is emitted only for a drag of the handle, so on its
        # own the keyboard, the wheel and a click on the groove changed the
        # number beside the slider and never told the MCU - the panel then
        # showed a speed the motor was not turning at, which is the one thing
        # this control must not do. `valueChanged` covers all of those, and
        # defers to the release while the handle is actually held down so a
        # drag still spends one SET_PARAM rather than one per step.
        self.sl_motor.valueChanged.connect(self._on_motor_speed)
        self.sl_motor.sliderReleased.connect(self._on_motor_speed_released)
        speed.addWidget(self.sl_motor, 1)
        self.lbl_motor_speed = QtWidgets.QLabel("100 %")
        self.lbl_motor_speed.setMinimumWidth(42)
        self.lbl_motor_speed.setAlignment(QtCore.Qt.AlignRight
                                          | QtCore.Qt.AlignVCenter)
        self.lbl_motor_speed.setStyleSheet(f"color:{style.MUTED};"
                                           " font-size:11px;")
        speed.addWidget(self.lbl_motor_speed)
        sec.add(speed)

        # Start/Stop mirror the membrane's Drive/Stop: a run is a state the
        # operator holds, ended only by Stop (or an abort). One pulse is the
        # bounded 5 s drive a release also schedules, kept as its own button
        # so the flight drive can still be rehearsed exactly.
        row3 = QtWidgets.QHBoxLayout()
        row3.setContentsMargins(0, 0, 0, 0)
        row3.setSpacing(6)
        self.btn_motor_start = QtWidgets.QPushButton("Start")
        self.btn_motor_start.setStyleSheet(style.primary_btn())
        self.btn_motor_start.setToolTip("Run the motor forward at the speed "
                                        "above until Stop (DISPERSE run)")
        self.btn_motor_start.clicked.connect(self._motor_start)
        row3.addWidget(self.btn_motor_start, 1)
        self.btn_motor_stop = QtWidgets.QPushButton("Stop")
        self.btn_motor_stop.setStyleSheet(style.flat_btn())
        self.btn_motor_stop.setToolTip("Stop the motor now - ends a run and "
                                       "cuts a pulse short (DISPERSE stop)")
        self.btn_motor_stop.clicked.connect(self._motor_stop)
        row3.addWidget(self.btn_motor_stop, 1)
        sec.add(row3)

        self.btn_pulse = QtWidgets.QPushButton("One pulse")
        self.btn_pulse.setStyleSheet(style.flat_btn())
        self.btn_pulse.setToolTip("One forward pulse at the speed above, "
                                  "timed on the MCU (5 s) - what a release "
                                  "schedules. Stop cuts it short. Refused "
                                  "while the motor is running")
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

    def _send(self, cmd: Command) -> None:
        if self._cmd is None:
            self.lbl_cmd_status.setText("no command link")
            return
        try:
            r = self._cmd.send(cmd)
            self.lbl_cmd_status.setText(f"{cmd.name} -> {r.name}")
        except CommandError as e:
            self.lbl_cmd_status.setText(str(e))

    def _release(self, valve: int) -> None:
        if self._cmd is None:
            self.lbl_cmd_status.setText("no command link")
            return
        # The dialog is the only thing between the click and the valve: the
        # ground interlock and the ARM step that used to stand in front of it
        # are gone (2026-09-18).
        ok = QtWidgets.QMessageBox.question(
            self.sec_cmd, "Confirm release",
            f"Fire pinch valve {valve}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if ok != QtWidgets.QMessageBox.Yes:
            return
        try:
            r = self._cmd.release(valve)
            self.lbl_cmd_status.setText(f"RELEASE {valve} -> {r.name}")
        except CommandError as e:
            self.lbl_cmd_status.setText(str(e))

    # -- actuators -----------------------------------------------------------

    def _membrane_start(self) -> None:
        """Frequency first, then the drive: PARAM_MEMBRANE_MHZ is read when
        the drive starts, so setting it afterwards would leave the solenoid
        running at the old rate while the panel showed the new one."""
        if self._cmd is None:
            self.lbl_act_status.setText("no command link")
            return
        try:
            r = self._cmd.membrane_hz(self.sp_hz.value())
            if r != AckResult.OK:
                self.lbl_act_status.setText(
                    f"MEMBRANE_MHZ -> {r.name}, not driving")
                return
            # Only once the MCU has ACKed it: the switch light judges a
            # missing edge against this rate, so it must be the rate the MCU
            # took, not the one the spin box shows.
            self._membrane_hz = self.sp_hz.value()
            r = self._cmd.membrane(self.sp_duty.value())
            self.lbl_act_status.setText(
                f"membrane {self.sp_duty.value()} % @ {self.sp_hz.value():g} Hz "
                f"-> {r.name}")
        except (CommandError, ValueError) as e:
            self.lbl_act_status.setText(str(e))

    def _membrane_stop(self) -> None:
        if self._cmd is None:
            self.lbl_act_status.setText("no command link")
            return
        try:
            r = self._cmd.membrane(0)
            self.lbl_act_status.setText(f"membrane off -> {r.name}")
        except (CommandError, ValueError) as e:
            self.lbl_act_status.setText(str(e))

    def _on_motor_speed(self, value: int) -> None:
        """The number beside the handle, always - and the MCU too, unless the
        handle is being dragged right now.

        Mid-drag the send waits for `sliderReleased`, so a drag costs one
        SET_PARAM instead of one per intermediate step: uplink is not spent on
        settings nobody chose. Every other way the value moves - arrow keys,
        the wheel, a click on the groove, `setValue` - emits no release at
        all, so for those this is the only chance to tell the MCU, and it
        takes it.
        """
        self.lbl_motor_speed.setText(f"{value} %")
        if not self.sl_motor.isSliderDown():
            self._push_motor_speed()

    def _on_motor_speed_released(self) -> None:
        """The end of a drag: the value it settled on goes to the MCU now."""
        self._push_motor_speed()

    def _push_motor_speed(self) -> None:
        """A running motor takes its new speed as soon as the operator has
        chosen one - the MCU re-latches PARAM_DISPERSE_DUTY at once while it
        runs. Idle, nothing is sent; the next Start or pulse carries the
        speed. An unchanged value is not re-sent: a drag that ends where it
        started, or a release after `valueChanged` already pushed, is not a
        new setting."""
        if not self._motor_running or self._cmd is None:
            return
        speed = self.sl_motor.value()
        if speed == self._motor_speed_sent:
            return
        try:
            r = self._cmd.set_param(int(Param.DISPERSE_DUTY), speed)
            if r == AckResult.OK:
                self._motor_speed_sent = speed
            self.lbl_act_status.setText(f"motor speed {speed} % -> {r.name}")
        except (CommandError, ValueError) as e:
            self.lbl_act_status.setText(str(e))

    def _send_motor_speed(self, what: str) -> int | None:
        """SET_PARAM DISPERSE_DUTY from the slider; the speed the panel shows
        must be the speed that runs. Returns it, or None (and says why) when
        the MCU did not take it - then no drive is started."""
        speed = self.sl_motor.value()
        r = self._cmd.set_param(int(Param.DISPERSE_DUTY), speed)
        if r != AckResult.OK:
            self.lbl_act_status.setText(
                f"DISPERSE_DUTY -> {r.name}, not {what}")
            return None
        self._motor_speed_sent = speed
        return speed

    def _motor_start(self) -> None:
        """Speed first, then the run - the same order as the membrane, and
        for the same reason: the duty is latched when the drive starts."""
        if self._cmd is None:
            self.lbl_act_status.setText("no command link")
            return
        try:
            speed = self._send_motor_speed("starting")
            if speed is None:
                return
            r = self._cmd.disperse_run()
            self._motor_running = r == AckResult.OK
            self.lbl_act_status.setText(f"motor run {speed} % -> {r.name}")
        except (CommandError, ValueError) as e:
            self.lbl_act_status.setText(str(e))

    def _motor_stop(self) -> None:
        if self._cmd is None:
            self.lbl_act_status.setText("no command link")
            return
        self._motor_running = False
        try:
            r = self._cmd.disperse_stop()
            self.lbl_act_status.setText(f"motor stop -> {r.name}")
        except (CommandError, ValueError) as e:
            self.lbl_act_status.setText(str(e))

    def _disperse(self) -> None:
        """Speed first, then the pulse: PARAM_DISPERSE_DUTY is latched when
        the drive is queued, so setting it afterwards would run the motor at
        the old speed while the panel showed the new one."""
        if self._cmd is None:
            self.lbl_act_status.setText("no command link")
            return
        try:
            speed = self._send_motor_speed("pulsing")
            if speed is None:
                return
            r = self._cmd.disperse()
            self.lbl_act_status.setText(f"disperse {speed} % -> {r.name}")
        except (CommandError, ValueError) as e:
            self.lbl_act_status.setText(str(e))

    # -- refresh -------------------------------------------------------------

    def _set_switch(self, pulled: bool | None, cycling: bool | None,
                    duty: int = 0, reason: str = "") -> None:
        """Set the position-switch light: does the switch agree with the
        drive that is running?

        `pulled` None means there is no reading at all and `reason` says why.
        `duty` is the commanded membrane duty from the same HK packet - with
        the drive off there is nothing to agree with, so the light is grey
        whatever the switch says, and the text reports the switch plainly.

        With the drive on, MEMBRANE_CYCLING is the verdict, not
        MEMBRANE_PULLED: HK is sampled at 1 Hz against a drive that is
        normally 2 Hz, so the position alone lands at an arbitrary phase and
        proves nothing either way. Cycling means the plunger is following the
        drive - green. Not cycling, while an edge was due inside the packet's
        second, is the stuck plunger - red. If the drive is slower than that,
        a clear bit is the sampling rather than a fault, and the light stays
        grey and says so.
        """
        colour = style.GRAY
        if pulled is None:
            text = f"switch: {reason or 'no reading'}"
        else:
            where = "pressed" if pulled else "released"
            if not duty:
                # No drive: the switch is reported, not judged. It should sit
                # released; pressed with nothing driving is worth seeing, so
                # it is spelled out rather than coloured.
                text = (f"solenoid off - switch {where}"
                        + (" (plunger still out)" if pulled else ""))
                if cycling:
                    text += ", cycling"
            elif cycling:
                colour = style.GREEN
                text = f"driving {duty} % - plunger cycling, switch {where}"
            elif membrane_longest_phase_ms(self._membrane_hz,
                                           duty) < HK_PERIOD_MS:
                colour = style.RED
                text = (f"driving {duty} % - plunger NOT cycling, "
                        f"switch stuck {where}")
            else:
                text = (f"driving {duty} % at {self._membrane_hz:g} Hz - "
                        "too slow to judge from 1 Hz HK, "
                        f"switch {where}")
        self.dot_switch.setStyleSheet(f"color:{colour}; font-size:15px;")
        self.lbl_switch.setText(text)
        self.lbl_switch.setStyleSheet(
            f"color:{style.GRAY if pulled is None else style.TEXT};"
            " font-size:11px;")

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
            if age is not None and age > STALE_HK_S:
                self._set_switch(None, None, h.membrane_duty,
                                 "stale telemetry")
            elif h.membrane_pulled is None:
                self._set_switch(None, None, h.membrane_duty,
                                 "no reading (MCU build without GP30)")
            else:
                self._set_switch(h.membrane_pulled, h.membrane_cycling,
                                 h.membrane_duty)

        if self._cmd is None:
            link = "no command link (listen-only)"
        elif self._cmd.connected:
            rtt = self._cmd.last_rtt_s
            link = (f"cmd up ({rtt * 1000:.0f} ms)" if rtt is not None
                    else "cmd up")
        else:
            link = "cmd DOWN - retrying"
        # Decode errors are on this line because the panel has no other way to
        # say "packets are arriving and none of them mean anything". A wire
        # format the ground and the MCU disagree about looks exactly like a
        # dead link from every readout in this window - every field stays at
        # its startup dash - and the receiver counts the failures silently.
        # rx climbing while hk age stays `-` is that fault, and this is where
        # an operator can see it.
        # And when the receiver knows *which* disagreement it is - an HK
        # payload of a length this build does not read - it says so above the
        # counters instead of leaving the operator to infer a version skew
        # from a number. That is the case worth naming: it is the one decode
        # failure that hides behind a healthy-looking link, because events,
        # quick-look and the command ACKs all keep working.
        errs = getattr(self._rx, "decode_errors", 0)
        bad = f"  undecoded {errs}" if errs else ""
        why = getattr(self._rx, "hk_reject_reason", None)
        self.lbl_downlink.setText(
            (f"{why}\n" if why else "") +
            f"rx {self._rx.gaps.received}  lost {self._rx.gaps.lost}  "
            f"hk age {'-' if age is None else f'{age:.1f} s'}{bad}\n{link}")

        while self.event_list.count() < len(self._rx.events):
            ev = self._rx.events[self.event_list.count()]
            self.event_list.addItem(
                f"[{severity_name(ev['severity'])}] "
                f"{event_name(ev['code'])}: {ev['text']}")
            self.event_list.scrollToBottom()
