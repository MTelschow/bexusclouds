@echo off
setlocal

REM Path to Raspberry Pi toolchain for Windows to be added to environmental variable PATH
REM For example:
REM C:\SysGCC\raspberry\bin; C:\SysGCC\raspberry64\bin
REM which can be downloaded from here:
REM arm-linux-gnueabihf-gcc compiler (32 bit): https://sysprogs.com/getfile/2076/raspberry-gcc10.2.1-r2.exe
REM aarch64-linux-gnu-gcc compiler (64 bit): https://sysprogs.com/getfile/1804/raspberry64-gcc10.2.1.exe

REM specify build type, build directory and compiler
set build_type="release"
set build_folder="./build"
set compiler="aarch64-linux-gnu-gcc"

REM host_interface selection - SPI = 1 (Default); I2C = 2;
set host_interface=1

echo [96mUsage: build_raspberry_pi_64bit.cmd {armv8-a} [spi^|i2c]
echo Arguments: {armv8-a} (mandatory)
echo   armv8-a  - ARMv8-A architecture
echo Arguments: [spi^|i2c] (optional, default: spi)
echo   spi - use spi as the host communication interface
echo   i2c - use i2c as the host communication interface
echo   e.g. to use spi as the host communication interface: build_raspberry_pi_64bit.cmd armv8-a spi (default: spi)
echo   e.g. to use i2c as the host communication interface: build_raspberry_pi_64bit.cmd armv8-a i2c[0m

if [%1]==[] (
    echo [93mRefer to the usage information above for correct syntax[0m 
    exit /B 1
)

set arch=%1

if /i "%1%"=="armv8-a" (
    set arch="armv8-a"
) else (
    echo [91mSelected arch / SoC: %arch% is not a valid option[0m
    exit /B 1
)

echo [92mSelected arch / SoC: %arch%[0m

set host_communication_interface=%2

if [%2]==[] (
    set host_communication_interface="spi"
    set host_interface=1
) else (
    if /i "%2%"=="i2c" (
        set host_communication_interface="i2c"
        set host_interface=2
    ) else (
        if /i "%2%"=="spi" (
            set host_communication_interface="spi"
            set host_interface=1
        ) else (
            echo [91mSelected host communication interface: %host_communication_interface% is not a valid option[0m
            exit /B 1
        )
    )
)

echo [92mSelected host communication interface: %host_communication_interface%[0m

:main_script
set original_path="%cd%"
call :create_folders
call :build_platform
exit /b || goto:eof

:create_folders
set build_path=%build_folder%/%arch%/%compiler%
if not exist %build_path% md %build_path% && ^
exit /b || goto:eof

REM compile
:build_platform
cd %build_path% && ^
cmake -DCMAKE_BUILD_TYPE=%build_type% -DHOST_INTERFACE=%host_interface% -DBUILD_32=OFF -DARCH=%arch% -DCMAKE_TOOLCHAIN_FILE=raspberry-gcc-toolchain.cmake -G  "Unix Makefiles" ./../../../ && ^
make && ^
cd %original_path% && ^
exit /b || goto:eof