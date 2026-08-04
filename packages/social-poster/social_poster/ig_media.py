"""Process IG voice notes and photos the way the rest of ghost's stack does.

* **voice** → ffmpeg transcode to 16k mono WAV → whisper.cpp server (`/inference`,
  the same large-v3 ROCm server the repo's STT uses) → transcript text.
* **photo** → tesseract OCR (slk+ces+eng, the `elo-shot` default — instant) and,
  optionally, a `qwen3-vl:8b` vision caption via ollama (the `elo-shot` "qwen"
  engine; ~2 min/image on this ROCm GPU, so off by default behind a flag).

The transcript / extracted text then flows into the dispatch bridge exactly like
a typed message would — voice becomes a spoken task, a photo's content becomes
order context. Network/subprocess lives here; the pure request-shaping and
response-parsing helpers are unit-tested offline.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional

WHISPER_URL = os.environ.get("ELO_WHISPER_URL", "http://127.0.0.1:8771/inference")
OLLAMA_URL = os.environ.get("ELO_OLLAMA_URL", "http://localhost:11434")
VISION_MODEL = os.environ.get("ELO_IG_VISION_MODEL", "qwen3-vl:8b")
# elo-shot lang set; slk+ces+eng all installed on this box.
OCR_LANGS = os.environ.get("ELO_IG_OCR_LANGS", "slk+ces+eng")
# qwen3-vl caption is high quality but ~2 min/image — opt in.
VISION_ENABLED = os.environ.get("ELO_IG_VISION", "0").strip() not in {"", "0", "false", "no"}

VISION_PROMPT = (
    "Describe this image concisely in one or two sentences. If it contains UI, "
    "code, a screenshot or any text, say what it shows. Answer in the language "
    "of the visible text, else English."
)


# ---- pure helpers (unit-tested) --------------------------------------------
def parse_whisper_response(body: str) -> str:
    """whisper.cpp /inference returns {"text": "..."} (or plain text)."""
    body = (body or "").strip()
    if not body:
        return ""
    if body[0] in "{[":
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                return str(data.get("text", "")).strip()
        except Exception:
            pass
    return body


def ffmpeg_wav_args(src: str, dst: str) -> list[str]:
    """Args to transcode any audio (IG voice = .m4a) → 16 kHz mono WAV."""
    return ["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1", dst, "-loglevel", "error"]


def build_ollama_vision_payload(image_b64: str, model: str = VISION_MODEL,
                                prompt: str = VISION_PROMPT) -> dict:
    return {"model": model, "prompt": prompt, "images": [image_b64], "stream": False}


def compose_voice_order(transcript: str) -> str:
    return transcript.strip()


def compose_photo_order(ocr: str, caption: str = "") -> str:
    """Build the order rawInput from a photo's extracted content."""
    parts: list[str] = ["[IG foto]"]
    if caption.strip():
        parts.append(caption.strip())
    if ocr.strip():
        parts.append("OCR:\n" + ocr.strip())
    if len(parts) == 1:
        parts.append("(žiadny text/popis rozpoznaný)")
    return "\n".join(parts)


# ---- IO functions ----------------------------------------------------------
def transcribe(audio_path: str | Path, whisper_url: str = WHISPER_URL,
               timeout: int = 120) -> str:
    """Voice file → transcript via ffmpeg + whisper.cpp server."""
    src = Path(audio_path)
    wav = src.with_suffix(".16k.wav")
    subprocess.run(ffmpeg_wav_args(str(src), str(wav)), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        body, content_type = _multipart_file(str(wav), field="file",
                                              extra={"response_format": "json"})
        req = urllib.request.Request(whisper_url, data=body, method="POST")
        req.add_header("content-type", content_type)
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (localhost)
            return parse_whisper_response(resp.read().decode(errors="replace"))
    finally:
        try:
            wav.unlink()
        except Exception:
            pass


def ocr_image(image_path: str | Path, langs: str = OCR_LANGS, timeout: int = 60) -> str:
    """Photo → text via tesseract (the elo-shot default engine)."""
    try:
        out = subprocess.run(
            ["tesseract", str(image_path), "stdout", "-l", langs],
            capture_output=True, text=True, timeout=timeout,
        )
        return (out.stdout or "").strip()
    except Exception:
        return ""


def caption_image(image_path: str | Path, ollama_url: str = OLLAMA_URL,
                  timeout: int = 180) -> str:
    """Photo → one-line vision caption via qwen3-vl (ollama). Best-effort."""
    try:
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
        payload = build_ollama_vision_payload(b64)
        req = urllib.request.Request(
            f"{ollama_url}/api/generate",
            data=json.dumps(payload).encode(),
            method="POST",
        )
        req.add_header("content-type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (localhost)
            data = json.loads(resp.read().decode(errors="replace") or "{}")
            return str(data.get("response", "")).strip()
    except Exception:
        return ""


def process_photo(image_path: str | Path, vision: Optional[bool] = None) -> dict:
    """Run OCR (always) + caption (if enabled or OCR is empty). Returns parts."""
    ocr = ocr_image(image_path)
    use_vision = VISION_ENABLED if vision is None else vision
    caption = ""
    if use_vision or len(ocr) < 8:
        caption = caption_image(image_path)
    return {"ocr": ocr, "caption": caption, "raw_input": compose_photo_order(ocr, caption)}


def _multipart_file(path: str, field: str = "file", extra: Optional[dict] = None):
    """Minimal multipart/form-data body for a single file + text fields."""
    import mimetypes
    import uuid

    boundary = uuid.uuid4().hex
    name = Path(path).name
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    pre = b""
    for k, v in (extra or {}).items():
        pre += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
        ).encode()
    pre += (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
        f"filename=\"{name}\"\r\nContent-Type: {ctype}\r\n\r\n"
    ).encode()
    post = f"\r\n--{boundary}--\r\n".encode()
    body = pre + Path(path).read_bytes() + post
    return body, f"multipart/form-data; boundary={boundary}"
