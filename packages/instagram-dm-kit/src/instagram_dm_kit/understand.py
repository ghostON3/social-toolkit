"""understand — watch & understand saved reels/posts with local models only.

The generic *media-understanding* half of the kit, hanging off the same
normalized :class:`~instagram_dm_kit.direct.Record` seam as the messaging half.
Per item:

    download bytes → (speech-gate) whisper transcript → qwen3-vl reads a frame
    (OCR + scene) → one structured :class:`ReelUnderstanding` record.

The speech gate is the trick: whisper is used as a *speech detector* — when it
returns real speech that's the content; when it returns music/filler (a
text-overlay reel), the vision model reads the on-screen text instead. Both
models run locally on CPU (``qwen3-vl:8b`` vision, ``faster-whisper base``
audio); nothing leaves the machine.

Public surface (all thread-parameterized, all importable):

- :func:`understand_reel` — one reel (an :class:`IgMessage`/``Record``, or a bare
  reel web-URL/pk) → one :class:`ReelUnderstanding`.
- :func:`understand_thread` — a whole thread → an ``Iterator[ReelUnderstanding]``,
  resumable (skips ids already in ``out_path``; ``retry_errors`` re-runs the
  error-marked ones), loading the whisper model **once**.

Heavy deps are optional: ``faster-whisper`` ships in the ``[understand]`` extra
and ``ffmpeg`` is a system dependency; a bare ``pip install instagram-dm-kit``
imports this module fine and only fails (with an actionable hint) at the point a
model is actually needed.

    idk understand --url  https://www.instagram.com/reel/DYZ5Ra2Rwpt/
    idk understand --thread <id> --limit 5 [--retry-errors]
"""

from __future__ import annotations

import base64
import glob
import json
import os
import subprocess
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from .direct import IgMessage, Record

OLLAMA_URL_DEFAULT = "http://localhost:11434/api/chat"
VISION_MODEL_DEFAULT = "qwen3-vl:8b"
WHISPER_SIZE_DEFAULT = "base"

# whisper's placeholder outputs for music/silence — treated as "no real speech"
# so the vision model takes over for text-overlay reels.
_JUNK_TRANSCRIPT = {
    "", "music", "[music]", "you", "thank you", "thanks for watching",
    "thanks for watching!", "bye", "...", ". .",
}


@dataclass
class ReelUnderstanding:
    """The structured record one reel resolves to (parity with the proven run)."""

    id: str
    date: Optional[str]
    author: Optional[str]
    url: Optional[str]
    transcript: str
    vision: str
    error: Optional[str]

    def as_dict(self) -> dict:
        return asdict(self)


# ---- model calls (each gated / retried; the proven config is kept verbatim) ---

def ollama_chat(
    imgs: list[str],
    prompt: str,
    *,
    model: str = VISION_MODEL_DEFAULT,
    ollama_url: str = OLLAMA_URL_DEFAULT,
) -> str:
    """One /api/chat call. ``think:False`` + no ``num_predict`` + warm keep_alive.

    Returns the message content; falls back to the ``thinking`` field (stripped)
    when a CPU run puts the answer there instead of ``content``.
    """
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": imgs}],
        "stream": False, "think": False, "keep_alive": "30m",
        # bound runaway repetition on the quantized CPU model ("70% of of of…"):
        # a generous cap still fits thinking+content, repeat_penalty curbs loops.
        "options": {"num_predict": 4096, "repeat_penalty": 1.3},
    }).encode()
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(
                ollama_url, data=body, headers={"Content-Type": "application/json"}
            ),
            timeout=1800,
        )
        msg = json.loads(r.read())["message"]
    except Exception:
        # RemoteDisconnected / URLError under memory pressure — treat as an empty
        # result so the caller's warm-retry loop retries instead of the whole
        # reel record dying with an error.
        return ""
    content = (msg.get("content") or "").strip()
    if content:
        return content
    think = (msg.get("thinking") or "").strip()
    return think.replace("<think>", "").replace("</think>", "").strip()


def ollama_vision(
    frames: list[str],
    caption: str,
    *,
    model: str = VISION_MODEL_DEFAULT,
    ollama_url: str = OLLAMA_URL_DEFAULT,
) -> str:
    """Read on-screen text + core idea from reel keyframes (3× empty-retry)."""
    imgs = [base64.b64encode(open(f, "rb").read()).decode() for f in frames]
    prompt = (
        "Keyframes from a short Instagram reel saved by a developer who builds AI "
        "agent systems. Caption/author hint: " + (caption or "(none)") + ".\n"
        "1) Transcribe ALL on-screen text verbatim.\n"
        "2) One line: the single core idea.\n"
        "3) One line 'useful_for:' — how this could apply to an AI-agent / "
        "dev-tools builder."
    )
    # qwen3-vl on CPU intermittently returns an empty message; retry warm.
    for _ in range(3):
        out = ollama_chat(imgs, prompt, model=model, ollama_url=ollama_url)
        if out:
            return out
    return ""


def load_whisper(size: str = WHISPER_SIZE_DEFAULT):
    """Load a faster-whisper model (CPU int8). Optional dep → actionable hint."""
    try:
        from faster_whisper import WhisperModel  # noqa: WPS433
    except ImportError as e:  # pragma: no cover - dependency hint
        raise RuntimeError(
            "video understanding needs the optional dependency:\n"
            "    pip install 'instagram-dm-kit[understand]'   (or: pip install faster-whisper)\n"
            "and `ffmpeg` on PATH."
        ) from e
    return WhisperModel(size, device="cpu", compute_type="int8")


def transcribe(wav: str, model: Any) -> str:
    """Transcribe a wav with a pre-loaded whisper model (loaded once per batch)."""
    segments, _ = model.transcribe(wav)
    return " ".join(s.text.strip() for s in segments).strip()


def is_real_speech(txt: str) -> bool:
    """Whisper is the detector: reject its music/filler placeholders."""
    t = (txt or "").strip().lower().strip(".!, ")
    return len(t) >= 12 and t not in _JUNK_TRANSCRIPT


# ---- ffmpeg helpers (ffmpeg is a system dep) --------------------------------

def extract_audio(mp4: str, media_dir: str | Path) -> str:
    """mp4 → 16k mono wav for whisper. Returns the wav path."""
    stem = os.path.splitext(os.path.basename(mp4))[0]
    wav = os.path.join(str(media_dir), f"{stem}.wav")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", mp4, "-ar", "16000", "-ac", "1", wav],
        check=True, timeout=120,
    )
    return wav


def extract_frames(mp4: str, media_dir: str | Path) -> list[str]:
    """Extract ONE middle keyframe (multi-image on CPU returns empty from qwen3-vl).

    Text-overlay reels settle their on-screen text around the middle, so the
    single middle frame is the reliable choice — the documented fix, not a stub.
    """
    stem = os.path.splitext(os.path.basename(mp4))[0]
    out_dir = os.path.join(str(media_dir), f"f_{stem}")
    os.makedirs(out_dir, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", mp4, "-vf", "fps=1/3,scale=640:-1",
         os.path.join(out_dir, "%02d.jpg")],
        check=True, timeout=120,
    )
    got = sorted(glob.glob(os.path.join(out_dir, "*.jpg")))
    return got[len(got) // 2:len(got) // 2 + 1] if got else []


# ---- the seam: any Record OR a bare reel url/pk becomes a downloadable msg ----

def _as_message(source: Record | str) -> IgMessage:
    """Normalize the ``understand_reel`` input to something ``download_media`` eats.

    A ``Record`` (an :class:`IgMessage`) passes through; a bare string (a reel
    web-URL or pk) is wrapped in a minimal video ``IgMessage`` so the existing
    ``IgDirect.download_media`` share-page → real-bytes path handles it.
    """
    if isinstance(source, str):
        url = source.strip()
        return IgMessage(
            id="", user_id="", from_me=False, timestamp=None,
            kind="video", item_type="clip", text="", media_url=url,
        )
    return source  # already a Record (IgMessage)


# ---- public API -------------------------------------------------------------

def understand_reel(
    source: Record | str,
    *,
    ig,
    media_dir: str | Path = "media",
    vision_model: str = VISION_MODEL_DEFAULT,
    whisper_size: str = WHISPER_SIZE_DEFAULT,
    ollama_url: str = OLLAMA_URL_DEFAULT,
    whisper_model: Any = None,
) -> ReelUnderstanding:
    """Understand a single reel → one :class:`ReelUnderstanding`.

    ``source`` is a :class:`~instagram_dm_kit.direct.Record` (e.g. an
    :class:`IgMessage` from ``ig.read_thread``) or a bare reel web-URL / pk.
    ``ig`` is an :class:`~instagram_dm_kit.direct.IgDirect` (used only to fetch
    bytes). Pass ``whisper_model`` to reuse a model already loaded for a batch;
    otherwise it is loaded on demand. Never raises — failures land in
    ``.error`` so a batch keeps going.
    """
    msg = _as_message(source)
    os.makedirs(str(media_dir), exist_ok=True)
    rec = ReelUnderstanding(
        id=str(getattr(msg, "id", "") or ""),
        date=getattr(msg, "timestamp", None),
        author=getattr(msg, "text", None),
        url=getattr(msg, "media_url", None),
        transcript="", vision="", error=None,
    )
    try:
        mp4 = ig.download_media(msg, media_dir)
        if not mp4:
            raise RuntimeError("download produced no media (private/expired share?)")
        wav = extract_audio(mp4, media_dir)
        model = whisper_model or load_whisper(whisper_size)
        rec.transcript = transcribe(wav, model)
        # whisper is the speech detector: real speech IS the content; otherwise
        # (music-only / text-overlay reel) the vision model reads the frame.
        if not is_real_speech(rec.transcript):
            frames = extract_frames(mp4, media_dir)
            rec.vision = ollama_vision(
                frames, getattr(msg, "text", "") or "",
                model=vision_model, ollama_url=ollama_url,
            )
    except Exception as e:  # noqa: BLE001 — recorded, not swallowed
        rec.error = f"{type(e).__name__}: {e}"
    return rec


def understand_thread(
    thread_id: str | int,
    *,
    ig,
    out_path: str | Path = "understanding.jsonl",
    media_dir: str | Path = "media",
    limit: Optional[int] = None,
    retry_errors: bool = False,
    vision_model: str = VISION_MODEL_DEFAULT,
    whisper_size: str = WHISPER_SIZE_DEFAULT,
    ollama_url: str = OLLAMA_URL_DEFAULT,
) -> Iterator[ReelUnderstanding]:
    """Understand every reel/clip in a thread → ``Iterator[ReelUnderstanding]``.

    Resumable: ids already present in ``out_path`` are skipped, unless
    ``retry_errors`` is set (then error-marked ids are re-run). Each result is
    appended to ``out_path`` as it completes AND yielded, so a caller can stream
    progress. The whisper model is loaded **once** for the whole batch.
    ``thread_id`` accepts any form ``resolve_thread_id`` handles (numeric id,
    ``/direct/t/`` web URL, ``@handle``).
    """
    tid = ig.resolve_thread_id(thread_id)

    prior: dict[str, dict] = {}
    out_path = str(out_path)
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    prior[rec["id"]] = rec  # last write wins on dup ids
                except Exception:
                    continue

    msgs = ig.read_thread(tid, amount=1000)
    reels = [m for m in msgs if getattr(m, "kind", "") in ("video", "reel_share")]
    if limit is not None:
        reels = reels[:limit]

    model = load_whisper(whisper_size)  # ONCE, not per item

    os.makedirs(str(media_dir), exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as sink:
        for m in reels:
            mid = str(getattr(m, "id", "") or "")
            seen = prior.get(mid)
            if seen and not (retry_errors and seen.get("error")):
                continue
            rec = understand_reel(
                m, ig=ig, media_dir=media_dir, vision_model=vision_model,
                whisper_size=whisper_size, ollama_url=ollama_url,
                whisper_model=model,
            )
            sink.write(json.dumps(rec.as_dict(), ensure_ascii=False) + "\n")
            sink.flush()
            yield rec
