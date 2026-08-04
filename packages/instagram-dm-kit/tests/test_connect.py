"""Offline tests for the browser-connect path.

No network and no real browser: drive the pure helpers with a synthetic
Chromium-shaped Cookies SQLite DB and monkeypatched ``browser_cookie3``.
The live ``connect()`` (which calls Instagram) is covered manually via
``idk connect``, not here.
"""
from __future__ import annotations

import sqlite3

import pytest

import importlib

# NB: the package re-exports a `connect` *function* at top level, which shadows
# the `connect` submodule as a package attribute — so grab the module from
# sys.modules explicitly (it is still fully importable this way).
C = importlib.import_module("instagram_dm_kit.connect")


def _make_cookie_db(path, *, with_ig=True):
    con = sqlite3.connect(path)
    con.execute("create table cookies (host_key text, name text, value text)")
    if with_ig:
        con.executemany(
            "insert into cookies values (?,?,?)",
            [
                (".instagram.com", "sessionid", "SESSIONID%3Aabc%3A1"),
                (".instagram.com", "ds_user_id", "17841400000000000"),
                (".instagram.com", "csrftoken", "tok123"),
            ],
        )
    con.execute("insert into cookies values ('.example.com','other','x')")
    con.commit()
    con.close()


def test_profile_detection_positive_and_negative(tmp_path):
    yes = tmp_path / "Cookies"
    _make_cookie_db(yes, with_ig=True)
    no = tmp_path / "empty" / "Cookies"
    no.parent.mkdir()
    _make_cookie_db(no, with_ig=False)

    assert C._profile_has_ig_cookies(str(yes)) is True
    assert C._profile_has_ig_cookies(str(no)) is False


def test_autodetect_picks_the_logged_in_profile(tmp_path):
    p1 = tmp_path / "Profile 1" / "Cookies"
    p1.parent.mkdir()
    _make_cookie_db(p1, with_ig=False)
    p2 = tmp_path / "Default" / "Cookies"
    p2.parent.mkdir()
    _make_cookie_db(p2, with_ig=True)

    found = C._autodetect_cookie_file([str(tmp_path / "*" / "Cookies")])
    assert found == str(p2)


def test_autodetect_returns_none_when_nothing_logged_in(tmp_path):
    p = tmp_path / "Default" / "Cookies"
    p.parent.mkdir()
    _make_cookie_db(p, with_ig=False)
    assert C._autodetect_cookie_file([str(tmp_path / "*" / "Cookies")]) is None


def test_unknown_browser_raises(monkeypatch):
    # stub the optional dependency so import doesn't gate the check
    monkeypatch.setitem(__import__("sys").modules, "browser_cookie3", object())
    with pytest.raises(RuntimeError, match="unknown --browser"):
        C.sessionid_from_browser(browser="netscape")


def test_missing_cookie_file_raises(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "browser_cookie3", object())
    with pytest.raises(RuntimeError, match="not found"):
        C.sessionid_from_browser(browser="chrome", cookie_file="/no/such/Cookies")


class _FakeCookie:
    def __init__(self, name, value):
        self.name, self.value = name, value


def test_sessionid_extracted_from_jar(monkeypatch, tmp_path):
    db = tmp_path / "Cookies"
    _make_cookie_db(db, with_ig=True)

    class _FakeBC:
        def chrome(self, **kw):
            assert kw["domain_name"] == "instagram.com"
            return [
                _FakeCookie("sessionid", "SESSIONID%3Aabc%3A1"),
                _FakeCookie("csrftoken", "tok123"),
                _FakeCookie("noise", "x"),
            ]

    monkeypatch.setitem(__import__("sys").modules, "browser_cookie3", _FakeBC())
    got = C.sessionid_from_browser(browser="chrome", cookie_file=str(db))
    assert got["sessionid"] == "SESSIONID%3Aabc%3A1"
    assert got["csrftoken"] == "tok123"
    assert "noise" not in got


def test_no_sessionid_in_jar_raises(monkeypatch, tmp_path):
    db = tmp_path / "Cookies"
    _make_cookie_db(db, with_ig=True)

    class _FakeBC:
        def chrome(self, **kw):
            return [_FakeCookie("csrftoken", "tok")]  # no sessionid

    monkeypatch.setitem(__import__("sys").modules, "browser_cookie3", _FakeBC())
    with pytest.raises(RuntimeError, match="no instagram.com sessionid"):
        C.sessionid_from_browser(browser="chrome", cookie_file=str(db))
