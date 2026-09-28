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

# --- BMV080 vendor library ----------------------------------------------------
# The particulate sensor has NO public register map: the datasheet documents
# only the SPI transaction format, and the measurement algorithm ships as two
# prebuilt Bosch archives. src/hw/bmv080_dev.c drives them through the port
# layer in src/hw/bmv080_port.c.
#
# The SDK lives in the sibling sensor-driver/ tree by default (same git repo,
# one level up from CLOUDS-Spectral-Engine). Override for an unpacked copy
# elsewhere:
#   cmake -S flight/mcu -B flight/mcu/build -DCLOUDS_BMV080_SDK_DIR=/path/to/sdk
#
# LICENSING: these archives and the vendor headers are Bosch Sensortec
# confidential, with no redistribution grant (sensor-driver/LICENSE.md). The
# flight image cannot be built without them, so a published copy of this repo
# cannot be built by its recipients without Bosch's permission. Bosch also
# disclaim fitness for "safety or security sensitive systems" - which is why
# nothing in core/ reads this sensor.
set(CLOUDS_BMV080_SDK_DIR ${CMAKE_CURRENT_LIST_DIR}/../../../sensor-driver
    CACHE PATH "Unpacked Bosch BMV080 SDK (contains api/inc and api/lib)")

# Pick the archive that matches this core AND this float ABI.
#
# The Pico SDK builds RP2350 with -mfloat-abi=softfp: FPU instructions, but
# arguments in core registers. Bosch ship two Cortex-M33 archives and only one
# of them matches - api/lib/arm_cortex_m33f is tagged Tag_ABI_VFP_args "VFP
# registers" (hard float) and the linker refuses it against an SDK build. The
# plain arm_cortex_m33 archive carries no VFP-args tag, i.e. base AAPCS, which
# is what softfp links against. Verify with:
#   arm-none-eabi-readelf -A <lib_bmv080.a> | grep Tag_ABI_VFP_args
if(PICO_PLATFORM STREQUAL "rp2040")
    set(BMV080_LIB_ARCH arm_cortex_m0plus)
elseif(PICO_PLATFORM MATCHES "^rp2350")
    set(BMV080_LIB_ARCH arm_cortex_m33)
else()
    message(FATAL_ERROR "No BMV080 vendor library for PICO_PLATFORM=${PICO_PLATFORM}")
endif()

set(BMV080_INC_DIR ${CLOUDS_BMV080_SDK_DIR}/api/inc)
set(BMV080_LIB_DIR ${CLOUDS_BMV080_SDK_DIR}/api/lib/${BMV080_LIB_ARCH}/arm_none_eabi_gcc/release)
if(NOT EXISTS ${BMV080_LIB_DIR}/lib_bmv080.a)
    message(FATAL_ERROR
        "BMV080 library not found: ${BMV080_LIB_DIR}/lib_bmv080.a\n"
        "Set -DCLOUDS_BMV080_SDK_DIR to an unpacked BMV080 SDK.")
endif()
message(STATUS "BMV080 vendor library: ${BMV080_LIB_DIR}")

# Every target links hw/hw.c, which calls into the driver, so every target
# needs the archives - including the bench probes.
#
# lib_bmv080 and lib_postProcessor reference each other's symbols, so they go
# in a link group: a single pass over them in either order leaves undefined
# references behind. `m` is for the powf/sqrtf/expf the post-processor needs.
#
# THE STACK. Bosch's own footprint table asks for 10 kB of stack on a
# Cortex-M33. The SDK gives core 0 the whole of SCRATCH_Y, which on an RP2350
# is 4 kB - so raising PICO_STACK_SIZE alone does not work and does not fail
# quietly either:
#
#   ld: section `.stack_dummy' will not fit in region `SCRATCH_Y'
#   ld: region `SCRATCH_Y' overflowed by 12288 bytes
#
# The stack has to leave the scratch banks. Rather than override the SDK's
# linker fragments - which would mean carrying a copy of section_end.incl and
# its __StackTop / __StackLimit / heap arithmetic, and having it silently
# diverge on the next SDK bump - the memory regions themselves are moved.
# set_memory_locations.incl takes every region's origin and length from a
# linker symbol if one is defined, so three --defsym flags are enough and all
# of the SDK's symbol math stays correct by construction, including the
# ASSERT(__StackLimit >= __HeapLimit) that stops the heap growing into it:
#
#   SCRATCH_Y  grows DOWN from the top of SRAM: 0x2007E000 + 16 kB, ending at
#              0x20082000 as before. Physically that spans the top of main
#              SRAM and both scratch banks, which are contiguous in the
#              address map.
#   RAM        loses those 12 kB: 512 kB -> 504 kB, ending exactly where the
#              stack now begins, so __StackLimit still equals the heap's
#              ceiling.
#   SCRATCH_X  goes to zero length. It held the core 1 stack, and nothing
#              here launches core 1 - but it also OVERLAPS the new SCRATCH_Y,
#              and a future __scratch_x placement would otherwise land
#              silently inside the stack. At length 0 it fails the link
#              instead. Checked before doing this: .scratch_x and .scratch_y
#              are both 0 bytes in the map, so nothing was evicted.
#
# 520 kB of SRAM is still 520 kB; 12 kB of it is now stack instead of heap
# the firmware does not use (nothing here calls malloc).
function(clouds_add_bmv080 target)
    target_include_directories(${target} PRIVATE ${BMV080_INC_DIR})
    target_compile_definitions(${target} PRIVATE PICO_STACK_SIZE=0x4000)
    target_link_options(${target} PRIVATE
        -Wl,--defsym=RAM_LENGTH=0x7E000
        -Wl,--defsym=SCRATCH_X_LENGTH=0
        -Wl,--defsym=SCRATCH_Y_ORIGIN=0x2007E000
        -Wl,--defsym=SCRATCH_Y_LENGTH=0x4000
    )
    target_link_libraries(${target}
        -Wl,--start-group
        ${BMV080_LIB_DIR}/lib_bmv080.a
        ${BMV080_LIB_DIR}/lib_postProcessor.a
        -Wl,--end-group
        m
    )
endfunction()

# The dispersion motor encoder's quadrature counter is a PIO program
# (src/hw/quadrature_encoder.pio), and hw/hw.c includes its generated header,
# so every target that links hw.c needs both.
function(clouds_add_encoder target)
    pico_generate_pio_header(${target}
        ${CMAKE_CURRENT_LIST_DIR}/src/hw/quadrature_encoder.pio)
    target_link_libraries(${target} hardware_pio)
endfunction()

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
    src/core/motor_enc.c
    src/hw/hw.c
    src/hw/bme280.c
    src/hw/bmv080_dev.c
    src/hw/bmv080_port.c
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
    # hardware_spi is linked for the two parts on SPI_1 - the chamber BME280
    # and the BMV080 - and NOT for the SD cards: M-11 still needs FatFs, and
    # SPI_0's pins are still the equalisation valve pins (src/hw/board.h).
    # Adding FatFs here does not unblock it.
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
clouds_add_bmv080(clouds_fsw_mcu)
clouds_add_encoder(clouds_fsw_mcu)

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
        src/core/motor_enc.c
        src/hw/hw.c
        src/hw/bme280.c
    src/hw/bmv080_dev.c
    src/hw/bmv080_port.c
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
    clouds_add_bmv080(bno055_probe)
    clouds_add_encoder(bno055_probe)
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
        src/core/motor_enc.c
        src/hw/hw.c
        src/hw/bme280.c
    src/hw/bmv080_dev.c
    src/hw/bmv080_port.c
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
    clouds_add_bmv080(membrane_switch_probe)
    clouds_add_encoder(membrane_switch_probe)
    pico_enable_stdio_uart(membrane_switch_probe 0)
    pico_enable_stdio_usb(membrane_switch_probe 1)
    pico_add_extra_outputs(membrane_switch_probe)

    # encoder_pin_probe: which pins does the dispersion motor encoder land
    # on? Counts edges on every undriven GPIO with the motor off, driven and
    # hand-turned. DRIVES THE MOTOR. Standalone: no hw.c, so nothing else on
    # the board is initialised.
    add_executable(encoder_pin_probe
        src/tools/encoder_pin_probe.c
        src/core/pwmdiv.c
    )
    target_compile_options(encoder_pin_probe PRIVATE -Wall -Wextra)
    target_link_libraries(encoder_pin_probe pico_stdlib hardware_pwm)
    pico_enable_stdio_uart(encoder_pin_probe 0)
    pico_enable_stdio_usb(encoder_pin_probe 1)
    pico_add_extra_outputs(encoder_pin_probe)

    # encoder_trace_probe: timestamped trace of the four ACT_EC pins while
    # the motor turns, so A, B, complement and index can be told apart on
    # the host. DRIVES THE MOTOR. Standalone like encoder_pin_probe.
    add_executable(encoder_trace_probe
        src/tools/encoder_trace_probe.c
        src/core/pwmdiv.c
    )
    target_compile_options(encoder_trace_probe PRIVATE -Wall -Wextra)
    target_link_libraries(encoder_trace_probe pico_stdlib hardware_pwm)
    pico_enable_stdio_uart(encoder_trace_probe 0)
    pico_enable_stdio_usb(encoder_trace_probe 1)
    pico_add_extra_outputs(encoder_trace_probe)

    # bme280_probe: which chip select / SPI mode / i2c0 address does a
    # BME280 answer on? Reads CHIP_ID only; commands no actuator.
    add_executable(bme280_probe
        src/tools/bme280_probe.c
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
        src/core/motor_enc.c
        src/hw/hw.c
        src/hw/bme280.c
    src/hw/bmv080_dev.c
    src/hw/bmv080_port.c
        src/hw/bno055.c
        src/hw/ina226.c
        src/hw/uart_io.c
    )
    target_compile_options(bme280_probe PRIVATE -Wall -Wextra)
    target_link_libraries(bme280_probe
        pico_stdlib
        hardware_adc
        hardware_i2c
        hardware_spi
        hardware_pwm
        hardware_uart
        hardware_watchdog
    )
    clouds_add_bmv080(bme280_probe)
    clouds_add_encoder(bme280_probe)
    pico_enable_stdio_uart(bme280_probe 0)
    pico_enable_stdio_usb(bme280_probe 1)
    pico_add_extra_outputs(bme280_probe)

    # bmv080_probe: does the particulate sensor answer at all, and on which
    # chip select? Raw 16-bit reads, then bmv080_open() per select, then PM
    # lines. Commands no actuator.
    #
    # -u_printf_float: the vendor output is floats and this tool prints them.
    # The flight target does not need it - it converts to a uint16 in
    # hw/bmv080_dev.c and never formats a float.
    add_executable(bmv080_probe
        src/tools/bmv080_probe.c
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
        src/core/motor_enc.c
        src/hw/hw.c
        src/hw/bme280.c
        src/hw/bmv080_dev.c
        src/hw/bmv080_port.c
        src/hw/bno055.c
        src/hw/ina226.c
        src/hw/uart_io.c
    )
    target_compile_options(bmv080_probe PRIVATE -Wall -Wextra)
    target_link_libraries(bmv080_probe
        pico_stdlib
        hardware_adc
        hardware_i2c
        hardware_spi
        hardware_pwm
        hardware_uart
        hardware_watchdog
        -Wl,-u_printf_float
    )
    clouds_add_bmv080(bmv080_probe)
    clouds_add_encoder(bmv080_probe)
    pico_enable_stdio_uart(bmv080_probe 0)
    pico_enable_stdio_usb(bmv080_probe 1)
    pico_add_extra_outputs(bmv080_probe)
endif()
