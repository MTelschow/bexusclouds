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
sidebar** (~410 px) in a `QScrollArea`. Sidebar order: branding; Connect /
identify; Acquisition (exposure, averaging, run/stop); Dark frame
(capture / subtract); Channels (measurement & reference roles, calibration);
View (raw / transmission / absorbance, nm vs pixel axis); Export. A hint line
under the action area is the feedback channel; a stats card overlays the plot
top-left. This section grows as the panels land.
