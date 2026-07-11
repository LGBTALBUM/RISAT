from __future__ import annotations

from string import Formatter

from risat.i18n import (
    LANGUAGE_NAMES,
    SUPPORTED_LANGUAGES,
    TRANSLATIONS,
    Translator,
    load_language,
    normalize_language,
    save_language,
)


def _fields(template: str) -> set[str]:
    return {
        field_name
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name is not None
    }


def test_catalogs_have_identical_keys_and_placeholders() -> None:
    english = TRANSLATIONS["en"]
    expected_keys = set(english)
    assert tuple(TRANSLATIONS) == SUPPORTED_LANGUAGES
    assert tuple(LANGUAGE_NAMES) == SUPPORTED_LANGUAGES

    for language, catalog in TRANSLATIONS.items():
        assert set(catalog) == expected_keys, language
        for key, template in catalog.items():
            assert _fields(template) == _fields(english[key]), (language, key)


def test_language_aliases() -> None:
    assert normalize_language("zh_TW") == "zh-TW"
    assert normalize_language("zh-Hant") == "zh-TW"
    assert normalize_language("eng") == "en"
    assert normalize_language("jpn") == "ja"
    assert normalize_language("cat") == "ca"
    assert normalize_language("unknown") == "en"


def test_language_setting_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RISAT_CONFIG_DIR", str(tmp_path))
    save_language("cat")
    assert load_language() == "ca"


def test_translator_formats_and_falls_back() -> None:
    translator = Translator("zh-TW")
    message = translator.t(
        "tx.done_message",
        path="demo.wav",
        width=320,
        height=240,
        format="jpeg",
        duration=1.25,
        frames=4,
    )
    assert "demo.wav" in message
    assert "影格" in message
    assert translator.t("missing.translation.key") == "missing.translation.key"
