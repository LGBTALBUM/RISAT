from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    input_channels: int
    output_channels: int

    @property
    def input_label(self) -> str:
        return f"{self.index}: {self.name} ({self.input_channels} in)"

    @property
    def output_label(self) -> str:
        return f"{self.index}: {self.name} ({self.output_channels} out)"


def _sounddevice():
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("audio I/O requires: pip install 'risat[audio]'") from exc
    return sd


def parse_device(value: str | int | None) -> str | int | None:
    """Convert a CLI value or GUI device label into a sounddevice selector."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = value.strip()
    if not text or text.lower() in {"default", "system default", "系统默认"}:
        return None
    prefix, separator, _ = text.partition(":")
    if separator and prefix.strip().isdigit():
        return int(prefix.strip())
    try:
        return int(text)
    except ValueError:
        return text


def list_audio_devices() -> list[AudioDevice]:
    sd = _sounddevice()
    devices: list[AudioDevice] = []
    for index, item in enumerate(sd.query_devices()):
        devices.append(
            AudioDevice(
                index=index,
                name=str(item["name"]),
                input_channels=int(item["max_input_channels"]),
                output_channels=int(item["max_output_channels"]),
            )
        )
    return devices


def play_audio(
    audio: np.ndarray,
    sample_rate: int,
    *,
    device: str | int | None = None,
) -> None:
    sd = _sounddevice()
    sd.play(audio, sample_rate, device=parse_device(device), blocking=True)


def record_audio(
    seconds: float,
    sample_rate: int,
    *,
    device: str | int | None = None,
    channels: int = 2,
) -> np.ndarray:
    if seconds <= 0:
        raise ValueError("recording duration must be greater than zero")
    sd = _sounddevice()
    frames = round(seconds * sample_rate)
    return sd.rec(
        frames,
        samplerate=sample_rate,
        channels=channels,
        dtype="float32",
        device=parse_device(device),
        blocking=True,
    )
