"""connect — mint an instagrapi session from an already-logged-in *browser*.

The alternative to :mod:`instagram_dm_kit.login` (username/password). If you are
already signed in to https://www.instagram.com/direct/inbox/ in Chrome (or any
Chromium/Firefox browser), this reuses that browser's ``sessionid`` cookie to
hydrate an instagrapi session — no password typed, no 2FA challenge, no device
re-verification. The saved session is identical in shape to ``idk login`` output,
so every other command (`threads`, `read`, `harvest`, …) works unchanged.

    idk connect                          # auto-detect Chrome profile w/ IG login
    idk connect --browser brave
    idk connect --cookie-file "~/.config/google-chrome/Default/Cookies"
    idk connect --sessionid "<sessionid>"   # paste it yourself, no browser read

Cookie decryption is handled by ``browser-cookie3`` (an optional dependency —
``pip install instagram-dm-kit[browser]``). It works while the browser is open.

Security: the ``sessionid`` is a full-account bearer token. It only ever leaves
your machine inside instagrapi's own authenticated calls to Instagram, and lands
on disk in the same session file ``idk login`` already writes.
"""

from __future__ import annotations

import glob
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Optional

from .direct import default_session_path

_IG_AUTH_COOKIES = ("sessionid", "ds_user_id", "csrftoken")

# browser name → (browser_cookie3 function attr, glob of default cookie DB paths)
_BROWSERS = {
    "chrome": ("chrome", [
        "~/.config/google-chrome/*/Cookies",
        "~/.var/app/com.google.Chrome/config/google-chrome/*/Cookies",
    ]),
    "chromium": ("chromium", [
        "~/.config/chromium/*/Cookies",
        "~/.var/app/org.chromium.Chromium/config/chromium/*/Cookies",
    ]),
    "brave": ("brave", [
        "~/.config/BraveSoftware/Brave-Browser/*/Cookies",
    ]),
    "edge": ("edge", [
        "~/.config/microsoft-edge/*/Cookies",
    ]),
    "firefox": ("firefox", []),  # firefox path resolution is handled by the lib
}


def _profile_has_ig_cookies(cookie_db: str) -> bool:
    """True if this Chromium Cookies DB has an instagram.com sessionid row."""
    tmp = None
    try:
        # copy — the live browser holds a lock on the original
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        with open(cookie_db, "rb") as src, open(tmp, "wb") as dst:
            dst.write(src.read())
        con = sqlite3.connect(tmp)
        try:
            row = con.execute(
                "select count(*) from cookies "
                "where host_key like '%instagram.com%' and name='sessionid'"
            ).fetchone()
            return bool(row and row[0])
        finally:
            con.close()
    except Exception:
        return False
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)


def _autodetect_cookie_file(globs: list[str]) -> Optional[str]:
    """First Chromium profile Cookies DB that actually holds an IG login."""
    for pat in globs:
        for path in sorted(glob.glob(os.path.expanduser(pat))):
            if _profile_has_ig_cookies(path):
                return path
    return None


def sessionid_from_browser(
    browser: str = "chrome",
    cookie_file: Optional[str] = None,
) -> dict:
    """Extract the instagram.com auth cookies from a local browser.

    Returns ``{"sessionid", "ds_user_id", "csrftoken"}`` (missing keys absent).
    Raises ``RuntimeError`` with an actionable message on any failure.
    """
    try:
        import browser_cookie3 as bc
    except ImportError as e:  # pragma: no cover - dependency hint
        raise RuntimeError(
            "browser cookie reading needs the optional dependency:\n"
            "    pip install 'instagram-dm-kit[browser]'   (or: pip install browser-cookie3)"
        ) from e

    browser = browser.lower()
    if browser not in _BROWSERS:
        raise RuntimeError(f"unknown --browser {browser!r}; try one of {list(_BROWSERS)}")

    fn_name, default_globs = _BROWSERS[browser]

    if cookie_file:
        cookie_file = os.path.expanduser(cookie_file)
        if not os.path.exists(cookie_file):
            raise RuntimeError(f"--cookie-file not found: {cookie_file}")
    elif default_globs:  # chromium family — pick the profile that has IG
        cookie_file = _autodetect_cookie_file(default_globs)
        if not cookie_file:
            raise RuntimeError(
                f"no {browser} profile is logged in to instagram.com.\n"
                "Sign in at https://www.instagram.com/direct/inbox/ first, "
                "or pass --cookie-file <path to that profile's Cookies>."
            )

    fn = getattr(bc, fn_name)
    kwargs = {"domain_name": "instagram.com"}
    if cookie_file:
        kwargs["cookie_file"] = cookie_file
    try:
        jar = fn(**kwargs)
    except Exception as e:
        raise RuntimeError(
            f"could not read/decrypt {browser} cookies ({type(e).__name__}: {e}).\n"
            "On Linux this usually means the browser keyring is locked — unlock it, "
            "or pass --sessionid to skip the browser read entirely."
        ) from e

    got = {c.name: c.value for c in jar if c.name in _IG_AUTH_COOKIES}
    if not got.get("sessionid"):
        where = cookie_file or browser
        raise RuntimeError(
            f"no instagram.com sessionid found in {where}. "
            "Are you actually signed in in that browser/profile?"
        )
    return got


def connect(
    browser: str = "chrome",
    cookie_file: Optional[str] = None,
    sessionid: Optional[str] = None,
    session_path: Optional[Path] = None,
) -> dict:
    """Hydrate + persist an instagrapi session from a browser login.

    If ``sessionid`` is given it is used directly; otherwise the auth cookies are
    pulled from the chosen browser. Writes the session to the same path
    ``idk login`` uses and returns the logged-in identity.
    """
    from instagrapi import Client  # lazy: only the live path needs it

    csrftoken = None
    if sessionid:
        sessionid = sessionid.strip()
        source = "sessionid"
    else:
        cookies = sessionid_from_browser(browser=browser, cookie_file=cookie_file)
        sessionid = cookies["sessionid"]
        csrftoken = cookies.get("csrftoken")
        source = f"{browser} cookie"

    dest = Path(session_path or default_session_path())
    dest.parent.mkdir(parents=True, exist_ok=True)

    cl = Client()
    # reuse device/uuids from a prior session so Instagram sees a known device
    if dest.exists():
        try:
            cl.load_settings(dest)
        except Exception:
            pass
    if csrftoken:
        # seed the CSRF token so the very first authenticated call is clean
        try:
            cl.set_settings({**cl.get_settings(), "cookies": {"csrftoken": csrftoken}})
        except Exception:
            pass

    # login_by_sessionid validates the cookie against Instagram and populates
    # the client's user id / settings from the live account.
    cl.login_by_sessionid(sessionid)
    cl.dump_settings(dest)

    me = cl.account_info()
    return {
        "username": me.username,
        "pk": str(me.pk),
        "session": str(dest),
        "source": source,
    }
