"""Offline text extraction for inbound photos and explicit speech processing."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

OCR_LANGS = os.environ.get("ELO_IG_OCR_LANGS", "slk+ces+eng")
MediaReader = Callable[[Path], str]


class MediaUnavailable(RuntimeError):
    """The requested media capability has not been supplied."""


def parse_transcript_response(body: str) -> str:
    """Read a previously saved JSON or plain text transcript."""
    body = (body or "").strip()
    if body.startswith("{"):
        try:
            value = json.loads(body).get("text")
            return value.strip() if isinstance(value, str) else ""
        except ValueError:
            pass
    return body


def ffmpeg_wav_args(src: str, dst: str) -> list[str]:
    return ["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1", dst, "-loglevel", "error"]


def compose_voice_order(transcript: str) -> str:
    return transcript.strip()


def compose_photo_order(ocr: str, caption: str = "") -> str:
    parts = []
    if caption.strip():
        parts.append(caption.strip())
    if ocr.strip():
        parts.append("OCR:\n" + ocr.strip())
    return "\n".join(["[IG foto]", *parts]) if parts else ""


def transcribe(audio_path: str | Path, *, transcriber: MediaReader | None = None) -> str:
    if not callable(transcriber):
        raise MediaUnavailable("transcription_unavailable")
    return transcriber(Path(audio_path)).strip()


def ocr_available(langs: str = OCR_LANGS) -> bool:
    if not shutil.which("tesseract"):
        return False
    try:
        result = subprocess.run(["tesseract", "--list-langs"], capture_output=True,
                                text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    available = {line.strip() for line in result.stdout.splitlines()}
    return result.returncode == 0 and bool(available.intersection(langs.split("+")))


def ocr_image(image_path: str | Path, langs: str = OCR_LANGS, timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            ["tesseract", str(image_path), "stdout", "-l", langs],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def process_photo(image_path: str | Path, vision: bool | None = None, *,
                  captioner: MediaReader | None = None) -> dict[str, str]:
    """Read text offline, or use the specific caption capability selected by the caller."""
    if vision:
        if not callable(captioner):
            raise MediaUnavailable("caption_unavailable")
        caption = captioner(Path(image_path)).strip()
        ocr = ""
    else:
        if not ocr_available():
            raise MediaUnavailable("ocr_unavailable")
        ocr = ocr_image(image_path)
        caption = ""
    return {"ocr": ocr, "caption": caption, "raw_input": compose_photo_order(ocr, caption)}
