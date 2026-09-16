@echo off
setlocal EnableExtensions
title CLOUDS Spectral Engine
cd /d "%~dp0"

rem ---------------------------------------------------------------------------
rem The Windows counterpart to run_clouds_ui.sh, and it exists for the same two
rem reasons: the interpreter and PYTHONPATH are both easy to get wrong, and both
rem fail in ways that look like the app being broken.
rem
rem   PYTHONPATH needs three entries - the repo root for clouds_link/ and
rem   spectro/, gse\ for clouds_gse, flight\pi for clouds_fsw. Miss one and the
rem   app dies on an ImportError naming a package that is plainly sitting right
rem   there. (This script used to set none of them and pin one developer's
rem   python.exe by absolute path, so it ran on exactly one machine.)
rem
rem Every argument is passed straight through to `python -m clouds_ui`:
rem
rem   run_clouds_spectral.bat                        the Duo on this PC
rem   run_clouds_spectral.bat --net 192.168.100.10   the Duo on the bench Pi
rem   run_clouds_spectral.bat --flight               ground station, no detector
rem   run_clouds_spectral.bat --mock                 no hardware at all
rem   run_clouds_spectral.bat --help                 the full flag list
rem
rem Ethernet to the Pi is a one-time setup: see setup_windows_net.ps1.
rem ---------------------------------------------------------------------------

rem The console is cp1252 by default and the UI prints degree signs and mu.
rem Without this a print() can raise UnicodeEncodeError inside a Qt slot, and
rem PyQt5 aborts the process on an unhandled exception in a slot.
chcp 65001 >nul 2>&1
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

set "PYTHONPATH=%~dp0.;%~dp0gse;%~dp0flight\pi"

rem -- interpreter: an explicit override, then the repo venv, then the py
rem    launcher, then whatever `python` is. Checked here rather than left to
rem    fail later on a Qt import with nothing to say about why.
set "PYCMD="
if defined CLOUDS_PYTHON if exist "%CLOUDS_PYTHON%" set "PYCMD="%CLOUDS_PYTHON%""
if not defined PYCMD if exist "%~dp0.venv\Scripts\python.exe" set "PYCMD="%~dp0.venv\Scripts\python.exe""
if not defined PYCMD if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" set "PYCMD="%VIRTUAL_ENV%\Scripts\python.exe""
if not defined PYCMD (
  py -3 -c "import sys" >nul 2>&1 && set "PYCMD=py -3"
)
if not defined PYCMD (
  python -c "import sys" >nul 2>&1 && set "PYCMD=python"
)
if not defined PYCMD (
  echo.
  echo     [!] no Python found.
  echo         Install Python 3.13 from python.org or the Microsoft Store, then:
  echo             py -3 -m venv .venv
  echo             .venv\Scripts\python.exe -m pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

echo.
echo                                 #############
echo                              #######     #######
echo                            #####              ####
echo                           ###                   ####
echo                          ###                      #############
echo                         ###                        ###############
echo                        ###                  ####                ####
echo                ###########       ######      ##                   ###
echo             ##############      ########                    ##########
echo            ####    #######      ##   ###              ####   ##########
echo           ###     #####         #######              ######      ###########
echo          ###      ###              ##                ######        ############
echo          ##       ###                       ###       ####          #####################
echo      ######        #                        ###                      ######## ##     ######
echo   ########   ####                                    ###                   ###           ####
echo  ###        ######     ######          ####        ######             ###                  ##
echo ###         ######     ### ###        ######       ### ##            ######                ###
echo ###          ###       ######        ### ####       #####    ####   ### ###                ###
echo  ###                     ###          ######                ######   #####               ####
echo   ####         ####                                          ####             ##############
echo     ##################                                                       ############
echo        #######     #####        #####                      ##              ####
echo                       ##################     #####################      #####
echo                           #####     #######################  ##############
echo                                        ####
echo.
echo         C L O U D S
echo         S P E C T R A L   E N G I N E
echo         -----------------------------
echo         BEXUS 38  -  dual-spectrometer operating software
echo.

rem -- dependencies: PyQt5 is the one that is routinely missing (no wheel for
rem    the newest CPython), and matplotlib goes with it because the spectrum
rem    view is useless without it. Fail with the fix, not with a traceback.
%PYCMD% -c "import PyQt5, matplotlib" >nul 2>&1
if errorlevel 1 (
  echo     [!] this Python cannot import PyQt5 / matplotlib:
  %PYCMD% -c "import sys; print('        ' + sys.executable)"
  echo.
  echo         %PYCMD% -m pip install -r requirements.txt
  echo.
  echo         PyQt5 has no wheel for the newest CPython - if pip tries to
  echo         build it from source, use Python 3.13 in a repo venv:
  echo             py -3.13 -m venv .venv
  echo             .venv\Scripts\python.exe -m pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

echo     starting up:
echo       [1/2] connecting to the EURECA Duo  (FTDI VCP / libe9u DLL)
echo       [2/2] opening the operator interface  (instrument + flight)
echo.
echo     this box can stay minimised - closing it closes the engine.
echo.

%PYCMD% -u -m clouds_ui %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo     [!] the interface hit a problem above  ^(exit %RC%^).
  echo         headless self-check:        %PYCMD% verify.py
  echo         no detector, downlink only: %PYCMD% -m clouds_ui --flight
  echo         no hardware at all:         %PYCMD% -m clouds_ui --mock
  echo         detector on the bench Pi:   %PYCMD% -m clouds_ui --net 192.168.100.10
  echo         Ethernet link to the Pi:    powershell -ExecutionPolicy Bypass -File setup_windows_net.ps1 -Check
  echo.
)
echo.
echo     window closed - safe to close this box.
pause >nul
exit /b %RC%
