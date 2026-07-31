"""Serve a locally attached spectrometer over TCP (bench tool, runs on the Pi).

The CLOUDS bench panel (``clouds_spectral.py``) was written against a
spectrometer on the same machine. With the detector on the flight Pi, run this
there and point the panel at it:

    # Pi  (spectrometer on USB)
    PYTHONPATH=/opt/clouds python3 -m spectro.net_server

    # PC  (Qt panel, full 2048-px live view)
    python clouds_spectral.py --net 192.168.100.10

Every ``SpectrometerDriver`` call becomes one request/response, so the panel's
grab loop behaves as it does locally, only with a <1 ms cable in the middle.

This is NOT the flight downlink. FSW-PI's quicklook is binned and rate-limited
to the E-Link budget (O.4); this ships whole frames and assumes a direct cable.
The vendor library owns the USB device exclusively, so stop the FSW before
running this - both cannot hold the detector at once.
"""
from __future__ import annotations

import argparse
import socket
import socketserver
import sys

from .driver import DriverError, open_driver
from .net_protocol import (DEFAULT_PORT, ProtocolError, read_request,
                           send_error, send_json, send_response, TAG_BYTES)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        drv = self.server.driver
        peer = f"{self.client_address[0]}:{self.client_address[1]}"
        print(f"[net_server] client connected: {peer}", flush=True)
        try:
            while True:
                try:
                    req = read_request(self.rfile)
                except ProtocolError as exc:
                    send_error(self.connection, str(exc))
                    break
                if req is None:
                    break
                op = req.get("op")
                try:
                    if op == "identity":
                        info = self.server.info
                        send_json(self.connection, {
                            "model": info.model, "serial": info.serial,
                            "com_port": info.com_port, "pixels": info.pixels,
                            "firmware": info.firmware, "raw": info.raw,
                        })
                    elif op == "set_times":
                        drv.set_times_us(int(req["exposure_us"]),
                                         req.get("frame_us"))
                        send_json(self.connection, {"ok": True})
                    elif op == "grab":
                        frame = drv.grab(discard=int(req.get("discard", 0)))
                        send_response(self.connection, TAG_BYTES,
                                      frame.tobytes())
                    elif op == "dark_value":
                        send_json(self.connection, {"value": drv.dark_value()})
                    elif op == "frame_counter":
                        send_json(self.connection,
                                  {"value": drv.frame_counter()})
                    else:
                        send_error(self.connection, f"unknown op {op!r}")
                except (DriverError, KeyError, TypeError, ValueError) as exc:
                    # one bad call must not drop the session
                    send_error(self.connection, f"{type(exc).__name__}: {exc}")
        except (ConnectionError, OSError) as exc:
            print(f"[net_server] {peer} dropped: {exc}", flush=True)
        finally:
            print(f"[net_server] client gone: {peer}", flush=True)


class _Server(socketserver.TCPServer):
    allow_reuse_address = True
    # one detector, one owner: serialise clients rather than corrupt the stream
    request_queue_size = 1

    def __init__(self, addr, driver, info):
        self.driver = driver
        self.info = info
        super().__init__(addr, _Handler)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--kind", default=None, help="std (default) or edu")
    ap.add_argument("--mock", action="store_true",
                    help="serve the synthetic driver (no hardware)")
    ap.add_argument("--exposure-us", type=int, default=100_000)
    args = ap.parse_args(argv)

    drv = open_driver(mock=args.mock, kind=args.kind)
    try:
        info = drv.connect()
    except DriverError as exc:
        print(f"[net_server] connect failed: {exc}", file=sys.stderr)
        return 1
    drv.set_times_us(args.exposure_us)
    print(f"[net_server] {info.summary()}", flush=True)

    srv = _Server((args.bind, args.port), drv, info)
    host = socket.gethostname()
    print(f"[net_server] serving on {args.bind}:{args.port} ({host})",
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        drv.close()
        print("[net_server] stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
