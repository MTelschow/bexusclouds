"""Plot a session log over time - everything that was recorded, on one time axis.

    python plot_session.py                    # the newest session in ./gse_sessions
    python plot_session.py --list             # what is there, newest first
    python plot_session.py <any session file> # that session (any of its files)
    python plot_session.py output/session_20260918_205940.csv   # instrument log
    python plot_session.py --save out.pdf     # write instead of show

The session log is five files with one stamp (`gse/clouds_gse/session_log.py`):
housekeeping, events, quick-look, Pi status and the command uplink. Naming any
one of them plots **all** of them - they are one session, and the question a
log is opened for ("the rail sagged, what else happened at that moment") is
answered by the overlay, not by five separate plots. The instrument half's own
`output/session_*.csv` is a different shape (one row per acquired frame,
detector-side) and is recognised and plotted on its own terms.

Three rules are inherited from the operator interface's timeline
(`clouds_ui/timeline.py`), because these are the same numbers and a plot that
disagreed with the live one would be worse than no plot:

* **A field with no sensor behind it is a gap, never a zero.** The MCU sends
  zeros for a part it has no reading from, and `error_flags` says which. A
  zero on an acceleration axis is a reading; a gap is the truth.
* **An unreadable rail is a gap.** `RAIL_MV_INVALID` is not 0 V - 0 V is what
  a rail with no supply genuinely reads.
* **A dropout is a gap, not a straight line.** More than `--gap` seconds
  without a packet breaks the trace rather than bridging it.

Series are stacked one sub-axis per unit and share the time axis: hPa beside A
on one scale is unreadable, and normalising everything to 0..1 throws away the
only thing an engineering readout is for.
"""
from __future__ import annotations

import argparse
import ast
import csv
import glob
import os
import sys
import time

import numpy as np

from clouds_link.hk import (HB_SENSE_INVALID, RAIL_MV_INVALID, RAIL_NAMES,
                            HkErrors, SeqState)

HERE = os.path.dirname(os.path.abspath(__file__))

#: Same default the app writes to (`clouds_ui --log-dir`), and the instrument
#: half's own directory, searched in that order when nothing is named.
DEFAULT_DIRS = ("gse_sessions", "output")

#: A hole longer than this breaks a trace. Housekeeping is 1 Hz and the panel
#: calls the link stale at 5 s, so the two agree on what "it stopped" means.
GAP_S = 5.0

#: Colours, from `clouds_ui/style.py` - a plot that is filed next to a
#: screenshot of the window should not be a different brand.
NAVY = "#01386a"
ORANGE = "#E8821E"
GREEN = "#1D9E75"
RED = "#FF2A2A"
MUTED = "#5a6b7a"
GRID = "#dde3e9"

#: Event severities (clouds_link.frames.EventSeverity) to marker colours.
SEVERITY_COLOUR = {0: MUTED, 1: ORANGE, 2: RED, 3: RED}


# --------------------------------------------------------------- finding logs
def _newest(paths):
    return max(paths, key=os.path.getmtime) if paths else None


def list_sessions(directory: str):
    """Session stamps in ``directory``, newest first, as (stamp, files)."""
    out = []
    for hk_path in sorted(glob.glob(os.path.join(directory, "session_*_hk.csv")),
                          key=os.path.getmtime, reverse=True):
        out.append((_stamp_of(hk_path), session_files(hk_path)))
    return out


def _stamp_of(path: str) -> str:
    base = os.path.basename(path)
    for suffix in ("_hk.csv", "_events.csv", "_quicklook.jsonl",
                   "_pistatus.csv", "_commands.csv", "_summary.json"):
        if base.endswith(suffix):
            return base[len("session_"):-len(suffix)]
    return os.path.splitext(base)[0]


def session_files(any_path: str) -> dict:
    """Every file of the session ``any_path`` belongs to, by kind.

    One name is enough: the operator remembers a session, not which of its
    five files happens to hold the column they are after.
    """
    directory = os.path.dirname(os.path.abspath(any_path))
    stamp = _stamp_of(any_path)
    found = {}
    for kind, suffix in (("hk", "_hk.csv"), ("events", "_events.csv"),
                         ("pistatus", "_pistatus.csv"),
                         ("commands", "_commands.csv"),
                         ("quicklook", "_quicklook.jsonl"),
                         ("summary", "_summary.json")):
        p = os.path.join(directory, f"session_{stamp}{suffix}")
        if os.path.exists(p) and os.path.getsize(p) > 0:
            found[kind] = p
    return found


def resolve(target: str | None, directory: str | None):
    """What to plot, from what the operator typed - or from nothing at all.

    Returns ``(kind, payload)`` where kind is "session" (payload: the files
    dict) or "instrument" (payload: one path). A directory, a session file, an
    instrument CSV and no argument at all are all accepted, because all four
    are things somebody will type.
    """
    if target and os.path.isdir(target):
        directory, target = target, None
    if target:
        if not os.path.exists(target):
            raise SystemExit(f"plot_session: no such file: {target}")
        if is_instrument_csv(target):
            return "instrument", target
        files = session_files(target)
        if not files:
            raise SystemExit(
                f"plot_session: {target} is not a session log or an "
                f"instrument CSV (unknown columns)")
        return "session", files

    searched = [directory] if directory else list(DEFAULT_DIRS)
    for d in searched:
        d = d if os.path.isabs(d) else os.path.join(HERE, d)
        hk_path = _newest(glob.glob(os.path.join(d, "session_*_hk.csv")))
        if hk_path:
            return "session", session_files(hk_path)
        inst = _newest([p for p in glob.glob(os.path.join(d, "session_*.csv"))
                        if is_instrument_csv(p)])
        if inst:
            return "instrument", inst
    raise SystemExit(f"plot_session: no session log found in "
                     f"{', '.join(searched)} - name one, or --dir elsewhere")


def is_instrument_csv(path: str) -> bool:
    """The detector-side log: one row per acquired frame, `iso_time` first."""
    if not path.endswith(".csv"):
        return False
    try:
        with open(path, newline="", encoding="utf-8") as f:
            header = next(csv.reader(f), [])
    except OSError:
        return False
    return bool(header) and header[0] == "iso_time"


# ------------------------------------------------------------------- loading
def _f(value, scale=1.0):
    """One CSV cell as a float - blank, "None" and junk all become NaN.

    A blank cell is the log saying "no reading" (a rail with no monitor, a
    motor sense this MCU build cannot read). It has to stay a gap.
    """
    try:
        return float(value) * scale
    except (TypeError, ValueError):
        return float("nan")


def _tuple_col(rows, name):
    """A column whose cell is a Python tuple literal - `rail_mv`, `shunt_raw`."""
    out = []
    for r in rows:
        try:
            v = ast.literal_eval(r.get(name, "") or "()")
        except (ValueError, SyntaxError):
            v = ()
        out.append(tuple(v))
    width = max((len(v) for v in out), default=0)
    cols = []
    for i in range(width):
        cols.append(np.array([float(v[i]) if i < len(v) else float("nan")
                              for v in out]))
    return cols


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_hk(path: str) -> dict:
    """Housekeeping CSV -> named float arrays, with the flags applied.

    Masking happens here rather than in the plotting code so that every
    consumer of this function gets the same answer to "was that a reading".
    """
    rows = _read_csv(path)
    if not rows:
        return {}
    t = np.array([_f(r.get("frame_t")) for r in rows])
    err = np.array([int(_f(r.get("error_flags", 0)) or 0) for r in rows])

    def mask(values, bit):
        """NaN wherever ``bit`` says the field has no sensor behind it."""
        return np.where((err & int(bit)).astype(bool), np.nan, values)

    d = {"t": t, "error_flags": err,
         "state": np.array([_f(r.get("state")) for r in rows]),
         "state_name": [r.get("state_name", "") for r in rows],
         "membrane_duty": np.array([_f(r.get("membrane_duty")) for r in rows])}

    amb = HkErrors.BME280_FAIL
    chm = HkErrors.BME280_CHM_FAIL
    col = lambda name, scale=1.0: np.array(          # noqa: E731 - one line
        [_f(r.get(name), scale) for r in rows])
    d["p_amb_hpa"] = mask(col("p_amb_pa", 0.01), amb)
    d["p_chm_hpa"] = mask(col("chm_p_pa", 0.01), chm)
    d["t_amb_c"] = mask(col("bme_temp_cc", 0.01), amb)
    d["t_chm_c"] = mask(col("chm_temp_cc", 0.01), chm)
    d["rh_amb"] = mask(col("rh1_cpct", 0.01), amb)
    d["rh_chm"] = mask(col("chm_rh_cpct", 0.01), chm)
    # p_amb held at its last good value is still the number the MCU sequenced
    # on, so it is drawn - but marked, because it is not a fresh measurement.
    d["p_stale"] = (err & int(HkErrors.P_AMB_STALE)).astype(bool)

    imu = HkErrors.IMU_FAIL
    for ax in "xyz":
        d[f"accel_{ax}"] = mask(
            np.array([_f(r.get(f"accel_{ax}_mg")) for r in rows]), imu)
        d[f"gyro_{ax}"] = mask(
            np.array([_f(r.get(f"gyro_{ax}_ddps"), 0.1) for r in rows]), imu)

    # Rails: volts from the packed register column, amps from the derived
    # ones beside it. RAIL_MV_INVALID is "no monitor answered", not 0 V.
    for i, mv in enumerate(_tuple_col(rows, "rail_mv")):
        if i >= len(RAIL_NAMES):
            break
        d[f"rail_v_{i}"] = np.where(mv == RAIL_MV_INVALID, np.nan, mv / 1000.0)
    for i, key in enumerate(("vin", "24v", "5v", "3v3")):
        d[f"rail_a_{i}"] = np.array([_f(r.get(f"rail_{key}_a")) for r in rows])
    d["motor_a"] = np.array([_f(r.get("hb_sense_a")) for r in rows])
    raw = np.array([_f(r.get("hb_sense_raw")) for r in rows])
    d["motor_a"] = np.where(raw == HB_SENSE_INVALID, np.nan, d["motor_a"])

    # Actuator lines: one lane each. Columns added 2026-09-18; a log written
    # before that has only the packed `valve_status`, so they are optional.
    for name in ("valve_pinch_1", "valve_pinch_2", "valve_eq1_close",
                 "valve_eq2_close", "valve_disperse"):
        if name in rows[0]:
            d[name] = np.array([_f(r.get(name)) for r in rows])
    if "membrane_pulled" in rows[0]:
        pulled = np.array([1.0 if r.get("membrane_pulled") == "True" else 0.0
                           for r in rows])
        d["membrane_pulled"] = np.where(
            (err & int(HkErrors.NO_MEMBRANE_SENSE)).astype(bool), np.nan, pulled)
    if "membrane_cycling" in rows[0]:
        d["membrane_cycling"] = np.array(
            [1.0 if r.get("membrane_cycling") == "True" else 0.0 for r in rows])
    return d


def load_pistatus(path: str) -> dict:
    rows = _read_csv(path)
    if not rows:
        return {}
    return {"t": np.array([_f(r.get("frame_t")) for r in rows]),
            "disk_free_mb": np.array([_f(r.get("disk_free_mb")) for r in rows]),
            "spectra_count": np.array([_f(r.get("spectra_count")) for r in rows]),
            "cpu_temp_c": np.array([_f(r.get("cpu_temp_cc"), 0.01) for r in rows]),
            "uart_ok": np.array([1.0 if r.get("uart_ok") == "True" else 0.0
                                 for r in rows]),
            "spectro_ok": np.array([1.0 if r.get("spectro_ok") == "True" else 0.0
                                    for r in rows])}


def load_events(path: str) -> list:
    return [{"t": _f(r.get("frame_t")), "name": r.get("code_name", ""),
             "severity": int(_f(r.get("severity")) or 0),
             "text": r.get("text", "")} for r in _read_csv(path)]


def load_commands(path: str) -> list:
    return [{"t": _f(r.get("send_t")), "name": r.get("cmd_name", ""),
             "result": r.get("result_name", ""),
             "origin": r.get("origin", ""), "key": r.get("key", "")}
            for r in _read_csv(path)]


def load_instrument(path: str) -> dict:
    """The detector-side log: `iso_time` plus per-frame scalars."""
    import datetime as _dt

    rows = _read_csv(path)
    if not rows:
        return {}
    t = []
    for r in rows:
        try:
            t.append(_dt.datetime.fromisoformat(r["iso_time"]).timestamp())
        except (KeyError, ValueError):
            t.append(float("nan"))
    cols = {"t": np.array(t)}
    for name in ("exposure_ms", "navg", "meas_peak", "meas_peak_nm",
                 "ref_peak", "ref_peak_nm", "sat_frac"):
        cols[name] = np.array([_f(r.get(name)) for r in rows])
    return cols


# ------------------------------------------------------------------ plotting
def _stream_gap(t, gap_s: float) -> float:
    """The gap threshold for *this* stream, not for housekeeping's cadence.

    ``--gap`` is about housekeeping, which is 1 Hz. Pi status arrives every
    10 s (`FswConfig.pistatus_interval_s`), so measured against 5 s every
    sample would be its own island and the trace would vanish - which is how
    the first version of this plot drew an empty Pi row from a full file.
    Anything slower than the threshold widens it to 2.5x its own median
    interval; nothing narrows it below what the caller asked for.
    """
    t = np.asarray(t, dtype=float)
    if t.size < 3:
        return gap_s
    dt = np.diff(t)
    dt = dt[np.isfinite(dt) & (dt > 0)]
    if dt.size == 0:
        return gap_s
    return max(gap_s, 2.5 * float(np.median(dt)))


def _split_gaps(t, y, gap_s):
    """NaN where the record has a hole, so the line breaks instead of lying."""
    if len(t) < 2:
        return np.asarray(y, dtype=float)
    y = np.asarray(y, dtype=float).copy()
    holes = np.nonzero(np.diff(t) > gap_s)[0]
    y[holes] = np.nan
    return y


def _plot(ax, t0, t, y, gap_s, label, colour=None, step=False, **kw):
    """One series, or nothing at all if it has no readings in this session."""
    y = np.asarray(y, dtype=float)
    if not np.any(np.isfinite(y)):
        return False
    style = dict(lw=1.2, color=colour, label=label)
    style.update(kw)
    x = t - t0
    if step:
        ax.step(x, _split_gaps(t, y, gap_s), where="post", **style)
    else:
        ax.plot(x, _split_gaps(t, y, gap_s), **style)
    return True


def _finish(ax, ylabel):
    ax.set_ylabel(ylabel, fontsize=9, color=NAVY)
    ax.grid(True, color=GRID, lw=0.6)
    ax.tick_params(labelsize=8)
    handles, _ = ax.get_legend_handles_labels()
    if handles:
        ax.legend(fontsize=7, loc="upper right", ncol=max(1, len(handles) // 3),
                  framealpha=0.85)


def _mark_events(axes, t0, events, commands):
    """Events and commands on every axis: the overlay is the point of one plot.

    Only the top axis is labelled - the same line repeated on eight axes with
    eight copies of the text is unreadable, and the shared x axis means one
    label locates the line on all of them.
    """
    for ev in events:
        for ax in axes:
            ax.axvline(ev["t"] - t0, color=SEVERITY_COLOUR.get(ev["severity"],
                                                               MUTED),
                       lw=0.8, ls="--", alpha=0.55, zorder=0)
    for cmd in commands:
        refused = cmd["result"] not in ("OK", "")
        for ax in axes:
            ax.axvline(cmd["t"] - t0, color=RED if refused else GREEN,
                       lw=0.7, ls=":", alpha=0.45, zorder=0)


def _marker_lane(ax, t0, events, commands):
    """The legend for those lines: what happened, when, and how it ended."""
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    # Labels are staggered over three heights each: a state change, its cause
    # and the command that asked for it land within a second of each other,
    # and three labels at one height are one unreadable smear.
    for i, ev in enumerate(events):
        colour = SEVERITY_COLOUR.get(ev["severity"], MUTED)
        ax.axvline(ev["t"] - t0, color=colour, lw=0.9, ls="--", alpha=0.8)
        ax.text(ev["t"] - t0, 0.55 + 0.15 * (i % 3), f" {ev['name']}",
                rotation=90, fontsize=6.5, color=colour, va="bottom",
                ha="center")
    for i, cmd in enumerate(c for c in commands
                            if c["origin"] != "heartbeat"):
        # 5 s of PINGs is the link proving itself, not an operator acting.
        refused = cmd["result"] not in ("OK", "")
        colour = RED if refused else GREEN
        ax.axvline(cmd["t"] - t0, color=colour, lw=0.9, ls=":", alpha=0.85)
        label = cmd["name"] if not refused else f"{cmd['name']} {cmd['result']}"
        ax.text(cmd["t"] - t0, 0.45 - 0.15 * (i % 3), f" {label}", rotation=90,
                fontsize=6.5, color=colour, va="top", ha="center")
    ax.set_ylabel("events\ncommands", fontsize=8, color=NAVY)
    ax.grid(True, axis="x", color=GRID, lw=0.6)


def _has(*arrays) -> bool:
    """Is there a single reading in any of these? An axis with nothing on it
    is a claim that the session carried that quantity and it was flat."""
    for a in arrays:
        a = np.asarray(a, dtype=float)
        if a.size and np.any(np.isfinite(a)):
            return True
    return False


def plot_session(files: dict, gap_s: float = GAP_S, marks: bool = True):
    """The whole session on one time axis; returns the figure."""
    from matplotlib.figure import Figure

    hk = load_hk(files["hk"]) if "hk" in files else {}
    ps = load_pistatus(files["pistatus"]) if "pistatus" in files else {}
    events = load_events(files["events"]) if "events" in files else []
    commands = load_commands(files["commands"]) if "commands" in files else []
    if not hk and not ps:
        raise SystemExit("plot_session: the session has no housekeeping and "
                         "no Pi status - nothing to plot over time")

    ps_gap = _stream_gap(ps["t"], gap_s) if ps else gap_s
    starts = [a["t"][0] for a in (hk, ps) if a and len(a["t"])]
    starts += [e["t"] for e in events[:1]] + [c["t"] for c in commands[:1]]
    t0 = min(starts)
    t = hk.get("t")

    lanes = [(k, k.replace("valve_", "").replace("_", " "))
             for k in ("valve_pinch_1", "valve_pinch_2", "valve_eq1_close",
                       "valve_eq2_close", "valve_disperse") if k in hk]
    lanes += [(k, k.replace("_", " ")) for k in
              ("membrane_pulled", "membrane_cycling") if k in hk]

    # One row per unit, and only for the units this session actually carried.
    # An empty axis is not neutral: it reads as a quantity that was recorded
    # and stayed flat, which is the opposite of "this part had no reading".
    rows = []
    if hk:
        if _has(hk["p_amb_hpa"], hk["p_chm_hpa"]):
            rows.append("pressure")
        if _has(hk["t_amb_c"], hk["t_chm_c"], ps.get("cpu_temp_c", [])):
            rows.append("temperature")
        if _has(hk["rh_amb"], hk["rh_chm"]):
            rows.append("humidity")
        if _has(*[hk.get(f"rail_v_{i}", []) for i in range(len(RAIL_NAMES))]):
            rows.append("rails")
        if _has(*[hk.get(f"rail_a_{i}", []) for i in range(len(RAIL_NAMES))],
                hk["motor_a"]):
            rows.append("current")
        if _has(hk["accel_x"], hk["accel_y"], hk["accel_z"]):
            rows.append("accel")
        if _has(hk["gyro_x"], hk["gyro_y"], hk["gyro_z"]):
            rows.append("gyro")
        if lanes and _has(*[hk[k] for k, _ in lanes]):
            rows.append("actuators")
        if _has(hk["membrane_duty"]):
            rows.append("duty")
        rows.append("state")
    if ps and _has(ps["disk_free_mb"], ps["spectra_count"]):
        rows.append("pi")
    if marks and (events or commands):
        rows.append("marks")

    fig = Figure(figsize=(13.5, 2.0 + 1.5 * len(rows)), dpi=110)
    fig.patch.set_facecolor("white")
    axes = fig.subplots(len(rows), 1, sharex=True, squeeze=False)[:, 0].tolist()
    drawn = dict(zip(rows, axes))

    if "pressure" in drawn:
        ax = drawn["pressure"]
        _plot(ax, t0, t, hk["p_amb_hpa"], gap_s, "ambient (BME280)", NAVY)
        _plot(ax, t0, t, hk["p_chm_hpa"], gap_s, "chamber (SPI_1)", ORANGE)
        # A held value is drawn, and said to be held: it is the number the MCU
        # sequenced on, and dropping it would leave a gap nothing explains.
        stale = np.where(hk["p_stale"], hk["p_amb_hpa"], np.nan)
        _plot(ax, t0, t, stale, gap_s, "ambient held (stale)", RED, lw=2.6,
              alpha=0.7)
        _finish(ax, "hPa")

    if "temperature" in drawn:
        ax = drawn["temperature"]
        _plot(ax, t0, t, hk["t_amb_c"], gap_s, "ambient", NAVY)
        _plot(ax, t0, t, hk["t_chm_c"], gap_s, "chamber", ORANGE)
        if ps:
            _plot(ax, t0, ps["t"], ps["cpu_temp_c"], ps_gap, "Pi CPU", GREEN,
                  ls="--")
        _finish(ax, "C")

    if "humidity" in drawn:
        ax = drawn["humidity"]
        _plot(ax, t0, t, hk["rh_amb"], gap_s, "ambient", NAVY)
        _plot(ax, t0, t, hk["rh_chm"], gap_s, "chamber", ORANGE)
        _finish(ax, "%RH")

    if "rails" in drawn:
        ax = drawn["rails"]
        for i, name in enumerate(RAIL_NAMES):
            _plot(ax, t0, t, hk.get(f"rail_v_{i}", []), gap_s, name)
        _finish(ax, "V")

    if "current" in drawn:
        ax = drawn["current"]
        for i, name in enumerate(RAIL_NAMES):
            _plot(ax, t0, t, hk.get(f"rail_a_{i}", []), gap_s, name)
        _plot(ax, t0, t, hk["motor_a"], gap_s, "motor (IPROPI)", RED, ls="--")
        _finish(ax, "A")

    if "accel" in drawn:
        ax = drawn["accel"]
        for axis_name in "xyz":
            _plot(ax, t0, t, hk[f"accel_{axis_name}"], gap_s, axis_name)
        _finish(ax, "mg")

    if "gyro" in drawn:
        ax = drawn["gyro"]
        for axis_name in "xyz":
            _plot(ax, t0, t, hk[f"gyro_{axis_name}"], gap_s, axis_name)
        _finish(ax, "dps")

    if "actuators" in drawn:
        # Lanes, not five square waves on one 0..1 scale - that is one square
        # wave. Each line gets its own row and its own baseline.
        ax = drawn["actuators"]
        for i, (key, label) in enumerate(lanes):
            y = np.asarray(hk[key], dtype=float)
            colour = ORANGE if "membrane" in key else NAVY
            _plot(ax, t0, t, y * 0.7 + i, gap_s, None, colour, step=True)
            ax.axhline(i, color=GRID, lw=0.6, zorder=0)
        ax.set_yticks(range(len(lanes)))
        ax.set_yticklabels([label for _, label in lanes], fontsize=7)
        ax.set_ylim(-0.4, len(lanes) - 0.1)
        ax.grid(True, axis="x", color=GRID, lw=0.6)
        ax.set_ylabel("drives", fontsize=9, color=NAVY)
        ax.tick_params(labelsize=8)

    if "duty" in drawn:
        ax = drawn["duty"]
        _plot(ax, t0, t, hk["membrane_duty"], gap_s, "membrane duty", GREEN,
              step=True)
        ax.set_ylim(-3, 103)
        _finish(ax, "duty %")

    if "state" in drawn:
        ax = drawn["state"]
        _plot(ax, t0, t, hk["state"], gap_s, None, NAVY, step=True)
        # Label each state with the name **the log carried**, not with this
        # build's enum: the sequencer's states are renumbered from time to
        # time, and decoding an old log against today's `SeqState` would put
        # a confident wrong word on the axis. The enum is only the fallback
        # for a log written before `state_name` existed.
        known = {int(s) for s in SeqState}
        recorded = {}
        for value, name in zip(hk["state"], hk.get("state_name", [])):
            if np.isfinite(value) and name:
                recorded.setdefault(int(value), name)
        seen = sorted({int(v) for v in hk["state"] if np.isfinite(v)})
        ax.set_yticks(seen)
        ax.set_yticklabels([recorded.get(v, SeqState(v).name if v in known
                                         else str(v)) for v in seen],
                           fontsize=7)
        ax.grid(True, color=GRID, lw=0.6)
        ax.set_ylabel("sequencer", fontsize=9, color=NAVY)
        ax.tick_params(labelsize=8)

    if "pi" in drawn:
        # Free disk is tens of thousands of MB and the stored-frame count is
        # tens: one y axis would draw the second as the x axis. Twin scales,
        # each labelled in its own colour.
        ax = drawn["pi"]
        _plot(ax, t0, ps["t"], ps["disk_free_mb"], ps_gap, "disk free (MB)",
              NAVY)
        ax.set_ylabel("MB free", fontsize=9, color=NAVY)
        ax.grid(True, color=GRID, lw=0.6)
        ax.tick_params(labelsize=8)
        # Free disk moves by a few MB over a session, so matplotlib would
        # otherwise label the axis "+4.27e4" and three decimals - a number
        # nobody can compare with `df` on the Pi.
        ax.ticklabel_format(axis="y", style="plain", useOffset=False)
        twin = ax.twinx()
        _plot(twin, t0, ps["t"], ps["spectra_count"], ps_gap, "spectra stored",
              ORANGE)
        twin.set_ylabel("frames stored", fontsize=9, color=ORANGE)
        twin.tick_params(labelsize=8, colors=ORANGE)
        # The left axes' patch is opaque and is drawn last, so without this
        # the twin's line is behind a white rectangle - present in the legend
        # and invisible on the plot, which is the worst of both.
        ax.set_zorder(twin.get_zorder() + 1)
        ax.patch.set_visible(False)
        # The two booleans are drawn as the thing they mean: a shaded span
        # where the Pi said it had no MCU, or no detector. That is what
        # explains a quiet stretch in the other files.
        for series, colour, label in ((ps["uart_ok"], RED, "no UART to MCU"),
                                      (ps["spectro_ok"], MUTED,
                                       "no detector")):
            first = True
            for i, ok in enumerate(series):
                if ok:
                    continue
                lo = ps["t"][i] - t0
                hi = (ps["t"][i + 1] if i + 1 < len(ps["t"]) else ps["t"][i]
                      + ps_gap) - t0
                ax.axvspan(lo, hi, color=colour, alpha=0.12,
                           label=label if first else None)
                first = False
        handles, _ = ax.get_legend_handles_labels()
        th, _ = twin.get_legend_handles_labels()
        if handles or th:
            ax.legend(handles=handles + th, fontsize=7, loc="upper right",
                      framealpha=0.85)

    if "marks" in drawn:
        _mark_events([a for n, a in drawn.items() if n != "marks"], t0,
                     events, commands)
        _marker_lane(drawn["marks"], t0, events, commands)

    axes[-1].set_xlabel("seconds since the first packet of the session",
                        fontsize=9, color=NAVY)
    stamp = _stamp_of(files.get("hk") or files.get("pistatus"))
    counts = ", ".join(
        f"{len(v) if isinstance(v, list) else len(v['t'])} {k}"
        for k, v in (("HK", hk), ("Pi status", ps), ("events", events),
                     ("commands", commands)) if len(v))
    fig.suptitle(f"CLOUDS session {stamp}   -   {counts}",
                 color=NAVY, fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    return fig


def plot_instrument(path: str, gap_s: float = GAP_S):
    """The detector-side log: peaks, their wavelengths, exposure, saturation."""
    from matplotlib.figure import Figure

    d = load_instrument(path)
    if not d:
        raise SystemExit(f"plot_session: {path} has no rows")
    t, t0 = d["t"], d["t"][0]
    gap_s = _stream_gap(t, gap_s)
    fig = Figure(figsize=(13.5, 8.0), dpi=110)
    fig.patch.set_facecolor("white")
    ax1, ax2, ax3, ax4 = fig.subplots(4, 1, sharex=True)

    _plot(ax1, t0, t, d["meas_peak"], gap_s, "measurement peak", NAVY)
    _plot(ax1, t0, t, d["ref_peak"], gap_s, "reference peak", ORANGE)
    _finish(ax1, "counts")

    _plot(ax2, t0, t, d["meas_peak_nm"], gap_s, "measurement", NAVY)
    _plot(ax2, t0, t, d["ref_peak_nm"], gap_s, "reference", ORANGE)
    _finish(ax2, "peak nm")

    _plot(ax3, t0, t, d["exposure_ms"], gap_s, "exposure", NAVY, step=True)
    _plot(ax3, t0, t, d["navg"], gap_s, "averaging", GREEN, step=True)
    _finish(ax3, "ms / n")

    _plot(ax4, t0, t, d["sat_frac"], gap_s, "saturated fraction", RED)
    _finish(ax4, "fraction")

    ax4.set_xlabel("seconds since the first frame", fontsize=9, color=NAVY)
    fig.suptitle(f"CLOUDS instrument log {os.path.basename(path)}   -   "
                 f"{len(t)} frames, {t[-1] - t0:.0f} s",
                 color=NAVY, fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return fig


# ----------------------------------------------------------------------- main
def _show_or_save(fig, save: str | None, default_name: str) -> None:
    """Show it if there is a screen, write it if there is not.

    A tool that draws nothing and says nothing on a headless box reads as a
    crash, so the fallback is a file and the path is printed.
    """
    if save:
        fig.savefig(save, facecolor=fig.get_facecolor())
        print(f"wrote {save}")
        return
    try:
        import matplotlib
        import matplotlib.pyplot as plt
        if matplotlib.get_backend().lower() == "agg":
            raise ImportError("no interactive backend")
        manager = plt.figure(fig.number if fig.number else 1).canvas.manager
        manager.canvas.figure = fig
        fig.set_canvas(manager.canvas)
        plt.show()
    except Exception:                       # noqa: BLE001 - headless is normal
        out = os.path.join("output", default_name)
        os.makedirs("output", exist_ok=True)
        fig.savefig(out, facecolor=fig.get_facecolor())
        print(f"no display - wrote {out}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="plot_session.py",
        description="Plot a CLOUDS session log over time (the newest one by "
                    "default).")
    ap.add_argument("path", nargs="?",
                    help="any file of a session log (hk / events / pistatus / "
                         "commands), an instrument output/session_*.csv, or a "
                         "directory to take the newest from")
    ap.add_argument("--dir", default=None,
                    help=f"where to look when no path is given (default: "
                         f"{', '.join(DEFAULT_DIRS)})")
    ap.add_argument("--save", metavar="FILE",
                    help="write the figure here (.png/.pdf) instead of "
                         "showing it")
    ap.add_argument("--gap", type=float, default=GAP_S, metavar="S",
                    help=f"break a trace after this many seconds without a "
                         f"packet (default {GAP_S:g})")
    ap.add_argument("--no-marks", action="store_true",
                    help="leave events and commands off the plot")
    ap.add_argument("--list", action="store_true",
                    help="list the sessions found and exit")
    args = ap.parse_args(argv)

    if args.save:
        import matplotlib
        matplotlib.use("Agg")

    if args.list:
        for d in ([args.dir] if args.dir else list(DEFAULT_DIRS)):
            d = d if os.path.isabs(d) else os.path.join(HERE, d)
            sessions = list_sessions(d)
            inst = sorted((p for p in glob.glob(os.path.join(d, "session_*.csv"))
                           if is_instrument_csv(p)),
                          key=os.path.getmtime, reverse=True)
            if not sessions and not inst:
                continue
            print(f"{d}:")
            for stamp, files in sessions:
                when = time.strftime("%Y-%m-%d %H:%M",
                                     time.localtime(os.path.getmtime(files["hk"])))
                print(f"  {stamp:24s} {when}  "
                      f"[{', '.join(sorted(files))}]")
            for p in inst:
                when = time.strftime("%Y-%m-%d %H:%M",
                                     time.localtime(os.path.getmtime(p)))
                print(f"  {os.path.basename(p):24s} {when}  [instrument]")
        return 0

    kind, payload = resolve(args.path, args.dir)
    if kind == "instrument":
        print(f"plotting instrument log {payload}")
        fig = plot_instrument(payload, gap_s=args.gap)
        name = os.path.basename(payload).replace(".csv", "") + "_plot.png"
    else:
        print("plotting session " + _stamp_of(payload.get("hk") or
                                              payload.get("pistatus")) +
              f": {', '.join(sorted(payload))}")
        fig = plot_session(payload, gap_s=args.gap, marks=not args.no_marks)
        name = ("session_" + _stamp_of(payload.get("hk") or
                                       payload.get("pistatus")) + "_plot.png")
    _show_or_save(fig, args.save, name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
