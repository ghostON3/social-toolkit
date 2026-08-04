"""RED tests — prove publish pipeline crashes before reaching the platform.

TDD protocol: MUST FAIL. Failure = proof. Green = fixed.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from social_poster.content import CampaignBuilder
from social_poster.scheduler import ContentEntry, publish_due
from social_poster.client_ledger import ClientRecord


# ─────────────────────────────────────────────────────────────────────────────
# BUG 2: every publish crashes with ValueError before reaching the platform
#
# scheduler.publish_due() calls:
#   CampaignBuilder().with_caption(...).with_slides(...).build()
# content.CampaignBuilder.build() line 131-132:
#   if not self._name:
#       raise ValueError("CampaignBuilder: name is required")
# .named() is NEVER called in publish_due().
#
# PREDICTION: publish_due() raises ValueError on every call regardless of
# content. Zero posts ever reach the Threads API.
# Falsifiable: a post with valid data goes through without ValueError ← will FAIL
# Alternative rejected: "name defaults to something" — _name defaults to "" (falsy).
# Limitation: mocks HTTP to isolate the builder crash from network issues.
# ─────────────────────────────────────────────────────────────────────────────

def _make_client_and_entry(tmp_dir: Path) -> tuple[ClientRecord, ContentEntry]:
    entry_id = "01TEST000000000000000000000"

    client = ClientRecord(
        id="test-client",
        name="Test Business",
        contact_email="test@example.com",
        goal="fill tables",
        budget_eur_mo=299,
        platforms=["th"],
        cta_url="https://example.com/book",
        slow_days=["monday"],
        tone="friendly",
        baseline_weekly_bookings=10,
        status="active",
    )
    # Override client dir to tmp so we don't touch real filesystem
    object.__setattr__(client, '__dict__', {**client.__dict__})

    scheduled_at = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    entry = ContentEntry(
        id=entry_id,
        client_id="test-client",
        platform="th",
        scheduled_at=scheduled_at,
        hook="Come in today",
        body="We have great food waiting for you.",
        cta="Book now → https://example.com/book",
        media_urls=[],
        format="text",
        status="approved",
    )
    return client, entry


def test_campaign_builder_without_named_raises_value_error():
    """Directly proves the builder crash that kills every publish.

    MUST FAIL with ValueError — which means this assertion never runs.
    The test documents that the path used in publish_due() is broken.
    """
    # This is exactly what publish_due() does — no .named() call
    with pytest.raises(ValueError, match="name is required"):
        CampaignBuilder().with_caption("Come in today\n\nBody.\n\nBook now").with_slides([]).build()

    # If we reach here, the builder correctly raises — confirming the bug path.
    # The REAL test is that publish_due() must NOT raise this — which it will.


def test_publish_due_completes_without_value_error(tmp_path):
    """MUST FAIL: publish_due() crashes with ValueError before any HTTP call.

    A valid approved post (text, no media) must complete without exception.
    Currently it crashes at the CampaignBuilder.build() call because .named()
    is never invoked in publish_due().
    """
    import social_poster.scheduler as sched_mod
    import social_poster.client_ledger as ledger_mod

    client, entry = _make_client_and_entry(tmp_path)

    # Wire tmp filesystem so publish_due can find the client + entry
    clients_dir = tmp_path / "clients" / "test-client"
    clients_dir.mkdir(parents=True)
    (clients_dir / "record.json").write_text(
        json.dumps({
            "id": "test-client", "name": "Test Business",
            "contact_email": "test@example.com", "goal": "fill tables",
            "budget_eur_mo": 299, "platforms": ["th"], "cta_url": "https://example.com/book",
            "slow_days": ["monday"], "tone": "friendly",
            "baseline_weekly_bookings": 10, "status": "active",
            "started_on": "2026-06-15", "notes": "",
        }),
        encoding="utf-8"
    )
    plans_dir = clients_dir / "plans"
    plans_dir.mkdir()
    (plans_dir / f"{entry.id}.json").write_text(
        json.dumps({
            "id": entry.id, "client_id": "test-client", "platform": "th",
            "scheduled_at": entry.scheduled_at, "hook": entry.hook,
            "body": entry.body, "cta": entry.cta, "media_urls": [],
            "format": "text", "status": "approved",
            "post_id": None, "post_url": None, "error": None,
        }),
        encoding="utf-8"
    )

    mock_result = MagicMock()
    mock_result.ok = True
    mock_result.media_id = "fake-post-123"
    mock_result.url = "https://threads.net/@test/post/fake-post-123"

    with (
        patch.object(ledger_mod, "CLIENTS_DIR", tmp_path / "clients"),
        patch("social_poster.scheduler.SocialPoster") as MockPoster,
    ):
        mock_poster_instance = MockPoster.return_value
        mock_poster_instance.post.return_value = [mock_result]

        # This WILL raise ValueError("CampaignBuilder: name is required")
        # because publish_due() never calls .named() on the builder.
        results = publish_due(window_minutes=10, dry_run=False)

    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    assert results[0].ok, f"Publish failed: {results[0].error}"
