# RISAT

**RCA-Image Stereo Analog Transport** converts an image into a stereo audio signal that can pass through two RCA cables or be recorded onto an analog audio medium, then reconstructs the image with channel correction and error recovery.

This repository contains the first working RISAT-1 reference implementation:

- `risat-enc-tx`: image → stereo WAV / live sound-card output
- `risat-dec-rx`: stereo WAV / live sound-card input → recovered image
- continuous-phase 4-FSK at 600, 1200, or 2400 baud
- Mid/Side diversity over the two RCA channels
- calibration tone and chirp
- global tape-speed correction
- left/right gain and delay correction
- per-FSK-tone equalization learned from the training sequence
- Reed–Solomon correction, CRC-32 validation, frame repetition, and interleaving
- SHA-256 validation of the final image

> RISAT-1 is an experimental transport. Preserve the complete calibration preamble when recording or trimming audio.

## Install

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -e .
```

For direct playback/recording through an audio interface:

```bash
python -m pip install -e ".[audio]"
```

## Encode / transmit

```bash
risat-enc-tx photo.png -o photo-risat.wav
```

Higher robustness for cassette tape:

```bash
risat-enc-tx photo.png -o tape.wav \
  --resolution 320x240 \
  --format jpeg \
  --quality 60 \
  --baud 600 \
  --repeats 5 \
  --report tx-report.json
```

Generate the WAV and immediately play it through the selected stereo interface:

```bash
risat-enc-tx photo.png -o tx.wav --play --device 3
```

Connect the interface's left and right line outputs to the two RCA inputs. Avoid microphone inputs, automatic gain control, spatial effects, bass enhancement, Dolby processing, and lossy audio codecs.

## Decode / receive

```bash
risat-dec-rx recorded.wav -o recovered.jpg
```

Record a 90-second stereo RCA input and decode it:

```bash
risat-dec-rx --record 90 --device 2 \
  --save-recording capture.wav \
  -o recovered.jpg \
  --report rx-report.json
```

The RX report records the measured speed ratio, synchronized channel candidates, training accuracy, equalization weights, frame count, and embedded image metadata.

## Suggested analog settings

For a normal cassette deck, start with 600 baud, a 320×240 JPEG, five repeats, and manual record level. Keep peaks below clipping and disable all enhancement/normalization. For direct RCA cable transport, 1200 or 2400 baud is appropriate.

RISAT uses a common-mode/main stream and a differential/side diversity stream:

```text
L = 0.75 M + 0.45 S
R = 0.75 M - 0.45 S
```

The decoder also tries the raw left and right channels. A mono capture may therefore still recover the main stream, while a proper stereo capture offers packet diversity.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
```

Protocol details are in [docs/RISAT-1.md](docs/RISAT-1.md).

## License

Apache License 2.0.
