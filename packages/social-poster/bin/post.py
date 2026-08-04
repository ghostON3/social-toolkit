#!/usr/bin/env python3
"""Thin CLI wrapper around SocialPoster.post()."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from social_poster import AdapterRegistry, CampaignBuilder, SocialPoster


def _print_event(event: str, data: dict) -> None:
    if event == "pre_post":
        print(f"  [{data['platform']}] uploading…")
    elif event == "post_success":
        r = data["result"]
        marker = "✓" if not r.warning else "✓ ⚠"
        print(f"  [{data['platform']}] {marker} {r}")
        if r.warning:
            print(f"           ⚠ {r.warning}")
    elif event == "post_failure":
        print(f"  [{data['platform']}] ✗ {data['result'].error}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True, help="comma-separated platforms")
    ap.add_argument("--video", action="store_true")
    ap.add_argument("--gap", type=float, default=10.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("campaigns", nargs="+", type=Path)
    args = ap.parse_args()

    requested = [p.strip() for p in args.to.split(",") if p.strip()]
    unknown = [p for p in requested if p not in AdapterRegistry.names()]
    if unknown:
        print(f"unknown platforms: {unknown}", file=sys.stderr)
        print(f"available: {' '.join(AdapterRegistry.names())}", file=sys.stderr)
        sys.exit(2)

    if args.dry_run:
        import os
        os.environ["SOCIAL_POSTER_DRY_RUN"] = "1"

    poster = SocialPoster()
    poster.on("pre_post", _print_event)
    poster.on("post_success", _print_event)
    poster.on("post_failure", _print_event)

    for i, cdir in enumerate(args.campaigns):
        if i > 0:
            print(f"\n[gap] {args.gap}s")
        content = CampaignBuilder().from_directory(cdir).build()
        print(f"\n[{i+1}/{len(args.campaigns)}] {content}")
        poster.post(content, to=requested, prefer_video=args.video, gap_seconds=0)


if __name__ == "__main__":
    main()
