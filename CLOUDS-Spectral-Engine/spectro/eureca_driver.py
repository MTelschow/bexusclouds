"""Real EURECA e9u_LSMD Duo driver - ctypes wrapper over the vendor library.

The whole Duo is one camera to the library: one readout yields both fibre
channels in a single 2048-px frame at one shared integration time.

Cross-platform by design (feature P-01): Windows loads the prebuilt
``libe9u_LSMD_x64.dll`` from ``vendor/``, Linux loads ``libe9u_LSMD.so`` built
from the vendor source in ``drivers/e9u_LSMD_LIB_Linux/``. Both expose the same
``e9u_LSMD_*`` convenience API, so only library loading differs.
See docs/DRIVER.md.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import sys
import tempfile

import numpy as np

from .driver import DeviceInfo, DriverError, SpectrometerDriver

_IS_WINDOWS = sys.platform == "win32"
_DLL_NAME = "libe9u_LSMD_x64.dll"
_SO_NAME = "libe9u_LSMD.so"
_LIB_NAME = _DLL_NAME if _IS_WINDOWS else _SO_NAME
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir))
# `make install` default (autotools LIBDIR); /etc/ld.so.conf may not list it.
_LINUX_FALLBACK_DIRS = ("/usr/local/lib", "/usr/lib")

# Data scaling (docs/CALIBRATION.md): the ADC is 12-bit, and the *Windows* DLL
# returns each sample already left-shifted into 16 bits (value ~= adc x 16), so
# counts run 0..65520 - the scale `calibration.json`'s `saturation_count`, the
# mock driver and every QC script assume. The Linux `.so` (2.4.02, measured on
# the flight Pi: max 2336, dark 76, values not multiples of 16) returns the raw
# 12-bit sample instead. Normalise Linux to the documented scale so one
# calibration is valid on both platforms - otherwise clipping flags never fire
# and the P-09 exposure servo only ever ramps up. Override with
# CLOUDS_E9U_COUNT_SHIFT (0 disables) if a vendor release changes this.
_COUNT_SHIFT_ENV = "CLOUDS_E9U_COUNT_SHIFT"
_DEFAULT_COUNT_SHIFT = 0 if _IS_WINDOWS else 4


def _resolve_count_shift() -> int:
    env = os.environ.get(_COUNT_SHIFT_ENV)
    if env not in (None, ""):
        try:
            return max(0, min(8, int(env)))
        except ValueError:
            pass
    return _DEFAULT_COUNT_SHIFT


def _resolve_lib_dir() -> str | None:
    """Directory holding the vendor library, or None if only the loader knows.

    Windows: ``CLOUDS_E9U_DLL_DIR`` -> repo-local ``vendor/`` -> the legacy
    ``EURECA_e9u\\e9u_LSMD_GTK_x64`` folder.
    Linux: ``CLOUDS_E9U_LIB_DIR`` -> repo-local ``vendor/`` -> the usual
    ``make install`` prefixes -> None (fall back to the dynamic loader, i.e.
    ``ldconfig`` after ``sudo make install``).
    """
    env = os.environ.get("CLOUDS_E9U_DLL_DIR" if _IS_WINDOWS else "CLOUDS_E9U_LIB_DIR")
    if env and os.path.isfile(os.path.join(env, _LIB_NAME)):
        return env
    vendor = os.path.join(_ROOT, "vendor")
    if os.path.isfile(os.path.join(vendor, _LIB_NAME)):
        return vendor
    if _IS_WINDOWS:
        return r"C:\Users\kai-w\projects\EURECA_e9u\e9u_LSMD_GTK_x64"
    for d in _LINUX_FALLBACK_DIRS:
        if os.path.isfile(os.path.join(d, _SO_NAME)):
            return d
    return None


def _load_vendor_lib():
    """Load the vendor library for this platform. Raises DriverError."""
    lib_dir = _resolve_lib_dir()
    if _IS_WINDOWS:
        path = os.path.join(lib_dir, _DLL_NAME)
        if not os.path.isfile(path):
            raise DriverError(
                f"vendor DLL not found: {path}\n"
                f"set CLOUDS_E9U_DLL_DIR or drop {_DLL_NAME} into vendor/."
            )
        os.add_dll_directory(lib_dir)       # mingw runtime deps live beside it
        return ctypes.WinDLL(path)
    if lib_dir is not None:
        return ctypes.CDLL(os.path.join(lib_dir, _SO_NAME))
    # Linux, not found on any known path: let the dynamic loader try.
    for cand in (_SO_NAME, f"{_SO_NAME}.0", ctypes.util.find_library("e9u_LSMD")):
        if not cand:
            continue
        try:
            return ctypes.CDLL(cand)
        except OSError:
            continue
    raise DriverError(
        f"vendor library {_SO_NAME} not found.\n"
        f"Build + install it from drivers/e9u_LSMD_LIB_Linux/ "
        f"(see that folder's README, or run its install.sh), or set "
        f"CLOUDS_E9U_LIB_DIR to the directory holding {_SO_NAME}."
    )


def _flush_c_stdout() -> None:
    """Flush the vendor library's C ``stdout``.

    The library identifies the camera with ``printf``; we read it off a
    redirected fd 1. Redirected to a file, glibc block-buffers, so the identity
    text can still sit in the C buffer when we read - ``fflush(NULL)`` on the
    process' own libc (shared with the .so) pushes it out. Best-effort: without
    it we only lose the identity string, never the connect result.
    """
    if _IS_WINDOWS:
        return                          # the mingw DLL's CRT is not ours to flush
    try:
        ctypes.CDLL(None).fflush(None)
    except Exception:
        pass


class EurecaDriver(SpectrometerDriver):
    PIXELS = 2048
    CHANNEL = 0     # the Duo is one camera / one channel to the vendor library

    def __init__(self, cam: int = 0):
        self.cam = int(cam)
        self._lib = None
        self._ptr = None
        self._info = None
        self._count_shift = _resolve_count_shift()

    # ------------------------------------------------------------------ load
    def _load(self):
        lib = _load_vendor_lib()
        lib.e9u_LSMD_search_for_camera.argtypes = (ctypes.c_uint,)
        lib.e9u_LSMD_search_for_camera.restype = ctypes.c_int
        lib.e9u_LSMD_start_camera_async.argtypes = (ctypes.c_uint,)
        lib.e9u_LSMD_start_camera_async.restype = ctypes.c_int
        lib.e9u_LSMD_set_times_us.argtypes = (ctypes.c_uint, ctypes.c_uint, ctypes.c_uint)
        lib.e9u_LSMD_set_times_us.restype = ctypes.c_int
        lib.e9u_LSMD_get_next_frame.argtypes = (ctypes.c_uint,)
        lib.e9u_LSMD_get_next_frame.restype = ctypes.c_int
        lib.e9u_LSMD_get_pixel_pointer.argtypes = (ctypes.c_uint, ctypes.c_uint)
        lib.e9u_LSMD_get_pixel_pointer.restype = ctypes.POINTER(ctypes.c_uint16)
        # optional reads (on-chip black / drop detect). Arities are from the
        # vendor headers (include/e9u_LSMD.h): dark_value takes (cam, channel,
        # x, y), frame_counter (cam, channel) - not one arg each.
        for _name, _args, _rt in (
            ("e9u_LSMD_get_dark_value",
             (ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint), ctypes.c_int),
            ("e9u_LSMD_get_frame_counter",
             (ctypes.c_uint, ctypes.c_uint), ctypes.c_uint),
        ):
            _fn = getattr(lib, _name, None)
            if _fn is not None:
                _fn.argtypes = _args
                _fn.restype = _rt
        self._lib = lib

    # --------------------------------------------------------------- connect
    def connect(self) -> DeviceInfo:
        if self._lib is None:
            self._load()
        text, rc = "", None
        try:
            sys.stdout.flush()
            tmp = tempfile.TemporaryFile(mode="w+b")
            saved = os.dup(1)
            try:
                os.dup2(tmp.fileno(), 1)               # capture the library's printf identity
                rc = self._lib.e9u_LSMD_search_for_camera(self.cam)
                sys.stdout.flush()
                _flush_c_stdout()
            finally:
                os.dup2(saved, 1)
                os.close(saved)
            tmp.seek(0)
            text = tmp.read().decode("utf-8", "replace")
            tmp.close()
        except Exception:
            if rc is None:
                rc = self._lib.e9u_LSMD_search_for_camera(self.cam)

        if rc != 0:
            raise DriverError(
                f"no e9u camera found (rc={rc}). Use a USB DATA cable - a "
                f"charge-only cable enumerates as 'Port Reset Failed' / Code 43."
            )
        self._info = self._parse_identity(text)
        self._lib.e9u_LSMD_start_camera_async(self.cam)
        self._ptr = self._lib.e9u_LSMD_get_pixel_pointer(self.cam, 0)
        if not self._ptr:
            raise DriverError("camera started but the pixel buffer pointer is null.")
        return self._info

    def _parse_identity(self, text: str) -> DeviceInfo:
        def g(pat, default=""):
            m = re.search(pat, text)
            return m.group(1).strip() if m else default

        # (?<!\w) so "Dark_Pixel: 0 x 16", which precedes it in the identity
        # text, cannot match - it used to report pixels=16 on a 2048-px line.
        px = g(r"(?<!\w)Pixel:\s*\d+\s*x\s*(\d+)")
        return DeviceInfo(
            model=g(r"(e9u_LSMD-\S+)", "e9u_LSMD"),
            serial=g(r"SN:\s*(\S+)"),
            com_port=g(r"using device\s+(.+?):"),
            pixels=int(px) if px.isdigit() else self.PIXELS,
            firmware=g(r"FW:\s*(\S+)"),
            raw=text.strip(),
        )

    # ----------------------------------------------------------- acquisition
    def set_times_us(self, exposure_us: int, frame_us: int | None = None) -> None:
        if self._lib is None:
            raise DriverError("set_times_us before connect()")
        frame_us = int(exposure_us if frame_us is None else frame_us)
        self._lib.e9u_LSMD_set_times_us(self.cam, int(exposure_us), frame_us)

    def grab(self, discard: int = 0) -> np.ndarray:
        if self._ptr is None:
            raise DriverError("grab before connect()")
        for _ in range(max(0, discard)):
            self._lib.e9u_LSMD_get_next_frame(self.cam)
        self._lib.e9u_LSMD_get_next_frame(self.cam)
        arr = np.ctypeslib.as_array(self._ptr, shape=(self.PIXELS,))
        out = arr.astype(np.uint16).copy()     # detach from the live DLL buffer
        if self._count_shift:                  # raw 12-bit -> documented 16-bit
            np.minimum(out, 0xFFFF >> self._count_shift, out)   # no wraparound
            out <<= self._count_shift
        return out

    def dark_value(self):
        fn = getattr(self._lib, "e9u_LSMD_get_dark_value", None) if self._lib else None
        try:                                       # (cam, channel, x, y) - line sensor: y=0
            if fn is None:
                return None
            # same scale as grab(): it is subtracted straight from frame counts
            return float(fn(self.cam, self.CHANNEL, 0, 0)) * (1 << self._count_shift)
        except Exception:
            return None

    def frame_counter(self):
        fn = getattr(self._lib, "e9u_LSMD_get_frame_counter", None) if self._lib else None
        try:
            return int(fn(self.cam, self.CHANNEL)) if fn is not None else None
        except Exception:
            return None

    def close(self) -> None:
        if self._lib is not None:
            for name in ("e9u_LSMD_stop_camera", "e9u_LSMD_close_camera", "e9u_LSMD_disconnect"):
                fn = getattr(self._lib, name, None)
                if fn is not None:
                    try:
                        fn(self.cam)
                    except Exception:
                        pass
        self._lib = None
        self._ptr = None
