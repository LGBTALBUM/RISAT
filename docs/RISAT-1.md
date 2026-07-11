# RISAT-1 transport specification

Status: experimental reference profile, version 1.

## Physical/audio profile

- PCM working rate: 48,000 samples/s
- stereo line-level transport over two RCA channels
- 16-bit WAV interchange; internal DSP uses floating point
- 4-FSK tones: 2100, 3500, 4900, and 6300 Hz
- continuous phase modulation
- supported symbol rates: 600, 1200, and 2400 symbols/s
- dibit mapping: `00`, `01`, `10`, `11` in ascending tone order

## Record layout

1. 250 ms silence for DC/noise observation
2. 500 ms, 1 kHz common-mode reference tone
3. 500 ms logarithmic 400–9000 Hz common-mode chirp
4. 120 ms guard interval
5. 192-symbol repeating 0/1/2/3 modem training sequence
6. `RISAT-AUDIO-SYNC 1D C7`
7. repeated/interleaved frame byte stream

The RX estimates global speed error from the reference tone and resamples the complete capture. It uses the chirp to align the stereo channels, normalizes their reference RMS levels, derives M/S candidates, and learns a relative energy correction for each FSK tone from the known training sequence.

## Stereo diversity matrix

```text
L = 0.75 M + 0.45 S
R = 0.75 M - 0.45 S

M = (L + R) / 1.50
S = (L - R) / 0.90
```

M and S carry the same logical frames in different orders. The receiver merges every frame that passes Reed–Solomon decoding and CRC validation. Raw L and R are also attempted as fallback candidates.

## Image container

The reconstructed byte container begins with:

| Field | Size | Meaning |
|---|---:|---|
| magic | 4 | `RIC1` |
| version | 1 | `1` |
| metadata length | 4 | big-endian JSON byte length |
| digest | 32 | SHA-256 of encoded image bytes |
| metadata | variable | UTF-8 JSON |
| image | variable | JPEG, PNG, or WebP bytes |

Metadata includes filename, dimensions, image format, baud, repetition count, Reed–Solomon parity size, chunk size, and protocol name.

## Frame format

| Field | Size | Meaning |
|---|---:|---|
| magic | 4 | `RFP1` |
| version | 1 | `1` |
| sequence | 2 | zero-based frame number |
| total | 2 | total frame count |
| raw length | 2 | decoded payload bytes |
| encoded length | 2 | RS-coded payload bytes |
| CRC-32 | 4 | CRC of raw payload |
| RS payload | variable | default RS(223,191)-style shortened codeword with 32 parity bytes |

Frames are repeated and permuted. The default transmission sends three copies. This converts contiguous analog dropouts into losses distributed across different copies.

## Integrity and correction hierarchy

1. analog correction: sample-rate conversion, reference-frequency speed correction, DC removal, channel gain matching, channel delay alignment, FSK-tone equalization
2. symbol diversity: M, S, L, and R candidate decoding
3. frame correction: 32-byte Reed–Solomon parity per shortened frame
4. frame integrity: CRC-32
5. dropout resilience: repeated and interleaved frame copies
6. object integrity: SHA-256 of the final image byte stream

A decoder must not emit an image when the final SHA-256 check fails.

## Known v0.1 limitations

- global tape-speed correction is implemented; continuous wow/flutter tracking is not yet implemented
- no cross-frame erasure parity is present
- calibration must remain at the beginning of the recording
- aggressive noise reduction and perceptual audio codecs can destroy FSK symbols
- 2400 baud is intended primarily for direct cable or high-quality media
