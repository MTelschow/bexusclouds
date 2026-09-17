"""Housekeeping over time: the lower half of the operator's plot view.

The spectrum answers "what is the instrument seeing now". Nothing in the
window answered "what has the experiment been doing", and the sidebar's
Sensors section cannot: it is a snapshot, so a rail that sagged for three
seconds two minutes ago left no trace an operator could see. This is the
history of the same numbers, on the same screen, under the spectrum.

The source is the **downlink only** - one sample per housekeeping packet,
1 Hz, so the buffer is the ground station's own record of what arrived. There
is no detector data here: the spectrum above already is that, and mixing a
60 ms instrument trace with a 1 Hz telemetry series on one time axis is the
same confusion the source banner exists to prevent.

Three rules it inherits from the Sensors section, because they are about the
same numbers and disagreeing would be worse than not plotting at all:

* **A field with no sensor behind it is not drawn.** The MCU sends zeros
  whenever a part has no reading to give - the BNO055 through its 650 ms
  boot, and permanently if its bring-up fails. A zero plotted on an
  acceleration axis is a reading. So a sample whose `HkErrors` flag is set
  becomes a gap, and the legend says why. The STLM20 pair has no rows here at all - like the
  Sensors section, a series that could only ever be empty is not offered;
  `HKE_NO_TEMP` in the Errors row is where those two wire fields are
  declared.
* **An unreadable rail is a gap, not a zero.** `RAIL_MV_INVALID` means the
  monitor did not answer; 0 V is a real reading for a rail with no supply.
  `Housekeeping.rail_a()` already enforces that pair, and is used as-is.
* **A dropout is a gap, not a straight line.** Miss `GAP_S` of packets and the
  buffer breaks the trace, because a line drawn across a link outage claims
  the ground station knows what happened during it.

Series are grouped onto one sub-axis per **unit**, stacked and sharing the
time axis, rather than squeezed onto one scale: hPa next to A on a shared
y axis is unreadable, and a normalised "everything 0..1" plot throws away the
only thing an engineering readout is for.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from PyQt5 import QtCore, QtGui, QtWidgets

from clouds_link.hk import RAIL_I2C_ADDR, RAIL_NAMES, HkErrors

from . import style

#: How long the ring buffer keeps history, in samples. Housekeeping is 1 Hz,
#: so this is two hours - longer than any bench session and longer than the
#: flight, at ~30 floats per sample it costs a couple of MB.
MAXLEN = 7200

#: A hole in the record longer than this breaks the trace instead of being
#: bridged. Housekeeping is 1 Hz and the state banner already goes red at 5 s
#: (`flight.STALE_HK_S`), so the two agree on what "the link stopped" means.
GAP_S = 5.0

#: Selectable spans, shortest first. "All" is the whole buffer.
WINDOWS = (("1 min", 60.0), ("5 min", 300.0), ("15 min", 900.0),
           ("1 h", 3600.0), ("All", None))


def fig_to_pixmap(fig):
    """Render a matplotlib figure to a QPixmap (shared with the spectrum)."""
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    w, h = canvas.get_width_height()
    data = bytes(canvas.buffer_rgba())      # keep alive until the pixmap copies
    img = QtGui.QImage(data, w, h, QtGui.QImage.Format_RGBA8888)
    return QtGui.QPixmap.fromImage(img.copy())


@dataclass(frozen=True)
class Series:
    """One plottable housekeeping number.

    `get` returns the value in `unit`, or **None where there is no reading** -
    an unreadable rail, a field the MCU filled with zeros because nothing is
    fitted. None becomes a gap in the trace; it is never turned into 0.

    `flag` is the `HkErrors` bit that means this field has no source, read
    per sample rather than once: `BME280_FAIL` and `IMU_FAIL` come and go.

    `fitted` is False where the reading belongs to a rail whose monitor is
    reserved but unpopulated - the 24 V slot. Those series stay in the table
    with their toggle disabled, because the operator needs to find out that
    the monitor is missing, and the slot is expected to be filled. A part
    that is simply not part of the experiment gets no entry at all (the
    STLM20 pair): a row that can never draw anything, ever, teaches nothing
    that `error_flags` does not already say.
    """
    key: str
    label: str
    unit: str
    group: str
    color: str
    get: Callable
    flag: int | None = None
    fitted: bool = True


def _rail_v(i: int):
    def get(h):
        mv = h.rail_mv[i]
        return None if h.rail_a(i) is None else mv / 1000.0
    return get


def _rail_i(i: int):
    return lambda h: h.rail_a(i)


def _vec(attr: str, axis: int, scale: float = 1.0):
    return lambda h: float(getattr(h, attr)[axis]) * scale


# Per-group ramps rather than one rainbow: the four rail voltages belong
# together and read as a family, and a rail's current is the same hue as its
# voltage so the two axes can be followed down the stack.
_RAIL_C = ("#01386a", "#8a97a3", "#1D9E75", "#E8821E")
_AXIS_C = ("#b0413e", "#1D9E75", "#4d8fd1")

#: Everything the 64-byte housekeeping packet carries that varies over time.
#: `state`, `fired` and the link flags are deliberately absent - they are
#: enumerations, and a step plot of "SEAL = 3" invites reading the number.
SERIES: tuple[Series, ...] = (
    Series("p_amb", "Ambient p", "hPa", "BME280", "#01386a",
           lambda h: h.p_amb_pa / 100.0, HkErrors.BME280_FAIL),
    Series("bme_t", "Ambient T", "C", "BME280", "#b0413e",
           lambda h: h.bme_temp_cc / 100.0, HkErrors.BME280_FAIL),
    Series("rh1", "Ambient RH", "%", "BME280", "#4d8fd1",
           lambda h: h.rh1_cpct / 100.0, HkErrors.BME280_FAIL),
    # The chamber part, on SPI_1. Its own group rather than three more rows
    # under "BME280": the interesting trace is chamber against ambient, and
    # two groups that can be ticked as wholes is how an operator gets that
    # pair onto the plot. Same three hues as the ambient triple, so
    # `Chamber p` and `Ambient p` read as the same quantity from two places.
    Series("chm_p", "Chamber p", "hPa", "BME280 chamber", "#01386a",
           lambda h: h.chm_p_pa / 100.0, HkErrors.BME280_CHM_FAIL),
    Series("chm_t", "Chamber T", "C", "BME280 chamber", "#b0413e",
           lambda h: h.chm_temp_cc / 100.0, HkErrors.BME280_CHM_FAIL),
    Series("chm_rh", "Chamber RH", "%", "BME280 chamber", "#4d8fd1",
           lambda h: h.chm_rh_cpct / 100.0, HkErrors.BME280_CHM_FAIL),
) + tuple(
    Series(f"acc_{ax}", f"Accel {ax.upper()}", "mg", "BNO055", _AXIS_C[i],
           _vec("accel_mg", i), HkErrors.IMU_FAIL)
    for i, ax in enumerate("xyz")
) + tuple(
    Series(f"gyr_{ax}", f"Gyro {ax.upper()}", "dps", "BNO055", _AXIS_C[i],
           _vec("gyro_ddps", i, 0.1), HkErrors.IMU_FAIL)
    for i, ax in enumerate("xyz")
) + tuple(
    Series(f"rail_v{i}", f"{name} bus", "V", "INA226", _RAIL_C[i],
           _rail_v(i), None, fitted=RAIL_I2C_ADDR[i] is not None)
    for i, name in enumerate(RAIL_NAMES)
) + tuple(
    Series(f"rail_i{i}", f"{name} current", "A", "INA226", _RAIL_C[i],
           _rail_i(i), None, fitted=RAIL_I2C_ADDR[i] is not None)
    for i, name in enumerate(RAIL_NAMES)
) + (
    Series("membrane", "Membrane duty", "%", "Actuators", "#1D9E75",
           lambda h: float(h.membrane_duty)),
    # The dispersion motor's sensed current beside the membrane duty: the
    # DRV8251A IPROPI chain on GP46, scaled to amps by hk.HB_SENSE_A_PER_V.
    # It moves only during the bounded 5 s motor pulses and reads 0 in coast
    # (see HB_SENSE_A_PER_V), so a flat trace between releases is expected.
    # A sentinel is a gap, like an unreadable rail.
    Series("hb_sense", "Dispersion motor current", "A", "Actuators", "#b0413e",
           lambda h: h.hb_sense_a()),
)

SERIES_BY_KEY = {s.key: s for s in SERIES}

#: What the plot shows before anyone touches a checkbox. Two series on two
#: axes: the ambient pair is what a gondola ascent shows first, and it is the
#: one group whose sensor is actually fitted and known good.
DEFAULT_KEYS = ("p_amb", "bme_t")

#: Groups in sidebar order, each with its series.
GROUPS: tuple[tuple[str, tuple[Series, ...]], ...] = tuple(
    (g, tuple(s for s in SERIES if s.group == g))
    for g in dict.fromkeys(s.group for s in SERIES)
)

#: Units in the order their first series appears, so the stack does not
#: reshuffle when a series is toggled.
_UNIT_ORDER = tuple(dict.fromkeys(s.unit for s in SERIES))


class TimelineBuffer:
    """Ring buffer of housekeeping samples, one column per `Series`.

    Values are stored already converted, as float with NaN for "no reading",
    so the renderer never has to know which field meant what. Sampling is the
    caller's job (`window._sample_timeline`), driven off the receiver's
    `last_hk_time` so a 2 Hz poll of a 1 Hz stream records one point, not two.
    """

    def __init__(self, maxlen: int = MAXLEN, gap_s: float = GAP_S):
        self._maxlen = maxlen
        self._gap_s = gap_s
        self.t: deque = deque(maxlen=maxlen)
        self.v: dict[str, deque] = {s.key: deque(maxlen=maxlen) for s in SERIES}
        #: `error_flags` of the newest sample, for labelling unsourced series.
        self.last_flags = 0

    def __len__(self) -> int:
        return len(self.t)

    def clear(self) -> None:
        self.t.clear()
        for d in self.v.values():
            d.clear()
        self.last_flags = 0

    def append(self, t: float, hk) -> None:
        """Record one housekeeping packet, timestamped with its arrival.

        A sample more than `gap_s` after the previous one gets an all-NaN
        sample inserted just before it, which is what breaks the line across
        a dropout instead of drawing a straight segment through it.
        """
        if self.t and (t - self.t[-1]) > self._gap_s:
            self.t.append(t - self._gap_s / 2.0)
            for d in self.v.values():
                d.append(np.nan)
        self.t.append(t)
        self.last_flags = int(getattr(hk, "error_flags", 0))
        for s in SERIES:
            self.v[s.key].append(self._value(s, hk))

    @staticmethod
    def _value(s: Series, hk) -> float:
        """One field of one packet, or NaN where it is not a measurement.

        The flag check comes first and the broad `except` behind it: an
        unsourced field is the expected case on this carrier, not an error,
        and a decode surprise in one series must not cost the whole sample.
        """
        if s.flag is not None and (getattr(hk, "error_flags", 0) & s.flag):
            return np.nan
        try:
            val = s.get(hk)
        except Exception:                       # noqa: BLE001 - see above
            return np.nan
        return np.nan if val is None else float(val)

    def window(self, keys, window_s: float | None):
        """`(x, {key: y})` for the last `window_s` seconds, x in seconds
        **before the newest sample** - 0 at the right edge, negative to the
        left. Relative because the operator's question is "how long ago", and
        because a wall-clock axis on a 1 min span is six identical labels."""
        if not self.t:
            return np.empty(0), {}
        t = np.fromiter(self.t, dtype=float, count=len(self.t))
        x = t - t[-1]
        keep = slice(0, None) if window_s is None else slice(
            int(np.searchsorted(x, -float(window_s), side="left")), None)
        out = {}
        for k in keys:
            col = self.v.get(k)
            if col is None:
                continue
            out[k] = np.fromiter(col, dtype=float, count=len(col))[keep]
        return x[keep], out


class TimelineView(QtWidgets.QWidget):
    """The housekeeping history plot: a matplotlib figure into a QLabel, the
    same way the spectrum is drawn, so both halves of the view share a look
    and neither needs a Qt canvas widget.

    It owns no data and no timer. `set_selection()` / `set_window()` come from
    the sidebar and `refresh()` from the flight tick; a repaint happens only
    when one of those says something changed, which is at most 1 Hz.
    """

    def __init__(self, buffer: TimelineBuffer, parent=None):
        super().__init__(parent)
        self.buf = buffer
        self.selected: list[str] = [k for k in DEFAULT_KEYS if k in SERIES_BY_KEY]
        self.window_s: float | None = 300.0
        self._note = "waiting for housekeeping"
        self.setStyleSheet(f"background:{style.VIEW_BG};")
        self.setMinimumHeight(150)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.plot = QtWidgets.QLabel(self)
        self.plot.setAlignment(QtCore.Qt.AlignCenter)
        self.plot.setStyleSheet("background:transparent;")
        lay.addWidget(self.plot)
        self.refresh()

    # -- inputs -------------------------------------------------------------

    def set_selection(self, keys) -> None:
        self.selected = [k for k in (s.key for s in SERIES) if k in set(keys)]
        self.refresh()

    def set_window(self, window_s) -> None:
        self.window_s = window_s
        self.refresh()

    def set_note(self, text: str) -> None:
        """Why the plot is empty, when it is. Set once by the window: a bench
        session with no receiver is not a fault and should not read as one."""
        self._note = text
        self.refresh()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.refresh()

    # -- rendering ----------------------------------------------------------

    def refresh(self) -> None:
        w = max(420, self.width())
        h = max(150, self.height())
        dpi = 105
        fig = Figure(figsize=(w / dpi, h / dpi), dpi=dpi)
        fig.patch.set_facecolor(style.VIEW_BG)
        x, cols = self.buf.window(self.selected, self.window_s)
        units = [u for u in _UNIT_ORDER
                 if any(SERIES_BY_KEY[k].unit == u for k in self.selected)]
        if not units or x.size == 0:
            self._draw_empty(fig, "no series selected" if not units
                             else self._note)
            return
        axes = fig.subplots(len(units), 1, sharex=True,
                            squeeze=False)[:, 0]
        fig.subplots_adjust(left=0.10, right=0.97, top=0.97, bottom=0.18,
                            hspace=0.12)
        for ax, unit in zip(axes, units):
            self._draw_axis(ax, unit, x, cols)
        axes[-1].set_xlabel("time before latest housekeeping  [s]",
                            color=style.MUTED, fontsize=8)
        self.plot.setPixmap(fig_to_pixmap(fig))

    def _draw_axis(self, ax, unit, x, cols) -> None:
        ax.set_facecolor("#ffffff")
        ax.grid(alpha=0.15)
        for sp in ax.spines.values():
            sp.set_color(style.BORDER)
        ax.tick_params(colors=style.MUTED, labelsize=7)
        ax.set_ylabel(unit, color=style.MUTED, fontsize=8)
        drawn = 0
        for key in self.selected:
            s = SERIES_BY_KEY[key]
            if s.unit != unit:
                continue
            y = cols.get(key)
            if y is None or y.size != x.size:
                continue
            # A series whose every point is a gap gets its reason in the
            # legend instead of an invisible line: the operator ticked a box
            # and must be told why nothing appeared.
            live = bool(np.isfinite(y).any())
            label = s.label if live else f"{s.label}  ({self._why(s)})"
            ax.plot(x, y, color=s.color, lw=1.2,
                    ls="-" if live else ":", label=label)
            drawn += 1
        if drawn:
            ax.legend(loc="upper left", fontsize=7, framealpha=0.9,
                      ncol=min(drawn, 4))
        if self.window_s is not None:
            ax.set_xlim(-self.window_s, 0)

    def _why(self, s: Series) -> str:
        """Why a selected series drew nothing. Distinguishes a part the board
        never had from one that is fitted and silent - the operator chases
        only the second."""
        if not s.fitted:
            return "not fitted"
        if s.flag is not None and (self.buf.last_flags & s.flag):
            return "no source"
        return "no reading"

    def _draw_empty(self, fig, text: str) -> None:
        ax = fig.add_axes([0.10, 0.18, 0.87, 0.79])
        ax.set_facecolor("#ffffff")
        ax.set_xticks([])
        ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_color(style.BORDER)
        ax.text(0.5, 0.5, text, ha="center", va="center",
                color=style.SECTION, fontsize=9, transform=ax.transAxes)
        self.plot.setPixmap(fig_to_pixmap(fig))
