from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import signal

SAMPLE_RATE = 48_000
DEFAULT_BAUD = 1_200
DEFAULT_TONES = (2100.0, 3500.0, 4900.0, 6300.0)
TRAINING_SYMBOLS = np.random.default_rng(0x52495341).integers(0, 4, size=192, dtype=np.uint8)
SYNC_WORD = b"RISAT-AUDIO-SYNC\x1d\xc7"
SILENCE_SECONDS = 0.25
REFERENCE_SECONDS = 0.50
CHIRP_SECONDS = 0.50
GUARD_SECONDS = 0.12
REFERENCE_FREQUENCY = 1000.0


class ModemError(RuntimeError):
    """Raised when an audio stream cannot be synchronized or demodulated."""


@dataclass(frozen=True)
class DemodulationReport:
    start_sample: int
    training_accuracy: float
    tone_weights: tuple[float, float, float, float]
    speed_ratio: float


def bytes_to_symbols(data: bytes) -> np.ndarray:
    values = np.frombuffer(data, dtype=np.uint8)
    output = np.empty(values.size * 4, dtype=np.uint8)
    output[0::4] = values >> 6
    output[1::4] = (values >> 4) & 0x03
    output[2::4] = (values >> 2) & 0x03
    output[3::4] = values & 0x03
    return output


def symbols_to_bytes(symbols: np.ndarray) -> bytes:
    usable = len(symbols) - (len(symbols) % 4)
    if usable <= 0:
        return b""
    s = symbols[:usable].reshape(-1, 4).astype(np.uint8)
    values = (s[:, 0] << 6) | (s[:, 1] << 4) | (s[:, 2] << 2) | s[:, 3]
    return values.tobytes()


def build_symbol_stream(payload: bytes) -> np.ndarray:
    return np.concatenate((TRAINING_SYMBOLS, bytes_to_symbols(SYNC_WORD + payload)))


def cpfsk_modulate(
    symbols: np.ndarray,
    *,
    sample_rate: int = SAMPLE_RATE,
    baud: int = DEFAULT_BAUD,
    tones: tuple[float, float, float, float] = DEFAULT_TONES,
    amplitude: float = 0.75,
) -> np.ndarray:
    samples_per_symbol = sample_rate // baud
    if sample_rate % baud:
        raise ValueError("sample_rate must be an integer multiple of baud")
    frequencies = np.asarray(tones, dtype=np.float64)[symbols]
    frequency_per_sample = np.repeat(frequencies, samples_per_symbol)
    phase = 2.0 * np.pi * np.cumsum(frequency_per_sample) / sample_rate
    wave = amplitude * np.sin(phase)
    ramp_length = min(samples_per_symbol * 4, len(wave) // 2)
    if ramp_length > 0:
        ramp = np.sin(np.linspace(0.0, np.pi / 2.0, ramp_length)) ** 2
        wave[:ramp_length] *= ramp
        wave[-ramp_length:] *= ramp[::-1]
    return wave.astype(np.float32)


def _tone(length: int, frequency: float, amplitude: float = 0.42) -> np.ndarray:
    time = np.arange(length, dtype=np.float64) / SAMPLE_RATE
    return (amplitude * np.sin(2.0 * np.pi * frequency * time)).astype(np.float32)


def calibration_audio() -> np.ndarray:
    silence = np.zeros(round(SILENCE_SECONDS * SAMPLE_RATE), dtype=np.float32)
    reference = _tone(round(REFERENCE_SECONDS * SAMPLE_RATE), REFERENCE_FREQUENCY)
    chirp_len = round(CHIRP_SECONDS * SAMPLE_RATE)
    t = np.arange(chirp_len, dtype=np.float64) / SAMPLE_RATE
    chirp = (0.38 * signal.chirp(t, f0=400.0, f1=9000.0, t1=CHIRP_SECONDS, method="logarithmic")).astype(np.float32)
    guard = np.zeros(round(GUARD_SECONDS * SAMPLE_RATE), dtype=np.float32)
    return np.concatenate((silence, reference, chirp, guard))


def encode_stereo(main_payload: bytes, side_payload: bytes, *, baud: int = DEFAULT_BAUD) -> np.ndarray:
    main = cpfsk_modulate(build_symbol_stream(main_payload), baud=baud)
    side = cpfsk_modulate(build_symbol_stream(side_payload), baud=baud)
    length = max(len(main), len(side))
    main = np.pad(main, (0, length - len(main)))
    side = np.pad(side, (0, length - len(side)))

    left_data = 0.75 * main + 0.45 * side
    right_data = 0.75 * main - 0.45 * side
    peak = max(float(np.max(np.abs(left_data))), float(np.max(np.abs(right_data))), 1e-9)
    if peak > 0.92:
        left_data *= 0.92 / peak
        right_data *= 0.92 / peak

    calibration = calibration_audio()
    left = np.concatenate((calibration, left_data))
    right = np.concatenate((calibration, right_data))
    return np.column_stack((left, right)).astype(np.float32)


def _dominant_frequency(samples: np.ndarray, sample_rate: int, low: float, high: float) -> float:
    if len(samples) < 64:
        return REFERENCE_FREQUENCY
    window = np.hanning(len(samples))
    spectrum = np.abs(np.fft.rfft(samples * window))
    frequencies = np.fft.rfftfreq(len(samples), 1.0 / sample_rate)
    mask = (frequencies >= low) & (frequencies <= high)
    if not np.any(mask):
        return REFERENCE_FREQUENCY
    masked_spectrum = spectrum[mask]
    masked_frequencies = frequencies[mask]
    local = int(np.argmax(masked_spectrum))
    frequency = float(masked_frequencies[local])
    if 0 < local < len(masked_spectrum) - 1:
        # Quadratic interpolation on log magnitude gives sub-bin precision,
        # which is essential because a tiny residual tape-speed error accumulates
        # into whole-symbol timing errors over a long recording.
        y0, y1, y2 = np.log(np.maximum(masked_spectrum[local - 1 : local + 2], 1e-18))
        denominator = y0 - 2.0 * y1 + y2
        if abs(denominator) > 1e-12:
            delta = 0.5 * (y0 - y2) / denominator
            bin_width = float(masked_frequencies[1] - masked_frequencies[0])
            frequency += float(delta) * bin_width
    return frequency


def correct_global_speed(audio: np.ndarray, sample_rate: int) -> tuple[np.ndarray, float]:
    if sample_rate != SAMPLE_RATE:
        target_len = round(len(audio) * SAMPLE_RATE / sample_rate)
        audio = signal.resample(audio, target_len, axis=0).astype(np.float32)
        sample_rate = SAMPLE_RATE
    mono = np.mean(audio, axis=1) if audio.ndim == 2 else audio
    start = round(0.29 * sample_rate)
    end = min(len(mono), round(0.70 * sample_rate))
    measured = _dominant_frequency(mono[start:end], sample_rate, 800.0, 1200.0)
    ratio = measured / REFERENCE_FREQUENCY
    if not 0.94 <= ratio <= 1.06:
        ratio = 1.0
    if abs(ratio - 1.0) >= 0.0005:
        new_len = max(1, round(len(audio) * ratio))
        audio = signal.resample(audio, new_len, axis=0).astype(np.float32)
    return audio, ratio


def align_and_normalize_channels(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        audio = np.column_stack((audio, audio))
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    audio = audio[:, :2].astype(np.float64)
    audio -= np.median(audio[: min(len(audio), SAMPLE_RATE // 5)], axis=0)

    ref_start = round(SILENCE_SECONDS * SAMPLE_RATE)
    ref_end = min(len(audio), ref_start + round(REFERENCE_SECONDS * SAMPLE_RATE))
    if ref_end > ref_start:
        rms = np.sqrt(np.mean(audio[ref_start:ref_end] ** 2, axis=0) + 1e-12)
        target = float(np.mean(rms))
        audio *= target / np.maximum(rms, 1e-6)

    chirp_start = round((SILENCE_SECONDS + REFERENCE_SECONDS) * SAMPLE_RATE)
    chirp_end = min(len(audio), chirp_start + round(CHIRP_SECONDS * SAMPLE_RATE))
    if chirp_end - chirp_start > 256:
        left = audio[chirp_start:chirp_end, 0]
        right = audio[chirp_start:chirp_end, 1]
        corr = signal.correlate(right, left, mode="full", method="fft")
        lags = signal.correlation_lags(len(right), len(left), mode="full")
        mask = np.abs(lags) <= 128
        lag = int(lags[mask][np.argmax(corr[mask])])
        if lag > 0:
            audio[lag:, 1] = audio[:-lag, 1]
            audio[:lag, 1] = 0.0
        elif lag < 0:
            shift = -lag
            audio[:-shift, 1] = audio[shift:, 1]
            audio[-shift:, 1] = 0.0

    peak = np.max(np.abs(audio))
    if peak > 1.0:
        audio /= peak
    return audio.astype(np.float32)


def channel_candidates(audio: np.ndarray) -> dict[str, np.ndarray]:
    left = audio[:, 0]
    right = audio[:, 1]
    return {
        "mid": (left + right) / 1.5,
        "side": (left - right) / 0.9,
        "left": left,
        "right": right,
    }


def _tone_basis(samples_per_symbol: int, tones: tuple[float, float, float, float]) -> tuple[np.ndarray, np.ndarray]:
    n = np.arange(samples_per_symbol, dtype=np.float64)
    window = np.hanning(samples_per_symbol)
    cosines = np.array([window * np.cos(2.0 * np.pi * tone * n / SAMPLE_RATE) for tone in tones])
    sines = np.array([window * np.sin(2.0 * np.pi * tone * n / SAMPLE_RATE) for tone in tones])
    return cosines, sines


def _symbol_energies(block: np.ndarray, cosines: np.ndarray, sines: np.ndarray) -> np.ndarray:
    return (cosines @ block) ** 2 + (sines @ block) ** 2


def _score_training(
    samples: np.ndarray,
    start: int,
    samples_per_symbol: int,
    cosines: np.ndarray,
    sines: np.ndarray,
    count: int = 64,
) -> float:
    correct = 0
    available = min(count, len(TRAINING_SYMBOLS))
    for index in range(available):
        a = start + index * samples_per_symbol
        b = a + samples_per_symbol
        if a < 0 or b > len(samples):
            return 0.0
        detected = int(np.argmax(_symbol_energies(samples[a:b], cosines, sines)))
        correct += detected == int(TRAINING_SYMBOLS[index])
    return correct / available


def find_modem_start(samples: np.ndarray, *, baud: int, tones: tuple[float, float, float, float]) -> tuple[int, float]:
    samples_per_symbol = SAMPLE_RATE // baud
    cosines, sines = _tone_basis(samples_per_symbol, tones)
    expected = round((SILENCE_SECONDS + REFERENCE_SECONDS + CHIRP_SECONDS + GUARD_SECONDS) * SAMPLE_RATE)
    radius = round(0.08 * SAMPLE_RATE)
    best_start = expected
    best_score = -1.0
    for candidate in range(max(0, expected - radius), min(len(samples), expected + radius), max(1, samples_per_symbol // 4)):
        score = _score_training(samples, candidate, samples_per_symbol, cosines, sines)
        if score > best_score:
            best_score = score
            best_start = candidate
    fine_start = best_start
    for candidate in range(max(0, best_start - samples_per_symbol), min(len(samples), best_start + samples_per_symbol + 1)):
        score = _score_training(samples, candidate, samples_per_symbol, cosines, sines)
        if score > best_score:
            best_score = score
            fine_start = candidate
    if best_score < 0.70:
        raise ModemError(f"training sequence not found (best accuracy {best_score:.1%})")
    return fine_start, best_score


def demodulate(samples: np.ndarray, *, baud: int = DEFAULT_BAUD, tones: tuple[float, float, float, float] = DEFAULT_TONES, speed_ratio: float = 1.0) -> tuple[bytes, DemodulationReport]:
    samples = np.asarray(samples, dtype=np.float64)
    samples_per_symbol = SAMPLE_RATE // baud
    if SAMPLE_RATE % baud:
        raise ValueError("sample rate must be an integer multiple of baud")
    cosines, sines = _tone_basis(samples_per_symbol, tones)
    start, accuracy = find_modem_start(samples, baud=baud, tones=tones)

    calibration = np.zeros(4, dtype=np.float64)
    counts = np.zeros(4, dtype=np.int32)
    for index, expected_symbol in enumerate(TRAINING_SYMBOLS):
        a = start + index * samples_per_symbol
        b = a + samples_per_symbol
        if b > len(samples):
            break
        energies = _symbol_energies(samples[a:b], cosines, sines)
        calibration[int(expected_symbol)] += math.sqrt(max(energies[int(expected_symbol)], 1e-12))
        counts[int(expected_symbol)] += 1
    levels = calibration / np.maximum(counts, 1)
    median_level = float(np.median(levels[levels > 0])) if np.any(levels > 0) else 1.0
    weights = median_level / np.maximum(levels, median_level * 0.1)

    symbol_count = (len(samples) - start) // samples_per_symbol
    decoded = np.empty(symbol_count, dtype=np.uint8)
    for index in range(symbol_count):
        a = start + index * samples_per_symbol
        b = a + samples_per_symbol
        energies = _symbol_energies(samples[a:b], cosines, sines) * (weights**2)
        decoded[index] = int(np.argmax(energies))

    payload_symbols = decoded[len(TRAINING_SYMBOLS) :]
    raw = symbols_to_bytes(payload_symbols)
    sync_index = raw.find(SYNC_WORD)
    if sync_index < 0 or sync_index > 8:
        raise ModemError("audio sync word was not recovered")
    payload = raw[sync_index + len(SYNC_WORD) :]
    report = DemodulationReport(
        start_sample=start,
        training_accuracy=accuracy,
        tone_weights=tuple(float(value) for value in weights),
        speed_ratio=speed_ratio,
    )
    return payload, report
