"""Scheduler — ContentPlan store + Publisher cron for Variant A.

ContentPlan: 7-entry weekly plan per client, stored as NDJSON in
~/.config/social-poster/clients/<id>/plans/.

Publisher: drain ScheduledPost queue. Designed to be called from a systemd
timer or cron: `sp-publish --now` runs posts due in the next 5 minutes.

Approval flow (zero-UI): Ghost reviews the plan file, edits status
"pending" → "approved" inline, then the publisher picks it up.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import social_poster.client_ledger as _ledger
from .client_ledger import ClientRecord
from .content import CampaignBuilder
from .facade import SocialPoster


@dataclass
class ContentEntry:
    id: str                          # ulid
    client_id: str
    platform: str                    # "th", "ig", …
    scheduled_at: str                # ISO-8601
    hook: str                        # first line / headline
    body: str                        # caption body
    cta: str                         # call-to-action line
    media_urls: list[str]            # public CDN URLs (empty = text post)
    format: Literal["text", "image", "carousel", "video"] = "text"
    status: Literal["pending", "approved", "published", "failed"] = "pending"
    post_id: str | None = None       # filled after publish
    post_url: str | None = None
    error: str | None = None

    # ── persistence ──

    def save(self, client_dir: Path) -> None:
        plans_dir = client_dir / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        path = plans_dir / f"{self.id}.json"
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "ContentEntry":
        return cls(**json.loads(path.read_text("utf-8")))

    @classmethod
    def list_for_client(cls, client_id: str, status: str | None = None) -> list["ContentEntry"]:
        plans_dir = _ledger.CLIENTS_DIR / client_id / "plans"
        if not plans_dir.exists():
            return []
        entries = []
        for p in sorted(plans_dir.glob("*.json")):
            try:
                e = cls.load(p)
                if status is None or e.status == status:
                    entries.append(e)
            except (KeyError, TypeError):
                continue
        return entries


@dataclass
class PublishResult:
    entry_id: str
    client_id: str
    platform: str
    ok: bool
    post_id: str | None = None
    post_url: str | None = None
    error: str | None = None


def publish_due(window_minutes: int = 10, dry_run: bool = False) -> list[PublishResult]:
    """Publish all approved posts scheduled within the next `window_minutes`.

    Called from sp-publish CLI. Idempotent: published entries are skipped.
    """
    now = datetime.now(timezone.utc)
    results: list[PublishResult] = []
    poster = SocialPoster()

    for client in ClientRecord.list_all():
        if client.status != "active":
            continue
        for entry in ContentEntry.list_for_client(client.id, status="approved"):
            scheduled = datetime.fromisoformat(entry.scheduled_at)
            delta = (scheduled - now).total_seconds() / 60
            if not (-2 <= delta <= window_minutes):
                continue

            client.set_env_for_platform(entry.platform)
            content = (
                CampaignBuilder()
                .named(f"{client.id}-{entry.id}")
                .with_caption(f"{entry.hook}\n\n{entry.body}\n\n{entry.cta}")
                .with_slides(entry.media_urls)
                .build()
            )

            if dry_run:
                print(f"[dry] would post {entry.id} for {client.id} on {entry.platform}")
                results.append(PublishResult(entry.id, client.id, entry.platform, True))
                continue

            res = poster.post(content, to=[entry.platform])
            r = res[0] if res else None
            if r and r.ok:
                entry.status = "published"
                entry.post_id = r.media_id
                entry.post_url = r.url
                result = PublishResult(entry.id, client.id, entry.platform, True, r.media_id, r.url)
            else:
                err = r.error if r else "no result"
                entry.status = "failed"
                entry.error = err
                result = PublishResult(entry.id, client.id, entry.platform, False, error=err)

            entry.save(client.dir)
            results.append(result)
            print(result)

    return results


# ── CLI entrypoint ──

def publish_cli() -> None:
    """Entry point for `sp-publish` systemd timer / cron invocation."""
    import argparse
    parser = argparse.ArgumentParser(description="Drain the scheduled post queue")
    parser.add_argument("--window", type=int, default=10, help="Publish window in minutes (default 10)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    args = parser.parse_args()
    results = publish_due(window_minutes=args.window, dry_run=args.dry_run)
    ok = sum(1 for r in results if r.ok)
    fail = sum(1 for r in results if not r.ok)
    print(f"published={ok} failed={fail} total={len(results)}")
    if fail:
        raise SystemExit(1)


# ── attribution stub ──

ATTRIBUTION_LOG = Path.home() / ".config" / "social-poster" / "attribution.ndjson"


def record_attribution(post_id: str, client_id: str, conversions: int, revenue_est_eur: float) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "post_id": post_id,
        "client_id": client_id,
        "conversions": conversions,
        "revenue_est_eur": revenue_est_eur,
    }
    with ATTRIBUTION_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
