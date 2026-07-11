from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .audio_io import parse_device, play_audio, record_audio
from .channel import decode_from_audio, encode_to_audio, read_wav, write_report, write_wav
from .image_codec import encode_image, parse_resolution
from .modem import DEFAULT_BAUD, SAMPLE_RATE
from .protocol import ProtocolError



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="risat", description="RISAT image-over-stereo-audio modem")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tx = subparsers.add_parser("enc-tx", help="encode an image into a stereo WAV/RCA signal")
    tx.add_argument("input", type=Path)
    tx.add_argument("-o", "--output", type=Path, default=Path("risat-tx.wav"))
    tx.add_argument("--resolution", default="640x480", help="maximum image box, e.g. 640x480; use 'original' to disable")
    tx.add_argument("--format", choices=("jpeg", "png", "webp"), default="jpeg")
    tx.add_argument("--quality", type=int, default=70)
    tx.add_argument("--baud", type=int, choices=(600, 1200, 2400), default=DEFAULT_BAUD)
    tx.add_argument("--repeats", type=int, default=3)
    tx.add_argument("--play", action="store_true", help="play the generated signal through a sound device")
    tx.add_argument("--device", help="sounddevice output device name or index")
    tx.add_argument("--report", type=Path)

    rx = subparsers.add_parser("dec-rx", help="decode a RISAT stereo WAV/RCA recording")
    rx.add_argument("input", nargs="?", type=Path)
    rx.add_argument("-o", "--output", type=Path, default=Path("risat-recovered.img"))
    rx.add_argument("--baud", choices=("auto", "600", "1200", "2400"), default="auto")
    rx.add_argument("--record", type=float, metavar="SECONDS", help="record stereo input instead of reading a WAV")
    rx.add_argument("--device", help="sounddevice input device name or index")
    rx.add_argument("--save-recording", type=Path)
    rx.add_argument("--report", type=Path, default=Path("risat-rx-report.json"))

    subparsers.add_parser("gui", help="open the RISAT TX/RX desktop application")
    return parser



def command_tx(args: argparse.Namespace) -> int:
    if not args.input.is_file():
        raise FileNotFoundError(args.input)
    resolution = None if args.resolution.lower() == "original" else parse_resolution(args.resolution)
    if not 1 <= args.quality <= 100:
        raise ValueError("quality must be between 1 and 100")
    encoded = encode_image(args.input, resolution=resolution, output_format=args.format, quality=args.quality)
    audio, report = encode_to_audio(
        args.input,
        encoded.data,
        width=encoded.width,
        height=encoded.height,
        image_format=encoded.image_format,
        repeats=args.repeats,
        baud=args.baud,
    )
    write_wav(args.output, audio)
    if args.report:
        write_report(args.report, report)
    print(f"encoded {encoded.width}x{encoded.height} {encoded.image_format} image to {args.output}")
    print(f"duration: {report['audio_seconds']:.2f}s, frames: {report['frames']}, image bytes: {report['encoded_bytes']}")
    if args.play:
        play_audio(audio, SAMPLE_RATE, device=parse_device(args.device))
    return 0


def command_rx(args: argparse.Namespace) -> int:
    if args.record is not None:
        audio = record_audio(args.record, SAMPLE_RATE, device=parse_device(args.device), channels=2)
        sample_rate = SAMPLE_RATE
        if args.save_recording:
            write_wav(args.save_recording, audio)
    else:
        if args.input is None:
            raise ValueError("provide an input WAV or use --record SECONDS")
        sample_rate, audio = read_wav(args.input)
    result, report = decode_from_audio(
        audio, sample_rate, baud=None if args.baud == "auto" else int(args.baud)
    )
    output = args.output
    if output.suffix == ".img":
        image_format = str(result.metadata.get("format", "png"))
        output = output.with_suffix(".jpg" if image_format == "jpeg" else f".{image_format}")
    output.write_bytes(result.image_bytes)
    write_report(args.report, report)
    print(f"recovered image to {output}")
    print(
        f"frames: {result.recovered_frames}/{result.total_frames}; "
        f"baud: {report['detected_baud']}; "
        f"candidates: {', '.join(report['successful_candidates'])}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "gui":
            from .gui import gui_main

            return gui_main()
        return command_tx(args) if args.command == "enc-tx" else command_rx(args)
    except (ValueError, RuntimeError, OSError, ProtocolError) as exc:
        parser.error(str(exc))
        return 2


def tx_main() -> int:
    return main(["enc-tx", *sys.argv[1:]])


def rx_main() -> int:
    return main(["dec-rx", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
