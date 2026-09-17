/* Board header for the CLOUDS main electronics board (the carrier).
 *
 * The carrier is an RP2350B - QFN80, GP0..GP47 - confirmed by the schematic
 * (pin_layout.jpeg, 2026-09-11) and independently by `picotool info` on
 * serial 21DD2AE08840C863 (`package: QFN80`). Until 2026-09-17 the firmware
 * was built with -DPICO_BOARD=pico2, i.e. RP2350A with GP0..GP29, which made
 * every net above GP29 unreachable and was harmless only for as long as
 * nothing above GP29 was in use. The membrane position switch on GP30
 * (src/hw/board.h, PIN_MEMBRANE_SENSE) is the first such net.
 *
 * What differs from pico2.h: PICO_RP2350A is 0, which sets NUM_BANK0_GPIOS to
 * 48 and moves the ADC base pin to GP40. No LED, I2C or SPI defaults are
 * declared here - the SDK defaults would name pins that are real actuators
 * on this board (pico2's PICO_DEFAULT_SPI_CSN_PIN is GP17, the dispersion
 * motor), and nothing in this firmware uses the SDK's default-pin macros
 * anyway; the pin map is src/hw/board.h. The UART default is kept because
 * uart_io.c's downlink really is uart0 on GP0/GP1 (RP->PI / RP<-PI).
 *
 * The flash size is the pico2 value and is an ASSUMPTION about the carrier's
 * QSPI part - it only bounds the linker's FLASH region, and the image is a
 * small fraction of it. Confirm with `picotool info -a` when convenient.
 *
 * Selected by default in CMakeLists.txt; -DPICO_BOARD=pico2 still builds the
 * same firmware for a bare Pico 2, with the GP30 sense reported as unsourced.
 */
#ifndef _BOARDS_CLOUDS_CARRIER_H
#define _BOARDS_CLOUDS_CARRIER_H

// pico_cmake_set PICO_PLATFORM=rp2350

#define CLOUDS_CARRIER

#define PICO_RP2350A 0

// --- UART0 to the Raspberry Pi: RP->PI GP0, RP<-PI GP1 ---
#ifndef PICO_DEFAULT_UART
#define PICO_DEFAULT_UART 0
#endif
#ifndef PICO_DEFAULT_UART_TX_PIN
#define PICO_DEFAULT_UART_TX_PIN 0
#endif
#ifndef PICO_DEFAULT_UART_RX_PIN
#define PICO_DEFAULT_UART_RX_PIN 1
#endif

// --- FLASH ---
#define PICO_BOOT_STAGE2_CHOOSE_W25Q080 1

#ifndef PICO_FLASH_SPI_CLKDIV
#define PICO_FLASH_SPI_CLKDIV 2
#endif

// pico_cmake_set_default PICO_FLASH_SIZE_BYTES = (4 * 1024 * 1024)
#ifndef PICO_FLASH_SIZE_BYTES
#define PICO_FLASH_SIZE_BYTES (4 * 1024 * 1024)
#endif

// pico_cmake_set_default PICO_RP2350_A2_SUPPORTED = 1
#ifndef PICO_RP2350_A2_SUPPORTED
#define PICO_RP2350_A2_SUPPORTED 1
#endif

#endif
