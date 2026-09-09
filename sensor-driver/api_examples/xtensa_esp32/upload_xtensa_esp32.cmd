@echo off

set buildType="release"

echo [96mUsage: upload_xtensa_esp32.cmd COMport {esp32^|esp32s2^|esp32s3^|esp32c6} [spi^|i2c]
echo   e.g. to use spi as the host communication interface on esp32: upload_xtensa_esp32.cmd COM1 esp32 spi (default: spi)
echo   e.g. to use i2c as the host communication interface on esp32s3: upload_xtensa_esp32.cmd COM1 esp32s3 i2c[0m

if [%1]==[] (
    echo [93mRefer to the usage information above for correct syntax[0m 
    exit /B 1
)

set comport=%1
setlocal enableDelayedExpansion
echo %comport%|findstr /r /i /c:"^COM[1-9][0-9]*$" >nul && (
    echo [92mSelected COMport: %comport%[0m
) || (
    echo [91mSelected COMport: %comport% is not valid[0m
    exit /B 1
)

if [%2]==[]  (
    echo [93mRefer to the usage information above for correct syntax[0m 
    exit /B 1
)

set chip=%2

if /i "%2%"=="esp32" (
    set chip="esp32"
) else (
    if /i "%2%"=="esp32s2" (
        set chip="esp32s2"
    ) else (
        if /i "%2%"=="esp32s3" (
            set chip="esp32s3"
        ) else (
            if /i "%2%"=="esp32c6" (
            set chip="esp32c6"
            ) else (
                echo [91mSelected chip / SoC: %chip% is not a valid option[0m
                exit /B 1
            )
        )
    )
)

echo [92mSelected chip / SoC: %chip%[0m

set hostCommunicationInterface=%3

if [%3]==[] (
    set hostCommunicationInterface="spi"
) else (
    if /i "%3%"=="i2c" (
        set hostCommunicationInterface="i2c"
    ) else (
        if /i "%3%"=="spi" (
            set hostCommunicationInterface="spi"
        ) else (
            echo [91mSelected host communication interface: %hostCommunicationInterface% is not a valid option[0m
            exit /B 1
        )
    )
)

echo [92mSelected host communication interface: %hostCommunicationInterface%[0m

pio run --environment %buildType%_%hostCommunicationInterface%_%chip% --target upload --upload-port %comport%
