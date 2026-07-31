"""systemd watchdog integration (S.9): sd_notify over NOTIFY_SOCKET.

Zero dependencies - speaks the trivial datagram protocol directly. On
Windows or outside systemd it degrades to a no-op, so tests and bench runs
need no special handling. Pair with ``WatchdogSec=15`` in the unit file and
the kernel/hardware watchdog via ``RuntimeWatchdogSec=`` in system.conf.
"""
from __future__ import annotations

import os
import socket


class SystemdWatchdog:
    def __init__(self):
        self._addr = os.environ.get("NOTIFY_SOCKET")
        self._sock = None
        if self._addr and hasattr(socket, "AF_UNIX"):
            if self._addr.startswith("@"):   # abstract namespace
                self._addr = "\0" + self._addr[1:]
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

    @property
    def active(self) -> bool:
        return self._sock is not None

    def _notify(self, msg: str) -> None:
        if self._sock is not None:
            try:
                self._sock.sendto(msg.encode(), self._addr)
            except OSError:
                pass

    def ready(self) -> None:
        self._notify("READY=1")

    def kick(self) -> None:
        self._notify("WATCHDOG=1")

    def stopping(self) -> None:
        self._notify("STOPPING=1")
