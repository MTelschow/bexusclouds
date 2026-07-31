"""Wire format shared by ``net_server`` (Pi) and ``net_driver`` (PC).

Request  : one JSON object, newline-terminated.
Response : 1-byte tag + uint32 big-endian length + body.
           tag ``J`` -> body is JSON, tag ``B`` -> body is raw bytes,
           tag ``E`` -> body is a JSON error {"error": "..."}.

Deliberately dumb and synchronous: one request, one response, no streaming
state to get out of step. A frame is 2048 x uint16 = 4096 B, so a full-rate
bench session is ~50 KB/s - fine on a direct cable, nothing like the 2 kbit/s
flight budget.
"""
from __future__ import annotations

import json
import socket
import struct

DEFAULT_PORT = 4010
_HEAD = struct.Struct(">cI")
TAG_JSON = b"J"
TAG_BYTES = b"B"
TAG_ERROR = b"E"


class ProtocolError(RuntimeError):
    """Malformed or truncated exchange."""


def send_request(sock: socket.socket, obj: dict) -> None:
    sock.sendall(json.dumps(obj).encode("utf-8") + b"\n")


def send_response(sock: socket.socket, tag: bytes, body: bytes) -> None:
    sock.sendall(_HEAD.pack(tag, len(body)) + body)


def send_json(sock: socket.socket, obj: dict) -> None:
    send_response(sock, TAG_JSON, json.dumps(obj).encode("utf-8"))


def send_error(sock: socket.socket, message: str) -> None:
    send_response(sock, TAG_ERROR,
                  json.dumps({"error": message}).encode("utf-8"))


def recv_exactly(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes or raise - recv() alone is free to return short."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ProtocolError(f"connection closed after {len(buf)}/{n} bytes")
        buf += chunk
    return bytes(buf)


def recv_response(sock: socket.socket) -> tuple[bytes, bytes]:
    tag, length = _HEAD.unpack(recv_exactly(sock, _HEAD.size))
    return tag, recv_exactly(sock, length)


def read_request(reader) -> dict | None:
    """Read one newline-terminated JSON request from a file-like object."""
    line = reader.readline()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except ValueError as exc:
        raise ProtocolError(f"bad JSON request: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProtocolError("request must be a JSON object")
    return obj
