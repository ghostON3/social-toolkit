"""CircleHash News → scheduled social posts.

Reads published posts from CircleHash's public news API
(``GET /api/public/news/v1``: anonymous, the same contract the public site
uses) or from a saved JSON file with the same shape, and turns every post that
has not been seen before into one ``ContentEntry`` per platform for a client.

Nothing is published here. Entries are created as ``pending`` (or ``approved``
with ``approve=True``); the ``sp-publish`` timer posts approved entries when
their slot comes. A state file remembers which slugs were already planned, so
re-running is idempotent.
"""
from __future__ import annotations

import io
import json
import os
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .client_ledger import ClientRecord
from .scheduler import ContentEntry

DEFAULT_NEWS_URL = os.environ.get(
    "CIRCLEHASH_NEWS_URL", "https://www.circlehash.com/api/public/news/v1"
)
DEFAULT_WEB_URL = os.environ.get("CIRCLEHASH_WEB_URL", "https://www.circlehash.com")
STATE_FILE = Path(
    os.environ.get(
        "CIRCLEHASH_NEWS_STATE",
        str(Path.home() / ".config" / "social-poster" / "circlehash-news-state.json"),
    )
)


def fetch_bytes(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "*/*", "User-Agent": "social-poster/0.2"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https only in practice
        return resp.read()


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))


def load_items(source: str | Path | None = None) -> list[dict]:
    """Return the news cards from a URL or a JSON file (``{"data": {"items": []}}``)."""
    src = str(source or DEFAULT_NEWS_URL)
    raw = fetch_bytes(src) if _is_url(src) else Path(src).expanduser().read_bytes()
    doc = json.loads(raw)
    data = doc.get("data", doc) if isinstance(doc, dict) else doc
    items = data.get("items", []) if isinstance(data, dict) else data
    return [it for it in items if isinstance(it, dict) and it.get("slug") and it.get("title")]


def _get(item: dict, *keys: str) -> str | None:
    for k in keys:
        v = item.get(k)
        if v:
            return str(v)
    return None


def cover_url(item: dict) -> str | None:
    return _get(item, "cover_image_url", "coverImageUrl", "listing_image_url", "listingImageUrl")


def published_at(item: dict) -> str:
    return _get(item, "published_at", "publishedAt") or ""


def post_url(item: dict, web_url: str = DEFAULT_WEB_URL) -> str:
    """The public article URL; the contract publishes ``/blog/<slug>``."""
    return _get(item, "canonicalUrl") or f"{web_url.rstrip('/')}/blog/{item['slug']}"


def caption_parts(item: dict, web_url: str = DEFAULT_WEB_URL) -> tuple[str, str, str]:
    hook = str(item["title"]).strip()
    body = (_get(item, "lead", "seoDescription") or "").strip()
    cta = f"Read more: {post_url(item, web_url)}"
    return hook, body, cta


def to_jpeg(data: bytes, dest: Path) -> Path:
    """Instagram rejects PNG uploads, so every cover becomes a JPEG file."""
    from PIL import Image

    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(data)) as im:
        im.convert("RGB").save(dest, "JPEG", quality=90)
    return dest


def load_state(path: Path | None = None) -> dict:
    p = path or STATE_FILE
    return json.loads(p.read_text("utf-8")) if p.exists() else {}


def save_state(state: dict, path: Path | None = None) -> None:
    p = path or STATE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False), "utf-8")


@dataclass
class SyncReport:
    created: list[ContentEntry] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)       # already planned
    missing_cover: list[str] = field(default_factory=list)  # no image to post

    def as_dict(self) -> dict:
        from dataclasses import asdict

        return {
            "created": [asdict(e) for e in self.created],
            "skipped": self.skipped,
            "missing_cover": self.missing_cover,
        }


def sync(
    client_id: str,
    platforms: list[str],
    *,
    source: str | Path | None = None,
    scheduled_at: datetime | None = None,
    in_minutes: int = 15,
    gap_minutes: int = 30,
    limit: int | None = None,
    approve: bool = False,
    dry_run: bool = False,
    web_url: str = DEFAULT_WEB_URL,
    state_file: Path | None = None,
) -> SyncReport:
    """Plan one entry per platform for every unseen news post.

    ``dry_run`` reports what would be planned without downloading, writing
    entries or touching the state file.
    """
    client = ClientRecord.load(client_id)
    items = sorted(load_items(source), key=published_at, reverse=True)
    if limit:
        items = items[:limit]

    state = load_state(state_file)
    now = datetime.now(timezone.utc)
    slot = scheduled_at or (now + timedelta(minutes=in_minutes))
    if slot.tzinfo is None:
        slot = slot.replace(tzinfo=timezone.utc)

    report = SyncReport()
    for item in items:
        slug = item["slug"]
        if slug in state:
            report.skipped.append(slug)
            continue
        url = cover_url(item)
        if not url:
            report.missing_cover.append(slug)
            continue
        hook, body, cta = caption_parts(item, web_url)
        media: list[str]
        if dry_run:
            media = [url]
        else:
            media = [str(to_jpeg(fetch_bytes(url), client.dir / "media" / f"{slug}.jpg"))]

        ids: list[str] = []
        for platform in platforms:
            entry = ContentEntry(
                id=("dry-" if dry_run else "") + uuid.uuid4().hex[:16],
                client_id=client.id,
                platform=platform,
                scheduled_at=slot.isoformat(),
                hook=hook,
                body=body,
                cta=cta,
                media_urls=media,
                format="image",
                status="approved" if approve else "pending",
            )
            if not dry_run:
                entry.save(client.dir)
            report.created.append(entry)
            ids.append(entry.id)

        if not dry_run:
            state[slug] = {"entry_ids": ids, "planned_at": now.isoformat(), "title": hook}
            save_state(state, state_file)
        slot += timedelta(minutes=gap_minutes)
    return report
