"""CLOUDS shared link protocol (feature X-01).

One packet schema used by all three software items:
FSW-MCU (C mirror in flight/mcu/src/core/), FSW-PI, and the GSE.
Spec: docs/SOFTWARE_SPEC.md section 3; frame layout in frames.py.
"""
from . import cobs, commands, crc16, frames, hk  # noqa: F401

PROTOCOL_VERSION = 1
