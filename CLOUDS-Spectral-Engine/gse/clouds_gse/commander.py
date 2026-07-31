"""GSE command uplink (G-03, G-04): TCP client, ACK-checked, interlocked.

Ground interlock (S.10): while ``flight_mode`` is False - the default -
commands in GROUND_INTERLOCKED (RELEASE, START) are refused locally with
``InterlockError`` and never leave the laptop. Enabling flight mode is an
explicit operator action (``--flight-mode`` or the GUI toggle).

``release(n)`` performs the full arm/execute handshake (S.8) against the
Pi command server, which is the authoritative enforcer.
"""
from __future__ import annotations

import socket
import threading
import time

from clouds_link import frames
from clouds_link.commands import (GROUND_INTERLOCKED, HEARTBEAT_INTERVAL_S,
                                  Command)
from clouds_link.frames import AckResult, Frame, PacketType, SeqCounter


class InterlockError(RuntimeError):
    """Refused by the GSE ground interlock (S.10) - not sent."""


class CommandError(RuntimeError):
    """Sent but not accepted (NACK, timeout, or link failure)."""


class Commander:
    def __init__(self, host: str, port: int, flight_mode: bool = False,
                 timeout: float = 3.0, log=None):
        self.flight_mode = flight_mode
        self._timeout = timeout
        self._log = log or (lambda *_: None)
        self._seq = SeqCounter()
        self._lock = threading.Lock()
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        self._buf = bytearray()
        self._hb_stop = threading.Event()
        self._hb_thread: threading.Thread | None = None
        self.acks_ok = 0
        self.acks_failed = 0
        self.last_rtt_s: float | None = None

    # -- public API ----------------------------------------------------------

    def send(self, cmd: Command, key: int = 0, value: int = 0) -> AckResult:
        """Send one command and wait for its ACK. Raises on interlock/link."""
        if cmd in GROUND_INTERLOCKED and not self.flight_mode:
            self._log(f"INTERLOCK refused {cmd.name}")
            raise InterlockError(
                f"{cmd.name} is interlocked on ground (S.10); "
                "enable flight mode to send it")
        return self._transact(cmd, key, value)

    def release(self, valve: int) -> AckResult:
        """Arm/execute handshake for a particle release (S.8)."""
        if valve not in (1, 2):
            raise ValueError("valve must be 1 or 2")
        if not self.flight_mode:
            raise InterlockError("RELEASE is interlocked on ground (S.10)")
        r = self._transact(Command.ARM, key=int(Command.RELEASE))
        if r != AckResult.OK:
            raise CommandError(f"ARM refused: {AckResult(r).name}")
        return self._transact(Command.RELEASE, key=valve)

    def set_param(self, key: int, value: int) -> AckResult:
        return self._transact(Command.SET_PARAM, key=key, value=value)

    def ping(self) -> AckResult:
        return self._transact(Command.PING)

    def start_heartbeat(self) -> None:
        """PING every HEARTBEAT_INTERVAL_S - this is the signal the MCU's
        link-loss latch (O.2) watches through the Pi."""
        self._hb_thread = threading.Thread(target=self._heartbeat,
                                           daemon=True, name="gse-heartbeat")
        self._hb_thread.start()

    def close(self) -> None:
        self._hb_stop.set()
        if self._hb_thread:
            self._hb_thread.join(timeout=2.0)
        try:
            self._sock.close()
        except OSError:
            pass

    # -- internals -----------------------------------------------------------

    def _heartbeat(self) -> None:
        while not self._hb_stop.wait(HEARTBEAT_INTERVAL_S):
            try:
                self.ping()
            except (CommandError, OSError):
                pass   # keep trying; the operator sees hk_age_s rise

    def _transact(self, cmd: Command, key: int = 0, value: int = 0) -> AckResult:
        with self._lock:   # one in-flight command at a time
            seq = self._seq.next()
            f = Frame(type=PacketType.CMD,
                      payload=frames.pack_cmd(int(cmd), key, value),
                      seq=seq).stamp()
            t0 = time.time()
            try:
                self._sock.sendall(f.encode())
                ack = self._wait_ack(seq)
            except OSError as e:
                self.acks_failed += 1
                raise CommandError(f"link failure sending {cmd.name}: {e}") \
                    from e
            self.last_rtt_s = time.time() - t0
            self._log(f"{cmd.name} key={key} value={value} -> "
                      f"{AckResult(ack).name} ({self.last_rtt_s * 1000:.0f} ms)")
            if ack == AckResult.OK:
                self.acks_ok += 1
            else:
                self.acks_failed += 1
            return AckResult(ack)

    def _wait_ack(self, cmd_seq: int) -> int:
        deadline = time.time() + self._timeout
        while time.time() < deadline:
            frame = self._read_frame(deadline)
            if frame is None:
                break
            if frame.type != PacketType.ACK:
                continue
            seq, _cmd, result = frames.unpack_ack(frame.payload)
            if seq == cmd_seq:
                return result
        raise CommandError(f"no ACK for command seq {cmd_seq}")

    def _read_frame(self, deadline: float):
        while time.time() < deadline:
            frame, used = frames.try_parse_stream(bytes(self._buf))
            if used:
                del self._buf[:used]
                if frame is not None:
                    return frame
                continue
            try:
                chunk = self._sock.recv(4096)
            except TimeoutError:
                continue
            if not chunk:
                return None
            self._buf.extend(chunk)
        return None
