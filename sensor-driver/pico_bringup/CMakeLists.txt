# BMV080 bring-up firmware - official Raspberry Pi Pico SDK build.
#
#   export PICO_SDK_PATH=~/pico-sdk PICO_TOOLCHAIN_PATH=~/arm-gnu-toolchain
#   cmake -S . -B build -DPICO_PLATFORM=rp2350 -DPICO_BOARD=pico2
#   cmake --build build -j8
#   picotool load -f -x build/bmv080_bringup.uf2
#
# Pins come from src/board_pins.h and every one can be overridden here, e.g.
#   cmake -S . -B build -DPICO_PLATFORM=rp2350 -DPICO_BOARD=pico2 \
#         -DBMV080_PIN_MISO=12 -DBMV080_PIN_CS2=255
# (255 = BMV080_PIN_NONE, i.e. only one sensor on the bus).
cmake_minimum_required(VERSION 3.13)

include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)

project(bmv080_bringup C CXX ASM)
set(CMAKE_C_STANDARD 11)

pico_sdk_init()

set(BMV080_API_DIR ${CMAKE_CURRENT_LIST_DIR}/../api)

# Pick the vendor blob that matches this core AND this float ABI.
#
# The Pico SDK builds RP2350 with -mfloat-abi=softfp: FPU instructions, but
# arguments in core registers. Bosch ship two Cortex-M33 archives and only one
# of them matches - lib/arm_cortex_m33f is tagged Tag_ABI_VFP_args "VFP
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

set(BMV080_LIB_DIR ${BMV080_API_DIR}/lib/${BMV080_LIB_ARCH}/arm_none_eabi_gcc/release)
if(NOT EXISTS ${BMV080_LIB_DIR}/lib_bmv080.a)
    message(FATAL_ERROR "BMV080 library not found: ${BMV080_LIB_DIR}/lib_bmv080.a")
endif()
message(STATUS "BMV080 vendor library: ${BMV080_LIB_DIR}")

add_executable(bmv080_bringup
    src/main.c
    src/bmv080_port.c
    src/rails.c
)

target_compile_options(bmv080_bringup PRIVATE -Wall -Wextra)

target_include_directories(bmv080_bringup PRIVATE
    ${BMV080_API_DIR}/inc
    ${CMAKE_CURRENT_LIST_DIR}/src
)

# Pin overrides: only the ones actually passed on the command line reach the
# compiler; the rest keep the defaults in src/board_pins.h.
foreach(PIN_OPTION
        BMV080_SPI_INSTANCE
        BMV080_PIN_MISO
        BMV080_PIN_MOSI
        BMV080_PIN_SCK
        BMV080_PIN_CS1
        BMV080_PIN_CS2
        BMV080_SPI_CLK_HZ
        MEASUREMENT_READINGS
        BMV080_FORCE_BUS)
    if(DEFINED ${PIN_OPTION})
        target_compile_definitions(bmv080_bringup PRIVATE ${PIN_OPTION}=${${PIN_OPTION}})
        message(STATUS "BMV080 override: ${PIN_OPTION}=${${PIN_OPTION}}")
    endif()
endforeach()

# lib_bmv080 and lib_postProcessor reference each other's symbols, so they go
# in a link group - a single pass over them in either order leaves undefined
# references behind.
target_link_libraries(bmv080_bringup
    pico_stdlib
    hardware_spi
    hardware_adc
    -Wl,--start-group
    ${BMV080_LIB_DIR}/lib_bmv080.a
    ${BMV080_LIB_DIR}/lib_postProcessor.a
    -Wl,--end-group
    m
)

# stdio on USB only. The console is the whole point of this firmware, and USB
# stdio also brings the picotool reset interface, so reflashing needs no
# BOOTSEL button. UART stdio stays off: on the CLOUDS carrier the SDK's default
# stdio UART (uart0, GP0/GP1) is the HK downlink, and a printf there corrupts
# telemetry. Keeping the habit here means the port to that board cannot
# silently inherit the wrong setting.
pico_enable_stdio_uart(bmv080_bringup 0)
pico_enable_stdio_usb(bmv080_bringup 1)

pico_add_extra_outputs(bmv080_bringup)
