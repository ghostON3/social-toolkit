"""Tests for the facebook adapter.

Network is mocked via monkeypatch on `requests`. We exercise the *shape* of each
adapter (registration, capability metadata, the post path) without hitting any
real API.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from social_poster import AdapterRegistry, CampaignBuilder
from social_poster.adapters import facebook as fb_mod
from social_poster.errors import NotSupported


class _Resp:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


# ─────────────────────────── facebook ───────────────────────────

def test_facebook_registered_with_post_shape():
    info = {p.short: p for p in AdapterRegistry.list_all()}["fb"]
    assert info.display == "Facebook Page"
    assert info.max_carousel == 10
    assert info.supports_video is True


def test_facebook_text_post(monkeypatch):
    fb = AdapterRegistry.create("fb")
    fb._cfg = {"page_id": "123", "page_token": "tok"}
    fb._session_loaded = True

    captured = {}

    def fake_post(url, data=None, files=None, **kw):
        captured["url"] = url
        captured["data"] = data
        return _Resp({"id": "123_456"})

    monkeypatch.setattr(fb_mod.requests, "post", fake_post)

    content = CampaignBuilder().named("c").with_caption("hello fb").build()
    result = fb.post(content)
    assert result.ok
    assert result.media_id == "123_456"
    assert "/feed" in captured["url"]
    assert captured["data"]["message"] == "hello fb"
