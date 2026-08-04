"""view — turn a harvested records file into a browsable, human view.

The reusable rendering half of the kit: given a list of normalized records (or a
path to a ``records.jsonl`` produced by ``idk harvest``), emit a chronological
markdown feed plus a flat links table (csv + jsonl). Nothing is dropped — reels,
post-shares, external links, images, voice notes and your own text notes all
survive with their url + caption + date.

The pure helpers (:func:`clean_url`, :func:`first_line`, :func:`primary_url`) are
importable and unit-tested offline; author/caption splitting is delegated to
:func:`instagram_dm_kit.harvest.author_and_caption` so the logic lives in one
place. IG-specific bits (reel/p/tv permalink canonicalization, fbcdn handling,
kind icon/label maps) live here, on the IG adapter side.

    idk view --records thread.records.jsonl --out ./view
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .harvest import author_and_caption

KIND_ICON = {
    "video": "🎬", "other": "📄", "link": "🔗", "text": "📝",
    "media": "🖼", "external_share": "🌐", "voice": "🎙",
    "reel_share": "🎬", "post_share": "📄", "story_share": "📖",
    "placeholder": "…", "gif": "🎞", "visual": "👁", "igtv_share": "📺",
}
KIND_LABEL = {
    "video": "reel", "other": "post", "link": "link", "text": "note",
    "media": "image", "external_share": "external", "voice": "voice note",
    "placeholder": "expired", "reel_share": "reel", "post_share": "post",
}

_IG_CODE = re.compile(r"/(reel|p|tv)/([A-Za-z0-9_-]+)")


def clean_url(url: str) -> str:
    """Strip IG tracking cruft; canonicalize reel/post permalinks. Pure."""
    if not url:
        return url
    m = _IG_CODE.search(url)
    if "instagram.com" in url and m:
        kind, code = m.group(1), m.group(2)
        return f"https://www.instagram.com/{kind}/{code}/"
    parts = urlsplit(url)
    if parts.netloc.endswith("fbcdn.net"):  # signed CDN — keep whole (expires otherwise)
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def first_line(text: str, n: int = 120) -> str:
    """First line of ``text``, newline-flattened and clamped to ``n`` chars."""
    t = (text or "").strip().replace("\n", " ⏎ ")
    return t[:n] + ("…" if len(t) > n else "")


def primary_url(r: dict) -> str:
    """The single best clickable url for a record (media, or a link's text)."""
    return clean_url(r.get("media_url") or (r.get("text") if r.get("kind") == "link" else "") or "")


def render_markdown(rows: list[dict]) -> tuple[str, list[dict]]:
    """Pure: records → (markdown string, extracted link rows). No file I/O."""
    rows = sorted(rows, key=lambda r: r.get("timestamp") or "")  # oldest → newest
    span = ""
    if rows:
        span = f"{(rows[0].get('timestamp') or '')[:10]} → {(rows[-1].get('timestamp') or '')[:10]}"
    md = [
        "# instagram-dm-kit — saved thread",
        "",
        f"**{len(rows)} messages** · {span}  ",
        "Every reel, post, link, image, voice note and note you saved. Newest at the bottom.",
        "",
    ]
    link_rows: list[dict] = []
    cur_day = None
    for r in rows:
        ts = r.get("timestamp") or ""
        day = ts[:10]
        if day != cur_day:
            cur_day = day
            md.append(f"\n## {day}\n")
        kind = r.get("kind", "")
        icon = KIND_ICON.get(kind, "•")
        label = KIND_LABEL.get(kind, kind)
        author, caption = author_and_caption(r.get("text") or "", kind)
        url = primary_url(r)
        clock = ts[11:16]

        bits = [f"- `{clock}` {icon} **{label}**"]
        if author:
            bits.append(f" · @{author}")
        if url:
            bits.append(f" · [{'open' if kind != 'link' else url}]({url})")
        md.append("".join(bits))
        if caption:
            md.append(f"    > {first_line(caption, 300)}")

        if url:
            link_rows.append({
                "date": ts, "kind": label, "author": author, "url": url,
                "caption": first_line(caption, 500), "message_id": r.get("id"),
            })
    return "\n".join(md) + "\n", link_rows


def _load_records(records: list[dict] | str | Path) -> list[dict]:
    """Accept an in-memory record list OR a path to a records.jsonl."""
    if isinstance(records, (str, Path)):
        with open(records, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    return list(records)


def build_view(records: list[dict] | str | Path, out_dir: str | Path) -> dict:
    """Write ``inspiration.md`` + ``links.{csv,jsonl}`` for a set of records.

    ``records`` is an in-memory list (e.g. ``to_records(ig.read_thread(...))``)
    or a path to a ``records.jsonl`` — never a hardcoded filename. Returns a
    small summary of what was written.
    """
    rows = _load_records(records)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    markdown, link_rows = render_markdown(rows)
    (out / "inspiration.md").write_text(markdown, encoding="utf-8")

    with open(out / "links.jsonl", "w", encoding="utf-8") as fh:
        for lr in link_rows:
            fh.write(json.dumps(lr, ensure_ascii=False) + "\n")

    with open(out / "links.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["date", "kind", "author", "url", "caption", "message_id"]
        )
        w.writeheader()
        w.writerows(link_rows)

    return {
        "messages": len(rows),
        "links": len(link_rows),
        "by_kind": dict(Counter(lr["kind"] for lr in link_rows)),
        "out_dir": str(out),
    }
