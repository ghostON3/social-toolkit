"""login — mint and persist an instagrapi session for the kit.

Run once (interactively, or with env vars for automation); the saved settings
are reused by every other command, so credentials never live in code or in the
shell history of later runs.

    idk login                       # prompts for username/password (+2FA)
    IDK_USER=... IDK_PASS=... idk login

The session is written to :func:`instagram_dm_kit.direct.default_session_path`
(override with ``IDK_SESSION``).
"""

from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Optional

from .direct import default_session_path


def login(
    username: Optional[str] = None,
    password: Optional[str] = None,
    session_path: Optional[Path] = None,
    verification_code: Optional[str] = None,
) -> dict:
    """Authenticate and persist the session. Returns the logged-in identity."""
    from instagrapi import Client  # lazy: only needed for the live path

    username = username or os.environ.get("IDK_USER") or input("instagram username: ").strip()
    password = password or os.environ.get("IDK_PASS") or getpass.getpass("instagram password: ")

    dest = Path(session_path or default_session_path())
    dest.parent.mkdir(parents=True, exist_ok=True)

    cl = Client()
    # If a session already exists, load it first so re-login reuses device/uuids
    # (Instagram is far less likely to challenge a known device).
    if dest.exists():
        try:
            cl.load_settings(dest)
        except Exception:
            pass

    code = verification_code or os.environ.get("IDK_2FA") or ""
    cl.login(username, password, verification_code=code)
    cl.dump_settings(dest)

    me = cl.account_info()
    return {"username": me.username, "pk": str(me.pk), "session": str(dest)}
