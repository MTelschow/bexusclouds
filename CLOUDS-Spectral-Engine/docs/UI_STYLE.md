# UI design language

CLOUDS Spectral Engine adopts the CLOUDS design language defined for the
*CLOUDS Raytracing Engine* (`../CLOUDS-Raytracing-Engine/docs/UI_STYLE.md`).
Reference implementation for the widgets we reuse: that engine's
`live_sim_qt.py`.

## Tokens (shared)

| token | value |
|---|---|
| brand navy | `#01386a` - headings, accent buttons, stats |
| panel bg | `#ffffff`; viewport gradient `#e9eef4` -> `#ffffff` |
| card bg / border | `#eef3f8` / `#d3dde6`, radius 8 px |
| muted text | `#5a6b7a` (labels `#33414d`, section headers `#8a97a3`) |
| signal colours | orange `#E8821E`, green `#1D9E75`, red `#FF2A2A`, gray `#b4b2a9` |
| title font | Futura Bold (`assets/Futura-Bold.ttf`), fallback Century Gothic -> Arial |
| hint line | 11 px italic `#b25e00` - the feedback channel for long operations |

## Patterns we reuse (from `live_sim_qt.py`)

* `_wl_rgb(nm)` + `_SpectrumBar` - wavelength->colour bar under the spectrum.
* `_OverlayFrame` / `_rounded_pixmap` - corner-safe overlays (never transparent
  over a paint surface, which renders black).
* `_slider_row` / `_lin_slider_row` / `_log_slider_row` / `_spin_row` - sidebar
  controls with spin/slider sync via a `guard` flag against recursion.
* `_heading` + hideable `sec_*` sections toggled as one unit.
* matplotlib -> Agg -> `QPixmap` for every chart (the live spectrum + report).
* offscreen `verify_qt.py` headless QC (`QT_QPA_PLATFORM=offscreen`, stub the
  plot/driver, drive controls programmatically, `grab()` a screenshot).

## Spectrometer-specific layout (this app)

`QMainWindow` -> horizontal: **live spectrum view** (stretch 1) + **control
sidebar** (~410 px) in a `QScrollArea`. Sidebar order: branding; then the
group that steers the plot and the experiment - Spectrum source; Timeline
(which housekeeping series the lower plot draws); Sensors; Commands;
Actuators; Events - and below it what is set once and left alone -
Housekeeping (the full HK grid); Device (connect / identify); Acquisition
(exposure, averaging, run/stop); Dark frame (capture / subtract); Reference;
View (counts / transmission / absorbance, nm vs pixel axis); Calibration;
Export. What is expanded at startup is `fold_for()`, from two lists in
`clouds_ui/window.py`: `DEFAULT_OPEN` (Spectrum source, Sensors, Commands,
Actuators, Events) starts open and `DEFAULT_CLOSED` (Timeline, Device,
Acquisition, Dark frame, Reference, View, Calibration, Export) starts folded,
in either kind of session; only Housekeeping follows the half that was asked
for - open with `--flight`, folded on the bench. The folded ones are either
long (Timeline's two dozen series toggles, View) or set once and forgotten,
and on screen at startup they cost the sections above them the height they
are read in. A hint line under the action area is the feedback channel; a
stats card overlays the plot top-left.

The left half is a **vertical `QSplitter`**: the spectrum on top, the
housekeeping **timeline** under it (`clouds_ui/timeline.py`). A splitter, not
a fixed ratio - a calibration pass is all spectrum, an ascent is all timeline,
and either pane can be dragged shut without a restart.

`self._view` remains the **spectrum pane**, never the splitter. The stats,
cursor and source-banner cards are children of it and are moved against its
geometry, and the resize handler sizes the spectrum figure from it; pointing
it at the container would float those cards over the timeline.

Timeline rules, inherited from the `Sensors` section because they are the
same numbers:

- one sub-axis **per unit**, stacked and sharing the time axis. hPa beside A
  on one scale is unreadable, and normalising everything to 0..1 throws away
  the only thing an engineering readout is for;
- a value that is not a measurement is a **gap**, never a zero - an unsourced
  field (`HkErrors`), an unreadable rail (`RAIL_MV_INVALID`), or a link
  dropout longer than `GAP_S`. A selected series that drew nothing says why in
  its legend entry (`not fitted` / `no source` / `no reading`);
- series toggles live in the sidebar, not under the plot: there are two dozen
  of them and a checkbox strip that wide would cost the timeline the height
  it exists for. A part the carrier does not have keeps its row, disabled - an
  absent checkbox teaches the operator nothing.
