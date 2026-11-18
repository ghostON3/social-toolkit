"""Offline contract for media processing."""

from pathlib import Path

import pytest

from social_poster import ig_media


def test_saved_transcript_and_offline_conversion_args():
    assert ig_media.parse_transcript_response('{"text": "  ahoj svet  "}') == "ahoj svet"
    assert ig_media.parse_transcript_response("plain text body") == "plain text body"
    assert ig_media.parse_transcript_response("") == ""
    assert ig_media.parse_transcript_response('{"nope": 1}') == ""
    assert ig_media.ffmpeg_wav_args("src", "dst")[:8] == [
        "ffmpeg", "-y", "-i", "src", "-ar", "16000", "-ac", "1",
    ]
    assert ig_media.compose_voice_order("  hello  ") == "hello"
    assert ig_media.compose_photo_order("error 42", "screenshot") == "[IG foto]\nscreenshot\nOCR:\nerror 42"


def test_missing_capabilities_decline_before_read(tmp_path, monkeypatch):
    path = tmp_path / "missing"
    monkeypatch.setattr(ig_media, "ocr_available", lambda: False)
    monkeypatch.setattr(ig_media, "ocr_image", lambda path: pytest.fail("unexpected OCR"))
    with pytest.raises(ig_media.MediaUnavailable, match="ocr_unavailable"):
        ig_media.process_photo(path)
    with pytest.raises(ig_media.MediaUnavailable, match="transcription_unavailable"):
        ig_media.transcribe(path)
    with pytest.raises(ig_media.MediaUnavailable, match="caption_unavailable"):
        ig_media.process_photo(path, vision=True)
    assert ig_media.transcribe(path, transcriber=lambda p: p.name) == "missing"


@pytest.mark.parametrize("ocr", ["", "a", "offline text"])
def test_ocr_does_not_promote_input_to_captioning(monkeypatch, ocr):
    monkeypatch.setattr(ig_media, "ocr_available", lambda: True)
    monkeypatch.setattr(ig_media, "ocr_image", lambda path: ocr)
    for mode in (None, False):
        parts = ig_media.process_photo(Path("photo"), vision=mode,
                                       captioner=lambda path: pytest.fail("unexpected caption"))
        assert parts == {"ocr": ocr, "caption": "", "raw_input": ig_media.compose_photo_order(ocr)}
    assert ig_media.compose_photo_order("") == ""



def test_ocr_availability_requires_a_usable_language_without_opening_media(monkeypatch):
    from subprocess import CompletedProcess

    monkeypatch.setattr(ig_media.shutil, "which", lambda _: "/fixture/tesseract")
    def list_langs(args, **kwargs):
        assert args == ["tesseract", "--list-langs"]
        return CompletedProcess(args, 0, stdout="List of available languages (1):\neng\n")
    monkeypatch.setattr(ig_media.subprocess, "run", list_langs)
    assert ig_media.ocr_available("slk+eng")
    assert not ig_media.ocr_available("ces")
