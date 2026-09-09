@echo off

echo [96mUsage: upload_bst_application_board.cmd {mcu_app31} [spi^|i2c]
echo Arguments: {mcu_app31} (mandatory)
echo   mcu_app31 - upload SDK example for BST application board v3.1 MCU (Cortex-M4F)
echo Arguments: [spi^|i2c] (optional, default: spi)
echo   spi - use spi as the host communication interface
echo   i2c - use i2c as the host communication interface
echo   e.g. to use spi as the host communication interface on mcu_app31: upload_bst_application_board.cmd mcu_app31 spi (default: spi)
echo   e.g. to use i2c as the host communication interface on mcu_app31: upload_bst_application_board.cmd mcu_app31 i2c[0m

if [%1]==[] (
    echo [93mRefer to the usage information above for correct syntax[0m 
    exit /B 1
)

set target=%1

if /i "%1%"=="mcu_app31" (
    set target="MCU_APP31"
) else (
    echo [91mSelected target: %target% is not a valid option[0m
    exit /B 1
)

echo [92mSelected target: %target%[0m

set hostCommunicationInterface=%2

if [%2]==[] (
    set hostCommunicationInterface="spi"
    set commInterface=1
) else (
    if /i "%2%"=="i2c" (
        set hostCommunicationInterface="i2c"
        set commInterface=2
    ) else (
        if /i "%2%"=="spi" (
            set hostCommunicationInterface="spi"
            set commInterface=1
        ) else (
            echo [91mSelected host communication interface: %hostCommunicationInterface% is not a valid option[0m
            exit /B 1
        )
    )
)

echo [92mSelected host communication interface: %hostCommunicationInterface%[0m

set compiler=arm_none_eabi_gcc
set binPath=bin\%target%\%compiler%\release_%hostCommunicationInterface%
if exist %binPath% rmdir /s /q %binPath%
mkdir %binPath%

mingw32-make LOCATION=FLASH TARGET=%target% COMM_INTERFACE=%commInterface% download
