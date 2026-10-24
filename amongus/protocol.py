"""Wire format: 4-byte big-endian length prefix + UTF-8 JSON object.

JSON (not pickle) so a malicious peer can't execute code; explicit framing so
TCP's merging/splitting of segments never corrupts messages.
"""
import json
import struct

from .config import MAX_FRAME_BYTES

_HEADER = struct.Struct("!I")


class ProtocolError(Exception):
    pass


def encode(msg):
    body = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise ProtocolError(f"message too large ({len(body)} bytes)")
    return _HEADER.pack(len(body)) + body


class FrameReader:
    """Accumulates raw bytes and yields complete decoded messages."""

    def __init__(self, max_frame=MAX_FRAME_BYTES):
        self.buf = bytearray()
        self.max_frame = max_frame

    def feed(self, data):
        self.buf += data
        out = []
        while True:
            if len(self.buf) < _HEADER.size:
                break
            (n,) = _HEADER.unpack_from(self.buf)
            if n > self.max_frame:
                raise ProtocolError(f"frame of {n} bytes exceeds limit")
            if len(self.buf) < _HEADER.size + n:
                break
            body = bytes(self.buf[_HEADER.size:_HEADER.size + n])
            del self.buf[:_HEADER.size + n]
            try:
                msg = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as e:
                raise ProtocolError(f"bad frame: {e}") from None
            if not isinstance(msg, dict) or not isinstance(msg.get("t"), str):
                raise ProtocolError("frame is not a typed object")
            out.append(msg)
        return out
