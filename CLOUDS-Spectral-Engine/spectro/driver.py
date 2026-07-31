"""Hardware-agnostic spectrometer driver interface.

The UI talks only to ``SpectrometerDriver`` and never imports a concrete driver
directly - it asks ``open_driver(mock=..., kind=...)``. That keeps the UI
testable without hardware and lets future Ground Support Equipment (GSE) /
downlink consumers reuse the same interface.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass


class DriverError(RuntimeError):
    """Raised when the spectrometer cannot be reached or read."""


@dataclass
class DeviceInfo:
    model: str = ""
    serial: str = ""
    com_port: str = ""
    pixels: int = 2048
    firmware: str = ""
    raw: str = ""
    mock: bool = False

    def summary(self) -> str:
        tag = " [MOCK]" if self.mock else ""
        port = f"  {self.com_port}" if self.com_port else ""
        return f"{self.model or 'spectrometer'}{tag}  SN {self.serial or '?'}{port}  {self.pixels}px"


class SpectrometerDriver(ABC):
    """One Duo = one camera = one 2048-px readout carrying both fibre channels."""

    PIXELS = 2048

    @abstractmethod
    def connect(self) -> DeviceInfo:
        """Find + start the camera. Returns its identity. Raises DriverError."""

    @abstractmethod
    def set_times_us(self, exposure_us: int, frame_us: int | None = None) -> None:
        """Set integration (and frame) time in microseconds. Shared by both channels."""

    @abstractmethod
    def grab(self, discard: int = 0) -> "object":
        """Return the next full frame as a uint16 numpy array of length PIXELS.

        ``discard`` drops that many frames first (let new timing settle).
        """

    @abstractmethod
    def close(self) -> None:
        """Release the device. Safe to call more than once."""

    def dark_value(self):
        """On-chip optical-black level for the last frame, or None if unsupported."""
        return None

    def frame_counter(self):
        """Hardware frame counter (for drop/duplicate detection), or None."""
        return None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()
        return False


# "net" is not a hardware family: it forwards this same interface to a
# spectro.net_server on another machine (detector on the Pi, UI on the PC).
KINDS = ("std", "edu", "net")


def resolve_kind(kind: str | None = None) -> str:
    """``kind`` arg -> ``CLOUDS_SPECTRO_KIND`` env -> ``"std"``. Validated."""
    kind = (kind or os.environ.get("CLOUDS_SPECTRO_KIND") or "std").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"unknown spectrometer kind {kind!r}; expected one of {KINDS}")
    return kind


def open_driver(mock: bool = False, kind: str | None = None,
                **kwargs) -> SpectrometerDriver:
    """Factory: real EURECA driver, or a synthetic one for headless testing.

    ``kind`` picks the real hardware family - ``"std"`` (default) for the
    dual-channel Duo, ``"edu"`` for the single-channel e9u_LSMD_EDU board, or
    ``"net"`` for a detector attached to another machine running
    ``spectro.net_server`` (pass ``host=``, or set ``CLOUDS_SPECTRO_HOST``).
    Falls back to the ``CLOUDS_SPECTRO_KIND`` env var, then ``"std"``.

    Concrete drivers are imported lazily so that importing this module pulls in
    neither the vendor library (real) nor numpy until actually needed.
    """
    if mock:
        from .mock_driver import MockDriver
        return MockDriver(**kwargs)
    resolved = resolve_kind(kind)
    if resolved == "net":
        from .net_driver import NetDriver
        return NetDriver(**kwargs)
    if resolved == "edu":
        from .eureca_edu_driver import EurecaEduDriver
        return EurecaEduDriver(**kwargs)
    from .eureca_driver import EurecaDriver
    return EurecaDriver(**kwargs)
