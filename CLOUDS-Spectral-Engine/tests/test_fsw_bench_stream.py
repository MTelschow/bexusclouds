"""FSW bench frame stream: serves already-acquired frames, off by default.

Covers the invariant that makes it safe: the stream never touches the driver -
frames come from the acquisition callback and exposure changes are parked for
the acquisition thread to apply.
"""
import numpy as np
import pytest

from clouds_fsw.bench_stream import BenchStream, FrameHub
from spectro.driver import DeviceInfo
from spectro.net_driver import NetDriver


@pytest.fixture
def stream():
    applied = []
    info = DeviceInfo(model="e9u_LSMD-TCD1304-PRO", serial="SN-TEST",
                      com_port="/dev/ttyUSB1", pixels=2048)
    bs = BenchStream(info_provider=lambda: info,
                     exposure_setter=applied.append, port=0)
    bs.start()
    yield bs, applied
    bs.stop()


@pytest.fixture
def client(stream):
    bs, applied = stream
    drv = NetDriver(f"127.0.0.1:{bs.port}")
    drv.connect()
    yield drv, bs, applied
    drv.close()


class TestFrameHub:
    def test_wait_returns_the_new_frame(self):
        hub = FrameHub()
        hub.publish(np.arange(4, dtype=np.uint16), 1234)
        n, frame, exp = hub.wait_for_new(0)
        assert n == 1 and exp == 1234 and list(frame) == [0, 1, 2, 3]

    def test_wait_times_out_without_a_new_frame(self):
        hub = FrameHub()
        hub.publish(np.zeros(2, dtype=np.uint16), 10)
        n, _f, _e = hub.wait_for_new(1, timeout=0.05)   # nothing newer
        assert n == 1                                   # returns stale, no hang


class TestBenchStream:
    def test_identity_comes_from_the_flight_app(self, client):
        drv, _bs, _applied = client
        assert drv._info.serial == "SN-TEST"
        assert drv._info.pixels == 2048

    def test_grab_serves_the_published_frame(self, client):
        drv, bs, _applied = client
        bs.publish(np.full(2048, 4242, dtype=np.uint16), 20_000)
        got = drv.grab()
        assert got.shape == (2048,) and int(got[0]) == 4242

    def test_each_grab_waits_for_a_fresh_frame(self, client):
        """A polling UI must not spin on one frame; it paces to the FSW."""
        drv, bs, _applied = client
        bs.publish(np.full(2048, 1, dtype=np.uint16), 20_000)
        assert int(drv.grab()[0]) == 1
        bs.publish(np.full(2048, 2, dtype=np.uint16), 20_000)
        assert int(drv.grab()[0]) == 2

    def test_set_times_is_only_requested_not_applied_here(self, client):
        drv, _bs, applied = client
        drv.set_times_us(7_500)
        assert applied == [7_500]        # handed to the acquisition thread

    def test_client_count_tracked(self, client):
        _drv, bs, _applied = client
        assert bs.clients == 1


class TestDisabledByDefault:
    """Also a regression test for shutdown-before-start: CommandServer.stop()
    used to block forever when serve_forever() had never run, hanging any error
    path that unwound between FlightApp.__init__ and start()."""

    def _app(self, tmp_path, **kw):
        from clouds_fsw.config import FswConfig
        from clouds_fsw.main import FlightApp
        from clouds_fsw.uart_link import PipeTransport
        cfg = FswConfig.load(None, mock=True, cmd_port=0,
                             data_dir=str(tmp_path / "data"))
        transport, _peer = PipeTransport.pair()
        return FlightApp(cfg, transport=transport, **kw)

    def test_no_bench_stream_unless_asked(self, tmp_path):
        app = self._app(tmp_path)
        try:
            assert app.bench is None
        finally:
            app.shutdown()          # must not hang

    def test_bench_stream_created_when_asked(self, tmp_path):
        app = self._app(tmp_path, bench_port=0)
        try:
            assert app.bench is not None
        finally:
            app.shutdown()
