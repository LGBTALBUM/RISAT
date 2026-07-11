from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from reedsolo import RSCodec, ReedSolomonError

FRAME_MAGIC = b"RFP1"
CONTAINER_MAGIC = b"RIC1"
PROTOCOL_VERSION = 1
FRAME_HEADER = struct.Struct(">4sBHHHHI")
CONTAINER_HEADER = struct.Struct(">4sBI32s")


class ProtocolError(RuntimeError):
    """Raised when a RISAT stream cannot be reconstructed safely."""


@dataclass(frozen=True)
class Frame:
    sequence: int
    total: int
    payload: bytes


@dataclass(frozen=True)
class RecoveryResult:
    image_bytes: bytes
    metadata: dict[str, object]
    recovered_frames: int
    total_frames: int
    missing_frames: tuple[int, ...]


def build_container(image_bytes: bytes, metadata: dict[str, object]) -> bytes:
    meta = json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(image_bytes).digest()
    return CONTAINER_HEADER.pack(CONTAINER_MAGIC, PROTOCOL_VERSION, len(meta), digest) + meta + image_bytes


def parse_container(container: bytes) -> tuple[bytes, dict[str, object]]:
    if len(container) < CONTAINER_HEADER.size:
        raise ProtocolError("container header is truncated")
    magic, version, meta_len, expected_digest = CONTAINER_HEADER.unpack_from(container)
    if magic != CONTAINER_MAGIC or version != PROTOCOL_VERSION:
        raise ProtocolError("unsupported or invalid RISAT image container")
    meta_start = CONTAINER_HEADER.size
    meta_end = meta_start + meta_len
    if meta_end > len(container):
        raise ProtocolError("container metadata is truncated")
    try:
        metadata = json.loads(container[meta_start:meta_end].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("container metadata is invalid") from exc
    image_bytes = container[meta_end:]
    if hashlib.sha256(image_bytes).digest() != expected_digest:
        raise ProtocolError("reconstructed image failed SHA-256 verification")
    return image_bytes, metadata


def split_frames(container: bytes, chunk_size: int = 191, rs_nsym: int = 32) -> list[bytes]:
    if not 32 <= chunk_size <= 223:
        raise ValueError("chunk_size must be between 32 and 223 bytes")
    if not 8 <= rs_nsym <= 64 or chunk_size + rs_nsym > 255:
        raise ValueError("invalid Reed-Solomon parameters")
    total = math.ceil(len(container) / chunk_size)
    if total > 65535:
        raise ValueError("image container requires too many frames")
    codec = RSCodec(rs_nsym)
    frames: list[bytes] = []
    for sequence in range(total):
        raw = container[sequence * chunk_size : (sequence + 1) * chunk_size]
        encoded = bytes(codec.encode(raw))
        header = FRAME_HEADER.pack(
            FRAME_MAGIC,
            PROTOCOL_VERSION,
            sequence,
            total,
            len(raw),
            len(encoded),
            zlib.crc32(raw) & 0xFFFFFFFF,
        )
        frames.append(header + encoded)
    return frames


def _order_for_copy(count: int, copy_index: int, side: bool) -> list[int]:
    base = list(range(count))
    mode = (copy_index + (1 if side else 0)) % 4
    if mode == 0:
        return base
    if mode == 1:
        return list(reversed(base))
    if mode == 2:
        return base[::2] + base[1::2]
    stride = 5
    while math.gcd(stride, max(1, count)) != 1:
        stride += 2
    return [(i * stride) % count for i in range(count)]


def build_frame_stream(frames: list[bytes], repeats: int = 3, side: bool = False) -> bytes:
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    output = bytearray()
    for copy_index in range(repeats):
        for index in _order_for_copy(len(frames), copy_index, side):
            output.extend(frames[index])
    return bytes(output)


def scan_frames(stream: bytes, rs_nsym: int = 32) -> tuple[dict[int, bytes], int | None]:
    codec = RSCodec(rs_nsym)
    recovered: dict[int, bytes] = {}
    expected_total: int | None = None
    cursor = 0
    while True:
        found = stream.find(FRAME_MAGIC, cursor)
        if found < 0:
            break
        cursor = found + 1
        if found + FRAME_HEADER.size > len(stream):
            continue
        try:
            magic, version, sequence, total, raw_len, encoded_len, expected_crc = FRAME_HEADER.unpack_from(stream, found)
        except struct.error:
            continue
        if magic != FRAME_MAGIC or version != PROTOCOL_VERSION:
            continue
        if total == 0 or sequence >= total or raw_len == 0:
            continue
        if encoded_len != raw_len + rs_nsym or encoded_len > 255:
            continue
        body_start = found + FRAME_HEADER.size
        body_end = body_start + encoded_len
        if body_end > len(stream):
            continue
        encoded = stream[body_start:body_end]
        try:
            decoded_result = codec.decode(encoded)
            decoded = bytes(decoded_result[0] if isinstance(decoded_result, tuple) else decoded_result)
        except ReedSolomonError:
            continue
        raw = decoded[:raw_len]
        if (zlib.crc32(raw) & 0xFFFFFFFF) != expected_crc:
            continue
        if expected_total is None:
            expected_total = total
        if total != expected_total:
            continue
        recovered.setdefault(sequence, raw)
    return recovered, expected_total


def recover_container(streams: Iterable[bytes], rs_nsym: int = 32) -> RecoveryResult:
    merged: dict[int, bytes] = {}
    totals: list[int] = []
    for stream in streams:
        frames, total = scan_frames(stream, rs_nsym=rs_nsym)
        merged.update({key: value for key, value in frames.items() if key not in merged})
        if total is not None:
            totals.append(total)
    if not totals:
        raise ProtocolError("no valid RISAT frames were found")
    total = max(set(totals), key=totals.count)
    missing = tuple(index for index in range(total) if index not in merged)
    if missing:
        preview = ", ".join(map(str, missing[:12]))
        suffix = "…" if len(missing) > 12 else ""
        raise ProtocolError(f"missing {len(missing)} of {total} frames: {preview}{suffix}")
    container = b"".join(merged[index] for index in range(total))
    image_bytes, metadata = parse_container(container)
    return RecoveryResult(
        image_bytes=image_bytes,
        metadata=metadata,
        recovered_frames=len(merged),
        total_frames=total,
        missing_frames=missing,
    )


def default_metadata(path: Path, *, width: int, height: int, image_format: str) -> dict[str, object]:
    return {
        "filename": path.name,
        "width": width,
        "height": height,
        "format": image_format,
        "protocol": "RISAT-1",
    }
