"""Offline tests for the IG media (voice/photo) processing helpers — the pure
request-shaping and response-parsing parts. The whisper/tesseract/ollama IO is
exercised by hand / live."""

from social_poster.ig_media import (
    build_ollama_vision_payload,
    compose_photo_order,
    compose_voice_order,
    ffmpeg_wav_args,
    parse_whisper_response,
)


def test_parse_whisper_json_and_plain():
    assert parse_whisper_response('{"text": "  ahoj svet  "}') == "ahoj svet"
    assert parse_whisper_response("plain text body") == "plain text body"
    assert parse_whisper_response("") == ""
    assert parse_whisper_response('{"nope": 1}') == ""


def test_ffmpeg_args_target_16k_mono_wav():
    args = ffmpeg_wav_args("/in/voice.m4a", "/out/voice.wav")
    assert args[0] == "ffmpeg"
    assert "/in/voice.m4a" in args
    assert "/out/voice.wav" in args
    assert "16000" in args and "1" in args  # 16 kHz, mono


def test_ollama_vision_payload_shape():
    p = build_ollama_vision_payload("BASE64DATA", model="qwen3-vl:8b", prompt="describe")
    assert p["model"] == "qwen3-vl:8b"
    assert p["stream"] is False
    assert p["images"] == ["BASE64DATA"]
    assert p["prompt"] == "describe"


def test_compose_voice_order_trims():
    assert compose_voice_order("  uprav booking page  ") == "uprav booking page"


def test_compose_photo_order_variants():
    both = compose_photo_order("n+ ERROR line 42", "screenshot of a stack trace")
    assert both.startswith("[IG foto]")
    assert "screenshot of a stack trace" in both
    assert "OCR:" in both and "ERROR line 42" in both

    ocr_only = compose_photo_order("just ocr text", "")
    assert "OCR:" in ocr_only and "just ocr text" in ocr_only

    empty = compose_photo_order("", "")
    assert "žiadny text" in empty
