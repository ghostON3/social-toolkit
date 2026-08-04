"""Server configuration — all env reads happen HERE, at import time.

Tier-0 discipline: never read `os.environ` inside a request handler. The server
imports these module-level constants instead.
"""
from __future__ import annotations

import os

# Network binding for `sp-serve`.
# Default port 8787 is the contract the Social Injection Console FE expects
# (packages/app/src/features/injection-console/seam-client.ts DEFAULT_SEAM).
HOST: str = os.environ.get("SOCIAL_POSTER_HOST", "127.0.0.1")
PORT: int = int(os.environ.get("SOCIAL_POSTER_PORT", "8787"))

# Safety default: when a /post request omits `dry_run`, this is the value used.
# TRUE by default so an accidental call never publishes for real.
DRY_RUN_DEFAULT: bool = os.environ.get("SOCIAL_POSTER_DRY_RUN_DEFAULT", "1") not in ("0", "false", "no")

# The env var the adapter template-method honors (see base.PlatformAdapter.post).
DRY_RUN_ENV: str = "SOCIAL_POSTER_DRY_RUN"
