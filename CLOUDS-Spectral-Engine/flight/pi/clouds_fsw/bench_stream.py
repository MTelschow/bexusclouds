"""Optional bench frame stream served *by the flight app* (bench use only).

Why this exists: the vendor library owns the USB device exclusively, so the FSW
and a standalone ``spectro.net_server`` cannot both hold the spectrometer. That
forced an either/or - flight chain (FSW -> GSE dashboard) *or* the live bench
panel. This serves the frames the FSW has **already acquired**, so both run at
once from one process and one device owner:

    # Pi
    python -m clouds_fsw.main --no-uart --bench-stream

    # PC - both at the same time, same detector
    python -m clouds_ui --flight --experiment 192.168.100.10
    python -m clouds_ui --net 192.168.100.10

It never touches the driver: frames come from the acquisition thread's latest
sample and exposure changes are *requested*, then applied by that thread
(``SpectroSource.request_exposure_us``). The vendor library is not thread-safe,
so this is the only safe arrangement.

Consequences, deliberately:
  * The live view updates at the FSW's own cadence - ``sample_interval_s``,
    **1 Hz on the bench exactly as in flight**, never tuned up for bench use, so
    the tested configuration is the flown one. For a faster trace use the
    exclusive ``spectro.net_server`` instead of changing flight settings.
  * The exposure is the one setting a client can change, because the detector is
    physically shared. Each change is logged, and the configured flight
    ``exposure_us`` is **restored when the last client disconnects** so a bench
    session cannot leave the flight app on different settings. (Refusing the
    change outright is not an option: the panel calls ``set_times_us`` from a Qt
    slot without a guard, and PyQt5 aborts on an unhandled exception there.)
  * Off by default; enabled only by ``--bench-stream``.
"""
from __future__ import annotations

import socket
import socketserver
import threading

from spectro.net_protocol import (DEFAULT_PORT, ProtocolError, TAG_BYTES,
                                  read_request, send_error, send_json,
                                  send_response)

#: How long a ``grab`` waits for the acquisition thread to publish. It must
#: stay **below the client's socket timeout** (``NetDriver``: 10 s) or the
#: client gives up first and a stalled detector reports as a network fault -
#: "link failed during grab" - instead of as this server's own message, which
#: is the one that names the real problem. Well above the 1 Hz flight cadence,
#: so an ordinary sample never trips it.
_WAIT_TIMEOUT_S = 5.0


class FrameHub:
    """Latest acquired frame + a counter, so clients can wait for a *new* one.

    Without the wait a polling UI would spin on the same frame between
    samples; blocking until the next one paces the client to the FSW cadence.
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._frame = None
        self._exposure_us = 0
        self._n = 0

    def publish(self, counts, exposure_us: int) -> None:
        with self._cond:
            self._frame = counts
            self._exposure_us = int(exposure_us)
            self._n += 1
            self._cond.notify_all()

    def wait_for_new(self, since: int, timeout: float = _WAIT_TIMEOUT_S):
        """Block until a frame newer than ``since``; return
        ``(n, frame, exposure_us, fresh)``.

        ``fresh`` is False when the wait timed out, and then ``frame`` is the
        *old* one - the caller must not send it. That flag is in the tuple
        rather than left to the caller to infer from ``n``, because inferring
        it is exactly what the first version did not do: it returned the stale
        frame and the handler sent it as if it were new. Over this stream
        ``frame_counter`` is ``None``, so the panel's duplicate detection
        cannot catch that either - a stalled acquisition thread would show as
        a frozen trace that still looked live.
        """
        with self._cond:
            if self._n <= since:
                self._cond.wait_for(lambda: self._n > since, timeout=timeout)
            return self._n, self._frame, self._exposure_us, self._n > since


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        srv = self.server
        peer = f"{self.client_address[0]}:{self.client_address[1]}"
        srv.log("bench", f"stream client connected: {peer}")
        srv.clients.add(peer)
        served = 0
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
                if op == "identity":
                    info = srv.info_provider()
                    if info is None:
                        # No successful driver connect on this Pi yet
                        # (SpectroSource.info). Answering with an empty model
                        # and a default 2048 px let a panel show "connected"
                        # against an experiment that has no camera, and only
                        # the first grab said otherwise.
                        send_error(self.connection,
                                   "the flight app has no detector yet: no "
                                   "successful connect since it started "
                                   "(USB cable, or the vendor library)")
                        continue
                    send_json(self.connection, {
                        "model": getattr(info, "model", ""),
                        "serial": getattr(info, "serial", ""),
                        "com_port": getattr(info, "com_port", ""),
                        "pixels": getattr(info, "pixels", 2048),
                        "firmware": getattr(info, "firmware", ""),
                        "raw": getattr(info, "raw", ""),
                    })
                elif op == "grab":
                    # Passed, not defaulted: a default argument is bound
                    # at def time, so the tests could not shorten it.
                    n, frame, _exp, fresh = srv.hub.wait_for_new(
                        served, _WAIT_TIMEOUT_S)
                    if frame is None:
                        send_error(self.connection,
                                   "no frame acquired yet (spectrometer down?)")
                        continue
                    if not fresh:
                        # Never resend: a duplicate is indistinguishable from
                        # a live trace on the client (see wait_for_new).
                        send_error(self.connection,
                                   f"no new frame in {_WAIT_TIMEOUT_S:g} s - "
                                   f"the flight app's acquisition has stalled "
                                   f"(it retries; the last frame is held)")
                        continue
                    served = n
                    send_response(self.connection, TAG_BYTES, frame.tobytes())
                elif op == "set_times":
                    us = int(req["exposure_us"])
                    srv.exposure_setter(us)
                    srv.log("bench", f"exposure set to {us} us by {peer} "
                                     f"(shared detector: affects flight data)")
                    send_json(self.connection, {"ok": True})
                elif op in ("dark_value", "frame_counter"):
                    send_json(self.connection, {"value": None})
                else:
                    send_error(self.connection, f"unknown op {op!r}")
        except (ConnectionError, OSError) as exc:
            srv.log("bench", f"stream client {peer} dropped: {exc}")
        finally:
            srv.clients.discard(peer)
            srv.log("bench", f"stream client gone: {peer}")
            srv.restore_flight_exposure()


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, hub, info_provider, exposure_setter, log,
                 flight_exposure_us=None):
        self.hub = hub
        self.info_provider = info_provider
        self.exposure_setter = exposure_setter
        self.log = log
        self.flight_exposure_us = flight_exposure_us
        self.clients: set[str] = set()
        super().__init__(addr, _Handler)

    def restore_flight_exposure(self) -> None:
        """Put the configured flight exposure back once nobody is watching.

        The bench must not leave the flight app on different settings; only the
        last client out restores it, so two panels do not fight.
        """
        if self.clients or self.flight_exposure_us is None:
            return
        self.exposure_setter(self.flight_exposure_us)
        self.log("bench", f"last client gone: exposure restored to the "
                          f"configured {self.flight_exposure_us} us")


class BenchStream:
    """Lifecycle wrapper: ``publish()`` from the acquisition thread."""

    def __init__(self, info_provider, exposure_setter, log=None,
                 bind: str = "0.0.0.0", port: int = DEFAULT_PORT,
                 flight_exposure_us: int | None = None):
        self.hub = FrameHub()
        self._addr = (bind, int(port))
        self._info_provider = info_provider
        self._exposure_setter = exposure_setter
        self._log = log or (lambda *_: None)
        self._flight_exposure_us = flight_exposure_us
        self._srv: _Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def clients(self) -> int:
        return len(self._srv.clients) if self._srv else 0

    def publish(self, counts, exposure_us: int) -> None:
        self.hub.publish(counts, exposure_us)

    def start(self) -> None:
        self._srv = _Server(self._addr, self.hub, self._info_provider,
                            self._exposure_setter, self._log,
                            self._flight_exposure_us)
        self._thread = threading.Thread(target=self._srv.serve_forever,
                                        daemon=True, name="bench-stream")
        self._thread.start()
        host, port = self._srv.server_address[:2]
        self._log("bench", f"frame stream on {host}:{port} "
                           f"({socket.gethostname()})")

    @property
    def port(self) -> int:
        return self._srv.server_address[1] if self._srv else self._addr[1]

    def stop(self) -> None:
        if self._srv is not None:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
