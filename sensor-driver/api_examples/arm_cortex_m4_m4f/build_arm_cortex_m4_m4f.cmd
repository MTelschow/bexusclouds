@echo off

set buildType="release"

echo [96mUsage: build_arm_cortex_m4_m4f.cmd {m4f^|m4} [spi^|i2c]
echo Arguments: {m4f^|m4} (mandatory)
echo   m4f - build SDK example for Feather STM32F405 using api for Cortex-M4F (hardware fpu support)
echo   m4  - build SDK example for Feather STM32F405 using api for Cortex-M4 (software fpu support)
echo Arguments: [spi^|i2c] (optional, default: spi)
echo   spi - use spi as the host communication interface
echo   i2c - use i2c as the host communication interface
echo   e.g. to use spi as the host communication interface on m4f: build_arm_cortex_m4_m4f.cmd m4f spi (default: spi)
echo   e.g. to use i2c as the host communication interface on m4: build_arm_cortex_m4_m4f.cmd m4 i2c[0m

if [%1]==[] (
    echo [93mRefer to the usage information above for correct syntax[0m 
    exit /B 1
)

set chip=%1

if /i "%1%"=="m4f" (
    set chip="m4f"
) else (
    if /i "%1%"=="m4" (
        set chip="m4"
    ) else (
        echo [91mSelected chip / SoC: %chip% is not a valid option[0m
        exit /B 1
    )
)

echo [92mSelected chip / SoC: %chip%[0m

set hostCommunicationInterface=%2

if [%2]==[] (
    set hostCommunicationInterface="spi"
) else (
    if /i "%2%"=="i2c" (
        set hostCommunicationInterface="i2c"
    ) else (
        if /i "%2%"=="spi" (
            set hostCommunicationInterface="spi"
        ) else (
            echo [91mSelected host communication interface: %hostCommunicationInterface% is not a valid option[0m
            exit /B 1
        )
    )
)

echo [92mSelected host communication interface: %hostCommunicationInterface%[0m

pio run --environment %buildType%_%hostCommunicationInterface%_%chip%
