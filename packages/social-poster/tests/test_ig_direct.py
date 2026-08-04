"""Offline tests for the Instagram Direct message-normalization layer.

No network, no instagrapi Client, no session — drives :func:`normalize_message`
directly with fixture dicts shaped like instagrapi ``DirectMessage`` dumps.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from social_poster.ig_direct import (
    IgMessage,
    normalize_message,
    triage_emoji,
    triage_line,
)


def test_triage_line_full():
    line = triage_line("saved", "reel mrnotion.co", "inbox/x.mp4", "notion clone")
    assert line == "📥 saved · reel mrnotion.co → inbox/x.mp4 · notion clone"


def test_triage_line_minimal():
    assert triage_line("done") == "✅ processed"


def test_triage_line_unknown_disposition_falls_back_to_seen():
    assert triage_line("whatever").startswith("👀")


def test_triage_emoji_lookup():
    assert triage_emoji("task") == "🔁"
    assert triage_emoji("useful") == "⭐"


def test_plain_text_inbound():
    m = normalize_message(
        {"id": "1", "user_id": "17841400000000000", "item_type": "text",
         "is_sent_by_viewer": False, "text": "ahoj", "timestamp": "1700000000"}
    )
    assert isinstance(m, IgMessage)
    assert m.kind == "text"
    assert m.from_me is False
    assert m.text == "ahoj"
    assert m.media_url is None
    assert m.user_id == "17841400000000000"


def test_text_outbound_is_from_me():
    m = normalize_message({"id": "2", "item_type": "text",
                           "is_sent_by_viewer": True, "text": "channel up"})
    assert m.from_me is True


def test_clip_video_extracts_video_url():
    raw = {
        "id": "3", "item_type": "clip", "is_sent_by_viewer": False,
        "clip": {"clip": {"video_url": "https://cdn.example/clip.mp4",
                          "thumbnail_url": "https://cdn.example/thumb.jpg"}},
    }
    m = normalize_message(raw)
    assert m.kind == "video"
    assert m.media_url == "https://cdn.example/clip.mp4"


def test_uploaded_media_video_versions():
    raw = {
        "id": "4", "item_type": "media", "is_sent_by_viewer": False,
        "media": {"video_versions": [{"url": "https://cdn.example/v.mp4"}],
                  "thumbnail_url": "https://cdn.example/t.jpg"},
    }
    m = normalize_message(raw)
    assert m.kind == "media"
    assert m.media_url == "https://cdn.example/v.mp4"


def test_photo_falls_back_to_image_url():
    raw = {
        "id": "5", "item_type": "media", "is_sent_by_viewer": False,
        "media": {"image_versions2": {"candidates": [{"url": "https://cdn.example/p.jpg"}]}},
    }
    m = normalize_message(raw)
    assert m.media_url == "https://cdn.example/p.jpg"


def test_voice_media_url():
    raw = {
        "id": "6", "item_type": "voice_media", "is_sent_by_viewer": False,
        "voice_media": {"media": {"audio": {"audio_src": "x",
                        "url": "https://cdn.example/a.m4a"}}},
    }
    m = normalize_message(raw)
    assert m.kind == "voice"
    assert m.media_url == "https://cdn.example/a.m4a"


def test_unknown_item_type_is_other():
    m = normalize_message({"id": "7", "item_type": "videocall_event",
                           "is_sent_by_viewer": False})
    assert m.kind == "other"
    assert m.media_url is None


def test_link_text_pulled_from_link_node():
    m = normalize_message({"id": "8", "item_type": "link",
                           "is_sent_by_viewer": False,
                           "link": {"text": "look: https://x.com"}})
    assert m.kind == "link"
    assert "look" in m.text


def test_missing_fields_dont_crash():
    m = normalize_message({})
    assert m.kind == "text"
    assert m.id == ""
    assert m.from_me is False


def test_xma_clip_shared_reel_url_and_title():
    # Real shape observed in the bot ⇄ operator thread (a shared reel).
    raw = {
        "id": "10", "user_id": "17841400000000000", "item_type": "xma_clip",
        "is_sent_by_viewer": False,
        "xma_share": {
            "video_url": "https://www.instagram.com/reel/DYZ5Ra2Rwpt/",
            "title": None,
            "preview_url": "https://cdn.example/preview.jpg",
        },
    }
    m = normalize_message(raw)
    assert m.kind == "video"
    # the reel link is the primary asset; text falls back to it when no title
    assert m.media_url == "https://www.instagram.com/reel/DYZ5Ra2Rwpt/"
    assert "instagram.com/reel" in m.text


def test_xma_link_keeps_url_as_text():
    raw = {"id": "11", "item_type": "xma_link", "is_sent_by_viewer": False,
           "text": "https://github.com/vknow360/otaship"}
    m = normalize_message(raw)
    assert m.kind == "link"
    assert "github.com" in m.text


def test_uploaded_photo_resolves_thumbnail_url():
    # item_type 'media', photo (video_url null) → thumbnail is the asset.
    raw = {
        "id": "12", "item_type": "media", "is_sent_by_viewer": False,
        "media": {"id": "x", "media_type": 1, "video_url": None,
                  "thumbnail_url": "https://cdn.example/photo.png"},
    }
    m = normalize_message(raw)
    assert m.kind == "media"
    assert m.media_url == "https://cdn.example/photo.png"


def test_as_dict_roundtrip():
    m = normalize_message({"id": "9", "item_type": "text", "text": "x",
                           "is_sent_by_viewer": False})
    d = m.as_dict()
    assert d["id"] == "9" and d["kind"] == "text" and d["text"] == "x"
