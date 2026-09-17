# CLOUDS FSW-MCU firmware - official Raspberry Pi Pico SDK build (RP2350).
#
#   export PICO_SDK_PATH=/path/to/pico-sdk   (SDK >= 2.0 for rp2350)
#   mkdir build && cd build
#   cmake -DPICO_PLATFORM=rp2350 ..            (PICO_BOARD defaults to clouds_carrier)
#   make
#   -> clouds_fsw_mcu.uf2 (drag onto the BOOTSEL drive)
cmake_minimum_required(VERSION 3.13)

# The carrier is an RP2350B (GP0..GP47); boards/clouds_carrier.h says so to
# the SDK, which pico2 (RP2350A, GP0..GP29) does not - and GP30 carries the
# membrane position switch. -DPICO_BOARD=pico2 still builds for a bare Pico 2,
# with everything above GP29 compiled out (src/hw/board.h explains what that
# costs). Both must be set before the SDK is imported: the board header is
# resolved during pico_sdk_init().
set(PICO_BOARD clouds_carrier CACHE STRING "Board type")
list(APPEND PICO_BOARD_HEADER_DIRS ${CMAKE_CURRENT_LIST_DIR}/boards)

include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)

project(clouds_fsw_mcu C CXX ASM)
set(CMAKE_C_STANDARD 11)

pico_sdk_init()

add_executable(clouds_fsw_mcu
    src/main.c
    src/core/crc16.c
    src/core/cobs.c
    src/core/frame.c
    src/core/config.c
    src/core/link.c
    src/core/autonomy.c
    src/core/sequencer.c
    src/core/pulse.c
    src/core/pwmdiv.c
    src/core/sqwave.c
    src/hw/hw.c
    src/hw/bme280.c
    src/hw/bno055.c
    src/hw/ina226.c
    src/hw/uart_io.c
)

target_compile_options(clouds_fsw_mcu PRIVATE -Wall -Wextra)

target_link_libraries(clouds_fsw_mcu
    pico_stdlib
    hardware_adc
    hardware_i2c
    hardware_spi
    hardware_pwm
    hardware_uart
    hardware_watchdog
    # hardware_spi is linked for the chamber BME280 on SPI_1, NOT for the SD
    # cards: M-11 still needs FatFs, and SPI_0's pins are still the
    # equalisation valve pins (src/hw/board.h). Adding FatFs here does not
    # unblock it.
)

# stdio on USB, and UART stdio OFF - deliberately, both of them.
#
# USB on: it brings the picotool reset interface, so `picotool load -f` can
# reboot running firmware into BOOTSEL and reflashing no longer needs the
# button held during power-up. This only works because main() calls
# stdio_init_all(); the CMake line alone compiles the driver and the linker
# then discards it, which looks like success and changes nothing.
#
# UART stdio OFF is the safety-critical half. The SDK default stdio UART is
# uart0 on GP0/GP1 (PICO_DEFAULT_UART=0, TX pin 0, RX pin 1) - the exact UART
# and pins hw/uart_io.c uses for the HK downlink. With UART stdio enabled, any
# printf would inject raw text between framed HK packets and corrupt the
# telemetry stream. Keep it 0 so stdout can only ever reach USB.
#
# Cost: TinyUSB's flash and RAM plus its servicing timer, and a USB peripheral
# enumerating on the payload. This is a bring-up convenience - for a flight
# build where that is unacceptable, set USB to 0 and use reset_usb_boot() on a
# ground command, or SWD.
pico_enable_stdio_uart(clouds_fsw_mcu 0)
pico_enable_stdio_usb(clouds_fsw_mcu 1)

pico_add_extra_outputs(clouds_fsw_mcu)

# --- bench tool, not flight software -----------------------------------------
# bno055_probe: register-level IMU bring-up diagnostics over USB CDC. Built
# only when -DCLOUDS_BUILD_TOOLS=ON so a normal build cannot produce a .uf2
# that is not the flight image. Same stdio rules as the flight target: USB on,
# UART off, because uart0/GP0/GP1 carry the HK downlink.
if(CLOUDS_BUILD_TOOLS)
    add_executable(bno055_probe
        src/tools/bno055_probe.c
        src/core/crc16.c
        src/core/cobs.c
        src/core/frame.c
        src/core/config.c
        src/core/link.c
        src/core/autonomy.c
        src/core/sequencer.c
        src/core/pulse.c
        src/core/pwmdiv.c
        src/core/sqwave.c
        src/hw/hw.c
        src/hw/bme280.c
        src/hw/bno055.c
        src/hw/ina226.c
        src/hw/uart_io.c
    )
    target_compile_options(bno055_probe PRIVATE -Wall -Wextra)
    target_link_libraries(bno055_probe
        pico_stdlib
        hardware_adc
        hardware_i2c
        hardware_spi
        hardware_pwm
        hardware_uart
        hardware_watchdog
    )
    pico_enable_stdio_uart(bno055_probe 0)
    pico_enable_stdio_usb(bno055_probe 1)
    pico_add_extra_outputs(bno055_probe)

    # membrane_switch_probe: is the GP30 position switch wired, and does it
    # follow the GP26 solenoid drive? Drives the membrane, so it is a bench
    # tool by the same rule as the IMU probe.
    add_executable(membrane_switch_probe
        src/tools/membrane_switch_probe.c
        src/core/crc16.c
        src/core/cobs.c
        src/core/frame.c
        src/core/config.c
        src/core/link.c
        src/core/autonomy.c
        src/core/sequencer.c
        src/core/pulse.c
        src/core/pwmdiv.c
        src/core/sqwave.c
        src/hw/hw.c
        src/hw/bme280.c
        src/hw/bno055.c
        src/hw/ina226.c
        src/hw/uart_io.c
    )
    target_compile_options(membrane_switch_probe PRIVATE -Wall -Wextra)
    target_link_libraries(membrane_switch_probe
        pico_stdlib
        hardware_adc
        hardware_i2c
        hardware_spi
        hardware_pwm
        hardware_uart
        hardware_watchdog
    )
    pico_enable_stdio_uart(membrane_switch_probe 0)
    pico_enable_stdio_usb(membrane_switch_probe 1)
    pico_add_extra_outputs(membrane_switch_probe)
endif()
