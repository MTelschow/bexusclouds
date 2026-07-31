"""COBS (Consistent Overhead Byte Stuffing) for the Pi <-> RP2350 UART link.

Frames on the wire are ``cobs_encode(frame) + b"\\x00"``; 0x00 never appears
inside an encoded frame, so the delimiter resynchronises after any corruption.
Canonical algorithm (Cheshire & Baker); C mirror in flight/mcu/src/core/cobs.c.
"""
from __future__ import annotations


class CobsError(ValueError):
    pass


def encode(data: bytes) -> bytes:
    out = bytearray()
    block = bytearray()
    for b in data:
        if b == 0:
            out.append(len(block) + 1)
            out.extend(block)
            block.clear()
        else:
            block.append(b)
            if len(block) == 254:
                out.append(0xFF)
                out.extend(block)
                block.clear()
    out.append(len(block) + 1)
    out.extend(block)
    return bytes(out)


def decode(data: bytes) -> bytes:
    if not data:
        raise CobsError("empty COBS frame")
    if 0 in data:
        raise CobsError("zero byte inside COBS frame")
    out = bytearray()
    idx = 0
    while idx < len(data):
        code = data[idx]
        if code == 0:
            raise CobsError("zero byte inside COBS frame")
        if idx + code > len(data):
            raise CobsError("COBS group overruns frame")
        out.extend(data[idx + 1:idx + code])
        idx += code
        if code < 0xFF and idx < len(data):
            out.append(0)
    return bytes(out)
