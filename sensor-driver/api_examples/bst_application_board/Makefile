COINES_INSTALL_PATH ?= C:/COINES_SDK/v2.10.4

API_DIR_PATH ?= ../../api
TARGET ?= MCU_APP31

COMPILER_GCC = arm_none_eabi_gcc
BUILD_CONFIGURATION ?= release

INTERFACE_SEL ?= $(BUILD_CONFIGURATION)_spi

ifeq ($(COMM_INTERFACE), 2)
  INTERFACE_SEL = $(BUILD_CONFIGURATION)_i2c
else
  INTERFACE_SEL = $(BUILD_CONFIGURATION)_spi
endif

BIN_DIR_PATH ?= bin/$(TARGET)/$(COMPILER_GCC)/$(INTERFACE_SEL)
ARTIFACTS_FILE = $(BIN_DIR_PATH)/$(EXAMPLE_FILE)

COMMON_DIR_PATH ?= ../_common

EXAMPLE_FILE ?= bmv080_example

C_SRCS += \
$(COMMON_DIR_PATH)/src/$(EXAMPLE_FILE).c \
src/main.c \
src/combridge.c \

INCLUDEPATHS += \
inc \
$(API_DIR_PATH)/inc \
$(COMMON_DIR_PATH)/inc \

LIBPATHS += $(API_DIR_PATH)/lib/arm_cortex_m4f/$(COMPILER_GCC)/$(BUILD_CONFIGURATION)
LIBS += _bmv080 _postProcessor

CFLAGS += -DHOST_INTERFACE=$(COMM_INTERFACE) -Wno-discarded-qualifiers

#re-define BIN, HEX and EXE
BIN = $(ARTIFACTS_FILE).bin
EXE = $(ARTIFACTS_FILE).elf
HEX = $(ARTIFACTS_FILE).hex

include $(COINES_INSTALL_PATH)/coines.mk

