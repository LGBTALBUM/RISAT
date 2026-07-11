from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps


@dataclass(frozen=True)
class EncodedImage:
    data: bytes
    width: int
    height: int
    image_format: str


def parse_resolution(value: str | None) -> tuple[int, int] | None:
    if value is None:
        return None
    normalized = value.lower().replace("×", "x")
    try:
        width_text, height_text = normalized.split("x", 1)
        width, height = int(width_text), int(height_text)
    except (ValueError, TypeError) as exc:
        raise ValueError("resolution must look like 640x480") from exc
    if width < 16 or height < 16:
        raise ValueError("resolution must be at least 16x16")
    return width, height


def encode_image(path: Path, *, resolution: tuple[int, int] | None, output_format: str, quality: int) -> EncodedImage:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        if resolution is not None:
            image.thumbnail(resolution, Image.Resampling.LANCZOS)
        output = io.BytesIO()
        fmt = output_format.upper()
        if fmt == "JPEG":
            image.save(output, format="JPEG", quality=quality, optimize=True, progressive=True, subsampling="4:2:0")
        elif fmt == "WEBP":
            image.save(output, format="WEBP", quality=quality, method=6)
        elif fmt == "PNG":
            image.save(output, format="PNG", optimize=True)
        else:
            raise ValueError(f"unsupported image format: {output_format}")
        return EncodedImage(output.getvalue(), image.width, image.height, fmt.lower())
