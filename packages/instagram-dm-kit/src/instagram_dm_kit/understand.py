"""Analyze reels with a single capability selected by the calling application.

Recorded results use the same JSONL schema as earlier releases. A caller must
select either transcription or frame description before new media is accessed.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

from .direct import IgMessage, Record

Transcriber = Callable[[str], str]
FrameReader = Callable[[list[str], str], str]


class MediaCapabilityError(ValueError):
    """Analysis needs exactly one capability for this operation."""


def require_capability(transcriber: Transcriber | None, describe_frames: FrameReader | None) -> None:
    if transcriber is None and describe_frames is None:
        raise MediaCapabilityError("analysis_capability_unavailable")
    if transcriber is not None and describe_frames is not None:
        raise MediaCapabilityError("analysis_capability_ambiguous")
    if not callable(transcriber) and not callable(describe_frames):
        raise MediaCapabilityError("analysis_capability_invalid")


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


def is_real_speech(txt: str) -> bool:
    """Reject music and filler placeholders in recorded transcripts."""
    t = (txt or "").strip().lower().strip(".!, ")
    return len(t) >= 12 and t not in _JUNK_TRANSCRIPT


# ---- ffmpeg helpers (ffmpeg is a system dep) --------------------------------

def extract_audio(mp4: str, media_dir: str | Path) -> str:
    """Extract 16 kHz mono audio and return the WAV path."""
    stem = os.path.splitext(os.path.basename(mp4))[0]
    wav = os.path.join(str(media_dir), f"{stem}.wav")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", mp4, "-ar", "16000", "-ac", "1", wav],
        check=True, timeout=120,
    )
    return wav


def extract_frames(mp4: str, media_dir: str | Path) -> list[str]:
    """Extract a middle keyframe for the selected frame reader."""
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
    transcriber: Transcriber | None = None,
    describe_frames: FrameReader | None = None,
) -> ReelUnderstanding:
    """Analyze one record or URL using the selected capability."""
    try:
        require_capability(transcriber, describe_frames)
    except MediaCapabilityError as exc:
        return ReelUnderstanding("", None, None, None, "", "", str(exc))
    msg = _as_message(source)
    rec = ReelUnderstanding(
        id=str(getattr(msg, "id", "") or ""),
        date=getattr(msg, "timestamp", None),
        author=getattr(msg, "text", None),
        url=getattr(msg, "media_url", None),
        transcript="", vision="", error=None,
    )
    try:
        os.makedirs(str(media_dir), exist_ok=True)
        mp4 = ig.download_media(msg, media_dir)
        if not mp4:
            raise RuntimeError("download produced no media (private/expired share?)")
        if transcriber is not None:
            rec.transcript = transcriber(extract_audio(mp4, media_dir))
        elif describe_frames is not None:
            frames = extract_frames(mp4, media_dir)
            if not frames:
                raise RuntimeError("no frames available")
            rec.vision = describe_frames(frames, msg.text or "")
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
    transcriber: Transcriber | None = None,
    describe_frames: FrameReader | None = None,
) -> Iterator[ReelUnderstanding]:
    """Append results per reel and skip completed IDs unless retrying errors.

    An unavailable or ambiguous capability raises before accessing the thread,
    local media, or the record file.
    """
    require_capability(transcriber, describe_frames)
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

    os.makedirs(str(media_dir), exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as sink:
        for m in reels:
            mid = str(getattr(m, "id", "") or "")
            seen = prior.get(mid)
            if seen and not (retry_errors and seen.get("error")):
                continue
            rec = understand_reel(
                m, ig=ig, media_dir=media_dir, transcriber=transcriber,
                describe_frames=describe_frames,
            )
            sink.write(json.dumps(rec.as_dict(), ensure_ascii=False) + "\n")
            sink.flush()
            yield rec
