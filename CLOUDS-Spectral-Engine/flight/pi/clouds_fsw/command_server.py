"""TCP command uplink (S.8): framed commands, mandatory ACK, arm/execute.

Frames are self-delimiting on the TCP stream (header carries the payload
length). The server is authoritative for the arm/execute rule: RELEASE
without a preceding ARM(RELEASE) within ARM_WINDOW_S is refused with
AckResult.NOT_ARMED and never reaches the MCU. Every valid command
(including PING) is forwarded to the MCU - the MCU's own link-loss latch
(O.2) keys off command traffic, so a dead Pi and a dead E-Link look the
same to it, which is exactly the fail-safe intent.
"""
from __future__ import annotations

import socketserver
import threading
import time

from clouds_link import frames
from clouds_link.commands import ARM_WINDOW_S, ARMED_COMMANDS, Command


class CommandState:
    """Shared uplink state: heartbeat + one-shot arm latch."""

    def __init__(self):
        self.lock = threading.Lock()
        self.last_heartbeat = 0.0
        self._armed_cmd: int | None = None
        self._armed_until = 0.0

    def arm(self, cmd: int, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self.lock:
            self._armed_cmd = cmd
            self._armed_until = now + ARM_WINDOW_S

    def consume_arm(self, cmd: int, now: float | None = None) -> bool:
        """True if ``cmd`` is armed and inside the window; clears the latch
        either way (one ARM authorises exactly one execute)."""
        now = time.time() if now is None else now
        with self.lock:
            ok = self._armed_cmd == cmd and now <= self._armed_until
            self._armed_cmd = None
            return ok

    def heartbeat(self, now: float | None = None) -> None:
        with self.lock:
            self.last_heartbeat = time.time() if now is None else now


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:  # one connection = one GSE session
        srv: CommandServer = self.server.owner  # type: ignore[attr-defined]
        buf = bytearray()
        self.request.settimeout(1.0)
        while not srv.stopping.is_set():
            try:
                chunk = self.request.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                return
            if not chunk:
                return
            buf.extend(chunk)
            while True:
                frame, used = frames.try_parse_stream(bytes(buf))
                if used == 0:
                    break
                del buf[:used]
                if frame is not None:
                    reply = srv.handle_command(frame)
                    try:
                        self.request.sendall(reply.encode())
                    except OSError:
                        return


class CommandServer:
    """``forward(cmd, key, value)`` sends the command on to the MCU;
    ``on_status_req()`` triggers an immediate PISTATUS downlink."""

    def __init__(self, bind: str, port: int, forward, state: CommandState,
                 on_status_req=None, log=None):
        self._forward = forward
        self._on_status_req = on_status_req
        self._log = log or (lambda *_: None)
        self.state = state
        self.stopping = threading.Event()
        self._seq = frames.SeqCounter()

        class _Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = _Server((bind, port), _Handler)
        self._server.owner = self
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True, name="cmd-server")
        self._thread.start()

    def stop(self) -> None:
        self.stopping.set()
        # BaseServer.shutdown() waits for serve_forever() to exit, and blocks
        # forever if it never ran: an error path unwinding between __init__ and
        # start() would hang the app inside shutdown() instead of exiting. Only
        # stop a loop that is really running; always release the socket.
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=2.0)
            self._thread = None
        self._server.server_close()

    # -- command policy ------------------------------------------------------

    def handle_command(self, frame: frames.Frame) -> frames.Frame:
        try:
            cmd, key, value = frames.unpack_cmd(frame.payload)
        except Exception:  # noqa: BLE001
            return self._ack(frame.seq, 0xFF, frames.AckResult.INVALID)

        name = Command(cmd).name if cmd in Command._value2member_map_ else hex(cmd)
        self._log("up", f"cmd={name} key={key} value={value}")

        if cmd == Command.PING:
            self.state.heartbeat()
            self._forward(cmd, key, value)   # MCU link-ok keys off traffic
            return self._ack(frame.seq, cmd, frames.AckResult.OK)

        if cmd == Command.ARM:
            if key not in {int(c) for c in ARMED_COMMANDS}:
                return self._ack(frame.seq, cmd, frames.AckResult.INVALID)
            self.state.arm(key)
            return self._ack(frame.seq, cmd, frames.AckResult.OK)

        if cmd in {int(c) for c in ARMED_COMMANDS}:
            if not self.state.consume_arm(cmd):
                return self._ack(frame.seq, cmd, frames.AckResult.NOT_ARMED)

        if cmd == Command.STATUS_REQ and self._on_status_req is not None:
            self._on_status_req()
            return self._ack(frame.seq, cmd, frames.AckResult.OK)

        try:
            self._forward(cmd, key, value)
        except Exception:  # noqa: BLE001 - MCU link down
            return self._ack(frame.seq, cmd, frames.AckResult.REJECTED)
        return self._ack(frame.seq, cmd, frames.AckResult.OK)

    def _ack(self, cmd_seq: int, cmd: int, result: int) -> frames.Frame:
        f = frames.Frame(type=frames.PacketType.ACK,
                         payload=frames.pack_ack(cmd_seq, cmd, result),
                         seq=self._seq.next())
        return f.stamp()
