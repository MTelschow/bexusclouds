"""CLOUDS operator interface - one window for bench testing and for flight.

Replaces the two UIs this project used to have: the bench panel
(`clouds_spectral.py`) and the ground dashboard (`clouds_gse.main --gui`).
They were split because their data paths are: the bench panel drives
`spectro.driver` directly at full resolution and can change the hardware,
while the ground station only ever sees the 2 kbit/s downlink. That split is
still real and is still enforced here - what changed is that an operator no
longer has to run two applications, and no longer has to remember which
window's spectrum is the instrument and which is a binned quick-look, because
the plot says so.

    python -m clouds_ui --help

The non-UI halves of the old ground station (`clouds_gse.Receiver`,
`Commander`, `SessionLog`, and the headless `ConsoleMonitor`) are unchanged
and still the place the protocol work lives; this package is only the window.
"""
__version__ = "0.2.0"
