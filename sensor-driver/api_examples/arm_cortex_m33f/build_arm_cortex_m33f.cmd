@echo off

set buildType="release"

echo [96mUsage: build_arm_cortex_m33f.cmd [spi^|i2c]
echo Arguments: [spi^|i2c] (optional, default: spi)
echo   spi - use spi as the host communication interface
echo   i2c - use i2c as the host communication interface
echo   e.g. to use spi as the host communication interface: build_arm_cortex_m33f.cmd spi (default: spi)
echo   e.g. to use i2c as the host communication interface: build_arm_cortex_m33f.cmd i2c[0m

set hostCommunicationInterface=%1

if [%1]==[] (
    set hostCommunicationInterface="spi"
) else (
    if /i "%1%"=="i2c" (
        set hostCommunicationInterface="i2c"
    ) else (
        if /i "%1%"=="spi" (
            set hostCommunicationInterface="spi"
        ) else (
            echo [91mSelected host communication interface: %hostCommunicationInterface% is not a valid option[0m
            exit /B 1
        )
    )
)

echo [92mSelected host communication interface: %hostCommunicationInterface%[0m

pio run --environment %buildType%_%hostCommunicationInterface%
