from __future__ import annotations

import json
import locale
import os
import platform
from pathlib import Path
from typing import Final

DEFAULT_LANGUAGE: Final = "en"
SUPPORTED_LANGUAGES: Final = ("zh-TW", "en", "ja", "ca")
LANGUAGE_NAMES: Final = {
    "zh-TW": "繁體中文",
    "en": "English",
    "ja": "日本語",
    "ca": "Català",
}

_EN = {
    "app.subtitle": "Image ⇄ stereo RCA / analog audio media",
    "language.label": "Language",
    "language.changed": "Language changed to {language}",
    "language.busy": "The language cannot be changed while a task is running.",
    "audio.refresh": "Refresh audio devices",
    "audio.title": "RISAT Audio",
    "audio.disabled": "Audio-device support is unavailable: {error}",
    "audio.read_failed_title": "Failed to read audio devices",
    "audio.device_summary": "Found {inputs} stereo input(s) and {outputs} stereo output(s)",
    "tab.tx": "TX encode / transmit",
    "tab.rx": "RX decode / receive",
    "status.ready": "Ready",
    "status.tx_done": "TX encoding complete",
    "status.encoding": "Encoding TX audio…",
    "status.play_done": "Playback complete",
    "status.playing": "Playing TX WAV…",
    "status.rx_done": "RX decoding complete",
    "status.recording_decode": "Recording and decoding…",
    "status.decoding": "Decoding RX audio…",
    "status.failed": "Task failed",
    "tx.group": "TX settings",
    "tx.play_after": "Play through the audio device after generation",
    "tx.generate": "Generate TX WAV",
    "tx.play_existing": "Play existing WAV",
    "tx.done_message": (
        "Generated {path}\n{width}×{height} {format} · "
        "{duration:.2f} seconds · {frames} frames"
    ),
    "tx.play_done": "Playback complete: {path} ({seconds:.2f} seconds)",
    "rx.group": "RX settings",
    "rx.read_wav": "Read WAV",
    "rx.record_card": "Record from audio device",
    "rx.decode": "Start RX decoding",
    "rx.done_message": (
        "Recovered {path}\nFrames: {recovered}/{total} · "
        "speed ratio: {speed:.6f} · baud: {baud} · candidates: {candidates}"
    ),
    "label.input_image": "Input image",
    "label.output_wav": "Output WAV",
    "label.max_resolution": "Maximum resolution",
    "label.format": "Format",
    "label.quality": "Quality",
    "label.baud": "Baud",
    "label.repeats": "Repetitions",
    "label.tx_report": "TX report",
    "label.output_device": "Output device",
    "label.input_wav": "Input WAV",
    "label.record_seconds": "Recording duration (seconds)",
    "label.input_device": "Input device",
    "label.save_recording": "Save recording",
    "label.output_image": "Output image",
    "label.rx_report": "RX report",
    "preview.image_title": "Image preview",
    "preview.image_hint": "Select an image to show its preview",
    "preview.result_title": "Recovered result",
    "preview.result_hint": "The preview appears after decoding",
    "preview.failed": "Unable to preview: {error}",
    "common.browse": "Browse…",
    "common.log": "Run log",
    "device.system_default": "System default",
    "resolution.original": "original",
    "baud.auto": "Auto",
    "file.image": "Image files",
    "file.all": "All files",
    "file.wav": "WAV audio",
    "file.json": "JSON report",
    "file.recovered_image": "Recovered image",
    "dialog.choose_image": "Select input image",
    "dialog.choose_wav": "Select RISAT WAV",
    "error.parameter": "Invalid parameter format: {error}",
    "error.input_image_missing": "Input image not found: {path}",
    "error.quality_range": "Quality must be between 1 and 100",
    "error.repeats_min": "Repetitions must be at least 1",
    "error.wav_missing": "WAV not found: {path}",
    "error.input_wav_missing": "Input WAV not found: {path}",
    "error.title": "RISAT error",
    "error.log": "Error: {error}\n{trace}",
    "error.tk_required": (
        "RISAT GUI requires Tk. On Debian/Ubuntu install python3-tk; "
        "Windows and python.org macOS builds normally include it."
    ),
    "warning.busy": "A task is already running.",
}

_ZH_TW = {
    "app.subtitle": "圖片 ⇄ 雙聲道 RCA / 類比音訊媒體",
    "language.label": "語言",
    "language.changed": "語言已切換為{language}",
    "language.busy": "工作執行期間無法切換語言。",
    "audio.refresh": "重新整理音訊裝置",
    "audio.title": "RISAT 音訊",
    "audio.disabled": "音訊裝置功能尚未啟用：{error}",
    "audio.read_failed_title": "讀取音訊裝置失敗",
    "audio.device_summary": "找到 {inputs} 個雙聲道輸入、{outputs} 個雙聲道輸出",
    "tab.tx": "TX 編碼 / 傳送",
    "tab.rx": "RX 解碼 / 接收",
    "status.ready": "就緒",
    "status.tx_done": "TX 編碼完成",
    "status.encoding": "正在編碼 TX 音訊…",
    "status.play_done": "播放完成",
    "status.playing": "正在播放 TX WAV…",
    "status.rx_done": "RX 解碼完成",
    "status.recording_decode": "正在錄音並解碼…",
    "status.decoding": "正在解碼 RX 音訊…",
    "status.failed": "工作失敗",
    "tx.group": "TX 參數",
    "tx.play_after": "產生後立即從音訊裝置播放",
    "tx.generate": "產生 TX WAV",
    "tx.play_existing": "播放現有 WAV",
    "tx.done_message": (
        "已產生 {path}\n{width}×{height} {format} · "
        "{duration:.2f} 秒 · {frames} 影格"
    ),
    "tx.play_done": "播放完成：{path}（{seconds:.2f} 秒）",
    "rx.group": "RX 參數",
    "rx.read_wav": "讀取 WAV",
    "rx.record_card": "從音訊裝置錄音",
    "rx.decode": "開始 RX 解碼",
    "rx.done_message": (
        "已復原 {path}\n影格：{recovered}/{total} · "
        "速度比：{speed:.6f} · Baud：{baud} · 候選：{candidates}"
    ),
    "label.input_image": "輸入圖片",
    "label.output_wav": "輸出 WAV",
    "label.max_resolution": "最大解析度",
    "label.format": "格式",
    "label.quality": "品質",
    "label.baud": "Baud",
    "label.repeats": "重複次數",
    "label.tx_report": "TX 報告",
    "label.output_device": "輸出裝置",
    "label.input_wav": "輸入 WAV",
    "label.record_seconds": "錄音秒數",
    "label.input_device": "輸入裝置",
    "label.save_recording": "儲存錄音",
    "label.output_image": "輸出圖片",
    "label.rx_report": "RX 報告",
    "preview.image_title": "圖片預覽",
    "preview.image_hint": "選擇圖片後顯示預覽",
    "preview.result_title": "復原結果",
    "preview.result_hint": "解碼完成後顯示預覽",
    "preview.failed": "無法預覽：{error}",
    "common.browse": "瀏覽…",
    "common.log": "執行記錄",
    "device.system_default": "系統預設",
    "resolution.original": "原始尺寸",
    "baud.auto": "自動",
    "file.image": "圖片檔案",
    "file.all": "所有檔案",
    "file.wav": "WAV 音訊",
    "file.json": "JSON 報告",
    "file.recovered_image": "復原圖片",
    "dialog.choose_image": "選擇輸入圖片",
    "dialog.choose_wav": "選擇 RISAT WAV",
    "error.parameter": "參數格式錯誤：{error}",
    "error.input_image_missing": "找不到輸入圖片：{path}",
    "error.quality_range": "品質必須介於 1 到 100 之間",
    "error.repeats_min": "重複次數至少為 1",
    "error.wav_missing": "找不到 WAV：{path}",
    "error.input_wav_missing": "找不到輸入 WAV：{path}",
    "error.title": "RISAT 錯誤",
    "error.log": "錯誤：{error}\n{trace}",
    "error.tk_required": (
        "RISAT GUI 需要 Tk。Debian/Ubuntu 請安裝 python3-tk；"
        "Windows 與 python.org 的 macOS Python 通常已內建。"
    ),
    "warning.busy": "已有工作正在執行。",
}

_JA = {
    "app.subtitle": "画像 ⇄ ステレオ RCA / アナログ音声メディア",
    "language.label": "言語",
    "language.changed": "言語を{language}に変更しました",
    "language.busy": "処理中は言語を変更できません。",
    "audio.refresh": "オーディオデバイスを更新",
    "audio.title": "RISAT オーディオ",
    "audio.disabled": "オーディオデバイス機能を利用できません：{error}",
    "audio.read_failed_title": "オーディオデバイスの読み込みに失敗しました",
    "audio.device_summary": "ステレオ入力 {inputs} 件、ステレオ出力 {outputs} 件を検出しました",
    "tab.tx": "TX エンコード / 送信",
    "tab.rx": "RX デコード / 受信",
    "status.ready": "準備完了",
    "status.tx_done": "TX エンコード完了",
    "status.encoding": "TX 音声をエンコードしています…",
    "status.play_done": "再生完了",
    "status.playing": "TX WAV を再生しています…",
    "status.rx_done": "RX デコード完了",
    "status.recording_decode": "録音してデコードしています…",
    "status.decoding": "RX 音声をデコードしています…",
    "status.failed": "処理に失敗しました",
    "tx.group": "TX 設定",
    "tx.play_after": "生成後にオーディオデバイスから再生する",
    "tx.generate": "TX WAV を生成",
    "tx.play_existing": "既存 WAV を再生",
    "tx.done_message": (
        "{path} を生成しました\n{width}×{height} {format} · "
        "{duration:.2f} 秒 · {frames} フレーム"
    ),
    "tx.play_done": "再生完了：{path}（{seconds:.2f} 秒）",
    "rx.group": "RX 設定",
    "rx.read_wav": "WAV を読み込む",
    "rx.record_card": "オーディオデバイスから録音",
    "rx.decode": "RX デコード開始",
    "rx.done_message": (
        "{path} を復元しました\nフレーム：{recovered}/{total} · "
        "速度比：{speed:.6f} · Baud：{baud} · 候補：{candidates}"
    ),
    "label.input_image": "入力画像",
    "label.output_wav": "出力 WAV",
    "label.max_resolution": "最大解像度",
    "label.format": "形式",
    "label.quality": "品質",
    "label.baud": "Baud",
    "label.repeats": "反復回数",
    "label.tx_report": "TX レポート",
    "label.output_device": "出力デバイス",
    "label.input_wav": "入力 WAV",
    "label.record_seconds": "録音秒数",
    "label.input_device": "入力デバイス",
    "label.save_recording": "録音を保存",
    "label.output_image": "出力画像",
    "label.rx_report": "RX レポート",
    "preview.image_title": "画像プレビュー",
    "preview.image_hint": "画像を選択するとプレビューを表示します",
    "preview.result_title": "復元結果",
    "preview.result_hint": "デコード完了後にプレビューを表示します",
    "preview.failed": "プレビューできません：{error}",
    "common.browse": "参照…",
    "common.log": "実行ログ",
    "device.system_default": "システム既定",
    "resolution.original": "元のサイズ",
    "baud.auto": "自動",
    "file.image": "画像ファイル",
    "file.all": "すべてのファイル",
    "file.wav": "WAV 音声",
    "file.json": "JSON レポート",
    "file.recovered_image": "復元画像",
    "dialog.choose_image": "入力画像を選択",
    "dialog.choose_wav": "RISAT WAV を選択",
    "error.parameter": "パラメータ形式が正しくありません：{error}",
    "error.input_image_missing": "入力画像が見つかりません：{path}",
    "error.quality_range": "品質は 1～100 の範囲で指定してください",
    "error.repeats_min": "反復回数は 1 以上にしてください",
    "error.wav_missing": "WAV が見つかりません：{path}",
    "error.input_wav_missing": "入力 WAV が見つかりません：{path}",
    "error.title": "RISAT エラー",
    "error.log": "エラー：{error}\n{trace}",
    "error.tk_required": (
        "RISAT GUI には Tk が必要です。Debian/Ubuntu では python3-tk をインストールしてください。"
        "Windows および python.org の macOS 版 Python には通常含まれています。"
    ),
    "warning.busy": "別の処理が実行中です。",
}

_CA = {
    "app.subtitle": "Imatge ⇄ RCA estèreo / suport d'àudio analògic",
    "language.label": "Idioma",
    "language.changed": "L'idioma s'ha canviat a {language}",
    "language.busy": "No es pot canviar l'idioma mentre hi ha una tasca en curs.",
    "audio.refresh": "Actualitza els dispositius d'àudio",
    "audio.title": "Àudio RISAT",
    "audio.disabled": "El suport de dispositius d'àudio no està disponible: {error}",
    "audio.read_failed_title": "No s'han pogut llegir els dispositius d'àudio",
    "audio.device_summary": "S'han trobat {inputs} entrada/es i {outputs} sortida/es estèreo",
    "tab.tx": "Codificació / transmissió TX",
    "tab.rx": "Descodificació / recepció RX",
    "status.ready": "Preparat",
    "status.tx_done": "Codificació TX completada",
    "status.encoding": "S'està codificant l'àudio TX…",
    "status.play_done": "Reproducció completada",
    "status.playing": "S'està reproduint el WAV TX…",
    "status.rx_done": "Descodificació RX completada",
    "status.recording_decode": "S'està enregistrant i descodificant…",
    "status.decoding": "S'està descodificant l'àudio RX…",
    "status.failed": "La tasca ha fallat",
    "tx.group": "Paràmetres TX",
    "tx.play_after": "Reprodueix pel dispositiu d'àudio després de generar",
    "tx.generate": "Genera el WAV TX",
    "tx.play_existing": "Reprodueix un WAV existent",
    "tx.done_message": (
        "S'ha generat {path}\n{width}×{height} {format} · "
        "{duration:.2f} segons · {frames} trames"
    ),
    "tx.play_done": "Reproducció completada: {path} ({seconds:.2f} segons)",
    "rx.group": "Paràmetres RX",
    "rx.read_wav": "Llegeix un WAV",
    "rx.record_card": "Enregistra des del dispositiu d'àudio",
    "rx.decode": "Inicia la descodificació RX",
    "rx.done_message": (
        "S'ha recuperat {path}\nTrames: {recovered}/{total} · "
        "relació de velocitat: {speed:.6f} · baud: {baud} · candidats: {candidates}"
    ),
    "label.input_image": "Imatge d'entrada",
    "label.output_wav": "WAV de sortida",
    "label.max_resolution": "Resolució màxima",
    "label.format": "Format",
    "label.quality": "Qualitat",
    "label.baud": "Baud",
    "label.repeats": "Repeticions",
    "label.tx_report": "Informe TX",
    "label.output_device": "Dispositiu de sortida",
    "label.input_wav": "WAV d'entrada",
    "label.record_seconds": "Durada de l'enregistrament (segons)",
    "label.input_device": "Dispositiu d'entrada",
    "label.save_recording": "Desa l'enregistrament",
    "label.output_image": "Imatge de sortida",
    "label.rx_report": "Informe RX",
    "preview.image_title": "Previsualització de la imatge",
    "preview.image_hint": "Selecciona una imatge per previsualitzar-la",
    "preview.result_title": "Resultat recuperat",
    "preview.result_hint": "La previsualització apareixerà després de descodificar",
    "preview.failed": "No es pot previsualitzar: {error}",
    "common.browse": "Examina…",
    "common.log": "Registre d'execució",
    "device.system_default": "Predeterminat del sistema",
    "resolution.original": "mida original",
    "baud.auto": "Automàtic",
    "file.image": "Fitxers d'imatge",
    "file.all": "Tots els fitxers",
    "file.wav": "Àudio WAV",
    "file.json": "Informe JSON",
    "file.recovered_image": "Imatge recuperada",
    "dialog.choose_image": "Selecciona la imatge d'entrada",
    "dialog.choose_wav": "Selecciona el WAV RISAT",
    "error.parameter": "El format dels paràmetres no és vàlid: {error}",
    "error.input_image_missing": "No s'ha trobat la imatge d'entrada: {path}",
    "error.quality_range": "La qualitat ha d'estar entre 1 i 100",
    "error.repeats_min": "El nombre de repeticions ha de ser com a mínim 1",
    "error.wav_missing": "No s'ha trobat el WAV: {path}",
    "error.input_wav_missing": "No s'ha trobat el WAV d'entrada: {path}",
    "error.title": "Error de RISAT",
    "error.log": "Error: {error}\n{trace}",
    "error.tk_required": (
        "La interfície RISAT necessita Tk. A Debian/Ubuntu instal·leu python3-tk; "
        "les versions de Python per a Windows i macOS de python.org normalment ja l'inclouen."
    ),
    "warning.busy": "Ja hi ha una tasca en curs.",
}

TRANSLATIONS: Final = {
    "zh-TW": _ZH_TW,
    "en": _EN,
    "ja": _JA,
    "ca": _CA,
}

_ALIASES: Final = {
    "zh": "zh-TW",
    "zh-tw": "zh-TW",
    "zh_tw": "zh-TW",
    "zh-hant": "zh-TW",
    "zh_hant": "zh-TW",
    "zh-hk": "zh-TW",
    "zh-mo": "zh-TW",
    "tw": "zh-TW",
    "en": "en",
    "eng": "en",
    "english": "en",
    "ja": "ja",
    "jpn": "ja",
    "jp": "ja",
    "japanese": "ja",
    "ca": "ca",
    "cat": "ca",
    "catalan": "ca",
}


def normalize_language(value: str | None) -> str:
    if not value:
        return DEFAULT_LANGUAGE
    normalized = value.strip().replace("_", "-").lower()
    if normalized in _ALIASES:
        return _ALIASES[normalized]
    prefix = normalized.split("-", 1)[0]
    return _ALIASES.get(prefix, DEFAULT_LANGUAGE)


def detect_language() -> str:
    forced = os.environ.get("RISAT_LANG")
    if forced:
        return normalize_language(forced)
    candidates = [
        locale.getlocale()[0],
        os.environ.get("LC_ALL"),
        os.environ.get("LC_MESSAGES"),
        os.environ.get("LANG"),
    ]
    for candidate in candidates:
        if candidate:
            return normalize_language(candidate.split(".", 1)[0])
    return DEFAULT_LANGUAGE


def config_directory() -> Path:
    override = os.environ.get("RISAT_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    system = platform.system()
    if system == "Windows" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "RISAT"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "RISAT"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "risat"


def settings_path() -> Path:
    return config_directory() / "settings.json"


def load_language() -> str:
    path = settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get("language")
        if isinstance(value, str):
            return normalize_language(value)
    except (OSError, ValueError, TypeError):
        pass
    return detect_language()


def save_language(language: str) -> None:
    code = normalize_language(language)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"language": code}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class Translator:
    def __init__(self, language: str | None = None) -> None:
        self.language = normalize_language(language or load_language())

    def set_language(self, language: str) -> None:
        self.language = normalize_language(language)

    def t(self, key: str, **values: object) -> str:
        catalog = TRANSLATIONS.get(self.language, _EN)
        template = catalog.get(key, _EN.get(key, key))
        return template.format(**values) if values else template
