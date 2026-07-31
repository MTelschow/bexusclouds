"""CLOUDS FSW-PI: Raspberry Pi 5 flight application (spec section 1).

Data & communications node: spectrometer acquisition at 1 Hz (P.3), frame
storage (O.3), UDP telemetry downlink (O.4), TCP command uplink (S.8), UART
link to the RP2350 sequencer (S.4, S.7). The Pi never sequences the
experiment - losing it degrades the mission, never blocks the release.

Deployment: copy this folder plus ``clouds_link/`` and ``spectro/`` from the
repo root onto the Pi and install ``flight/pi/systemd/clouds-fsw.service``.
"""
__version__ = "0.1.0"
