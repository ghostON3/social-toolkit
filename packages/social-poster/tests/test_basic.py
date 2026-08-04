"""Smoke tests — exercise the public API without touching real platforms."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# Make `social_poster` importable when running pytest from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from social_poster import (
    AdapterRegistry,
    CampaignBuilder,
    CampaignContent,
    PostResult,
    SocialPoster,
    hooks,
    register,
)
from social_poster.base import PlatformAdapter


def test_registry_discovers_all_adapters():
    names = AdapterRegistry.names()
    assert "ig" in names
    assert "bsky" in names
    assert "mast" in names
    assert "dc" in names
    assert "rd" in names
    assert "tg" in names
    assert "yt" in names
    assert "x" in names
    assert "th" in names
    assert "tt" in names
    assert "pin" in names


def test_registry_metadata_is_consistent():
    for info in AdapterRegistry.list_all():
        assert info.short
        assert info.display
        assert info.caption_max > 0


def test_campaign_builder_fluent_api():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "test-campaign"
        d.mkdir()
        (d / "01.png").write_bytes(b"fake png")
        (d / "caption.txt").write_text("hello world")
        (d / "first-comment.txt").write_text("#hashtags")

        content = CampaignBuilder().from_directory(d).build()
        assert content.name == "test-campaign"
        assert len(content.slides) == 1
        assert content.caption == "hello world"
        assert content.first_comment == "#hashtags"


def test_campaign_content_is_immutable():
    c = CampaignBuilder().named("x").with_caption("orig").build()
    c2 = c.with_caption("new")
    assert c.caption == "orig"
    assert c2.caption == "new"


def test_post_result_factories():
    s = PostResult.success("ig", "abc", "https://example.com")
    assert s.ok and s.media_id == "abc"
    f = PostResult.failure("ig", "boom")
    assert not f.ok and f.error == "boom"


def test_hook_system_observer():
    seen = []
    hooks.on("test_event", lambda evt, data: seen.append((evt, data)))
    hooks.emit("test_event", x=1)
    assert seen == [("test_event", {"x": 1})]


class _FakeAdapter(PlatformAdapter):
    """Stub for testing template method without hitting any network."""

    MAX_CAROUSEL = 5
    CAPTION_MAX = 100
    SUPPORTS_COMMENTS = True

    def __init__(self):
        super().__init__()
        self.posted: CampaignContent | None = None
        self.commented: tuple[str, str] | None = None

    def _do_login(self):
        self.session_path.write_text("{}")

    def _do_load_session(self):
        return  # always pretend ok

    def _do_post(self, content, *, prefer_video):
        self.posted = content
        return PostResult.success(self.SHORT_NAME, "fake-id", "https://fake/x")

    def _do_first_comment(self, media_id, text):
        self.commented = (media_id, text)

    def whoami(self):
        return "@fake"


def test_template_method_calls_first_comment():
    register("fake", display="Fake")(_FakeAdapter)
    a = AdapterRegistry.create("fake")
    a._session_loaded = True
    c = CampaignBuilder().named("t").with_caption("c").with_first_comment("fc").build()
    r = a.post(c)
    assert r.ok
    assert a.commented == ("fake-id", "fc")


def test_template_method_truncates_long_caption():
    register("fake", display="Fake")(_FakeAdapter)
    a = AdapterRegistry.create("fake")
    a._session_loaded = True
    long = "x" * 500
    c = CampaignBuilder().named("t").with_caption(long).build()
    a.post(c)
    # caption was truncated to CAPTION_MAX before _do_post saw it
    assert len(a.posted.caption) <= a.CAPTION_MAX
