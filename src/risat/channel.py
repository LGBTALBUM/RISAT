from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from .modem import (
    DEFAULT_BAUD,
    SAMPLE_RATE,
    align_and_normalize_channels,
    channel_candidates,
    correct_global_speed,
    demodulate,
    encode_stereo,
)
from .protocol import (
    ProtocolError,
    RecoveryResult,
    build_container,
    build_frame_stream,
    default_metadata,
    recover_container,
    split_frames,
)


def write_wav(path: Path, audio: np.ndarray) -> None:
    pcm = np.clip(audio, -1.0, 1.0)
    wavfile.write(path, SAMPLE_RATE, (pcm * 32767.0).astype(np.int16))


def read_wav(path: Path) -> tuple[int, np.ndarray]:
    sample_rate, audio = wavfile.read(path)
    if np.issubdtype(audio.dtype, np.integer):
        scale = float(max(abs(np.iinfo(audio.dtype).min), np.iinfo(audio.dtype).max))
        audio = audio.astype(np.float32) / scale
    else:
        audio = audio.astype(np.float32)
    return sample_rate, audio


def encode_to_audio(
    image_path: Path,
    image_data: bytes,
    *,
    width: int,
    height: int,
    image_format: str,
    repeats: int = 3,
    baud: int = DEFAULT_BAUD,
    chunk_size: int = 191,
    rs_nsym: int = 32,
) -> tuple[np.ndarray, dict[str, object]]:
    metadata = default_metadata(image_path, width=width, height=height, image_format=image_format)
    metadata.update({"baud": baud, "repeats": repeats, "rs_nsym": rs_nsym, "chunk_size": chunk_size})
    container = build_container(image_data, metadata)
    frames = split_frames(container, chunk_size=chunk_size, rs_nsym=rs_nsym)
    main_stream = build_frame_stream(frames, repeats=repeats, side=False)
    side_stream = build_frame_stream(frames, repeats=repeats, side=True)
    audio = encode_stereo(main_stream, side_stream, baud=baud)
    metadata.update(
        {
            "frames": len(frames),
            "encoded_bytes": len(image_data),
            "audio_seconds": len(audio) / SAMPLE_RATE,
        }
    )
    return audio, metadata


def decode_from_audio(
    audio: np.ndarray,
    sample_rate: int,
    *,
    baud: int = DEFAULT_BAUD,
    rs_nsym: int = 32,
) -> tuple[RecoveryResult, dict[str, object]]:
    corrected, speed_ratio = correct_global_speed(audio, sample_rate)
    corrected = align_and_normalize_channels(corrected)
    streams: list[bytes] = []
    reports: dict[str, object] = {}
    errors: dict[str, str] = {}
    for name, samples in channel_candidates(corrected).items():
        try:
            stream, report = demodulate(samples, baud=baud, speed_ratio=speed_ratio)
            streams.append(stream)
            reports[name] = asdict(report)
        except Exception as exc:  # candidate diversity is intentional
            errors[name] = str(exc)
    if not streams:
        raise ProtocolError(f"all channel candidates failed: {errors}")
    result = recover_container(streams, rs_nsym=rs_nsym)
    diagnostic = {
        "sample_rate": SAMPLE_RATE,
        "input_sample_rate": sample_rate,
        "speed_ratio": speed_ratio,
        "successful_candidates": list(reports),
        "candidate_reports": reports,
        "candidate_errors": errors,
        "recovered_frames": result.recovered_frames,
        "total_frames": result.total_frames,
        "metadata": result.metadata,
    }
    return result, diagnostic


def write_report(path: Path, report: dict[str, object]) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
