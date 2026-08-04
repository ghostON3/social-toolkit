#!/usr/bin/env python3
"""Thin CLI wrapper around SocialPoster.delete()."""
from __future__ import annotations

import sys

from social_poster import SocialPoster


def main() -> None:
    if len(sys.argv) < 3:
        print(f"usage: {sys.argv[0]} <platform> <media_id> [<media_id> ...]")
        sys.exit(1)
    poster = SocialPoster()
    platform = sys.argv[1]
    for mid in sys.argv[2:]:
        ok = poster.delete(platform, mid)
        print(f"  {'✓' if ok else '✗'} {platform} {mid}")


if __name__ == "__main__":
    main()
