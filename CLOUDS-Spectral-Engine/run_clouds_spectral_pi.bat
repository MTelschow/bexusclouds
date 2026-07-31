@echo off
rem Live control panel with the spectrometer on the flight Pi (not on this PC).
rem
rem This is the LIVE instrument view. The GSE dashboard
rem (python -m clouds_gse.main --gui) is the flight *downlink* view: binned
rem quick-looks on the 2 kbit/s E-Link budget, ~30 s apart. Do not use it to
rem check the detector - use this.
rem
rem The Pi must be serving frames, either of:
rem   python3 -m clouds_fsw.main --no-uart --bench-stream   (flight app + live view)
rem   python3 -m spectro.net_server                         (live view only, full rate)
rem
rem Usage:  run_clouds_spectral_pi.bat [HOST[:PORT]]
title CLOUDS Spectral Engine - Pi detector
cd /d "%~dp0"
set "HOST=%~1"
if "%HOST%"=="" set "HOST=192.168.100.10"
echo.
echo     C L O U D S   -   live panel, detector on %HOST%
echo.
call "%~dp0run_clouds_spectral.bat" --net %HOST%
