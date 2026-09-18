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
import time

import numpy as np

from .driver import DeviceInfo, DriverError, SpectrometerDriver

_IS_WINDOWS = sys.platform == "win32"
_IS_MACOS = sys.platform == "darwin"
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

# Camera registers (vendor include/e9u_LSMD_defs.h). The exposure timestamps are
# the camera's own measurement of the integration window it just ran, in the same
# microseconds as CH0_EXP_TIME - the vendor's wait_times_us() spins on exactly
# this comparison, which is also its admission that a timing change is not live
# on the next frame.
_REG_CH0_EXP_TIME = 0x01
_REG_CH0_FRAME_TIME = 0x02
_REG_T_STAMP_EXP_STOP = 0x05
_REG_T_STAMP_EXP_START = 0x06
_BANK_TX, _BANK_SH = 1, 2

# Timing safety net, see docs/DRIVER.md "Integration time".
#
# The camera is opened in *async* mode: no internal frame timer, no external
# trigger - each frame is triggered over USB from inside get_next_frame(). The
# line is not clocked between two triggers, so charge keeps collecting on the
# photodiodes for the whole idle time and the first frame after a pause carries
# the pause, not the exposure. A 1 Hz live loop at 10 ms exposure then reads
# ~100x the light it asked for and sits at saturation whatever the operator sets.
# So: after an idle gap worth more than _FLUSH_GAP_FRACTION of the exposure,
# throw one frame away before the one we keep. That frame ends a readout, so the
# kept frame's integration starts from a known point.
_FLUSH_ENV = "CLOUDS_E9U_FLUSH"        # "0" disables, "always" flushes every grab
_FLUSH_GAP_FRACTION = 0.10             # idle worth >10 % of the exposure -> flush
_FLUSH_GAP_MIN_S = 0.001               # back-to-back USB latency is not an idle
_SETTLE_MAX_FRAMES = 3                 # frames spent waiting for a new exposure

# Used only if the vendor library does not export its limit calls. Worst case
# from its own type table (ECO), so the frame time is never asked to be shorter
# than a readout; a too-generous frame time costs nothing in async mode, where
# nothing runs the frame timer.
_FALLBACK_LIMITS = {"min_exp": 10, "step_exp": 10, "min_frame": 10_000, "step_frame": 10}


def _round_up(value: int, step: int) -> int:
    """Up to the next multiple of *step*.

    The vendor rounds *down* (`t /= step; t *= step`), so a value that is already
    a multiple survives its arithmetic unchanged - and rounding up rather than
    down keeps a frame time from being floored back under the exposure.
    """
    if step <= 1:
        return int(value)
    return ((int(value) + step - 1) // step) * step


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

    Windows: ``CLOUDS_E9U_DLL_DIR`` -> repo-local ``vendor/`` -> None.
    Linux: ``CLOUDS_E9U_LIB_DIR`` -> repo-local ``vendor/`` -> the usual
    ``make install`` prefixes -> None (fall back to the dynamic loader, i.e.
    ``ldconfig`` after ``sudo make install``).

    Every candidate is a directory that actually *contains* the library. The
    Windows branch used to end at one developer's absolute
    ``C:\\Users\\...\\EURECA_e9u`` path, which on any other machine turned a
    missing DLL into a DriverError naming a folder that had never existed
    there - so the operator went looking for the wrong thing. ``vendor/`` is
    in the repo (and in the PyInstaller bundle), so the real answer on Windows
    is almost always "it is already found"; if it is not, say so about a path
    the operator can act on.
    """
    env = os.environ.get("CLOUDS_E9U_DLL_DIR" if _IS_WINDOWS else "CLOUDS_E9U_LIB_DIR")
    if env and os.path.isfile(os.path.join(env, _LIB_NAME)):
        return env
    vendor = os.path.join(_ROOT, "vendor")
    if os.path.isfile(os.path.join(vendor, _LIB_NAME)):
        return vendor
    if _IS_WINDOWS:
        return None
    for d in _LINUX_FALLBACK_DIRS:
        if os.path.isfile(os.path.join(d, _SO_NAME)):
            return d
    return None


def _load_vendor_lib():
    """Load the vendor library for this platform. Raises DriverError."""
    if _IS_MACOS:
        # EURECA ships Windows and Linux builds only - there is nothing to point
        # CLOUDS_E9U_LIB_DIR at, so say that instead of sending the operator off
        # to build the Linux .so. A remote detector still works from here.
        raise DriverError(
            "no native detector driver for macOS - EURECA ships a Windows DLL "
            "and a Linux .so only.\n"
            "The detector is on the Pi from here: run the flight app there "
            "with --bench-stream (or spectro.net_server) and start this app "
            "as `--net <pi-ip>`."
        )
    lib_dir = _resolve_lib_dir()
    if _IS_WINDOWS:
        if lib_dir is None:
            raise DriverError(
                f"vendor DLL {_DLL_NAME} not found.\n"
                f"Looked in $CLOUDS_E9U_DLL_DIR and "
                f"{os.path.join(_ROOT, 'vendor')}.\n"
                f"Drop {_DLL_NAME} (with its libgcc_s_seh-1 / libssp-0 / "
                f"libwinpthread-1 mingw runtime DLLs) into vendor/, or set "
                f"CLOUDS_E9U_DLL_DIR to the directory holding it."
            )
        path = os.path.join(lib_dir, _DLL_NAME)
        # mingw runtime deps live beside it, and a plain WinDLL() would not
        # find them - the failure reads as "the DLL is missing" either way.
        os.add_dll_directory(lib_dir)
        try:
            return ctypes.WinDLL(path)
        except OSError as exc:
            raise DriverError(
                f"vendor DLL {path} failed to load ({exc}).\n"
                f"Usually a missing mingw runtime beside it "
                f"(libgcc_s_seh-1.dll, libssp-0.dll, libwinpthread-1.dll) or "
                f"a 32-bit Python against this 64-bit DLL."
            ) from exc
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
        self._limits = dict(_FALLBACK_LIMITS)
        self._exposure_us = None        # what the camera's register actually holds
        self._frame_us = None
        self._last_read = None          # monotonic time the last frame was read out
        self._flush_mode = (os.environ.get(_FLUSH_ENV) or "").strip().lower()

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
            # timing: the per-camera limits set_times_us() clamps against, and the
            # registers that say what the camera is really doing (see set_times_us,
            # measured_exposure_us). Optional so an older library still drives.
            ("e9u_LSMD_minimum_exposure", (ctypes.c_uint,), ctypes.c_uint),
            ("e9u_LSMD_step_exposure", (ctypes.c_uint,), ctypes.c_uint),
            ("e9u_LSMD_minimum_frame", (ctypes.c_uint,), ctypes.c_uint),
            ("e9u_LSMD_step_frame", (ctypes.c_uint,), ctypes.c_uint),
            ("e9u_LSMD_get_reg32",
             (ctypes.c_uint, ctypes.c_uint, ctypes.c_uint), ctypes.c_uint),
            ("e9u_LSMD_diff32", (ctypes.c_uint, ctypes.c_uint), ctypes.c_uint),
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
        self._read_limits()
        # start_camera_async leaves exposure = frame = minimum_frame; record that
        # rather than guess, and treat the camera as idle since now.
        self._exposure_us = self._reg(_REG_CH0_EXP_TIME) or self._limits["min_frame"]
        self._frame_us = self._reg(_REG_CH0_FRAME_TIME) or self._limits["min_frame"]
        self._last_read = None
        return self._info

    def _read_limits(self) -> None:
        """Per-camera timing limits from the vendor type table (PRO: exposure
        min/step 10 us, frame min 3750 us / step 10 us)."""
        for key, name in (("min_exp", "e9u_LSMD_minimum_exposure"),
                          ("step_exp", "e9u_LSMD_step_exposure"),
                          ("min_frame", "e9u_LSMD_minimum_frame"),
                          ("step_frame", "e9u_LSMD_step_frame")):
            fn = getattr(self._lib, name, None)
            if fn is None:
                continue
            try:
                value = int(fn(self.cam))
            except Exception:  # noqa: BLE001 - a limit call is not worth a connect failure
                continue
            if value > 0:
                self._limits[key] = value

    def _reg(self, register: int, bank: int = _BANK_TX):
        """One camera register, or None if this library cannot read registers."""
        fn = getattr(self._lib, "e9u_LSMD_get_reg32", None) if self._lib else None
        if fn is None:
            return None
        try:
            return int(fn(self.cam, register, bank))
        except Exception:  # noqa: BLE001
            return None

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
        """Set the integration time, and a frame time that can hold it.

        The default frame time used to be the exposure itself, which the vendor
        then clamps: it floors the frame time to a `step_frame` multiple, raises
        it to `minimum_frame`, and finally clamps the *exposure* to no more than
        the frame time - so an exposure asked for in the same breath as its own
        frame time has no readout margin at all. Ask for `exposure + minimum
        frame` instead (minimum_frame is the readout the camera needs, 3750 us on
        the PRO), rounded up so the vendor's floor cannot cut it back under the
        exposure, and the exposure register keeps the value that was requested.

        Then spend up to `_SETTLE_MAX_FRAMES` frames waiting for the camera to
        report the new integration window on its own timestamps - the vendor's
        `wait_times_us()` does the same thing, because a timing change is not
        live on the next frame.
        """
        if self._lib is None:
            raise DriverError("set_times_us before connect()")
        lim = self._limits
        exp = max(int(lim["min_exp"]), _round_up(int(exposure_us), int(lim["step_exp"])))
        frame = exp + int(lim["min_frame"]) if frame_us is None else int(frame_us)
        frame = max(int(lim["min_frame"]), exp, _round_up(frame, int(lim["step_frame"])))
        self._lib.e9u_LSMD_set_times_us(self.cam, exp, frame)
        # what the camera holds, not what we asked for: the two differ whenever a
        # limit bit above was wrong, and everything downstream should see the truth
        self._exposure_us = self._reg(_REG_CH0_EXP_TIME) or exp
        self._frame_us = self._reg(_REG_CH0_FRAME_TIME) or frame
        self._settle()

    @property
    def exposure_us(self):
        """Integration time the camera's register holds, or None before connect."""
        return self._exposure_us

    def measured_exposure_us(self):
        """The camera's own timestamped integration window for the last frame.

        None if the library cannot read registers. This is the only honest answer
        to "did the integration time take effect", and it is measured by the
        camera, not inferred from the spectrum.
        """
        stop = self._reg(_REG_T_STAMP_EXP_STOP, _BANK_SH)
        start = self._reg(_REG_T_STAMP_EXP_START, _BANK_SH)
        diff = getattr(self._lib, "e9u_LSMD_diff32", None) if self._lib else None
        if stop is None or start is None or diff is None:
            return None
        try:
            return int(diff(stop, start))
        except Exception:  # noqa: BLE001
            return None

    def _settle(self) -> None:
        """Burn frames until the camera's measured exposure matches its register."""
        want = self._exposure_us
        if want is None or self.measured_exposure_us() is None:
            return                                  # no register access: nothing to wait on
        tol = max(int(self._limits["step_exp"]), 1)
        for _ in range(_SETTLE_MAX_FRAMES):
            if abs((self.measured_exposure_us() or 0) - want) <= tol:
                return
            self._next_frame()

    def _idle_flush_needed(self) -> bool:
        """Has the line been sitting un-clocked long enough to matter?"""
        if self._flush_mode == "0":
            return False
        if self._flush_mode == "always" or self._last_read is None:
            return True                             # first frame after connect: unknown history
        exposure_s = (self._exposure_us or 0) / 1e6
        gap_limit = max(_FLUSH_GAP_MIN_S, _FLUSH_GAP_FRACTION * exposure_s)
        return (time.monotonic() - self._last_read) > gap_limit

    def _next_frame(self) -> None:
        self._lib.e9u_LSMD_get_next_frame(self.cam)
        self._last_read = time.monotonic()

    def grab(self, discard: int = 0) -> np.ndarray:
        if self._ptr is None:
            raise DriverError("grab before connect()")
        if self._idle_flush_needed():
            discard = max(0, discard) + 1           # drop the frame that holds the idle
        for _ in range(max(0, discard)):
            self._next_frame()
        self._next_frame()
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
        self._last_read = None      # a reconnect inherits no frame history
