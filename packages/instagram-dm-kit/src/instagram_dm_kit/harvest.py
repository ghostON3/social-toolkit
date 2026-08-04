"""harvest — turn an Instagram DM thread into a structured knowledge corpus.

The thing people actually do with Instagram: forward themselves reels, posts and
links worth remembering — a personal feed of "look at this later". That stream is
trapped in the app. ``harvest`` reads a thread and emits two machine-usable shapes:

- **records** — one JSON object per message (id, kind, text, media_url, ts),
  the full normalized log (good for media download / archival).
- **corpus** — JSONL of ``{"type": "user", "content": <text>}`` lines, the shape
  most RAG / LLM ingestion pipelines expect. Bare author handles from reel shares
  (e.g. ``somecreator`` with no caption) are dropped so only substantive prose
  (captions, link descriptions, your own notes) becomes knowledge.

Both functions are pure over a list of :class:`~instagram_dm_kit.direct.Record`
(the normalized seam — an :class:`IgMessage`, or any future source's equivalent),
so they are tested offline and reused by the CLI (``idk harvest`` / ``idk corpus``).
"""

from __future__ import annotations

import json
import re
from typing import Iterable

from .direct import Record

# A single token with no whitespace that looks like an @handle / username — the
# `text` instagrapi gives for a bare reel share is just the author's handle,
# which is a pointer, not knowledge.
_BARE_HANDLE = re.compile(r"^@?[a-z0-9._]+$", re.IGNORECASE)


def is_substantive(text: str) -> bool:
    """True if ``text`` is prose worth keeping (not blank, not a bare handle)."""
    t = (text or "").strip()
    if not t:
        return False
    if not re.search(r"\s", t) and _BARE_HANDLE.match(t):
        return False
    return True


# For a post/reel share instagrapi puts the text as "<handle> <caption>" — the
# canonical split, reused by the view layer instead of re-implementing it there.
_LEADING_HANDLE = re.compile(r"[a-z0-9._]+", re.IGNORECASE)
_SHARE_KINDS = {"other", "video", "reel_share", "post_share"}


def author_and_caption(text: str, kind: str = "") -> tuple[str, str]:
    """Split a share's ``"<handle> <caption>"`` text into ``(author, caption)``.

    Only shares (``kind`` in :data:`_SHARE_KINDS`) carry a leading author handle;
    for anything else the whole text is the caption and author is empty.
    """
    txt = (text or "").strip()
    if kind in _SHARE_KINDS and txt:
        head = txt.split(None, 1)
        if _LEADING_HANDLE.fullmatch(head[0]):
            return head[0], (head[1] if len(head) > 1 else "")
    return "", txt


def to_records(messages: Iterable[Record], include_from_me: bool = False) -> list[dict]:
    """Full normalized log — one dict per message."""
    out: list[dict] = []
    for m in messages:
        if not include_from_me and m.from_me:
            continue
        out.append(m.as_dict())
    return out


def to_corpus_lines(
    messages: Iterable[Record],
    include_from_me: bool = False,
    keep_thin: bool = False,
) -> list[str]:
    """JSONL corpus lines: ``{"type":"user","content":<text>}`` per message.

    ``keep_thin=False`` (default) drops bare author handles so only substantive
    captions / notes survive — the right default for feeding a knowledge base.

    Pure over any :class:`~instagram_dm_kit.direct.Record` (IG or a future
    source), so it stays reusable across message origins.
    """
    lines: list[str] = []
    for m in messages:
        if not include_from_me and m.from_me:
            continue
        text = (m.text or "").strip()
        if not text:
            continue
        if not keep_thin and not is_substantive(text):
            continue
        lines.append(json.dumps({"type": "user", "content": text}, ensure_ascii=False))
    return lines
