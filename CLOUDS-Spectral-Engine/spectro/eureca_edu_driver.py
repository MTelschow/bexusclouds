"""Real EURECA e9u_LSMD_EDU driver - ctypes wrapper over libe9u_LSMD_EDU_x64.dll.

The EDU board is a single-fibre TCD1304 unit (3648 px, no reference channel),
reached over an FTDI VCP UART instead of the Duo's async USB link - a
different device family from ``eureca_driver.py``, with its own DLL exports
(``e9u_LSMD_EDU_*`` instead of ``e9u_LSMD_*``). See docs/DRIVER.md.

**Windows only.** The vendored EDU SDK (``drivers/e9u_LSMD_EDU_LIB/``) ships a
Windows backend and the x64 DLL, but no Linux backend source - unlike the Duo
family, whose Linux sources are in ``drivers/e9u_LSMD_LIB_Linux/``. So the Pi
(feature P-01) flies the Duo; ``kind="edu"`` raises a clear error off Windows.
"""
from __future__ import annotations

import ctypes
import os
import sys

import numpy as np

from .driver import DeviceInfo, DriverError, SpectrometerDriver

_DLL_NAME = "libe9u_LSMD_EDU_x64.dll"
_MODEL = "e9u_LSMD-TCD1304-EDU"


def _resolve_dll_dir() -> str:
    """CLOUDS_E9U_EDU_DLL_DIR env -> repo-local drivers/e9u_LSMD_EDU_LIB/lib_x64 -> vendor/."""
    env = os.environ.get("CLOUDS_E9U_EDU_DLL_DIR")
    if env and os.path.isfile(os.path.join(env, _DLL_NAME)):
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    lib_dir = os.path.normpath(os.path.join(here, os.pardir, "drivers", "e9u_LSMD_EDU_LIB", "lib_x64"))
    if os.path.isfile(os.path.join(lib_dir, _DLL_NAME)):
        return lib_dir
    vendor = os.path.normpath(os.path.join(here, os.pardir, "vendor"))
    return vendor


class EurecaEduDriver(SpectrometerDriver):
    PIXELS = 3648

    def __init__(self, cam: int = 0, usb: bool = True):
        self.cam = int(cam)
        self.usb = 1 if usb else 0
        self._lib = None
        self._ptr = None
        self._pixels = self.PIXELS

    # ------------------------------------------------------------------ load
    def _load(self):
        if sys.platform != "win32":
            raise DriverError(
                f"the EDU board is Windows-only: the vendored SDK ships no Linux "
                f"backend for the e9u_LSMD_EDU family, only {_DLL_NAME}.\n"
                f"On Linux use the Duo (kind='std' / CLOUDS_SPECTRO_KIND=std) with "
                f"drivers/e9u_LSMD_LIB_Linux/, or --mock."
            )
        dll_dir = _resolve_dll_dir()
        dll = os.path.join(dll_dir, _DLL_NAME)
        if not os.path.isfile(dll):
            raise DriverError(
                f"vendor DLL not found: {dll}\n"
                f"set CLOUDS_E9U_EDU_DLL_DIR or drop {_DLL_NAME} into vendor/."
            )
        os.add_dll_directory(dll_dir)
        lib = ctypes.WinDLL(dll)
        lib.e9u_LSMD_EDU_search_for_camera.argtypes = (ctypes.c_uint, ctypes.c_int)
        lib.e9u_LSMD_EDU_search_for_camera.restype = ctypes.c_int
        lib.e9u_LSMD_EDU_start_camera_async.argtypes = (ctypes.c_uint,)
        lib.e9u_LSMD_EDU_start_camera_async.restype = ctypes.c_int
        lib.e9u_LSMD_EDU_set_exp_time_us.argtypes = (ctypes.c_uint, ctypes.c_uint)
        lib.e9u_LSMD_EDU_set_exp_time_us.restype = ctypes.c_int
        lib.e9u_LSMD_EDU_get_next_frame.argtypes = (ctypes.c_uint,)
        lib.e9u_LSMD_EDU_get_next_frame.restype = ctypes.c_int
        lib.e9u_LSMD_EDU_get_pixel_pointer.argtypes = (ctypes.c_uint,)
        lib.e9u_LSMD_EDU_get_pixel_pointer.restype = ctypes.POINTER(ctypes.c_uint16)
        lib.e9u_LSMD_EDU_get_pixel_count.argtypes = (ctypes.c_uint,)
        lib.e9u_LSMD_EDU_get_pixel_count.restype = ctypes.c_int
        self._lib = lib

    # --------------------------------------------------------------- connect
    def connect(self) -> DeviceInfo:
        if self._lib is None:
            self._load()
        rc = self._lib.e9u_LSMD_EDU_search_for_camera(self.cam, self.usb)
        if rc != 0:
            raise DriverError(
                f"no e9u_LSMD_EDU camera found (rc={rc}). Use a USB DATA cable - a "
                f"charge-only cable enumerates as 'Port Reset Failed' / Code 43."
            )
        self._lib.e9u_LSMD_EDU_start_camera_async(self.cam)
        pc = self._lib.e9u_LSMD_EDU_get_pixel_count(self.cam)
        self._pixels = int(pc) if pc and pc > 0 else self.PIXELS
        self._ptr = self._lib.e9u_LSMD_EDU_get_pixel_pointer(self.cam)
        if not self._ptr:
            raise DriverError("camera started but the pixel buffer pointer is null.")
        return DeviceInfo(model=_MODEL, pixels=self._pixels)

    # ----------------------------------------------------------- acquisition
    def set_times_us(self, exposure_us: int, frame_us: int | None = None) -> None:
        if self._lib is None:
            raise DriverError("set_times_us before connect()")
        self._lib.e9u_LSMD_EDU_set_exp_time_us(self.cam, int(exposure_us))

    def grab(self, discard: int = 0) -> np.ndarray:
        if self._ptr is None:
            raise DriverError("grab before connect()")
        for _ in range(max(0, discard)):
            self._lib.e9u_LSMD_EDU_get_next_frame(self.cam)
        self._lib.e9u_LSMD_EDU_get_next_frame(self.cam)
        arr = np.ctypeslib.as_array(self._ptr, shape=(self._pixels,))
        return arr.astype(np.uint16).copy()    # detach from the live DLL buffer

    def close(self) -> None:
        # the EDU DLL exports no public close/end/disconnect entry point for
        # this camera index - only internal IO_* functions that take a struct
        # pointer we don't have access to. Dropping the handle is the best we
        # can do; the OS reclaims the COM port when the process exits.
        self._lib = None
        self._ptr = None
