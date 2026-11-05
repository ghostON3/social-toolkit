"""publish_due must hand the adapters local JPEG files and read the facade's dict result."""
from __future__ import annotations

import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import social_poster.client_ledger as ledger_mod
import social_poster.scheduler as sched
from social_poster.client_ledger import ClientRecord
from social_poster.result import PostResult
from social_poster.scheduler import ContentEntry, _materialize_media, publish_due


def _png(path: Path) -> Path:
    from PIL import Image

    Image.new("RGB", (16, 16), "red").save(path, "PNG")
    return path


def test_materialize_converts_png_and_downloads_urls(tmp_path):
    png = _png(tmp_path / "cover.png")
    jpg = tmp_path / "ready.jpg"
    from PIL import Image
    Image.new("RGB", (8, 8)).save(jpg, "JPEG")
    buf = io.BytesIO(); Image.new("RGB", (8, 8), "green").save(buf, "PNG")
    with patch.object(sched, "_fetch_bytes", lambda url, timeout=30: buf.getvalue()):
        out = _materialize_media([str(png), str(jpg), "https://cdn.example/x.png"], tmp_path / "m")
    assert out[1] == jpg
    assert out[0].suffix == ".jpg" and out[2].suffix == ".jpg"
    for p in (out[0], out[2]):
        assert p.read_bytes()[:3] == b"\xff\xd8\xff"


class _FakePoster:
    """Returns what the real facade returns: a dict keyed by platform."""
    seen: list = []

    def post(self, content, *, to, **kw):
        _FakePoster.seen.append((content, to))
        return {to[0]: PostResult.success(to[0], "123", "https://instagram.com/p/abc/")}


def test_publish_due_marks_published_from_dict_result(tmp_path):
    png = _png(tmp_path / "cover.png")
    with patch.object(ledger_mod, "CLIENTS_DIR", tmp_path / "clients"), \
         patch.object(sched, "SocialPoster", _FakePoster):
        c = ClientRecord(id="ghost", name="G", contact_email="g@local", goal="", budget_eur_mo=0,
                         platforms=["ig"], cta_url="", slow_days=[], tone="", baseline_weekly_bookings=0,
                         status="active")
        c.save()
        e = ContentEntry(id="e1", client_id="ghost", platform="ig",
                         scheduled_at=(datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
                         hook="h", body="b", cta="c", media_urls=[str(png)], format="image", status="approved")
        e.save(c.dir)
        res = publish_due(window_minutes=10)
    assert len(res) == 1 and res[0].ok and res[0].post_url == "https://instagram.com/p/abc/"
    content, to = _FakePoster.seen[-1]
    assert to == ["ig"] and content.slides[0].suffix == ".jpg"
    saved = ContentEntry.load(tmp_path / "clients" / "ghost" / "plans" / "e1.json")
    assert saved.status == "published" and saved.post_id == "123"


def test_publish_due_fails_entry_when_media_is_unreadable(tmp_path):
    with patch.object(ledger_mod, "CLIENTS_DIR", tmp_path / "clients"), \
         patch.object(sched, "SocialPoster", _FakePoster):
        c = ClientRecord(id="ghost", name="G", contact_email="g@local", goal="", budget_eur_mo=0,
                         platforms=["ig"], cta_url="", slow_days=[], tone="", baseline_weekly_bookings=0,
                         status="active")
        c.save()
        e = ContentEntry(id="e2", client_id="ghost", platform="ig",
                         scheduled_at=datetime.now(timezone.utc).isoformat(),
                         hook="h", body="b", cta="c", media_urls=[str(tmp_path / "missing.png")],
                         format="image", status="approved")
        e.save(c.dir)
        res = publish_due(window_minutes=10)
    assert len(res) == 1 and not res[0].ok and "media:" in (res[0].error or "")
    assert ContentEntry.load(tmp_path / "clients" / "ghost" / "plans" / "e2.json").status == "failed"
