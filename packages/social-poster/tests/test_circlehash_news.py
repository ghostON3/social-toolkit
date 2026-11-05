"""CircleHash news → scheduled entries. Offline: the fetch is patched."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import social_poster.client_ledger as ledger_mod
from social_poster import circlehash_news as cn
from social_poster.client_ledger import ClientRecord
from social_poster.scheduler import ContentEntry


def _png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "blue").save(buf, "PNG")
    return buf.getvalue()


def _cards() -> dict:
    return {"data": {"items": [
        {"origin": "operator", "slug": "test-d", "title": "test d", "lead": None,
         "cover_image_url": "https://cdn.example/test-d.png", "listing_image_url": None,
         "published_at": "2026-11-04T14:21:00.812Z", "updated_at": "2026-11-04T14:21:00.812Z"},
        {"origin": "operator", "slug": "no-cover", "title": "No cover", "lead": "x",
         "cover_image_url": None, "listing_image_url": None,
         "published_at": "2026-10-28T17:31:37.915Z", "updated_at": "2026-10-28T17:31:37.915Z"},
        {"origin": "operator", "slug": "gggg2", "title": "gg66", "lead": "Lead text",
         "cover_image_url": None, "listing_image_url": "https://cdn.example/gggg2.jpg",
         "published_at": "2026-10-28T14:20:09.877Z", "updated_at": "2026-10-28T14:20:09.877Z"},
    ]}}


def _client(tmp_path: Path) -> ClientRecord:
    c = ClientRecord(id="ghost", name="Ghost", contact_email="g@local", goal="poc", budget_eur_mo=0,
                     platforms=["ig"], cta_url="", slow_days=[], tone="plain",
                     baseline_weekly_bookings=0, status="active")
    c.save()
    return c


def test_sync_plans_pending_entries_with_jpeg_cover_and_is_idempotent(tmp_path):
    src = tmp_path / "news.json"
    src.write_text(json.dumps(_cards()))
    state = tmp_path / "state.json"
    with patch.object(ledger_mod, "CLIENTS_DIR", tmp_path / "clients"), \
         patch.object(cn, "fetch_bytes", lambda url, timeout=30: _png_bytes()):
        client = _client(tmp_path)
        rep = cn.sync("ghost", ["ig"], source=src, state_file=state, in_minutes=5)
        assert [e.hook for e in rep.created] == ["test d", "gg66"]
        assert rep.missing_cover == ["no-cover"]
        e = rep.created[0]
        assert e.status == "pending" and e.platform == "ig" and e.format == "image"
        assert e.cta == "Read more: https://www.circlehash.com/blog/test-d"
        media = Path(e.media_urls[0])
        assert media.suffix == ".jpg" and media.exists() and media.read_bytes()[:3] == b"\xff\xd8\xff"
        assert len(ContentEntry.list_for_client("ghost", status="pending")) == 2
        # second run: nothing new
        rep2 = cn.sync("ghost", ["ig"], source=src, state_file=state)
        assert rep2.created == [] and sorted(rep2.skipped) == ["gggg2", "test-d"]
        assert len(ContentEntry.list_for_client("ghost")) == 2
        # slots are spaced by gap_minutes
        a, b = rep.created
        assert a.scheduled_at < b.scheduled_at


def test_dry_run_writes_nothing(tmp_path):
    src = tmp_path / "news.json"
    src.write_text(json.dumps(_cards()))
    state = tmp_path / "state.json"
    calls = []
    with patch.object(ledger_mod, "CLIENTS_DIR", tmp_path / "clients"), \
         patch.object(cn, "fetch_bytes", lambda url, timeout=30: calls.append(url) or _png_bytes()):
        _client(tmp_path)
        rep = cn.sync("ghost", ["ig", "th"], source=src, state_file=state, dry_run=True)
        assert len(rep.created) == 4 and all(e.id.startswith("dry-") for e in rep.created)
        assert calls == [] and not state.exists()
        assert ContentEntry.list_for_client("ghost") == []


def test_approve_flag_creates_approved_entries(tmp_path):
    src = tmp_path / "news.json"
    src.write_text(json.dumps(_cards()))
    with patch.object(ledger_mod, "CLIENTS_DIR", tmp_path / "clients"), \
         patch.object(cn, "fetch_bytes", lambda url, timeout=30: _png_bytes()):
        _client(tmp_path)
        rep = cn.sync("ghost", ["ig"], source=src, state_file=tmp_path / "s.json", approve=True, limit=1)
        assert [e.status for e in rep.created] == ["approved"]
        assert rep.created[0].hook == "test d"  # newest first
