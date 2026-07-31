"""CLOUDS GSE - ground station (spec section 1, SED section 4.12).

Python implementation of the GSE software: UDP telemetry receiver, TCP
commander with arm/execute + ground interlock (S.10), session logging with
CSV/JSON export (G-05), headless console monitor, and a PyQt5 dashboard.

This is the downlink-fed sibling of the bench software at the repo root:
it reuses ``clouds_link`` (protocol) and ``spectro`` (calibration +
processing) with the UDP receiver in place of the USB driver - exactly the
driver/UI split the bench app was built around.

Run from the repo root:  python -m clouds_gse.main --help  (see gse/README.md)
"""
__version__ = "0.1.0"
