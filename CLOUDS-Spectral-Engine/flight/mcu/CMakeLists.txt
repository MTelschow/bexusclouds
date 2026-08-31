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
    src/core/pwmdiv.c
    src/core/sqwave.c
    src/hw/hw.c
    src/hw/bme280.c
    src/hw/uart_io.c
)

target_compile_options(clouds_fsw_mcu PRIVATE -Wall -Wextra)

target_link_libraries(clouds_fsw_mcu
    pico_stdlib
    hardware_adc
    hardware_i2c
    hardware_pwm
    hardware_uart
    hardware_watchdog
    # TODO (M-11): add hardware_spi + FatFs once the SD stack lands
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
