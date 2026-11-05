#!/usr/bin/env python3
"""CircleHash News → social-poster connector (CLI).

Plans one scheduled post per platform for every CircleHash news post that has
not been planned before. Nothing is published by this command: entries start
as "pending" unless --approve is given, and the sp-publish timer posts
approved entries at their slot.

Usage:
    python -m connectors.circlehash_news_connector --client ghost --platforms ig --dry-run
    python -m connectors.circlehash_news_connector --client ghost --platforms ig --in-minutes 20
    python -m connectors.circlehash_news_connector --source news.json --client ghost --at 2026-11-05T18:00:00+01:00

Env vars:
    CIRCLEHASH_NEWS_URL   Public news list endpoint (default: https://www.circlehash.com/api/public/news/v1)
    CIRCLEHASH_WEB_URL    Base URL for article links   (default: https://www.circlehash.com)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "social-poster"))

from social_poster import circlehash_news  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--client", required=True, help="client id under ~/.config/social-poster/clients/")
    ap.add_argument("--platforms", default="ig", help="comma-separated social-poster short names")
    ap.add_argument("--source", default=None, help="news list URL or a saved JSON file (default: CIRCLEHASH_NEWS_URL)")
    ap.add_argument("--at", default=None, help="ISO-8601 time of the first slot")
    ap.add_argument("--in-minutes", type=int, default=15, help="first slot from now when --at is absent")
    ap.add_argument("--gap-minutes", type=int, default=30, help="minutes between consecutive posts")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--approve", action="store_true", help="create entries already approved")
    ap.add_argument("--dry-run", action="store_true", help="report only; no download, no files")
    args = ap.parse_args(argv)

    report = circlehash_news.sync(
        args.client,
        [p.strip() for p in args.platforms.split(",") if p.strip()],
        source=args.source,
        scheduled_at=datetime.fromisoformat(args.at) if args.at else None,
        in_minutes=args.in_minutes,
        gap_minutes=args.gap_minutes,
        limit=args.limit,
        approve=args.approve,
        dry_run=args.dry_run,
    )
    print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
