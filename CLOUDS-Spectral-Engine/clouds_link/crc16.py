"""CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) - requirement S.5.

Check value: crc16(b"123456789") == 0x29B1. The C mirror
(flight/mcu/src/core/crc16.c) embeds the same check vector in its tests.
"""
from __future__ import annotations


def _build_table() -> list[int]:
    table = []
    for byte in range(256):
        crc = byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
        table.append(crc)
    return table


_TABLE = _build_table()


def crc16(data: bytes, crc: int = 0xFFFF) -> int:
    for b in data:
        crc = ((crc << 8) & 0xFFFF) ^ _TABLE[((crc >> 8) ^ b) & 0xFF]
    return crc
