#!/usr/bin/env python3
"""StrojX → social-poster connector.

Fetches public machinery listings from StrojX's API and posts them
to configured social platforms via social-poster's SocialPoster facade.

Usage:
    python -m connectors.strojx_connector --platforms ig,bsky,telegram --dry-run
    python -m connectors.strojx_connector --since 2026-09-01 --limit 5

Env vars:
    STROJX_API_URL   Base URL of the StrojX API  (default: http://localhost:4000)
    STROJX_WEB_URL   Base URL for public listing links (default: http://localhost:3000)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "social-poster"))

from social_poster import CampaignBuilder, SocialPoster

STATE_FILE = Path.home() / ".strojx-social-state.json"
STROJX_API_URL = os.environ.get("STROJX_API_URL", "http://localhost:4000")
STROJX_WEB_URL = os.environ.get("STROJX_WEB_URL", "http://localhost:3000")

CONDITION_SK = {
    "NEW": "Nový",
    "USED": "Použitý",
    "REFURBISHED": "Renovovaný",
}


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text("utf-8"))
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), "utf-8")


def _fetch_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_listings(since: str | None = None, limit: int | None = None) -> list[dict]:
    url = f"{STROJX_API_URL}/api/v1/public/advertisements"
    data = _fetch_json(url)
    items = data if isinstance(data, list) else data.get("data", data.get("items", []))

    if since:
        cutoff = datetime.fromisoformat(since)
        items = [
            it for it in items
            if datetime.fromisoformat(it.get("publishedAt", "1970-01-01T00:00:00")) >= cutoff
        ]

    items.sort(key=lambda it: it.get("publishedAt", ""), reverse=True)

    if limit:
        items = items[:limit]

    return items


def download_media(media_list: list[dict], dest: Path) -> list[Path]:
    paths = []
    for i, m in enumerate(media_list):
        if m.get("kind", "IMAGE") != "IMAGE":
            continue
        url = m.get("url")
        if not url:
            continue
        ext = ".jpg"
        if ".png" in url.lower():
            ext = ".png"
        out = dest / f"{i:02d}{ext}"
        try:
            urllib.request.urlretrieve(url, out)
            paths.append(out)
        except urllib.error.URLError:
            continue
    return paths


def format_price(price: dict | None) -> str:
    if not price:
        return "Cena na vyžiadanie"
    amount = price.get("amountMinor", 0)
    currency = price.get("currency", "EUR")
    human = f"{amount / 100:,.0f}".replace(",", " ")
    vat = ""
    if price.get("vatMode") == "EXCLUDING":
        vat = " bez DPH"
    elif price.get("vatMode") == "INCLUDING":
        vat = " s DPH"
    negotiable = " (dohodou)" if price.get("negotiable") else ""
    return f"{human} {currency}{vat}{negotiable}"


def build_caption(listing: dict) -> str:
    manufacturer = listing.get("manufacturer", "")
    model = listing.get("model", "")
    year = listing.get("yearOfManufacture", "")
    title = f"{manufacturer} {model}".strip()
    if year:
        title += f" ({year})"

    condition = CONDITION_SK.get(listing.get("condition", ""), listing.get("condition", ""))
    hours = listing.get("operatingHours")
    hours_str = f" • {hours:,} mth".replace(",", " ") if hours else ""

    price_str = format_price(listing.get("price"))

    parts = [listing.get("city"), listing.get("region"), listing.get("country")]
    location = ", ".join(p for p in parts if p)

    slug = listing.get("slug", "")
    link = f"{STROJX_WEB_URL}/inzerat/{slug}" if slug else ""

    lines = [title]
    if condition or hours_str:
        lines.append(f"{condition}{hours_str}")
    lines.append(price_str)
    if location:
        lines.append(f"📍 {location}")
    if link:
        lines.append("")
        lines.append(link)

    return "\n".join(lines)


def build_hashtags(listing: dict) -> str:
    tags = ["#strojx", "#stroje", "#stavebnestroje"]

    manufacturer = listing.get("manufacturer", "").lower().replace(" ", "")
    if manufacturer:
        tags.append(f"#{manufacturer}")

    condition = listing.get("condition", "").lower()
    if condition:
        tags.append(f"#{condition}")

    country = listing.get("country", "").lower().replace(" ", "")
    if country:
        tags.append(f"#{country}")

    return " ".join(dict.fromkeys(tags))


def post_listing(listing: dict, poster: SocialPoster, platforms: list[str], tmpdir: Path) -> bool:
    slug = listing.get("slug", "unknown")
    media = listing.get("media", [])

    media_dir = tmpdir / slug
    media_dir.mkdir(exist_ok=True)

    slides = download_media(media, media_dir)

    builder = (
        CampaignBuilder()
        .named(slug)
        .with_caption(build_caption(listing))
        .with_first_comment(build_hashtags(listing))
    )

    for slide in slides:
        builder.add_slide(slide)

    videos = [m for m in media if m.get("kind") == "VIDEO" and m.get("url")]
    if videos:
        video_path = media_dir / "video.mp4"
        try:
            urllib.request.urlretrieve(videos[0]["url"], video_path)
            builder.with_video(video_path)
        except urllib.error.URLError:
            pass

    content = builder.build()
    print(f"  [{slug}] {content}")

    results = poster.post(content, to=platforms)
    ok = all(r.ok for r in results.values())

    for platform, result in results.items():
        marker = "✓" if result.ok else "✗"
        print(f"    [{platform}] {marker} {result}")

    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description="Post StrojX listings to social media")
    ap.add_argument("--platforms", default="ig,bsky,telegram", help="comma-separated platforms")
    ap.add_argument("--dry-run", action="store_true", help="don't actually post")
    ap.add_argument("--since", help="only listings published after this ISO date")
    ap.add_argument("--limit", type=int, help="max listings to process")
    ap.add_argument("--force", action="store_true", help="re-post already-posted listings")
    args = ap.parse_args()

    if args.dry_run:
        os.environ["SOCIAL_POSTER_DRY_RUN"] = "1"

    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]

    print(f"Fetching listings from {STROJX_API_URL} …")
    try:
        listings = fetch_listings(since=args.since, limit=args.limit)
    except urllib.error.URLError as e:
        print(f"Failed to reach StrojX API: {e}", file=sys.stderr)
        sys.exit(1)

    if not listings:
        print("No listings found.")
        return

    state = _load_state()
    to_post = []
    for listing in listings:
        slug = listing.get("slug", "")
        if not args.force and slug in state:
            continue
        to_post.append(listing)

    if not to_post:
        print(f"All {len(listings)} listings already posted. Use --force to re-post.")
        return

    print(f"Posting {len(to_post)}/{len(listings)} new listings to {', '.join(platforms)} …\n")

    poster = SocialPoster()
    posted = 0

    with tempfile.TemporaryDirectory(prefix="strojx-social-") as tmpdir:
        for listing in to_post:
            slug = listing.get("slug", "")
            ok = post_listing(listing, poster, platforms, Path(tmpdir))
            if ok or args.dry_run:
                state[slug] = {
                    "posted_at": datetime.now().isoformat(),
                    "platforms": platforms,
                }
                posted += 1

    _save_state(state)
    print(f"\nDone. Posted {posted}/{len(to_post)} listings.")


if __name__ == "__main__":
    main()
