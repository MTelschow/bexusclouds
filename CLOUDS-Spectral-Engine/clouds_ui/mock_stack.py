"""The whole flight chain in this process, for ``clouds_ui --mock``.

``--mock`` has to mean *no hardware anywhere*, not "no detector": the flight
half of the window is HK, events, quick-look and commanding, and all four
come from the Pi. So the mock starts the real flight app - the same
``clouds_fsw.FlightApp``, with a synthetic spectrometer - against a
``SimMcu`` on the far end of its UART pipe, and points the window's receiver
and commander at it over loopback.

Nothing here is a second implementation of the protocol: frames are built by
the real FSW and the sim MCU, travel over real UDP and TCP sockets, and are
decoded by the real GSE receiver. What is fake is exactly two things - the
light on the detector and the silicon on the UART.

Ports are ephemeral (`port=0`) and bound to 127.0.0.1: a mock session must
not collide with a real GSE already listening on UDP 4000, and must not
accept a command from anything off this machine. Data goes to a temporary
directory that is removed on ``stop()``; a mock run leaves no flight data
behind to be mistaken for a real one later.
"""
from __future__ import annotations

import shutil
import tempfile
import threading


class MockStack:
    """FSW (mock spectrometer) + simulated RP2350, on loopback.

    ``ground_port`` is the UDP port the window's receiver already bound, so
    the downlink lands where the window is listening. ``cmd_port`` is
    whatever the command server got; read it after ``start()``.
    """

    def __init__(self, ground_port: int, *, log=print, imu: bool = False):
        self._log = log or (lambda *_: None)
        self._ground_port = ground_port
        self._imu = imu
        self._data_dir = tempfile.mkdtemp(prefix="clouds-mock-")
        self.app = None
        self.mcu = None
        self._thread: threading.Thread | None = None

    @property
    def cmd_port(self) -> int:
        return self.app.cmd_server.port

    def start(self) -> None:
        # Imported here: --mock is the only caller, and the UI must not need
        # clouds_fsw on the path for a real session.
        from clouds_fsw.config import FswConfig
        from clouds_fsw.main import FlightApp
        from clouds_fsw.sim_mcu import SimMcu
        from clouds_fsw.uart_link import PipeTransport

        near, far = PipeTransport.pair()
        cfg = FswConfig(
            ground_host="127.0.0.1", ground_port=self._ground_port,
            cmd_bind="127.0.0.1", cmd_port=0,
            data_dir=self._data_dir, mock=True)
        self.app = FlightApp(cfg, transport=near)
        self.mcu = SimMcu(far, imu=self._imu, log=lambda *_: None)

        self.mcu.start()
        self._thread = threading.Thread(target=self.app.run, daemon=True,
                                        name="mock-fsw")
        self._thread.start()
        self._log(f"[CLOUDS] mock flight chain up: downlink -> 127.0.0.1:"
                  f"{self._ground_port}, commands on 127.0.0.1:{self.cmd_port}")
        self._log(f"[CLOUDS] mock data (discarded on exit): {self._data_dir}")

    def stop(self) -> None:
        if self.mcu is not None:
            self.mcu.stop()
        if self.app is not None:
            self.app.stop()
            if self._thread is not None:
                self._thread.join(timeout=3.0)
            self.app.shutdown()
        self.mcu = self.app = self._thread = None
        shutil.rmtree(self._data_dir, ignore_errors=True)
