"""SpectrometerDriver backed by a remote ``spectro.net_server`` over TCP.

Lets the Qt bench panel run on the PC while the detector hangs off the Pi:

    python clouds_spectral.py --net 192.168.100.10

The UI cannot tell the difference - it still gets full 2048-px uint16 frames
from ``grab()``. Frames arrive as raw little-endian uint16, the same scale the
local driver produces (the Linux count shift is applied server-side, see
docs/CALIBRATION.md).
"""
from __future__ import annotations

import json
import os
import socket

import numpy as np

from .driver import DeviceInfo, DriverError, SpectrometerDriver
from .net_protocol import (DEFAULT_PORT, ProtocolError, TAG_BYTES, TAG_ERROR,
                           TAG_JSON, recv_response, send_request)

_HOST_ENV = "CLOUDS_SPECTRO_HOST"


def resolve_host(host: str | None = None) -> tuple[str, int]:
    """``host[:port]`` arg -> ``CLOUDS_SPECTRO_HOST`` env. Raises if unset."""
    spec = host or os.environ.get(_HOST_ENV) or ""
    spec = spec.strip()
    if not spec:
        raise DriverError(
            "no spectrometer host given: pass --net HOST[:PORT] or set "
            f"{_HOST_ENV}."
        )
    if spec.count(":") == 1:
        h, _, p = spec.partition(":")
        try:
            return h, int(p)
        except ValueError as exc:
            raise DriverError(f"bad port in {spec!r}") from exc
    return spec, DEFAULT_PORT


class NetDriver(SpectrometerDriver):
    def __init__(self, host: str | None = None, timeout: float = 10.0,
                 **_kwargs):
        # Construction stays side-effect-free and never validates the target -
        # same contract as the hardware drivers, where reaching the device is
        # connect()'s job (tests/test_driver_factory.py).
        self._host_spec = host
        self.host, self.port = "", DEFAULT_PORT
        self.timeout = float(timeout)
        self._sock: socket.socket | None = None
        self._info: DeviceInfo | None = None

    # ----------------------------------------------------------------- plumbing
    def _request(self, obj: dict) -> tuple[bytes, bytes]:
        if self._sock is None:
            raise DriverError("request before connect()")
        try:
            send_request(self._sock, obj)
            tag, body = recv_response(self._sock)
        except (OSError, ProtocolError) as exc:
            raise DriverError(
                f"{self.host}:{self.port} link failed during {obj.get('op')}: "
                f"{exc}"
            ) from exc
        if tag == TAG_ERROR:
            try:
                msg = json.loads(body).get("error", body.decode("utf-8", "replace"))
            except ValueError:
                msg = body.decode("utf-8", "replace")
            raise DriverError(f"remote: {msg}")
        return tag, body

    def _json(self, obj: dict) -> dict:
        tag, body = self._request(obj)
        if tag != TAG_JSON:
            raise DriverError(f"expected JSON response, got tag {tag!r}")
        return json.loads(body)

    # ------------------------------------------------------------------- driver
    def connect(self) -> DeviceInfo:
        self.host, self.port = resolve_host(self._host_spec)
        try:
            self._sock = socket.create_connection((self.host, self.port),
                                                  timeout=self.timeout)
        except OSError as exc:
            raise DriverError(
                f"cannot reach spectrometer server at {self.host}:{self.port} "
                f"({exc}). Is `python3 -m spectro.net_server` running there, "
                f"and is the FSW stopped so the USB device is free?"
            ) from exc
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        d = self._json({"op": "identity"})
        self._info = DeviceInfo(
            model=d.get("model", ""), serial=d.get("serial", ""),
            com_port=d.get("com_port", ""),
            pixels=int(d.get("pixels") or self.PIXELS),
            firmware=d.get("firmware", ""), raw=d.get("raw", ""),
        )
        return self._info

    def set_times_us(self, exposure_us: int, frame_us: int | None = None) -> None:
        self._json({"op": "set_times", "exposure_us": int(exposure_us),
                    "frame_us": None if frame_us is None else int(frame_us)})

    def grab(self, discard: int = 0) -> np.ndarray:
        tag, body = self._request({"op": "grab", "discard": int(discard)})
        if tag != TAG_BYTES:
            raise DriverError(f"expected a frame, got tag {tag!r}")
        expect = self.PIXELS * 2
        if len(body) != expect:
            raise DriverError(f"short frame: {len(body)} bytes, want {expect}")
        return np.frombuffer(body, dtype="<u2").copy()

    def dark_value(self):
        try:
            return self._json({"op": "dark_value"}).get("value")
        except DriverError:
            return None

    def frame_counter(self):
        try:
            return self._json({"op": "frame_counter"}).get("value")
        except DriverError:
            return None

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
