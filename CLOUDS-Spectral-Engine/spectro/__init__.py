"""CLOUDS Spectral Engine - device-driver + calibration + processing layer.

Kept import-light on purpose: importing ``spectro`` (or ``spectro.calibration``)
must NOT pull in PyQt5 or the vendor DLL, so ``verify.py`` runs hardware-free.
"""
