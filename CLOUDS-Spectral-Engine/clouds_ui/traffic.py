"""Ethernet traffic indicator - what is actually moving on the wire.

A NIC activity LED for the operator: one lane per direction, each with a
blinking light, a smoothed rate and the session total. It answers the
question the housekeeping rows cannot - *is the cable carrying anything* -
without the operator opening a terminal, and it separates "the Pi is quiet"
from "the link is dead" from "the packets arrive and fail CRC".

Three lanes, deliberately not summed into one number:

* **Down** - the UDP telemetry the ``Receiver`` takes in (HK, events,
  quick-look, Pi status). This is the lane with a budget: 2 kbit/s
  continuous, and the indicator says so when it is exceeded.
* **Up** - the TCP command socket's tx: commands and the PING heartbeat,
  which is all it carries when nobody is commanding. Its ACK bytes come
  back on that same socket and are counted here too (``+ack``), because an
  ACK is not downlink telemetry and must not inflate the budget lane.
* **Bench** - the ``--net`` frame stream off the Pi (TCP 4010), when the
  spectrum is coming from a remote detector. ~50 kB/s, three orders of
  magnitude above the flight downlink; adding it to the Down lane would
  make the budget reading meaningless, so it gets its own row and only
  appears when that driver is in use.

Everything here is polled from a QTimer on the GUI thread - the receiver and
the acquisition worker keep their own counters and never touch Qt (the
dashboard's rule, kept). Counters are plain ints written from one thread and
read from another, which under the GIL is the one case where that is safe;
nothing here needs them to be consistent with each other.
"""
from __future__ import annotations

import math
import time

from PyQt5 import QtCore, QtWidgets

from . import style

#: Continuous downlink allowance (FswConfig.budget_kbit_s). Over this the
#: Down lane goes amber - the same limit tests/test_fsw_telemetry.py enforces
#: on the Pi, shown to the operator instead of only failing in CI.
BUDGET_BIT_S = 2000.0

#: A source that has delivered nothing for this long is not idle, it is
#: silent. HK is 1 Hz, so three seconds is three missed packets.
SILENT_S = 3.0

#: Rate smoothing time constant. HK arrives in 1 Hz bursts and the poll is
#: 500 ms, so the instantaneous rate alternates between zero and a spike;
#: the LED is what shows the burst, the number is what shows the load.
TAU_S = 3.0

_LED_ON = style.GREEN
_LED_IDLE = "#9fc7b6"        # link alive, nothing in this poll window
_LED_OVER = style.ORANGE     # over the downlink budget
_LED_SILENT = style.RED
_LED_NONE = style.GRAY       # no such link in this session


def fmt_rate(bit_s: float) -> str:
    if bit_s < 1000:
        return f"{bit_s:.0f} bit/s"
    if bit_s < 1e6:
        return f"{bit_s / 1e3:.2f} kbit/s"
    return f"{bit_s / 1e6:.2f} Mbit/s"


def fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} kB"
    return f"{n / 1024 ** 2:.1f} MB"


class _Lane:
    """One direction: a byte counter turned into a rate, a light and a total.

    `read` returns ``(total_bytes, last_activity_epoch)`` or None when there
    is no such link in this session (no receiver, no command link, no remote
    detector) - which is a normal state here, not an error.
    """

    def __init__(self, name: str, read, budget: float | None = None):
        self.name = name
        self.read = read
        self.budget = budget
        self.reset()

    def reset(self) -> None:
        self.bit_s = 0.0
        self.total = 0
        self._prev: int | None = None
        self._prev_t: float | None = None
        self.state = "none"      # none | silent | idle | active | over

    def poll(self, now: float) -> None:
        try:
            got = self.read()
        except Exception:        # noqa: BLE001 - a missing link is not an error
            got = None
        if got is None:
            self.reset()
            return
        total, last_t = got
        first = self._prev is None
        moved = 0 if first else max(0, total - self._prev)
        dt = None if self._prev_t is None else max(1e-3, now - self._prev_t)
        self._prev, self._prev_t = total, now
        self.total = total
        if dt is not None:
            # Exponential moving average, time-constant based so the number
            # does not depend on how often the window happens to poll.
            a = 1.0 - math.exp(-dt / TAU_S)
            self.bit_s += a * (moved * 8.0 / dt - self.bit_s)
        quiet = now - last_t if last_t else None
        if quiet is None or quiet > SILENT_S:
            # Nothing ever arrived, or nothing for SILENT_S. The averaged rate
            # decays on its own from the zero deltas; the light is what says
            # the link is out.
            self.state = "silent"
        elif self.budget is not None and self.bit_s > self.budget:
            self.state = "over"
        elif moved or first:
            # `first` covers the poll that has no delta yet: the source's own
            # stamp already said it is carrying traffic, and a light that
            # waits a window before admitting it reads as a dead link.
            self.state = "active"
        else:
            self.state = "idle"

    @property
    def colour(self) -> str:
        return {"none": _LED_NONE, "silent": _LED_SILENT, "idle": _LED_IDLE,
                "active": _LED_ON, "over": _LED_OVER}[self.state]

    @property
    def rate_text(self) -> str:
        if self.state == "none":
            return "-"
        if self.state == "silent" and not self.total:
            return "no data"
        return fmt_rate(self.bit_s)


class TrafficIndicator(QtWidgets.QWidget):
    """Down / Up / Bench lanes with a live LED, rate and session total.

    Polls itself: it must keep reading when the flight timer is stopped
    (an instrument-only session over ``--net`` has Ethernet traffic and no
    downlink at all), and a link indicator that stops updating is worse than
    none - it shows the last value as if it were current.
    """

    def __init__(self, receiver=None, commander=None, driver=None,
                 parent=None, interval_ms: int = 500):
        super().__init__(parent)
        self._rx = receiver
        self._cmd = commander
        #: The detector driver, or a zero-argument callable returning it. The
        #: window re-opens its driver on reconnect and on Restart, so the
        #: callable form is what keeps the Bench lane on the socket that is
        #: live now instead of a closed one.
        self._driver = driver
        self._bench_of = None       # driver the Bench lane's counters belong to

        self.lane_down = _Lane("Down", self._read_down, budget=BUDGET_BIT_S)
        self.lane_up = _Lane("Up", self._read_up)
        self.lane_bench = _Lane("Bench", self._read_bench)
        self.lanes = [self.lane_down, self.lane_up, self.lane_bench]

        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(2, 1)
        head = QtWidgets.QLabel("ETHERNET")
        head.setStyleSheet(f"color:{style.SECTION}; font-size:10px;"
                           "letter-spacing:3px;")
        grid.addWidget(head, 0, 0, 1, 3)
        self.lbl_peer = QtWidgets.QLabel("-")
        self.lbl_peer.setAlignment(QtCore.Qt.AlignRight)
        self.lbl_peer.setStyleSheet(f"color:{style.SECTION}; font-size:10px;"
                                    f"font-family:{style.MONO};")
        grid.addWidget(self.lbl_peer, 0, 3)

        self._leds: dict[str, QtWidgets.QLabel] = {}
        self._rates: dict[str, QtWidgets.QLabel] = {}
        self._totals: dict[str, QtWidgets.QLabel] = {}
        for row, lane in enumerate(self.lanes, start=1):
            led = QtWidgets.QLabel()
            led.setFixedSize(9, 9)
            name = QtWidgets.QLabel(lane.name)
            name.setStyleSheet(f"color:{style.MUTED}; font-size:11px;")
            rate = QtWidgets.QLabel("-")
            rate.setAlignment(QtCore.Qt.AlignRight)
            rate.setStyleSheet(f"color:{style.NAVY}; font-family:{style.MONO};"
                               "font-size:11px; font-weight:bold;")
            total = QtWidgets.QLabel("-")
            total.setAlignment(QtCore.Qt.AlignRight)
            total.setStyleSheet(f"color:{style.MUTED};"
                                f"font-family:{style.MONO}; font-size:11px;")
            grid.addWidget(led, row, 0)
            grid.addWidget(name, row, 1)
            grid.addWidget(rate, row, 2)
            grid.addWidget(total, row, 3)
            self._leds[lane.name] = led
            self._rates[lane.name] = rate
            self._totals[lane.name] = total
        self.setToolTip(
            "Bytes on the wire, not decoded packets.\n"
            "Down: UDP telemetry from the Pi - HK, events, quick-look "
            f"(amber over the {BUDGET_BIT_S / 1000:.0f} kbit/s budget).\n"
            "Up: TCP commands and the PING heartbeat, ACK bytes counted "
            "back separately.\n"
            "Bench: the --net frame stream (TCP 4010), only when the "
            "spectrum comes from a remote detector.\n"
            "Red: the link exists but has been silent for "
            f"{SILENT_S:.0f} s.")

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    # -- sources -------------------------------------------------------------

    def _read_down(self):
        rx = self._rx
        if rx is None:
            return None
        return int(rx.rx_bytes), float(rx.last_rx_time)

    def _read_up(self):
        cmd = self._cmd
        if cmd is None:
            return None
        # The ACK bytes ride the same socket in the other direction; counting
        # them into this lane's total keeps the uplink's traffic in one place
        # while leaving the Down lane purely the telemetry budget.
        return int(cmd.tx_bytes + cmd.rx_bytes), float(max(cmd.last_tx_time,
                                                           cmd.last_rx_time))

    def _current_driver(self):
        d = self._driver
        if callable(d):
            try:
                d = d()
            except Exception:       # noqa: BLE001 - see the class docstring
                d = None
        return d

    def _read_bench(self):
        # Duck-typed: only NetDriver carries these. The local USB drivers are
        # not Ethernet and the lane stays grey for them.
        d = self._current_driver()
        if d is not self._bench_of:
            # A reconnect or a Restart opened a new driver: its counters start
            # at zero, so carrying the old totals across would read as a burst
            # of traffic followed by a stall.
            self._bench_of = d
            self.lane_bench.reset()
        tx = getattr(d, "tx_bytes", None)
        if tx is None:
            return None
        return int(tx + d.rx_bytes), float(max(d.last_tx_time, d.last_rx_time))

    # -- lifecycle -----------------------------------------------------------

    def rebind(self, receiver=None, commander=None, driver=None) -> None:
        """Point at a new receiver / commander / driver (the window's
        Restart), and start the counters over: the totals are the session's,
        and carrying the old ones across would read as traffic that this
        session never saw."""
        self._rx = receiver
        self._cmd = commander
        if driver is not None:
            self._driver = driver
        for lane in self.lanes:
            lane.reset()
        self.refresh()

    def _peer_text(self) -> str:
        """The far end of the link, so the operator can see at a glance
        whether this is the cable (192.168.100.10) or loopback (mock)."""
        cmd = self._cmd
        host = getattr(cmd, "peer", "") if cmd is not None else ""
        if not host:
            d = self._current_driver()
            if getattr(d, "tx_bytes", None) is not None and getattr(d, "host", ""):
                host = f"{d.host}:{d.port}"
        return host or "-"

    # -- refresh -------------------------------------------------------------

    def refresh(self) -> None:
        """Poll every counter. Guarded end to end: this is a QTimer slot, and
        PyQt5 aborts the process on an unhandled exception in one - a traffic
        readout is never worth the window."""
        try:
            now = time.time()
            for lane in self.lanes:
                lane.poll(now)
                self._leds[lane.name].setStyleSheet(
                    f"background:{lane.colour}; border-radius:4px;")
                self._rates[lane.name].setText(lane.rate_text)
                self._totals[lane.name].setText(
                    "-" if lane.state == "none" else fmt_bytes(lane.total))
            self.lbl_peer.setText(self._peer_text())
        except Exception:                       # noqa: BLE001 - see above
            pass
