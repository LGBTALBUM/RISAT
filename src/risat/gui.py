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
from .i18n import LANGUAGE_NAMES, Translator, load_language, save_language
from .image_codec import encode_image, parse_resolution
from .modem import DEFAULT_BAUD, SAMPLE_RATE

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError as exc:  # pragma: no cover - depends on the platform Python build
    raise RuntimeError(Translator(load_language()).t("error.tk_required")) from exc


DEFAULT_PREVIEW_SIZE = (360, 240)


class RISATApp(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=12)
        self.master = master
        self.i18n = Translator(load_language())
        self._language_name_to_code = {name: code for code, name in LANGUAGE_NAMES.items()}
        self._events: queue.Queue[tuple[str, Any, Any]] = queue.Queue()
        self._busy = False
        self._preview_images: dict[str, ImageTk.PhotoImage] = {}
        self._preview_paths: dict[str, Path] = {}
        self._input_device_map: dict[str, int | str | None] = {}
        self._output_device_map: dict[str, int | str | None] = {}

        self.grid(row=0, column=0, sticky="nsew")
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._init_variables()
        self._build_ui()
        self._refresh_devices(initial=True)
        self.after(100, self._poll_events)

    def t(self, key: str, **values: object) -> str:
        return self.i18n.t(key, **values)

    def _init_variables(self) -> None:
        self.language_var = tk.StringVar(value=LANGUAGE_NAMES[self.i18n.language])
        self.status_var = tk.StringVar(value=self.t("status.ready"))

        self.tx_input_var = tk.StringVar()
        self.tx_output_var = tk.StringVar(value="risat-tx.wav")
        self.tx_resolution_var = tk.StringVar(value="640x480")
        self.tx_format_var = tk.StringVar(value="jpeg")
        self.tx_quality_var = tk.IntVar(value=70)
        self.tx_baud_var = tk.IntVar(value=DEFAULT_BAUD)
        self.tx_repeats_var = tk.IntVar(value=3)
        self.tx_report_var = tk.StringVar(value="tx-report.json")
        self.tx_play_var = tk.BooleanVar(value=False)
        self.tx_device_var = tk.StringVar(value=self.t("device.system_default"))

        self.rx_mode_var = tk.StringVar(value="file")
        self.rx_input_var = tk.StringVar()
        self.rx_output_var = tk.StringVar(value="risat-recovered.img")
        self.rx_baud_var = tk.StringVar(value=self.t("baud.auto"))
        self.rx_report_var = tk.StringVar(value="risat-rx-report.json")
        self.rx_seconds_var = tk.DoubleVar(value=90.0)
        self.rx_save_recording_var = tk.StringVar(value="capture.wav")
        self.rx_device_var = tk.StringVar(value=self.t("device.system_default"))

    def _build_ui(self) -> None:
        self._build_header()
        self._build_notebook()
        self._build_footer()
        self._set_rx_mode()

    def _build_header(self) -> None:
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="RISAT TX / RX", font=("TkDefaultFont", 18, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(header, text=self.t("app.subtitle")).grid(row=1, column=0, sticky="w")

        controls = ttk.Frame(header)
        controls.grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))
        ttk.Label(controls, text=self.t("language.label")).grid(row=0, column=0, sticky="e")
        self.language_combo = ttk.Combobox(
            controls,
            textvariable=self.language_var,
            values=tuple(LANGUAGE_NAMES.values()),
            state="readonly",
            width=13,
        )
        self.language_combo.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.language_combo.bind("<<ComboboxSelected>>", self._on_language_selected)
        self.refresh_button = ttk.Button(
            controls,
            text=self.t("audio.refresh"),
            command=self._refresh_devices,
        )
        self.refresh_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    def _build_notebook(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1, column=0, sticky="nsew")

        self.tx_tab = ttk.Frame(self.notebook, padding=12)
        self.rx_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.tx_tab, text=self.t("tab.tx"))
        self.notebook.add(self.rx_tab, text=self.t("tab.rx"))
        self._build_tx_tab()
        self._build_rx_tab()

    def _build_footer(self) -> None:
        footer = ttk.Frame(self)
        footer.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(1, weight=1)
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=160)
        self.progress.grid(row=0, column=0, padx=(0, 10))
        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=1, sticky="w")

    def _build_tx_tab(self) -> None:
        tab = self.tx_tab
        tab.columnconfigure(0, weight=3)
        tab.columnconfigure(1, weight=2)
        tab.rowconfigure(0, weight=1)

        form = ttk.LabelFrame(tab, text=self.t("tx.group"), padding=12)
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        form.columnconfigure(1, weight=1)

        row = 0
        row = self._path_row(
            form,
            row,
            self.t("label.input_image"),
            self.tx_input_var,
            self._browse_tx_input,
        )
        row = self._path_row(
            form,
            row,
            self.t("label.output_wav"),
            self.tx_output_var,
            lambda: self._save_path(
                self.tx_output_var,
                ".wav",
                [(self.t("file.wav"), "*.wav")],
            ),
        )

        ttk.Label(form, text=self.t("label.max_resolution")).grid(
            row=row, column=0, sticky="w", pady=4
        )
        resolution = ttk.Combobox(
            form,
            textvariable=self.tx_resolution_var,
            values=("320x240", "640x480", "1280x720", self.t("resolution.original")),
        )
        resolution.grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        options = ttk.Frame(form)
        options.grid(row=row, column=0, columnspan=3, sticky="ew", pady=4)
        for column in range(6):
            options.columnconfigure(column, weight=1 if column % 2 else 0)
        ttk.Label(options, text=self.t("label.format")).grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            options,
            textvariable=self.tx_format_var,
            values=("jpeg", "png", "webp"),
            state="readonly",
            width=8,
        ).grid(row=0, column=1, sticky="ew", padx=(4, 12))
        ttk.Label(options, text=self.t("label.quality")).grid(row=0, column=2, sticky="w")
        ttk.Spinbox(options, from_=1, to=100, textvariable=self.tx_quality_var, width=7).grid(
            row=0, column=3, sticky="ew", padx=(4, 12)
        )
        ttk.Label(options, text=self.t("label.baud")).grid(row=0, column=4, sticky="w")
        ttk.Combobox(
            options,
            textvariable=self.tx_baud_var,
            values=(600, 1200, 2400),
            state="readonly",
            width=8,
        ).grid(row=0, column=5, sticky="ew", padx=(4, 0))
        row += 1

        ttk.Label(form, text=self.t("label.repeats")).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Spinbox(form, from_=1, to=15, textvariable=self.tx_repeats_var).grid(
            row=row, column=1, sticky="ew", pady=4
        )
        row += 1
        row = self._path_row(
            form,
            row,
            self.t("label.tx_report"),
            self.tx_report_var,
            lambda: self._save_path(
                self.tx_report_var,
                ".json",
                [(self.t("file.json"), "*.json")],
            ),
        )

        ttk.Checkbutton(form, text=self.t("tx.play_after"), variable=self.tx_play_var).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(8, 4)
        )
        row += 1
        ttk.Label(form, text=self.t("label.output_device")).grid(
            row=row, column=0, sticky="w", pady=4
        )
        self.tx_device_combo = ttk.Combobox(form, textvariable=self.tx_device_var, state="readonly")
        self.tx_device_combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
        row += 1

        actions = ttk.Frame(form)
        actions.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.tx_generate_button = ttk.Button(actions, text=self.t("tx.generate"), command=self._start_tx)
        self.tx_generate_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.tx_play_button = ttk.Button(
            actions,
            text=self.t("tx.play_existing"),
            command=self._start_play_wav,
        )
        self.tx_play_button.grid(row=0, column=1, sticky="ew", padx=(5, 0))

        side = ttk.Frame(tab)
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(0, weight=1)
        side.rowconfigure(0, weight=1)
        preview_box = ttk.LabelFrame(side, text=self.t("preview.image_title"), padding=8)
        preview_box.grid(row=0, column=0, sticky="nsew")
        preview_box.columnconfigure(0, weight=1)
        preview_box.rowconfigure(0, weight=1)
        self.tx_preview = ttk.Label(preview_box, text=self.t("preview.image_hint"), anchor="center")
        self.tx_preview.grid(row=0, column=0, sticky="nsew")
        self.tx_log = self._make_log(side)
        self.tx_log.master.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

    def _build_rx_tab(self) -> None:
        tab = self.rx_tab
        tab.columnconfigure(0, weight=3)
        tab.columnconfigure(1, weight=2)
        tab.rowconfigure(0, weight=1)

        form = ttk.LabelFrame(tab, text=self.t("rx.group"), padding=12)
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        form.columnconfigure(1, weight=1)

        mode = ttk.Frame(form)
        mode.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Radiobutton(
            mode,
            text=self.t("rx.read_wav"),
            value="file",
            variable=self.rx_mode_var,
            command=self._set_rx_mode,
        ).grid(row=0, column=0, padx=(0, 16))
        ttk.Radiobutton(
            mode,
            text=self.t("rx.record_card"),
            value="record",
            variable=self.rx_mode_var,
            command=self._set_rx_mode,
        ).grid(row=0, column=1)

        self.rx_file_widgets: list[tk.Widget] = []
        self.rx_record_widgets: list[tk.Widget] = []

        ttk.Label(form, text=self.t("label.input_wav")).grid(row=1, column=0, sticky="w", pady=4)
        rx_input_entry = ttk.Entry(form, textvariable=self.rx_input_var)
        rx_input_entry.grid(row=1, column=1, sticky="ew", pady=4, padx=(6, 6))
        rx_input_button = ttk.Button(form, text=self.t("common.browse"), command=self._browse_rx_input)
        rx_input_button.grid(row=1, column=2, pady=4)
        self.rx_file_widgets.extend((rx_input_entry, rx_input_button))

        ttk.Label(form, text=self.t("label.record_seconds")).grid(
            row=2, column=0, sticky="w", pady=4
        )
        seconds = ttk.Spinbox(form, from_=1, to=86400, increment=1, textvariable=self.rx_seconds_var)
        seconds.grid(row=2, column=1, columnspan=2, sticky="ew", pady=4)
        self.rx_record_widgets.append(seconds)

        ttk.Label(form, text=self.t("label.input_device")).grid(
            row=3, column=0, sticky="w", pady=4
        )
        self.rx_device_combo = ttk.Combobox(form, textvariable=self.rx_device_var, state="readonly")
        self.rx_device_combo.grid(row=3, column=1, columnspan=2, sticky="ew", pady=4)
        self.rx_record_widgets.append(self.rx_device_combo)

        ttk.Label(form, text=self.t("label.save_recording")).grid(
            row=4, column=0, sticky="w", pady=4
        )
        save_recording_entry = ttk.Entry(form, textvariable=self.rx_save_recording_var)
        save_recording_entry.grid(row=4, column=1, sticky="ew", pady=4, padx=(6, 6))
        save_recording_button = ttk.Button(
            form,
            text=self.t("common.browse"),
            command=lambda: self._save_path(
                self.rx_save_recording_var,
                ".wav",
                [(self.t("file.wav"), "*.wav")],
            ),
        )
        save_recording_button.grid(row=4, column=2, pady=4)
        self.rx_record_widgets.extend((save_recording_entry, save_recording_button))

        row = 5
        row = self._path_row(
            form,
            row,
            self.t("label.output_image"),
            self.rx_output_var,
            lambda: self._save_path(
                self.rx_output_var,
                ".img",
                [
                    (self.t("file.recovered_image"), "*.img *.png *.jpg *.jpeg *.webp"),
                    (self.t("file.all"), "*.*"),
                ],
            ),
        )
        ttk.Label(form, text=self.t("label.baud")).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Combobox(
            form,
            textvariable=self.rx_baud_var,
            values=(self.t("baud.auto"), "600", "1200", "2400"),
            state="readonly",
        ).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
        row += 1
        row = self._path_row(
            form,
            row,
            self.t("label.rx_report"),
            self.rx_report_var,
            lambda: self._save_path(
                self.rx_report_var,
                ".json",
                [(self.t("file.json"), "*.json")],
            ),
        )
        self.rx_decode_button = ttk.Button(form, text=self.t("rx.decode"), command=self._start_rx)
        self.rx_decode_button.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(12, 0))

        side = ttk.Frame(tab)
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(0, weight=1)
        side.rowconfigure(0, weight=1)
        preview_box = ttk.LabelFrame(side, text=self.t("preview.result_title"), padding=8)
        preview_box.grid(row=0, column=0, sticky="nsew")
        preview_box.columnconfigure(0, weight=1)
        preview_box.rowconfigure(0, weight=1)
        self.rx_preview = ttk.Label(preview_box, text=self.t("preview.result_hint"), anchor="center")
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
    ) -> int:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, sticky="ew", pady=4, padx=(6, 6)
        )
        ttk.Button(parent, text=self.t("common.browse"), command=command).grid(
            row=row, column=2, pady=4
        )
        return row + 1

    def _make_log(self, parent: ttk.Frame) -> tk.Text:
        box = ttk.LabelFrame(parent, text=self.t("common.log"), padding=6)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        text = tk.Text(box, height=9, width=44, wrap="word", state="disabled")
        scrollbar = ttk.Scrollbar(box, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        return text

    def _on_language_selected(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        selected = self._language_name_to_code.get(self.language_var.get())
        if not selected or selected == self.i18n.language:
            return
        if self._busy:
            self.language_var.set(LANGUAGE_NAMES[self.i18n.language])
            messagebox.showwarning("RISAT", self.t("language.busy"))
            return
        self._switch_language(selected)

    def _switch_language(self, language: str) -> None:
        old_default = self.t("device.system_default")
        old_auto = self.t("baud.auto")
        old_original = self.t("resolution.original")
        selected_tab = self.notebook.index("current") if hasattr(self, "notebook") else 0
        tx_log = self._read_log(self.tx_log) if hasattr(self, "tx_log") else ""
        rx_log = self._read_log(self.rx_log) if hasattr(self, "rx_log") else ""

        self.i18n.set_language(language)
        try:
            save_language(language)
        except OSError as exc:
            messagebox.showerror(self.t("error.title"), str(exc))

        if self.tx_device_var.get() == old_default:
            self.tx_device_var.set(self.t("device.system_default"))
        if self.rx_device_var.get() == old_default:
            self.rx_device_var.set(self.t("device.system_default"))
        if self.rx_baud_var.get() == old_auto:
            self.rx_baud_var.set(self.t("baud.auto"))
        if self.tx_resolution_var.get() == old_original:
            self.tx_resolution_var.set(self.t("resolution.original"))
        self.language_var.set(LANGUAGE_NAMES[self.i18n.language])

        for child in self.winfo_children():
            child.destroy()
        self._preview_images.clear()
        self._build_ui()
        self._refresh_devices(initial=True, log_unavailable=False)
        self._restore_log(self.tx_log, tx_log)
        self._restore_log(self.rx_log, rx_log)
        for key, label in (("tx", self.tx_preview), ("rx", self.rx_preview)):
            path = self._preview_paths.get(key)
            if path is not None:
                self._show_preview(path, label, key)
        self.notebook.select(min(selected_tab, 1))
        self.status_var.set(
            self.t("language.changed", language=LANGUAGE_NAMES[self.i18n.language])
        )

    @staticmethod
    def _read_log(widget: tk.Text) -> str:
        return widget.get("1.0", "end-1c")

    @staticmethod
    def _restore_log(widget: tk.Text, content: str) -> None:
        if not content:
            return
        widget.configure(state="normal")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def _browse_tx_input(self) -> None:
        path = filedialog.askopenfilename(
            title=self.t("dialog.choose_image"),
            filetypes=[
                (self.t("file.image"), "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"),
                (self.t("file.all"), "*.*"),
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
            title=self.t("dialog.choose_wav"),
            filetypes=[
                (self.t("file.wav"), "*.wav"),
                (self.t("file.all"), "*.*"),
            ],
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
        self._preview_paths[key] = path
        try:
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail(DEFAULT_PREVIEW_SIZE, Image.Resampling.LANCZOS)
                preview = ImageTk.PhotoImage(image)
            self._preview_images[key] = preview
            label.configure(image=preview, text="")
        except Exception as exc:
            label.configure(image="", text=self.t("preview.failed", error=exc))

    def _set_rx_mode(self) -> None:
        file_mode = self.rx_mode_var.get() == "file"
        for widget in self.rx_file_widgets:
            widget.configure(state="normal" if file_mode else "disabled")
        for widget in self.rx_record_widgets:
            if widget is self.rx_device_combo:
                widget.configure(state="disabled" if file_mode else "readonly")
            else:
                widget.configure(state="disabled" if file_mode else "normal")

    def _refresh_devices(self, initial: bool = False, log_unavailable: bool = True) -> None:
        try:
            devices = list_audio_devices()
        except RuntimeError as exc:
            if not initial:
                messagebox.showinfo(self.t("audio.title"), str(exc))
            if log_unavailable:
                message = self.t("audio.disabled", error=exc)
                self._append_log(self.tx_log, message)
                self._append_log(self.rx_log, message)
            devices = []
        except Exception as exc:
            if not initial:
                messagebox.showerror(self.t("audio.read_failed_title"), str(exc))
            devices = []

        default_label = self.t("device.system_default")
        self._input_device_map = {default_label: None}
        self._output_device_map = {default_label: None}
        for device in devices:
            if device.input_channels >= 2:
                self._input_device_map[device.input_label] = device.index
            if device.output_channels >= 2:
                self._output_device_map[device.output_label] = device.index
        self.rx_device_combo.configure(values=tuple(self._input_device_map))
        self.tx_device_combo.configure(values=tuple(self._output_device_map))
        if self.rx_device_var.get() not in self._input_device_map:
            self.rx_device_var.set(default_label)
        if self.tx_device_var.get() not in self._output_device_map:
            self.tx_device_var.set(default_label)
        if not initial:
            self.status_var.set(
                self.t(
                    "audio.device_summary",
                    inputs=len(self._input_device_map) - 1,
                    outputs=len(self._output_device_map) - 1,
                )
            )

    @staticmethod
    def _resolve_device(
        label: str,
        devices: dict[str, int | str | None],
    ) -> int | str | None:
        return devices[label] if label in devices else parse_device(label)

    def _start_tx(self) -> None:
        try:
            config = {
                "input": self.tx_input_var.get(),
                "output": self.tx_output_var.get(),
                "resolution": self.tx_resolution_var.get(),
                "original_resolution": self.t("resolution.original"),
                "format": self.tx_format_var.get(),
                "quality": int(self.tx_quality_var.get()),
                "repeats": int(self.tx_repeats_var.get()),
                "baud": int(self.tx_baud_var.get()),
                "report": self.tx_report_var.get(),
                "play": bool(self.tx_play_var.get()),
                "device": self._resolve_device(
                    self.tx_device_var.get(),
                    self._output_device_map,
                ),
            }
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("RISAT TX", self.t("error.parameter", error=exc))
            return

        def work() -> dict[str, Any]:
            input_path = Path(str(config["input"])).expanduser()
            if not input_path.is_file():
                raise FileNotFoundError(self.t("error.input_image_missing", path=input_path))
            output_path = Path(str(config["output"])).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            resolution_text = str(config["resolution"]).strip()
            resolution = (
                None
                if resolution_text == config["original_resolution"]
                else parse_resolution(resolution_text)
            )
            quality = int(config["quality"])
            repeats = int(config["repeats"])
            baud = int(config["baud"])
            if not 1 <= quality <= 100:
                raise ValueError(self.t("error.quality_range"))
            if repeats < 1:
                raise ValueError(self.t("error.repeats_min"))
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
            message = self.t(
                "tx.done_message",
                path=result["path"],
                width=result["width"],
                height=result["height"],
                format=result["format"],
                duration=result["duration"],
                frames=result["frames"],
            )
            self._append_log(self.tx_log, message)
            self.status_var.set(self.t("status.tx_done"))
            messagebox.showinfo("RISAT TX", message)

        self._run_background(self.t("status.encoding"), work, done)

    def _start_play_wav(self) -> None:
        path_text = self.tx_output_var.get()
        device = self._resolve_device(self.tx_device_var.get(), self._output_device_map)

        def work() -> dict[str, Any]:
            path = Path(path_text).expanduser()
            if not path.is_file():
                raise FileNotFoundError(self.t("error.wav_missing", path=path))
            sample_rate, audio = read_wav(path)
            play_audio(audio, sample_rate, device=device)
            return {"path": path, "seconds": len(audio) / sample_rate}

        def done(result: dict[str, Any]) -> None:
            self._append_log(
                self.tx_log,
                self.t("tx.play_done", path=result["path"], seconds=result["seconds"]),
            )
            self.status_var.set(self.t("status.play_done"))

        self._run_background(self.t("status.playing"), work, done)

    def _start_rx(self) -> None:
        try:
            baud_value = self.rx_baud_var.get()
            config = {
                "mode": self.rx_mode_var.get(),
                "seconds": float(self.rx_seconds_var.get()),
                "device": self._resolve_device(
                    self.rx_device_var.get(),
                    self._input_device_map,
                ),
                "save_recording": self.rx_save_recording_var.get(),
                "input": self.rx_input_var.get(),
                "baud": None if baud_value == self.t("baud.auto") else int(baud_value),
                "output": self.rx_output_var.get(),
                "report": self.rx_report_var.get(),
            }
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("RISAT RX", self.t("error.parameter", error=exc))
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
                    raise FileNotFoundError(self.t("error.input_wav_missing", path=input_path))
                sample_rate, audio = read_wav(input_path)

            result, report = decode_from_audio(
                np.asarray(audio),
                sample_rate,
                baud=config["baud"],
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
                "detected_baud": report["detected_baud"],
            }

        def done(result: dict[str, Any]) -> None:
            self._show_preview(Path(result["path"]), self.rx_preview, "rx")
            message = self.t(
                "rx.done_message",
                path=result["path"],
                recovered=result["recovered_frames"],
                total=result["total_frames"],
                speed=result["speed_ratio"],
                baud=result["detected_baud"],
                candidates=", ".join(result["candidates"]),
            )
            self._append_log(self.rx_log, message)
            self.status_var.set(self.t("status.rx_done"))
            messagebox.showinfo("RISAT RX", message)

        action = (
            self.t("status.recording_decode")
            if config["mode"] == "record"
            else self.t("status.decoding")
        )
        self._run_background(action, work, done)

    def _run_background(
        self,
        status: str,
        work: Callable[[], Any],
        done: Callable[[Any], None],
    ) -> None:
        if self._busy:
            messagebox.showwarning("RISAT", self.t("warning.busy"))
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
                    self._append_log(
                        active_log,
                        self.t("error.log", error=exc, trace=trace),
                    )
                    self.status_var.set(self.t("status.failed"))
                    messagebox.showerror(self.t("error.title"), str(exc))
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _set_action_state(self, state: str) -> None:
        self.tx_generate_button.configure(state=state)
        self.tx_play_button.configure(state=state)
        self.rx_decode_button.configure(state=state)
        self.refresh_button.configure(state=state)
        self.language_combo.configure(state="disabled" if state == "disabled" else "readonly")

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
