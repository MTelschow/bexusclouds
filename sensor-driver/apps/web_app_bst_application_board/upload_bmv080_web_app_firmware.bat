@echo off
REM Set the path to the COINES SDK installation directory
set COINES_INSTALL_PATH=C:\COINES_SDK\v2.10.4

"%COINES_INSTALL_PATH%\tools\app_switch\app_switch" usb_dfu_bl
"%COINES_INSTALL_PATH%\tools\usb-dfu\dfu-util" --device -,108c:ab39 -a FLASH -D bmv080_web_app_firmware.bin -R

pause
