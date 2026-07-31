"""FSW-PI UART link: COBS framing, resync after noise, liveness (S.4, S.9)."""
import time

import pytest

from clouds_link import cobs, frames, hk
from clouds_link.frames import Frame, PacketType
from clouds_fsw.uart_link import PipeTransport, UartLink


@pytest.fixture
def link_pair():
    """(UartLink under test, raw far-end transport = the 'MCU')."""
    near, far = PipeTransport.pair()
    received = []
    link = UartLink(near, on_frame=received.append)
    link.start()
    yield link, far, received
    link.stop()


def _wire(frame: Frame) -> bytes:
    return cobs.encode(frame.encode()) + b"\x00"


def _wait(predicate, timeout=2.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestUartLink:
    def test_receive_hk_frame(self, link_pair):
        link, far, received = link_pair
        h = hk.Housekeeping(state=hk.SeqState.STANDBY, uptime_s=12)
        far.write(_wire(Frame(type=PacketType.HK, payload=h.pack()).stamp()))
        assert _wait(lambda: len(received) == 1)
        assert hk.Housekeeping.unpack(received[0].payload).uptime_s == 12
        assert link.rx_frames == 1 and link.rx_errors == 0

    def test_noise_then_frame_resyncs(self, link_pair):
        link, far, received = link_pair
        far.write(b"\x07\x55\xaa\x00")   # garbage 'frame' + delimiter
        far.write(_wire(Frame(type=PacketType.EVENT,
                              payload=frames.pack_event(1, 0, "ok")).stamp()))
        assert _wait(lambda: len(received) == 1)
        assert link.rx_errors >= 1

    def test_split_delivery(self, link_pair):
        link, far, received = link_pair
        wire = _wire(Frame(type=PacketType.HK,
                           payload=hk.Housekeeping().pack()).stamp())
        far.write(wire[:10])
        far.write(wire[10:])
        assert _wait(lambda: len(received) == 1)

    def test_two_frames_one_chunk(self, link_pair):
        link, far, received = link_pair
        w = _wire(Frame(type=PacketType.HK,
                        payload=hk.Housekeeping().pack()).stamp())
        far.write(w + w)
        assert _wait(lambda: len(received) == 2)

    def test_send_encodes_cobs(self, link_pair):
        link, far, _ = link_pair
        f = Frame(type=PacketType.CMD, payload=frames.pack_cmd(0, 0, 0),
                  seq=1).stamp()
        link.send(f)
        wire = far.read(timeout=1.0)
        assert wire.endswith(b"\x00") and wire.count(b"\x00") == 1
        assert frames.decode(cobs.decode(wire[:-1])).seq == 1

    def test_liveness(self, link_pair):
        link, far, received = link_pair
        assert not link.alive(within_s=1.0)     # nothing received yet
        far.write(_wire(Frame(type=PacketType.HK,
                              payload=hk.Housekeeping().pack()).stamp()))
        assert _wait(lambda: link.alive(within_s=5.0))

    def test_handler_exception_does_not_kill_reader(self):
        near, far = PipeTransport.pair()
        seen = []

        def bad_handler(frame):
            seen.append(frame)
            raise RuntimeError("handler bug")

        link = UartLink(near, on_frame=bad_handler)
        link.start()
        w = _wire(Frame(type=PacketType.HK,
                        payload=hk.Housekeeping().pack()).stamp())
        far.write(w)
        far.write(w)
        assert _wait(lambda: len(seen) == 2)
        link.stop()
