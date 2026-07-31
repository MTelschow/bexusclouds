@echo off
title CLOUDS Spectral Engine
cd /d "%~dp0"
set "PY=C:\Users\kai-w\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"
if not exist "%PY%" set "PY=python"
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
echo     starting up:
echo       [1/2] connecting to the EURECA Duo  (FTDI VCP / libe9u DLL)
echo       [2/2] opening the control panel + live spectrum view
echo.
echo     this box can stay minimised - closing it closes the engine.
echo.
"%PY%" clouds_spectral.py %*
if errorlevel 1 (
  echo.
  echo     [!] the interface hit a problem above.
  echo         run a headless self-check:   "%PY%" verify.py
  echo         or try the synthetic camera: "%PY%" clouds_spectral.py --mock
  echo.
)
echo.
echo     window closed - safe to close this box.
pause >nul
