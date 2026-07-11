# RISAT desktop GUI

The `risat-gui` entry point wraps the existing RISAT encoder and decoder without changing the wire format.

## Launch

```bash
python -m pip install -e ".[audio]"
risat-gui
```

The `audio` extra is optional when working only with WAV files. It is required for live playback and recording.

## TX tab

1. Select an input image.
2. Select the maximum resolution and output image format.
3. Choose the modem baud rate and repetition count.
4. Choose an output WAV and optional JSON report.
5. Enable direct playback when the stereo interface is connected to the two RCA channels.
6. Select **Generate TX WAV**.

For ordinary cassette tape, start with 320×240, JPEG quality 60, 600 baud, and five repeats. For direct RCA transport, 1200 or 2400 baud is appropriate.

## RX tab

RX can read an existing stereo WAV or record a fixed duration from a stereo input device. The application saves the raw recording when a path is supplied, applies RISAT channel correction, writes the recovered image, and displays the decoder diagnostics.

The GUI automatically replaces an `.img` output extension with the image format embedded in the RISAT container.

## Audio devices

Only devices with at least two input or output channels are listed. **System default** delegates device selection to PortAudio. Press **Refresh audio devices** after connecting a USB interface.

Disable automatic gain control, noise suppression, spatial audio, equalizers, Dolby processing, and lossy codecs in the analog signal path.
