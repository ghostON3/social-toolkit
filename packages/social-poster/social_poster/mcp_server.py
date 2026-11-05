"""MCP server over the SocialPoster facade (stdio).

Lets an agent list platforms and sessions, post on demand, plan scheduled
posts and sync CircleHash news into the schedule. Every tool is dry-run
unless the caller asks for a live call AND the server was started with
``SOCIAL_POSTER_MCP_ALLOW_LIVE=1``; publishing stays a human decision.

Register for Claude Code:
    claude mcp add --scope user social-poster -- \\
        uv run --no-sync --directory <path to packages/social-poster> sp-mcp
"""
from __future__ import annotations

import contextlib
import os
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client_ledger import ClientRecord
from .content import CampaignBuilder
from .facade import SocialPoster
from .factory import AdapterRegistry
from .scheduler import ContentEntry, publish_due

ALLOW_LIVE_ENV = "SOCIAL_POSTER_MCP_ALLOW_LIVE"
DRY_RUN_ENV = "SOCIAL_POSTER_DRY_RUN"


def live_allowed() -> bool:
    return os.environ.get(ALLOW_LIVE_ENV) in ("1", "true", "yes")


@contextlib.contextmanager
def _dry_run(enabled: bool):
    prev = os.environ.get(DRY_RUN_ENV)
    if enabled:
        os.environ[DRY_RUN_ENV] = "1"
    else:
        os.environ.pop(DRY_RUN_ENV, None)
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(DRY_RUN_ENV, None)
        else:
            os.environ[DRY_RUN_ENV] = prev


def _quiet():
    """Adapters print progress; stdout is the MCP wire, so send it to stderr."""
    return contextlib.redirect_stdout(sys.stderr)


# ── plain functions (tested directly) ──

def platforms() -> list[dict[str, Any]]:
    with _quiet():
        return [asdict(p) for p in SocialPoster().available()]


def sessions() -> list[dict[str, Any]]:
    with _quiet():
        poster = SocialPoster()
        return [{"platform": n, "logged_in": poster.is_logged_in(n)} for n in AdapterRegistry.names()]


def whoami(platform: str) -> str:
    with _quiet():
        return SocialPoster().whoami(platform)


def post(caption: str, media_paths: list[str], platforms: list[str], live: bool = False) -> dict[str, Any]:
    if live and not live_allowed():
        return {"error": f"live posting is disabled; start the server with {ALLOW_LIVE_ENV}=1", "dry_run": True}
    missing = [p for p in media_paths if not Path(p).expanduser().exists()]
    if missing:
        return {"error": f"media not found: {missing}"}
    content = (
        CampaignBuilder()
        .named(f"mcp-{uuid.uuid4().hex[:8]}")
        .with_caption(caption)
        .with_slides([Path(p).expanduser() for p in media_paths])
        .build()
    )
    with _quiet(), _dry_run(not live):
        results = SocialPoster().post(content, to=platforms)
    return {"dry_run": not live, "results": {k: asdict(v) for k, v in results.items()}}


def schedule(
    client_id: str,
    platform: str,
    scheduled_at: str,
    hook: str,
    body: str = "",
    cta: str = "",
    media_paths: list[str] | None = None,
    approve: bool = False,
) -> dict[str, Any]:
    client = ClientRecord.load(client_id)
    when = datetime.fromisoformat(scheduled_at)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    entry = ContentEntry(
        id=uuid.uuid4().hex[:16],
        client_id=client.id,
        platform=platform,
        scheduled_at=when.isoformat(),
        hook=hook,
        body=body,
        cta=cta,
        media_urls=[str(Path(p).expanduser()) for p in (media_paths or [])],
        format="image" if media_paths else "text",
        status="approved" if approve else "pending",
    )
    entry.save(client.dir)
    return asdict(entry)


def list_schedule(client_id: str, status: str | None = None) -> list[dict[str, Any]]:
    return [asdict(e) for e in ContentEntry.list_for_client(client_id, status=status)]


def set_status(client_id: str, entry_id: str, status: str) -> dict[str, Any]:
    if status not in ("pending", "approved"):
        return {"error": "status must be pending or approved"}
    client = ClientRecord.load(client_id)
    path = client.dir / "plans" / f"{entry_id}.json"
    if not path.exists():
        return {"error": f"no entry {entry_id} for {client_id}"}
    entry = ContentEntry.load(path)
    entry.status = status  # type: ignore[assignment]
    entry.save(client.dir)
    return asdict(entry)


def publish(window_minutes: int = 10, dry_run: bool = True) -> dict[str, Any]:
    if not dry_run and not live_allowed():
        return {"error": f"live publishing is disabled; start the server with {ALLOW_LIVE_ENV}=1", "dry_run": True}
    with _quiet():
        results = publish_due(window_minutes=window_minutes, dry_run=dry_run)
    return {"dry_run": dry_run, "results": [asdict(r) for r in results]}


def news_sync(
    client_id: str = "ghost",
    platforms: list[str] | None = None,
    source: str | None = None,
    in_minutes: int = 15,
    gap_minutes: int = 30,
    limit: int | None = None,
    approve: bool = False,
    dry_run: bool = True,
) -> dict[str, Any]:
    from . import circlehash_news

    with _quiet():
        report = circlehash_news.sync(
            client_id,
            platforms or ["ig"],
            source=source,
            in_minutes=in_minutes,
            gap_minutes=gap_minutes,
            limit=limit,
            approve=approve,
            dry_run=dry_run,
        )
    return report.as_dict()


# ── MCP wiring ──

def build_server():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        "social-poster",
        instructions=(
            "Post to social platforms through social-poster. Calls are dry-run by default; "
            "a live post or publish needs live=True / dry_run=False and a server started with "
            f"{ALLOW_LIVE_ENV}=1. Scheduled entries start pending; set_status approves them and the "
            "sp-publish timer posts them."
        ),
    )
    server.tool(name="platforms", description="Platforms social-poster can post to, with their limits.")(platforms)
    server.tool(name="sessions", description="Which platforms have a saved login session on this machine.")(sessions)
    server.tool(name="whoami", description="The account behind a platform's saved session.")(whoami)
    server.tool(name="post", description="Post a caption with local image files to platforms now. Dry-run unless live=True.")(post)
    server.tool(name="schedule", description="Plan one post for a client at an ISO-8601 time. Pending unless approve=True.")(schedule)
    server.tool(name="list_schedule", description="Planned entries for a client, optionally by status.")(list_schedule)
    server.tool(name="set_status", description="Approve (or un-approve) a planned entry.")(set_status)
    server.tool(name="publish", description="Run the publisher for entries due in the window. Dry-run unless dry_run=False.")(publish)
    server.tool(name="news_sync", description="Plan posts from CircleHash public news that were not planned yet. Dry-run by default.")(news_sync)
    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
