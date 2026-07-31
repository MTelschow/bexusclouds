# CLOUDS FSW-MCU firmware - official Raspberry Pi Pico SDK build (RP2350).
#
#   export PICO_SDK_PATH=/path/to/pico-sdk   (SDK >= 2.0 for rp2350)
#   mkdir build && cd build
#   cmake -DPICO_PLATFORM=rp2350 -DPICO_BOARD=pico2 ..
#   make
#   -> clouds_fsw_mcu.uf2 (drag onto the BOOTSEL drive)
cmake_minimum_required(VERSION 3.13)

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
    src/core/autonomy.c
    src/core/sequencer.c
    src/core/pulse.c
    src/hw/hw.c
    src/hw/uart_io.c
)

target_compile_options(clouds_fsw_mcu PRIVATE -Wall -Wextra)

target_link_libraries(clouds_fsw_mcu
    pico_stdlib
    hardware_adc
    hardware_pwm
    hardware_uart
    hardware_watchdog
    # TODO (M-11): add hardware_spi + FatFs once the SD stack lands
)

pico_add_extra_outputs(clouds_fsw_mcu)
