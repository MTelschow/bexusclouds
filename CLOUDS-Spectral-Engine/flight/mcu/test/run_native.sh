#!/bin/sh
# Compile + run the FSW-MCU core tests with plain cc (no PlatformIO).
# Works on Linux / macOS / WSL / Git Bash with gcc or clang installed.
set -e
cd "$(dirname "$0")/.."
CC="${CC:-cc}"
OUT="${TMPDIR:-/tmp}/clouds_mcu_tests"
"$CC" -Wall -Wextra -std=c11 -Itest/unity_min \
    src/core/crc16.c src/core/cobs.c src/core/frame.c src/core/config.c \
    src/core/autonomy.c src/core/sequencer.c src/core/pulse.c \
    src/core/pwmdiv.c \
    test/unity_min/unity.c test/test_core/test_main.c \
    -o "$OUT"
exec "$OUT"
