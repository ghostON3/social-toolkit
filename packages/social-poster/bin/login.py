#!/usr/bin/env python3
"""Thin CLI wrapper around SocialPoster.login()."""
from __future__ import annotations

import sys

from social_poster import SocialPoster, AdapterRegistry


def main() -> None:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <platform>")
        print(f"  platforms: {' '.join(AdapterRegistry.names())}")
        sys.exit(1)
    SocialPoster().login(sys.argv[1])


if __name__ == "__main__":
    main()
