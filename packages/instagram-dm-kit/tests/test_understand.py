"""Offline tests for the understand pipeline, thread-id resolution and view.

No network, no real ollama / faster-whisper / ffmpeg — the pipeline stages are
monkeypatched, and thread resolution is driven with fake instagrapi clients.
"""
from __future__ import annotations

import json

import pytest

from instagram_dm_kit import understand as U
from instagram_dm_kit.direct import IgDirect, IgMessage, parse_thread_key
from instagram_dm_kit.understand import (
    ReelUnderstanding,
    is_real_speech,
    understand_reel,
    understand_thread,
)
from instagram_dm_kit.view import build_view, clean_url, primary_url, render_markdown


def _msg(mid: str, kind: str = "video", text: str = "author", url: str = "http://x/reel") -> IgMessage:
    return IgMessage(
        id=mid, user_id="", from_me=False, timestamp="2026-07-09T10:00:00",
        kind=kind, item_type="clip", text=text, media_url=url,
    )


class FakeIg:
    def __init__(self, msgs=None):
        self._msgs = list(msgs or [])
        self.downloaded = []

    def download_media(self, msg, media_dir):
        self.downloaded.append(msg)
        return f"{media_dir}/clip_{msg.id or 'x'}.mp4"

    def read_thread(self, tid, amount=20):
        return self._msgs

    def resolve_thread_id(self, x):
        return "999"


def _patch_pipeline(monkeypatch, transcript="", vision="VISION"):
    monkeypatch.setattr(U, "extract_audio", lambda mp4, md: "x.wav")
    monkeypatch.setattr(U, "load_whisper", lambda size="base": object())
    monkeypatch.setattr(U, "transcribe", lambda wav, model: transcript)
    monkeypatch.setattr(U, "extract_frames", lambda mp4, md: ["f.jpg"])
    monkeypatch.setattr(U, "ollama_vision", lambda frames, cap, **k: vision)


# ---- is_real_speech (the speech gate) ---------------------------------------

def test_is_real_speech_rejects_music_and_filler():
    assert is_real_speech("Music") is False
    assert is_real_speech("[music]") is False
    assert is_real_speech("thanks for watching!") is False
    assert is_real_speech("") is False
    assert is_real_speech("hi") is False  # too short


def test_is_real_speech_accepts_real_sentence():
    assert is_real_speech("Here is how you build an agent loop today.") is True


# ---- understand_reel: speech path vs vision path ----------------------------

def test_reel_real_speech_skips_vision(monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch, transcript="This is a real spoken sentence about agents.",
                    vision="SHOULD_NOT_APPEAR")
    rec = understand_reel(_msg("1"), ig=FakeIg(), media_dir=str(tmp_path))
    assert isinstance(rec, ReelUnderstanding)
    assert rec.transcript.startswith("This is a real")
    assert rec.vision == ""  # vision not consulted when speech is real
    assert rec.error is None


def test_reel_music_falls_through_to_vision(monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch, transcript="Music", vision="ON-SCREEN TEXT: RAG patterns")
    rec = understand_reel(_msg("2"), ig=FakeIg(), media_dir=str(tmp_path))
    assert rec.transcript == "Music"
    assert rec.vision == "ON-SCREEN TEXT: RAG patterns"
    assert rec.error is None


def test_reel_accepts_bare_url_source(monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch, transcript="Music", vision="V")
    ig = FakeIg()
    url = "https://www.instagram.com/reel/DYZ5Ra2Rwpt/"
    rec = understand_reel(url, ig=ig, media_dir=str(tmp_path))
    # the bare URL was wrapped and handed to download_media unchanged
    assert ig.downloaded[0].media_url == url
    assert rec.url == url
    assert rec.vision == "V"


def test_reel_download_failure_is_recorded_not_raised(monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch)

    class FailIg(FakeIg):
        def download_media(self, msg, media_dir):
            return None

    rec = understand_reel(_msg("3"), ig=FailIg(), media_dir=str(tmp_path))
    assert rec.error is not None
    assert "no media" in rec.error


def test_reel_record_parity_keys(monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch, transcript="Music", vision="V")
    rec = understand_reel(_msg("4"), ig=FakeIg(), media_dir=str(tmp_path))
    assert set(rec.as_dict()) == {
        "id", "date", "author", "url", "transcript", "vision", "error",
    }


# ---- understand_thread: resumable + retry -----------------------------------

def test_thread_only_reels_and_resumable(monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch, transcript="Music", vision="V")
    msgs = [_msg("a"), _msg("b", kind="text", url=None), _msg("c", kind="reel_share")]
    ig = FakeIg(msgs)
    out = tmp_path / "u.jsonl"

    recs = list(understand_thread(
        "https://www.instagram.com/direct/t/999/", ig=ig,
        out_path=str(out), media_dir=str(tmp_path),
    ))
    assert [r.id for r in recs] == ["a", "c"]  # 'b' is not a reel

    # second run: both already done → nothing re-processed
    recs2 = list(understand_thread(
        "999", ig=ig, out_path=str(out), media_dir=str(tmp_path),
    ))
    assert recs2 == []


def test_thread_retry_errors_reruns_error_ids(monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch, transcript="Music", vision="RECOVERED")
    out = tmp_path / "u.jsonl"
    out.write_text(
        json.dumps({"id": "a", "date": None, "author": None, "url": None,
                    "transcript": "", "vision": "", "error": "boom"}) + "\n",
        encoding="utf-8",
    )
    ig = FakeIg([_msg("a")])

    # default: an error id is treated as done → skipped
    assert list(understand_thread("999", ig=ig, out_path=str(out),
                                  media_dir=str(tmp_path))) == []

    # retry_errors: the error id is re-run and now succeeds
    recs = list(understand_thread("999", ig=ig, out_path=str(out),
                                  media_dir=str(tmp_path), retry_errors=True))
    assert [r.id for r in recs] == ["a"]
    assert recs[0].vision == "RECOVERED"
    assert recs[0].error is None


# ---- parse_thread_key (pure) ------------------------------------------------

def test_parse_thread_key_forms():
    assert parse_thread_key("340282366") == "340282366"
    assert parse_thread_key("340282366/") == "340282366"
    assert parse_thread_key("https://www.instagram.com/direct/t/340282366/") == "340282366"
    assert parse_thread_key("https://www.instagram.com/direct/t/340282366/?x=1#y") == "340282366"
    assert parse_thread_key("@somehandle") == "@somehandle"


def test_parse_thread_key_idempotent():
    once = parse_thread_key("https://www.instagram.com/direct/t/999/?x=1")
    assert parse_thread_key(once) == "999"


# ---- resolve_thread_id (fake instagrapi clients) ----------------------------

def _ig_with(cl) -> IgDirect:
    ig = IgDirect.__new__(IgDirect)  # bypass __init__ (no session/instagrapi needed)
    ig.cl = cl
    return ig


def test_resolve_long_thread_id_makes_no_network_call():
    """A real ~39-digit instagrapi thread id is addressable as-is — zero network."""
    long_id = "340282366841710301244259509938705598974"

    class NoNet:
        def user_id_from_username(self, u):
            raise AssertionError("must not resolve a username for a long thread id")

        def private_request(self, *a, **k):
            raise AssertionError("must not scan the inbox for a long thread id")

    ig = _ig_with(NoNet())
    assert ig.resolve_thread_id(f"https://www.instagram.com/direct/t/{long_id}/") == long_id
    assert ig.resolve_thread_id(long_id) == long_id


def test_resolve_numeric_web_key_scans_inbox_for_messaging_thread_key():
    """A SHORT numeric web id (messaging_thread_key) MUST resolve to the real
    thread id via a raw-inbox scan — not be returned verbatim (the real bug)."""
    web_key = "18048254750536515"
    real_id = "340282366841710301244259509938705598974"

    class InboxCl:
        def private_request(self, endpoint, params=None):
            assert endpoint == "direct_v2/inbox/"
            return {"inbox": {"threads": [
                {"thread_id": "111", "thread_v2_id": "999", "messaging_thread_key": "222"},
                {"thread_id": real_id, "thread_v2_id": "5979738325414604",
                 "messaging_thread_key": web_key},
            ], "has_older": False}}

    assert _ig_with(InboxCl()).resolve_thread_id(
        f"https://www.instagram.com/direct/t/{web_key}/") == real_id


def test_resolve_handle_routes_through_username_then_thread():
    class HandleCl:
        def user_id_from_username(self, u):
            assert u == "bob"
            return 777

        def direct_thread_by_participants(self, ids):
            assert ids == [777]
            return {"thread_id": "555"}

    assert _ig_with(HandleCl()).resolve_thread_id("@bob") == "555"


def test_resolve_scans_threads_for_v2_key():
    class ThreadObj:
        def __init__(self, tid, v2):
            self.id = tid
            self.thread_v2_id = v2

    class ScanCl:
        def user_id_from_username(self, u):
            raise Exception("not a username")

        def direct_threads(self, amount=100):
            return [ThreadObj("111", "abc"), ThreadObj("222", "xyz")]

    assert _ig_with(ScanCl()).resolve_thread_id("xyz") == "222"


# ---- view (pure + build) ----------------------------------------------------

def test_clean_url_canonicalizes_reel_permalink():
    assert clean_url("https://www.instagram.com/reel/ABC123/?igsh=trackingcruft") \
        == "https://www.instagram.com/reel/ABC123/"


def test_primary_url_prefers_media_then_link_text():
    assert primary_url({"kind": "video", "media_url": "https://www.instagram.com/reel/X/"}) \
        == "https://www.instagram.com/reel/X/"
    assert primary_url({"kind": "link", "text": "https://github.com/a/b?ref=z"}) \
        == "https://github.com/a/b"


def test_render_markdown_splits_author_and_caption():
    md, links = render_markdown([
        {"id": "1", "kind": "video", "text": "creatorhandle Real caption text",
         "media_url": "https://www.instagram.com/reel/ABC/", "timestamp": "2026-07-09T10:00:00"},
    ])
    assert "@creatorhandle" in md
    assert "Real caption text" in md
    assert links[0]["author"] == "creatorhandle"


def test_build_view_from_list_writes_files(tmp_path):
    recs = [{"id": "1", "kind": "video", "text": "creator caption",
             "media_url": "https://www.instagram.com/reel/ABC/",
             "timestamp": "2026-07-09T10:00:00"}]
    out = tmp_path / "v"
    summary = build_view(recs, str(out))
    assert (out / "inspiration.md").exists()
    assert (out / "links.csv").exists()
    assert (out / "links.jsonl").exists()
    assert summary["messages"] == 1 and summary["links"] == 1


def test_build_view_accepts_path(tmp_path):
    src = tmp_path / "records.jsonl"
    src.write_text(json.dumps({"id": "1", "kind": "text", "text": "just a note",
                               "media_url": None, "timestamp": "2026-07-09T10:00:00"}) + "\n",
                   encoding="utf-8")
    summary = build_view(str(src), str(tmp_path / "v2"))
    assert summary["messages"] == 1
