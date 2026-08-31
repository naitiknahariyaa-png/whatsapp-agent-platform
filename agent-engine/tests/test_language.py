"""Tests for multi-language detection + localisation."""
from language import detect_language, localize, is_supported, SUPPORTED_LANGUAGES


def test_detect_english():
    assert detect_language("Hello, how can I help you?") == "en"


def test_detect_hindi_devanagari():
    assert detect_language("नमस्ते, आपका स्वागत है") == "hi"


def test_detect_tamil_script():
    assert detect_language("வணக்கம், நீங்கள் எப்படி இருக்கிறீர்கள்") == "ta"


def test_detect_telugu_script():
    assert detect_language("నమస్కారం, మీరు ఎలా ఉన్నారు") == "te"


def test_detect_bengali_script():
    assert detect_language("নমস্কার, আপনি কেমন আছেন") == "bn"


def test_detect_romanised_hinglish():
    assert detect_language("namaste bhai, kaise ho aap") == "hi"


def test_detect_romanised_tamil():
    assert detect_language("vanakkam nga, eppadi irukkinga") == "ta"


def test_fallback_to_english():
    assert detect_language("") == "en"
    assert detect_language("asdfqwerty") == "en"


def test_localize_returns_template():
    for lang in SUPPORTED_LANGUAGES:
        out = localize("greeting", lang)
        assert isinstance(out, str) and len(out) > 0


def test_localize_unknown_language_falls_back():
    assert localize("greeting", "xx") == localize("greeting", "en")


def test_is_supported():
    assert is_supported("hi") and not is_supported("xx")
