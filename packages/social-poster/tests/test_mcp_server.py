"""MCP server: dry-run by default, live gated by env, tools registered."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import social_poster.client_ledger as ledger_mod
from social_poster import mcp_server as m
from social_poster.client_ledger import ClientRecord


def _png(path: Path) -> Path:
    from PIL import Image

    Image.new("RGB", (16, 16), "red").save(path, "PNG")
    return path


def test_post_is_dry_run_without_live(tmp_path, monkeypatch):
    monkeypatch.delenv(m.ALLOW_LIVE_ENV, raising=False)
    png = _png(tmp_path / "a.png")
    out = m.post("hello", [str(png)], ["bsky"])
    assert out["dry_run"] is True
    assert out["results"]["bsky"]["ok"] and out["results"]["bsky"]["media_id"] == "DRY-RUN"
    assert os.environ.get(m.DRY_RUN_ENV) is None  # restored


def test_live_post_refused_unless_env_allows(tmp_path, monkeypatch):
    monkeypatch.delenv(m.ALLOW_LIVE_ENV, raising=False)
    png = _png(tmp_path / "a.png")
    out = m.post("hello", [str(png)], ["bsky"], live=True)
    assert "error" in out and m.ALLOW_LIVE_ENV in out["error"]
    assert "error" in m.publish(dry_run=False)


def test_schedule_and_set_status(tmp_path):
    with patch.object(ledger_mod, "CLIENTS_DIR", tmp_path / "clients"):
        ClientRecord(id="ghost", name="G", contact_email="g@local", goal="", budget_eur_mo=0,
                     platforms=["ig"], cta_url="", slow_days=[], tone="", baseline_weekly_bookings=0,
                     status="active").save()
        e = m.schedule("ghost", "ig", "2026-11-05T18:00:00+01:00", "hook", "body", "cta")
        assert e["status"] == "pending" and e["format"] == "text"
        assert [x["id"] for x in m.list_schedule("ghost", "pending")] == [e["id"]]
        assert m.set_status("ghost", e["id"], "approved")["status"] == "approved"
        assert m.list_schedule("ghost", "approved")[0]["id"] == e["id"]
        assert "error" in m.set_status("ghost", "nope", "approved")
        assert "error" in m.set_status("ghost", e["id"], "published")


def test_server_registers_tools():
    pytest.importorskip("mcp")
    import asyncio

    server = m.build_server()
    tools = asyncio.run(server.list_tools())
    names = sorted(t.name for t in tools)
    assert names == sorted(["platforms", "sessions", "whoami", "post", "schedule",
                            "list_schedule", "set_status", "publish", "news_sync"])
