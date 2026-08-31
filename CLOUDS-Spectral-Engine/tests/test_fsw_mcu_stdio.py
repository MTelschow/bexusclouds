"""FSW-MCU stdio configuration: USB carries the reset interface, UART must not.

Two invariants, both easy to break by accident:

1. **UART stdio must stay off.** The SDK default stdio UART is uart0 on
   GP0/GP1 (`PICO_DEFAULT_UART` 0, TX pin 0, RX pin 1) - the same UART and
   pins `hw/uart_io.c` uses for the framed HK downlink. Enabling UART stdio
   lets any `printf` inject raw bytes between HK packets and corrupt the
   telemetry stream.

2. **Enabling USB stdio in CMake does nothing on its own.** Without a
   `stdio_init_all()` call the driver is compiled and then dropped by the
   linker, so the picotool reset interface silently does not exist. That
   failure looks exactly like success: the build gets bigger by ~50 bytes and
   the feature is absent.
"""
import os
import re

import pytest

MCU = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "flight", "mcu")


def _read(*parts):
    with open(os.path.join(MCU, *parts), encoding="utf-8") as fh:
        return fh.read()


def _stdio_flag(cmake, which):
    m = re.search(r"pico_enable_stdio_%s\s*\(\s*\w+\s+([01])\s*\)" % which,
                  cmake)
    return None if m is None else int(m.group(1))


@pytest.fixture(scope="module")
def cmake():
    return _read("CMakeLists.txt")


def test_uart_stdio_is_disabled(cmake):
    """A printf must never be able to reach the HK downlink pins."""
    assert _stdio_flag(cmake, "uart") == 0, (
        "stdio UART defaults to uart0 on GP0/GP1, the HK downlink - a printf "
        "there corrupts framed telemetry")


def test_hk_downlink_owns_uart0_directly(cmake):
    """The premise of the test above: the downlink really is uart0."""
    uart_io = _read("src", "hw", "uart_io.c")
    assert re.search(r"#define\s+UART_ID\s+uart0", uart_io)
    board = _read("src", "hw", "board.h")
    assert re.search(r"#define\s+PIN_UART_TX\s+0\b", board)
    assert re.search(r"#define\s+PIN_UART_RX\s+1\b", board)


def test_usb_stdio_is_actually_initialised(cmake):
    """If USB stdio is enabled, main() must register it, or the linker drops
    the driver and the reset interface does not exist."""
    if _stdio_flag(cmake, "usb") != 1:
        pytest.skip("USB stdio not enabled in this build")
    main_c = _read("src", "main.c")
    assert "stdio_init_all()" in main_c, (
        "pico_enable_stdio_usb without stdio_init_all() is inert: the driver "
        "is compiled and then discarded")
