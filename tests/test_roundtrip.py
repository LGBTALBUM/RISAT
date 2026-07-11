from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from scipy import signal

from risat.channel import decode_from_audio, encode_to_audio
from risat.image_codec import encode_image
from risat.modem import SAMPLE_RATE


def make_image(path: Path) -> None:
    y, x = np.mgrid[0:48, 0:64]
    pixels = np.stack(((x * 4) % 256, (y * 5) % 256, ((x + y) * 3) % 256), axis=-1).astype(np.uint8)
    Image.fromarray(pixels, mode="RGB").save(path)


def test_clean_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    make_image(source)
    encoded = encode_image(source, resolution=None, output_format="png", quality=80)
    audio, _ = encode_to_audio(
        source,
        encoded.data,
        width=encoded.width,
        height=encoded.height,
        image_format=encoded.image_format,
        repeats=2,
        baud=2400,
    )
    result, report = decode_from_audio(audio, SAMPLE_RATE, baud=2400)
    assert result.image_bytes == encoded.data
    assert result.metadata["width"] == 64
    assert "mid" in report["successful_candidates"]


def test_gain_noise_and_speed_correction(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    make_image(source)
    encoded = encode_image(source, resolution=(48, 36), output_format="jpeg", quality=55)
    audio, _ = encode_to_audio(
        source,
        encoded.data,
        width=encoded.width,
        height=encoded.height,
        image_format=encoded.image_format,
        repeats=3,
        baud=1200,
    )
    damaged = audio.copy()
    damaged[:, 0] *= 0.72
    damaged[:, 1] *= 1.12
    rng = np.random.default_rng(42)
    damaged += rng.normal(0.0, 0.004, damaged.shape).astype(np.float32)
    speed = 1.012
    damaged = signal.resample(damaged, round(len(damaged) / speed), axis=0).astype(np.float32)
    result, report = decode_from_audio(damaged, SAMPLE_RATE, baud=1200)
    assert result.image_bytes == encoded.data
    assert abs(report["speed_ratio"] - speed) < 0.004


def test_audio_device_parser() -> None:
    from risat.audio_io import parse_device

    assert parse_device(None) is None
    assert parse_device("系统默认") is None
    assert parse_device("3") == 3
    assert parse_device("7: USB Audio CODEC (2 in)") == 7
    assert parse_device("USB Audio CODEC") == "USB Audio CODEC"


def test_600_baud_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    make_image(source)
    encoded = encode_image(source, resolution=(48, 36), output_format="jpeg", quality=60)
    audio, _ = encode_to_audio(
        source,
        encoded.data,
        width=encoded.width,
        height=encoded.height,
        image_format=encoded.image_format,
        repeats=2,
        baud=600,
    )
    result, report = decode_from_audio(audio, SAMPLE_RATE, baud=600)
    assert result.image_bytes == encoded.data
    assert report["detected_baud"] == 600


def test_auto_baud_falls_back_from_wrong_preference(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    make_image(source)
    encoded = encode_image(source, resolution=(48, 36), output_format="jpeg", quality=60)
    audio, _ = encode_to_audio(
        source,
        encoded.data,
        width=encoded.width,
        height=encoded.height,
        image_format=encoded.image_format,
        repeats=2,
        baud=1200,
    )
    result, report = decode_from_audio(audio, SAMPLE_RATE, baud=600)
    assert result.image_bytes == encoded.data
    assert report["requested_baud"] == 600
    assert report["detected_baud"] == 1200


def test_leading_silence_is_trimmed(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    make_image(source)
    encoded = encode_image(source, resolution=(48, 36), output_format="jpeg", quality=60)
    audio, _ = encode_to_audio(
        source,
        encoded.data,
        width=encoded.width,
        height=encoded.height,
        image_format=encoded.image_format,
        repeats=2,
        baud=1200,
    )
    leading = np.zeros((round(0.45 * SAMPLE_RATE), 2), dtype=np.float32)
    capture = np.concatenate((leading, audio), axis=0)
    result, report = decode_from_audio(capture, SAMPLE_RATE, baud=None)
    assert result.image_bytes == encoded.data
    assert report["detected_baud"] == 1200
