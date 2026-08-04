"""Server smoke tests via FastAPI TestClient — no real platform calls.

dry_run defaults TRUE, so /post returns synthetic DRY-RUN successes without
touching any network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("fastapi", reason="install the [server] extra to run server tests")

from fastapi.testclient import TestClient

from social_poster.server import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["dry_run_default"] is True  # safe default


def test_platforms_lists_adapters_with_capabilities():
    r = client.get("/platforms")
    assert r.status_code == 200
    shorts = {p["short"] for p in r.json()}
    assert {"ig", "fb"} <= shorts
    by_short = {p["short"]: p for p in r.json()}
    assert by_short["fb"]["supports_post"] is True
    assert by_short["ig"]["supports_post"] is True


def test_sessions_reports_logged_in_state():
    r = client.get("/sessions")
    assert r.status_code == 200
    rows = r.json()
    assert all("platform" in row and "logged_in" in row for row in rows)
    assert all(isinstance(row["logged_in"], bool) for row in rows)


def test_post_dry_run_default_is_true_and_succeeds_without_network():
    r = client.post("/post", json={
        "platforms": ["ig", "fb"],
        "content": {"name": "t", "caption": "hello"},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    results = {x["platform"]: x for x in body["results"]}
    assert results["ig"]["ok"] is True
    assert results["ig"]["media_id"] == "DRY-RUN"
    assert results["fb"]["ok"] is True


def test_post_explicit_dry_run_false_hits_not_logged_in_path():
    # dry_run=false but no session saved → facade reports a clean failure result,
    # NOT a crash.
    r = client.post("/post", json={
        "platforms": ["fb"],
        "content": {"name": "t", "caption": "hi"},
        "dry_run": False,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is False
    assert body["results"][0]["ok"] is False


def test_post_unknown_platform_404():
    r = client.post("/post", json={
        "platforms": ["nope"],
        "content": {"name": "t", "caption": "x"},
    })
    assert r.status_code == 404


def test_login_unknown_platform_404():
    r = client.post("/login", json={"platform": "nope"})
    assert r.status_code == 404
