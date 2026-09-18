"""GSE command uplink (G-03): TCP client, ACK-checked.

**No interlock and no arm handshake (2026-09-18).** The ground interlock and
the flight-mode toggle that switched it off are gone, and so is the
ARM→RELEASE two-step: the operator's `START` is what begins the experiment,
and from then on every command goes out as sent and is answered by the MCU's
own verdict. Nothing is refused on the laptop any more - a command that does
not reach the Pi raises `CommandError`, which is a link failure, not a
policy.
"""
from __future__ import annotations

import socket
import threading
import time

from clouds_link import frames
from clouds_link.commands import (HEARTBEAT_INTERVAL_S, Command, DisperseKey,
                                  Param)
from clouds_link.frames import AckResult, Frame, PacketType, SeqCounter


class CommandError(RuntimeError):
    """Sent but not accepted (NACK, timeout, or link failure)."""


class Commander:
    def __init__(self, host: str, port: int, timeout: float = 3.0,
                 log=None, on_result=None):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._log = log or (lambda *_: None)
        #: Called with one dict per command attempt - accepted, refused or
        #: never sent (`SessionLog.log_command`). The uplink is the half of
        #: the session the downlink cannot record: a command that never
        #: reached the Pi leaves no trace on the far end. Never allowed to
        #: break a command - a session log is evidence, not a dependency.
        self._on_result = on_result or (lambda _rec: None)
        self._seq = SeqCounter()
        self._lock = threading.RLock()   # reentrant: _transact -> _disconnect, both lock
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        self._hb_stop = threading.Event()
        self._hb_thread: threading.Thread | None = None
        self.acks_ok = 0
        self.acks_failed = 0
        # Wire counters for the traffic indicator (clouds_ui/traffic.py). The
        # uplink is this socket's tx: commands and the PING heartbeat, which
        # is the only thing on it when nobody is commanding. Its rx (ACKs)
        # is counted separately - it arrives on the uplink's own TCP
        # connection, not on the UDP downlink, and the two must not be added
        # up into one number that matches neither.
        self.tx_bytes = 0
        self.tx_frames = 0
        self.rx_bytes = 0
        self.last_tx_time: float = 0.0
        self.last_rx_time: float = 0.0
        self.last_rtt_s: float | None = None
        self.connected = False
        self._connect_once()   # best-effort - a down Pi must not stop the GSE from starting

    @property
    def peer(self) -> str:
        """``host:port`` of the Pi command server - what the traffic
        indicator names as the far end of the link."""
        return f"{self._host}:{self._port}"

    # -- public API ----------------------------------------------------------

    def send(self, cmd: Command, key: int = 0, value: int = 0) -> AckResult:
        """Send one command and wait for its ACK. Raises on link failure."""
        return self._transact(cmd, key, value)

    def release(self, valve: int) -> AckResult:
        """One RELEASE, sent as it stands - no ARM in front of it."""
        if valve not in (1, 2):
            raise ValueError("valve must be 1 or 2")
        return self._transact(Command.RELEASE, key=valve)

    def set_param(self, key: int, value: int) -> AckResult:
        return self._transact(Command.SET_PARAM, key=key, value=value)

    def membrane_hz(self, hz: float) -> AckResult:
        """Set the membrane drive frequency in hertz, tenths allowed
        (0.1..400). The wire carries millihertz (SET_PARAM MEMBRANE_MHZ, an
        int32), so this is the one place the conversion lives; the MCU
        reads it when the next drive starts."""
        mhz = int(round(hz * 1000))
        if not 100 <= mhz <= 400000:
            raise ValueError("membrane frequency must be 0.1..400 Hz")
        return self.set_param(int(Param.MEMBRANE_MHZ), mhz)

    def membrane(self, duty_pct: int) -> AckResult:
        """Drive the membrane push-pull solenoid; 0 stops it (M-07).

        The drive is not irreversible and stops on the next call, and
        exercising it on the bench is what the control is for (see
        MANUAL_ACTUATORS). Frequency is a separate knob - ``membrane_hz()`` /
        SET_PARAM MEMBRANE_MHZ.
        """
        if not 0 <= duty_pct <= 100:
            raise ValueError("membrane duty must be 0..100 percent")
        return self._transact(Command.MEMBRANE, key=duty_pct)

    def disperse(self) -> AckResult:
        """One pulse of the CaCO3 dispersion motor (M-07).

        The drive is timed on the MCU (VALVE_PULSE_MS, 5 s); ``disperse_stop``
        cuts it short. Watch ``valve_status`` for the line actually being
        energized. Refused (REJECTED) while ``disperse_run`` has the motor on.
        """
        return self._transact(Command.DISPERSE, key=int(DisperseKey.PULSE))

    def disperse_run(self) -> AckResult:
        """Hold the dispersion motor on until ``disperse_stop`` (M-07).

        Speed is ``Param.DISPERSE_DUTY``; a SET_PARAM of it while the motor
        runs takes effect at once on the MCU. Like the membrane drive this is
        a state, not a pulse: it is not armed or interlocked, and the MCU
        refuses it in TERMINATION/SAFE. Note that nothing on the MCU times it
        out - a run lasts until Stop, an abort, or a reset.
        """
        return self._transact(Command.DISPERSE, key=int(DisperseKey.RUN))

    def disperse_stop(self) -> AckResult:
        """Stop the dispersion motor - ends a run and cuts a pulse short.
        Always accepted by the MCU (it can only de-energize)."""
        return self._transact(Command.DISPERSE, key=int(DisperseKey.STOP))

    def ping(self, origin: str = "operator") -> AckResult:
        """``origin`` separates the 5 s heartbeat from an operator's own PING
        in the session log - one is the link proving itself, the other is
        somebody asking."""
        return self._transact(Command.PING, origin=origin)

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
        with self._lock:
            self._disconnect()

    # -- internals -----------------------------------------------------------

    def _connect_once(self) -> None:
        """One connect attempt. Never raises - a down Pi must not stop the GSE
        from starting, and the heartbeat calls this on the same retry cadence
        whenever the link is down."""
        with self._lock:
            if self.connected:
                return
            try:
                sock = socket.create_connection((self._host, self._port),
                                                timeout=self._timeout)
            except OSError as e:
                self._log(f"command link: cannot reach "
                          f"{self._host}:{self._port} ({e})")
                return
            sock.settimeout(self._timeout)
            self._sock = sock
            self._buf = bytearray()
            self.connected = True
            self._log(f"command link: connected to {self._host}:{self._port}")

    def _disconnect(self) -> None:
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
            if self.connected:
                self.connected = False
                self._log("command link: lost - retrying")

    def _heartbeat(self) -> None:
        """PING every HEARTBEAT_INTERVAL_S while connected; the same cadence
        drives reconnect attempts while the link is down."""
        while not self._hb_stop.wait(HEARTBEAT_INTERVAL_S):
            if not self.connected:
                self._connect_once()
                continue
            try:
                self.ping(origin="heartbeat")
            except (CommandError, OSError):
                pass   # _transact already disconnected us; next tick retries

    def _record(self, cmd, key: int, value: int, *, result=None,
                result_name: str = "", seq=None, rtt_ms=None,
                origin: str = "operator", note: str = "") -> None:
        """Hand one command attempt to ``on_result``, whatever became of it.

        Swallows anything the sink raises: a session log that fails must not
        turn an accepted command into an exception at the caller, which
        would read as the command having failed.
        """
        try:
            self._on_result({
                "send_t": time.time(), "origin": origin,
                "cmd": int(cmd), "cmd_name": Command(cmd).name,
                "key": key, "value": value,
                "seq": "" if seq is None else seq,
                "result": "" if result is None else int(result),
                "result_name": result_name,
                "rtt_ms": "" if rtt_ms is None else round(rtt_ms, 1),
                "note": note})
        except Exception:      # noqa: BLE001 - logging is never load-bearing
            pass

    def _transact(self, cmd: Command, key: int = 0, value: int = 0,
                  origin: str = "operator") -> AckResult:
        with self._lock:   # one in-flight command at a time
            if not self.connected:
                self._record(cmd, key, value, result_name="NO_LINK",
                             origin=origin, note="not connected, never sent")
                raise CommandError("not connected to the Pi command server")
            seq = self._seq.next()
            f = Frame(type=PacketType.CMD,
                      payload=frames.pack_cmd(int(cmd), key, value),
                      seq=seq).stamp()
            t0 = time.time()
            try:
                wire = f.encode()
                self._sock.sendall(wire)
                self.tx_bytes += len(wire)
                self.tx_frames += 1
                self.last_tx_time = time.time()
                ack = self._wait_ack(seq)
            except OSError as e:
                self.acks_failed += 1
                self._record(cmd, key, value, seq=seq, result_name="NO_LINK",
                             origin=origin, rtt_ms=(time.time() - t0) * 1000,
                             note=f"link failure: {e}")
                self._disconnect()
                raise CommandError(f"link failure sending {cmd.name}: {e}") \
                    from e
            except CommandError as e:
                # Sent, nothing came back. The command may well have executed
                # (S.8: a missing ACK is a rejection to the operator, but the
                # wire does not say which), so the session has to keep it.
                self.acks_failed += 1
                self._record(cmd, key, value, seq=seq, result_name="NO_ACK",
                             origin=origin, rtt_ms=(time.time() - t0) * 1000,
                             note=str(e))
                raise
            self.last_rtt_s = time.time() - t0
            self._log(f"{cmd.name} key={key} value={value} -> "
                      f"{AckResult(ack).name} ({self.last_rtt_s * 1000:.0f} ms)")
            if ack == AckResult.OK:
                self.acks_ok += 1
            else:
                self.acks_failed += 1
            self._record(cmd, key, value, seq=seq, result=ack,
                         result_name=AckResult(ack).name, origin=origin,
                         rtt_ms=self.last_rtt_s * 1000)
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
            self.rx_bytes += len(chunk)
            self.last_rx_time = time.time()
            self._buf.extend(chunk)
        return None
