"""RED tests — prove critical bugs in client_ledger + scheduler.

TDD protocol: these tests MUST FAIL before any fix is applied.
Failure here = proof the bug exists. Green = bug fixed.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from social_poster.client_ledger import ClientRecord
from social_poster.adapters.threads import Threads
from social_poster.base import SESSIONS_DIR


# ─────────────────────────────────────────────────────────────────────────────
# BUG 1: per-client credentials are structurally broken
#
# client_ledger.ClientRecord.set_env_for_platform() sets
#   os.environ["SOCIAL_POSTER_SESSION_DIR"] = str(self.dir)
# but base.PlatformAdapter.session_path is hardcoded:
#   return SESSIONS_DIR / f"{self.SHORT_NAME}.json"
# where SESSIONS_DIR is a module-level constant that never reads the env var.
#
# PREDICTION: both clients resolve to the SAME session file path,
# meaning client B's posts go out under client A's account token.
# Falsifiable: session_path for client A ≠ session_path for client B ← will FAIL
# Alternative rejected: "env var is read lazily" — not true, SESSIONS_DIR is set
# at import time.
# Limitation: tests session_path only, not actual HTTP credential use.
# ─────────────────────────────────────────────────────────────────────────────

def make_client(client_id: str) -> ClientRecord:
    return ClientRecord(
        id=client_id,
        name=f"Business {client_id}",
        contact_email=f"{client_id}@example.com",
        goal="fill slow-day tables",
        budget_eur_mo=299,
        platforms=["th"],
        cta_url=f"https://example.com/{client_id}/book",
        slow_days=["monday"],
        tone="friendly",
        baseline_weekly_bookings=20,
    )


def test_per_client_credentials_resolve_to_different_session_paths():
    """MUST FAIL: both clients share ~/.config/social-poster/th.json.

    The fix requires base.PlatformAdapter.session_path to read
    SOCIAL_POSTER_SESSION_DIR (or equivalent) at call time, not at import.
    """
    client_a = make_client("pizzeria-roma")
    client_b = make_client("cafe-central")

    adapter = Threads()

    client_a.set_env_for_platform("th")
    path_for_a = adapter.session_path

    client_b.set_env_for_platform("th")
    path_for_b = adapter.session_path

    # These SHOULD be different — one per client's credential dir.
    # They will be IDENTICAL because session_path ignores the env var.
    assert path_for_a != path_for_b, (
        f"BUG CONFIRMED: both clients share the same session file: {path_for_a}\n"
        "Fix: make session_path read SOCIAL_POSTER_SESSION_DIR at call time."
    )


def test_client_session_path_is_inside_client_dir():
    """MUST FAIL: session_path lands in shared ~/.config/social-poster/, not client dir."""
    client = make_client("pizzeria-roma")
    client.set_env_for_platform("th")

    adapter = Threads()
    expected_dir = client.dir  # ~/.config/social-poster/clients/pizzeria-roma

    assert str(adapter.session_path).startswith(str(expected_dir)), (
        f"BUG CONFIRMED:\n"
        f"  expected path under: {expected_dir}\n"
        f"  got:                 {adapter.session_path}\n"
        "Fix: session_path must respect SOCIAL_POSTER_SESSION_DIR."
    )
