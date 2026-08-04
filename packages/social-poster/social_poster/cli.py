"""CLI entry points (declared in pyproject.toml as sp-login / sp-post / sp-delete).

Same code the bin/*.py wrappers call — separated here so the entry points work
after `pip install -e .`.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import AdapterRegistry, CampaignBuilder, SocialPoster


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


def login_cli() -> None:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <platform>")
        print(f"  platforms: {' '.join(AdapterRegistry.names())}")
        sys.exit(1)
    SocialPoster().login(sys.argv[1])


def post_cli() -> None:
    ap = argparse.ArgumentParser(prog="sp-post")
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
        os.environ["SOCIAL_POSTER_DRY_RUN"] = "1"

    poster = SocialPoster()
    poster.on("pre_post", _print_event)
    poster.on("post_success", _print_event)
    poster.on("post_failure", _print_event)

    for i, cdir in enumerate(args.campaigns):
        if i > 0 and args.gap > 0:
            print(f"\n[gap] {args.gap}s")
            import time as _t
            _t.sleep(args.gap)
        content = CampaignBuilder().from_directory(cdir).build()
        print(f"\n[{i+1}/{len(args.campaigns)}] {content}")
        poster.post(content, to=requested, prefer_video=args.video, gap_seconds=0)


def delete_cli() -> None:
    if len(sys.argv) < 3:
        print(f"usage: {sys.argv[0]} <platform> <media_id> [<media_id> ...]")
        sys.exit(1)
    poster = SocialPoster()
    platform = sys.argv[1]
    for mid in sys.argv[2:]:
        ok = poster.delete(platform, mid)
        print(f"  {'✓' if ok else '✗'} {platform} {mid}")
