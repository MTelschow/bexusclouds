"""The Pi's half of the RP2350 link: framing, ACK correlation, HK cache.

``UartLink`` moves bytes and frames; this is the CLOUDS-level conversation on
top of it, and the one place that knows what the Pi may conclude about the
MCU:

* **Commands are confirmed, not assumed.** Every command frame carries a
  sequence number and the MCU answers it with an ACK naming that number and
  its own verdict (accepted, refused in this state, not armed, bad
  parameter). ``send_command()`` waits for that ACK and returns it, so a
  ground operator learns what the *MCU* did rather than that the Pi managed
  to write to a UART. A missing ACK is a failure, not a success.

* **Housekeeping is decoded on the way past.** The relay to ground stays
  byte-identical (that is ``Downlink.relay``'s job); the copy kept here is
  what the ground interlock reads to answer "is this thing in flight?".

Nothing here can gate the experiment: the MCU sequences autonomously (S.7),
so every answer this class produces is reporting, never control.
"""
from __future__ import annotations

import collections
import threading
import time

from clouds_link import frames, hk
from clouds_link.frames import AckResult, Frame, PacketType

from .uart_link import UartLink


class _Pending:
    __slots__ = ("event", "result")

    def __init__(self):
        self.event = threading.Event()
        self.result: int | None = None


class McuLink:
    """``on_frame(Frame)`` receives everything except ACKs (which are
    answers to this class's own commands). It runs on the UART reader
    thread - keep it quick and exception-safe."""

    def __init__(self, transport, on_frame=None, ack_timeout_s: float = 1.0,
                 silent_s: float = 10.0, log=None):
        self.uart = UartLink(transport, on_frame=self._on_frame)
        self._on_frame_cb = on_frame
        self._ack_timeout_s = ack_timeout_s
        self._silent_s = silent_s
        self._log = log or (lambda *_: None)
        self._seq = frames.SeqCounter()
        self._pending: dict[int, _Pending] = {}
        # Sequence numbers sent without waiting (the heartbeat). The MCU acks
        # every command, so their ACKs arrive with no waiter and are expected -
        # logging them as unsolicited would bury the comms log in one line per
        # heartbeat and hide the late ACK that does mean something.
        self._unwatched: collections.deque = collections.deque(maxlen=16)
        self._pending_lock = threading.Lock()
        self._hk_lock = threading.Lock()
        self._last_hk: hk.Housekeeping | None = None
        self._last_hk_t: float = 0.0
        self.acks_missed = 0

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self.uart.start()

    def stop(self) -> None:
        self.uart.stop()
        with self._pending_lock:            # never leave a caller blocked
            pending = list(self._pending.values())
            self._pending.clear()
        for p in pending:
            p.event.set()

    # -- state ---------------------------------------------------------------

    def alive(self, within_s: float | None = None) -> bool:
        """True while the MCU has spoken recently (S.9 mirror)."""
        return self.uart.alive(self._silent_s if within_s is None else within_s)

    @property
    def last_rx(self) -> float:
        return self.uart.last_rx

    @property
    def last_hk(self) -> "hk.Housekeeping | None":
        with self._hk_lock:
            return self._last_hk

    @property
    def in_flight(self) -> bool:
        """True only on fresh housekeeping showing the MCU past STANDBY.

        The ground interlock (S.10) reads this, so every uncertainty resolves
        to False: no HK yet, stale HK, or a state at or before STANDBY all
        mean "treat this as on the ground".
        """
        with self._hk_lock:
            h, t = self._last_hk, self._last_hk_t
        if h is None or time.time() - t > self._silent_s:
            return False
        return hk.SeqState.ASCENT <= h.state <= hk.SeqState.MEASURE_2

    # -- sending -------------------------------------------------------------

    def send_command(self, cmd: int, key: int = 0, value: int = 0,
                     await_ack: bool = True) -> int:
        """Send one command; returns the MCU's AckResult.

        With ``await_ack`` false the frame is sent unconfirmed and the result
        is ``OK`` - used for the ground heartbeat, which is answered by the Pi
        itself and must not stall for a silent MCU.
        """
        seq = self._seq.next()
        frame = Frame(type=PacketType.CMD,
                      payload=frames.pack_cmd(cmd, key, value),
                      seq=seq).stamp()
        if not await_ack:
            with self._pending_lock:
                self._unwatched.append(seq)
            self.uart.send(frame)
            return AckResult.OK

        pending = _Pending()
        with self._pending_lock:
            self._pending[seq] = pending
        try:
            self.uart.send(frame)
            if not pending.event.wait(self._ack_timeout_s):
                self.acks_missed += 1
                self._log("mcu", f"no ACK for cmd={cmd} key={key} "
                                 f"seq={seq} within {self._ack_timeout_s}s")
                return AckResult.REJECTED
            if pending.result is None:      # link stopped under us
                return AckResult.REJECTED
            return pending.result
        finally:
            with self._pending_lock:
                self._pending.pop(seq, None)

    def send_timesync(self, t: float | None = None) -> None:
        """S.4 - and the beat the MCU's Pi-liveness monitor watches (M-13)."""
        self.uart.send(Frame(type=PacketType.TIMESYNC,
                             payload=frames.pack_timesync(
                                 time.time() if t is None else t),
                             seq=self._seq.next()).stamp())

    # -- receiving -----------------------------------------------------------

    def _on_frame(self, frame: Frame) -> None:
        if frame.type == PacketType.ACK:
            self._resolve_ack(frame)
            return
        if frame.type == PacketType.HK:
            try:
                decoded = hk.Housekeeping.unpack(frame.payload)
            except Exception:   # noqa: BLE001 - a short/odd HK must not stop the relay
                decoded = None
            if decoded is not None:
                with self._hk_lock:
                    self._last_hk = decoded
                    self._last_hk_t = time.time()
        if self._on_frame_cb is not None:
            self._on_frame_cb(frame)

    def _resolve_ack(self, frame: Frame) -> None:
        try:
            cmd_seq, cmd, result = frames.unpack_ack(frame.payload)
        except Exception:   # noqa: BLE001
            return
        with self._pending_lock:
            pending = self._pending.get(cmd_seq)
            expected = cmd_seq in self._unwatched
        if pending is None:
            if not expected:
                # Late ACK for a command that already timed out, or a repeat:
                # worth a line, it means the link is slower than the timeout.
                self._log("mcu", f"unsolicited ACK cmd={cmd} seq={cmd_seq} "
                                 f"result={result}")
            return
        pending.result = result
        pending.event.set()
