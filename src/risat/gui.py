from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageOps, ImageTk

from .audio_io import list_audio_devices, parse_device, play_audio, record_audio
from .channel import decode_from_audio, encode_to_audio, read_wav, write_report, write_wav
from .image_codec import encode_image, parse_resolution
from .modem import DEFAULT_BAUD, SAMPLE_RATE

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError as exc:  # pragma: no cover - depends on the platform Python build
    raise RuntimeError(
        "RISAT GUI requires Tk. On Debian/Ubuntu install python3-tk; "
        "Windows and python.org macOS builds normally include it."
    ) from exc


DEFAULT_PREVIEW_SIZE = (360, 240)


class RISATApp(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=12)
        self.master = master
        self._events: queue.Queue[tuple[str, Any, Any]] = queue.Queue()
        self._busy = False
        self._preview_images: dict[str, ImageTk.PhotoImage] = {}
        self._input_device_map: dict[str, int | None] = {"系统默认": None}
        self._output_device_map: dict[str, int | None] = {"系统默认": None}

        self.grid(row=0, column=0, sticky="nsew")
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_header()
        self._build_notebook()
        self._build_footer()
        self._set_rx_mode()
        self._refresh_devices(initial=True)
        self.after(100, self._poll_events)

    def _build_header(self) -> None:
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="RISAT TX / RX", font=("TkDefaultFont", 18, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="图片 ⇄ 双声道 RCA / 类比音频介质",
        ).grid(row=1, column=0, sticky="w")
        ttk.Button(header, text="刷新声卡", command=self._refresh_devices).grid(
            row=0, column=1, rowspan=2, padx=(12, 0)
        )

    def _build_notebook(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1, column=0, sticky="nsew")

        self.tx_tab = ttk.Frame(self.notebook, padding=12)
        self.rx_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.tx_tab, text="TX 编码 / 发送")
        self.notebook.add(self.rx_tab, text="RX 解码 / 接收")
        self._build_tx_tab()
        self._build_rx_tab()

    def _build_footer(self) -> None:
        footer = ttk.Frame(self)
        footer.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(1, weight=1)
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=160)
        self.progress.grid(row=0, column=0, padx=(0, 10))
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=1, sticky="w")

    def _build_tx_tab(self) -> None:
        tab = self.tx_tab
        tab.columnconfigure(0, weight=3)
        tab.columnconfigure(1, weight=2)
        tab.rowconfigure(0, weight=1)

        form = ttk.LabelFrame(tab, text="TX 参数", padding=12)
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        form.columnconfigure(1, weight=1)

        self.tx_input_var = tk.StringVar()
        self.tx_output_var = tk.StringVar(value="risat-tx.wav")
        self.tx_resolution_var = tk.StringVar(value="640x480")
        self.tx_format_var = tk.StringVar(value="jpeg")
        self.tx_quality_var = tk.IntVar(value=70)
        self.tx_baud_var = tk.IntVar(value=DEFAULT_BAUD)
        self.tx_repeats_var = tk.IntVar(value=3)
        self.tx_report_var = tk.StringVar(value="tx-report.json")
        self.tx_play_var = tk.BooleanVar(value=False)
        self.tx_device_var = tk.StringVar(value="系统默认")

        row = 0
        row = self._path_row(
            form,
            row,
            "输入图片",
            self.tx_input_var,
            self._browse_tx_input,
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"), ("All files", "*.*")],
        )
        row = self._path_row(
            form,
            row,
            "输出 WAV",
            self.tx_output_var,
            lambda: self._save_path(self.tx_output_var, ".wav", [("WAV audio", "*.wav")]),
        )

        ttk.Label(form, text="最大分辨率").grid(row=row, column=0, sticky="w", pady=4)
        resolution = ttk.Combobox(
            form,
            textvariable=self.tx_resolution_var,
            values=("320x240", "640x480", "1280x720", "original"),
        )
        resolution.grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        options = ttk.Frame(form)
        options.grid(row=row, column=0, columnspan=3, sticky="ew", pady=4)
        for column in range(6):
            options.columnconfigure(column, weight=1 if column % 2 else 0)
        ttk.Label(options, text="格式").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            options,
            textvariable=self.tx_format_var,
            values=("jpeg", "png", "webp"),
            state="readonly",
            width=8,
        ).grid(row=0, column=1, sticky="ew", padx=(4, 12))
        ttk.Label(options, text="质量").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(options, from_=1, to=100, textvariable=self.tx_quality_var, width=7).grid(
            row=0, column=3, sticky="ew", padx=(4, 12)
        )
        ttk.Label(options, text="Baud").grid(row=0, column=4, sticky="w")
        ttk.Combobox(
            options,
            textvariable=self.tx_baud_var,
            values=(600, 1200, 2400),
            state="readonly",
            width=8,
        ).grid(row=0, column=5, sticky="ew", padx=(4, 0))
        row += 1

        ttk.Label(form, text="重复次数").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Spinbox(form, from_=1, to=15, textvariable=self.tx_repeats_var).grid(
            row=row, column=1, sticky="ew", pady=4
        )
        row += 1
        row = self._path_row(
            form,
            row,
            "TX 报告",
            self.tx_report_var,
            lambda: self._save_path(self.tx_report_var, ".json", [("JSON report", "*.json")]),
        )

        ttk.Checkbutton(form, text="生成后立即从声卡播放", variable=self.tx_play_var).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(8, 4)
        )
        row += 1
        ttk.Label(form, text="输出设备").grid(row=row, column=0, sticky="w", pady=4)
        self.tx_device_combo = ttk.Combobox(form, textvariable=self.tx_device_var, state="readonly")
        self.tx_device_combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
        row += 1

        actions = ttk.Frame(form)
        actions.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.tx_generate_button = ttk.Button(actions, text="生成 TX WAV", command=self._start_tx)
        self.tx_generate_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.tx_play_button = ttk.Button(actions, text="播放现有 WAV", command=self._start_play_wav)
        self.tx_play_button.grid(row=0, column=1, sticky="ew", padx=(5, 0))

        side = ttk.Frame(tab)
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(0, weight=1)
        side.rowconfigure(0, weight=1)
        preview_box = ttk.LabelFrame(side, text="图片预览", padding=8)
        preview_box.grid(row=0, column=0, sticky="nsew")
        preview_box.columnconfigure(0, weight=1)
        preview_box.rowconfigure(0, weight=1)
        self.tx_preview = ttk.Label(preview_box, text="选择图片后显示预览", anchor="center")
        self.tx_preview.grid(row=0, column=0, sticky="nsew")
        self.tx_log = self._make_log(side)
        self.tx_log.master.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

    def _build_rx_tab(self) -> None:
        tab = self.rx_tab
        tab.columnconfigure(0, weight=3)
        tab.columnconfigure(1, weight=2)
        tab.rowconfigure(0, weight=1)

        form = ttk.LabelFrame(tab, text="RX 参数", padding=12)
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        form.columnconfigure(1, weight=1)

        self.rx_mode_var = tk.StringVar(value="file")
        self.rx_input_var = tk.StringVar()
        self.rx_output_var = tk.StringVar(value="risat-recovered.img")
        self.rx_baud_var = tk.IntVar(value=DEFAULT_BAUD)
        self.rx_report_var = tk.StringVar(value="risat-rx-report.json")
        self.rx_seconds_var = tk.DoubleVar(value=90.0)
        self.rx_save_recording_var = tk.StringVar(value="capture.wav")
        self.rx_device_var = tk.StringVar(value="系统默认")

        mode = ttk.Frame(form)
        mode.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Radiobutton(
            mode, text="读取 WAV", value="file", variable=self.rx_mode_var, command=self._set_rx_mode
        ).grid(row=0, column=0, padx=(0, 16))
        ttk.Radiobutton(
            mode, text="从声卡录音", value="record", variable=self.rx_mode_var, command=self._set_rx_mode
        ).grid(row=0, column=1)

        self.rx_file_widgets: list[tk.Widget] = []
        self.rx_record_widgets: list[tk.Widget] = []

        ttk.Label(form, text="输入 WAV").grid(row=1, column=0, sticky="w", pady=4)
        rx_input_entry = ttk.Entry(form, textvariable=self.rx_input_var)
        rx_input_entry.grid(row=1, column=1, sticky="ew", pady=4, padx=(6, 6))
        rx_input_button = ttk.Button(form, text="浏览…", command=self._browse_rx_input)
        rx_input_button.grid(row=1, column=2, pady=4)
        self.rx_file_widgets.extend((rx_input_entry, rx_input_button))

        ttk.Label(form, text="录音秒数").grid(row=2, column=0, sticky="w", pady=4)
        seconds = ttk.Spinbox(form, from_=1, to=86400, increment=1, textvariable=self.rx_seconds_var)
        seconds.grid(row=2, column=1, columnspan=2, sticky="ew", pady=4)
        self.rx_record_widgets.append(seconds)

        ttk.Label(form, text="输入设备").grid(row=3, column=0, sticky="w", pady=4)
        self.rx_device_combo = ttk.Combobox(form, textvariable=self.rx_device_var, state="readonly")
        self.rx_device_combo.grid(row=3, column=1, columnspan=2, sticky="ew", pady=4)
        self.rx_record_widgets.append(self.rx_device_combo)

        ttk.Label(form, text="保存录音").grid(row=4, column=0, sticky="w", pady=4)
        save_recording_entry = ttk.Entry(form, textvariable=self.rx_save_recording_var)
        save_recording_entry.grid(row=4, column=1, sticky="ew", pady=4, padx=(6, 6))
        save_recording_button = ttk.Button(
            form,
            text="浏览…",
            command=lambda: self._save_path(
                self.rx_save_recording_var, ".wav", [("WAV audio", "*.wav")]
            ),
        )
        save_recording_button.grid(row=4, column=2, pady=4)
        self.rx_record_widgets.extend((save_recording_entry, save_recording_button))

        row = 5
        row = self._path_row(
            form,
            row,
            "输出图片",
            self.rx_output_var,
            lambda: self._save_path(
                self.rx_output_var,
                ".img",
                [("Recovered image", "*.img *.png *.jpg *.jpeg *.webp"), ("All files", "*.*")],
            ),
        )
        ttk.Label(form, text="Baud").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Combobox(
            form,
            textvariable=self.rx_baud_var,
            values=(600, 1200, 2400),
            state="readonly",
        ).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
        row += 1
        row = self._path_row(
            form,
            row,
            "RX 报告",
            self.rx_report_var,
            lambda: self._save_path(self.rx_report_var, ".json", [("JSON report", "*.json")]),
        )
        self.rx_decode_button = ttk.Button(form, text="开始 RX 解码", command=self._start_rx)
        self.rx_decode_button.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(12, 0))

        side = ttk.Frame(tab)
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(0, weight=1)
        side.rowconfigure(0, weight=1)
        preview_box = ttk.LabelFrame(side, text="恢复结果", padding=8)
        preview_box.grid(row=0, column=0, sticky="nsew")
        preview_box.columnconfigure(0, weight=1)
        preview_box.rowconfigure(0, weight=1)
        self.rx_preview = ttk.Label(preview_box, text="解码完成后显示预览", anchor="center")
        self.rx_preview.grid(row=0, column=0, sticky="nsew")
        self.rx_log = self._make_log(side)
        self.rx_log.master.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

    def _path_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        command: Callable[[], None],
        *,
        filetypes: list[tuple[str, str]] | None = None,
    ) -> int:
        del filetypes  # retained for readable call sites
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, sticky="ew", pady=4, padx=(6, 6)
        )
        ttk.Button(parent, text="浏览…", command=command).grid(row=row, column=2, pady=4)
        return row + 1

    def _make_log(self, parent: ttk.Frame) -> tk.Text:
        box = ttk.LabelFrame(parent, text="运行日志", padding=6)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        text = tk.Text(box, height=9, wrap="word", state="disabled")
        scrollbar = ttk.Scrollbar(box, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        return text

    def _browse_tx_input(self) -> None:
        path = filedialog.askopenfilename(
            title="选择输入图片",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self.tx_input_var.set(path)
        source = Path(path)
        self.tx_output_var.set(str(source.with_name(f"{source.stem}-risat.wav")))
        self.tx_report_var.set(str(source.with_name(f"{source.stem}-tx-report.json")))
        self._show_preview(source, self.tx_preview, "tx")

    def _browse_rx_input(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 RISAT WAV",
            filetypes=[("WAV audio", "*.wav"), ("All files", "*.*")],
        )
        if not path:
            return
        self.rx_input_var.set(path)
        source = Path(path)
        self.rx_output_var.set(str(source.with_name(f"{source.stem}-recovered.img")))
        self.rx_report_var.set(str(source.with_name(f"{source.stem}-rx-report.json")))

    def _save_path(
        self,
        variable: tk.StringVar,
        default_extension: str,
        filetypes: list[tuple[str, str]],
    ) -> None:
        path = filedialog.asksaveasfilename(
            initialfile=Path(variable.get()).name if variable.get() else None,
            defaultextension=default_extension,
            filetypes=filetypes,
        )
        if path:
            variable.set(path)

    def _show_preview(self, path: Path, label: ttk.Label, key: str) -> None:
        try:
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail(DEFAULT_PREVIEW_SIZE, Image.Resampling.LANCZOS)
                preview = ImageTk.PhotoImage(image)
            self._preview_images[key] = preview
            label.configure(image=preview, text="")
        except Exception as exc:
            label.configure(image="", text=f"无法预览：{exc}")

    def _set_rx_mode(self) -> None:
        file_mode = self.rx_mode_var.get() == "file"
        for widget in self.rx_file_widgets:
            widget.configure(state="normal" if file_mode else "disabled")
        for widget in self.rx_record_widgets:
            if widget is self.rx_device_combo:
                widget.configure(state="disabled" if file_mode else "readonly")
            else:
                widget.configure(state="disabled" if file_mode else "normal")

    def _refresh_devices(self, initial: bool = False) -> None:
        try:
            devices = list_audio_devices()
        except RuntimeError as exc:
            if not initial:
                messagebox.showinfo("RISAT Audio", str(exc))
            self._append_log(self.tx_log, f"声卡功能未启用：{exc}")
            self._append_log(self.rx_log, f"声卡功能未启用：{exc}")
            devices = []
        except Exception as exc:
            if not initial:
                messagebox.showerror("读取声卡失败", str(exc))
            devices = []

        self._input_device_map = {"系统默认": None}
        self._output_device_map = {"系统默认": None}
        for device in devices:
            if device.input_channels >= 2:
                self._input_device_map[device.input_label] = device.index
            if device.output_channels >= 2:
                self._output_device_map[device.output_label] = device.index
        self.rx_device_combo.configure(values=tuple(self._input_device_map))
        self.tx_device_combo.configure(values=tuple(self._output_device_map))
        if self.rx_device_var.get() not in self._input_device_map:
            self.rx_device_var.set("系统默认")
        if self.tx_device_var.get() not in self._output_device_map:
            self.tx_device_var.set("系统默认")
        if not initial:
            self.status_var.set(
                f"发现 {len(self._input_device_map) - 1} 个双声道输入、"
                f"{len(self._output_device_map) - 1} 个双声道输出"
            )

    def _start_tx(self) -> None:
        try:
            config = {
                "input": self.tx_input_var.get(),
                "output": self.tx_output_var.get(),
                "resolution": self.tx_resolution_var.get(),
                "format": self.tx_format_var.get(),
                "quality": int(self.tx_quality_var.get()),
                "repeats": int(self.tx_repeats_var.get()),
                "baud": int(self.tx_baud_var.get()),
                "report": self.tx_report_var.get(),
                "play": bool(self.tx_play_var.get()),
                "device": self._output_device_map.get(
                    self.tx_device_var.get(), parse_device(self.tx_device_var.get())
                ),
            }
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("RISAT TX", f"参数格式错误：{exc}")
            return

        def work() -> dict[str, Any]:
            input_path = Path(str(config["input"])).expanduser()
            if not input_path.is_file():
                raise FileNotFoundError(f"找不到输入图片：{input_path}")
            output_path = Path(str(config["output"])).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            resolution_text = str(config["resolution"]).strip()
            resolution = None if resolution_text.lower() == "original" else parse_resolution(resolution_text)
            quality = int(config["quality"])
            repeats = int(config["repeats"])
            baud = int(config["baud"])
            if not 1 <= quality <= 100:
                raise ValueError("质量必须在 1 到 100 之间")
            if repeats < 1:
                raise ValueError("重复次数至少为 1")
            encoded = encode_image(
                input_path,
                resolution=resolution,
                output_format=str(config["format"]),
                quality=quality,
            )
            audio, report = encode_to_audio(
                input_path,
                encoded.data,
                width=encoded.width,
                height=encoded.height,
                image_format=encoded.image_format,
                repeats=repeats,
                baud=baud,
            )
            write_wav(output_path, audio)
            report_path_text = str(config["report"]).strip()
            if report_path_text:
                report_path = Path(report_path_text).expanduser()
                report_path.parent.mkdir(parents=True, exist_ok=True)
                write_report(report_path, report)
            if config["play"]:
                play_audio(audio, SAMPLE_RATE, device=config["device"])
            return {
                "path": output_path,
                "width": encoded.width,
                "height": encoded.height,
                "format": encoded.image_format,
                "duration": report["audio_seconds"],
                "frames": report["frames"],
                "bytes": report["encoded_bytes"],
            }

        def done(result: dict[str, Any]) -> None:
            message = (
                f"已生成 {result['path']}\n"
                f"{result['width']}×{result['height']} {result['format']} · "
                f"{result['duration']:.2f} 秒 · {result['frames']} 帧"
            )
            self._append_log(self.tx_log, message)
            self.status_var.set("TX 编码完成")
            messagebox.showinfo("RISAT TX", message)

        self._run_background("正在编码 TX 音频…", work, done)

    def _start_play_wav(self) -> None:
        path_text = self.tx_output_var.get()
        device = self._output_device_map.get(
            self.tx_device_var.get(), parse_device(self.tx_device_var.get())
        )

        def work() -> dict[str, Any]:
            path = Path(path_text).expanduser()
            if not path.is_file():
                raise FileNotFoundError(f"找不到 WAV：{path}")
            sample_rate, audio = read_wav(path)
            play_audio(audio, sample_rate, device=device)
            return {"path": path, "seconds": len(audio) / sample_rate}

        def done(result: dict[str, Any]) -> None:
            self._append_log(
                self.tx_log,
                f"播放完成：{result['path']}（{result['seconds']:.2f} 秒）",
            )
            self.status_var.set("播放完成")

        self._run_background("正在播放 TX WAV…", work, done)

    def _start_rx(self) -> None:
        try:
            config = {
                "mode": self.rx_mode_var.get(),
                "seconds": float(self.rx_seconds_var.get()),
                "device": self._input_device_map.get(
                    self.rx_device_var.get(), parse_device(self.rx_device_var.get())
                ),
                "save_recording": self.rx_save_recording_var.get(),
                "input": self.rx_input_var.get(),
                "baud": int(self.rx_baud_var.get()),
                "output": self.rx_output_var.get(),
                "report": self.rx_report_var.get(),
            }
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("RISAT RX", f"参数格式错误：{exc}")
            return

        def work() -> dict[str, Any]:
            if config["mode"] == "record":
                audio = record_audio(
                    float(config["seconds"]),
                    SAMPLE_RATE,
                    device=config["device"],
                    channels=2,
                )
                sample_rate = SAMPLE_RATE
                save_text = str(config["save_recording"]).strip()
                if save_text:
                    recording_path = Path(save_text).expanduser()
                    recording_path.parent.mkdir(parents=True, exist_ok=True)
                    write_wav(recording_path, audio)
            else:
                input_path = Path(str(config["input"])).expanduser()
                if not input_path.is_file():
                    raise FileNotFoundError(f"找不到输入 WAV：{input_path}")
                sample_rate, audio = read_wav(input_path)

            result, report = decode_from_audio(
                np.asarray(audio),
                sample_rate,
                baud=int(config["baud"]),
            )
            output = Path(str(config["output"])).expanduser()
            if output.suffix.lower() == ".img" or not output.suffix:
                image_format = str(result.metadata.get("format", "png")).lower()
                suffix = ".jpg" if image_format == "jpeg" else f".{image_format}"
                output = output.with_suffix(suffix)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(result.image_bytes)

            report_text = str(config["report"]).strip()
            if report_text:
                report_path = Path(report_text).expanduser()
                report_path.parent.mkdir(parents=True, exist_ok=True)
                write_report(report_path, report)
            return {
                "path": output,
                "recovered_frames": result.recovered_frames,
                "total_frames": result.total_frames,
                "speed_ratio": report["speed_ratio"],
                "candidates": report["successful_candidates"],
            }

        def done(result: dict[str, Any]) -> None:
            self._show_preview(Path(result["path"]), self.rx_preview, "rx")
            message = (
                f"已恢复 {result['path']}\n"
                f"帧：{result['recovered_frames']}/{result['total_frames']} · "
                f"速度比：{result['speed_ratio']:.6f} · "
                f"候选：{', '.join(result['candidates'])}"
            )
            self._append_log(self.rx_log, message)
            self.status_var.set("RX 解码完成")
            messagebox.showinfo("RISAT RX", message)

        action = "正在录音并解码…" if config["mode"] == "record" else "正在解码 RX 音频…"
        self._run_background(action, work, done)

    def _run_background(
        self,
        status: str,
        work: Callable[[], Any],
        done: Callable[[Any], None],
    ) -> None:
        if self._busy:
            messagebox.showwarning("RISAT", "已有任务正在运行。")
            return
        self._busy = True
        self.status_var.set(status)
        self.progress.start(12)
        self._set_action_state("disabled")

        def target() -> None:
            try:
                result = work()
            except Exception as exc:
                self._events.put(("error", exc, traceback.format_exc()))
            else:
                self._events.put(("done", done, result))

        threading.Thread(target=target, daemon=True).start()

    def _poll_events(self) -> None:
        try:
            while True:
                kind, first, second = self._events.get_nowait()
                self.progress.stop()
                self._busy = False
                self._set_action_state("normal")
                if kind == "done":
                    callback: Callable[[Any], None] = first
                    callback(second)
                else:
                    exc: Exception = first
                    trace: str = second
                    active_log = self.tx_log if self.notebook.index("current") == 0 else self.rx_log
                    self._append_log(active_log, f"错误：{exc}\n{trace}")
                    self.status_var.set("任务失败")
                    messagebox.showerror("RISAT 错误", str(exc))
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _set_action_state(self, state: str) -> None:
        self.tx_generate_button.configure(state=state)
        self.tx_play_button.configure(state=state)
        self.rx_decode_button.configure(state=state)

    @staticmethod
    def _append_log(widget: tk.Text, message: str) -> None:
        widget.configure(state="normal")
        widget.insert("end", f"{message.rstrip()}\n\n")
        widget.see("end")
        widget.configure(state="disabled")


def gui_main() -> int:
    root = tk.Tk()
    root.title("RISAT TX / RX")
    root.geometry("1040x720")
    root.minsize(900, 620)
    try:
        root.tk.call("tk", "scaling", 1.15)
    except tk.TclError:
        pass
    RISATApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(gui_main())
