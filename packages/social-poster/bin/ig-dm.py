#!/usr/bin/env python3
"""Standalone wrapper so `bin/ig-dm.py` works without `pip install -e .`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from social_poster.ig_dm_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
