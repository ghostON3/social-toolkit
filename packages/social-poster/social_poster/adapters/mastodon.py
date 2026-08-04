"""Mastodon via Mastodon.py."""
from __future__ import annotations

import getpass
import json
import os
import webbrowser

from mastodon import Mastodon

from ..base import PlatformAdapter
from ..content import CampaignContent
from ..factory import register
from ..result import PostResult


@register("mast", display="Mastodon")
class MastodonAdapter(PlatformAdapter):
    MAX_CAROUSEL = 4
    CAPTION_MAX = 500

    def __init__(self):
        super().__init__()
        self.api: Mastodon | None = None

    def _do_login(self):
        print(f"[{self.SHORT_NAME}] one-time login")
        raw = input("  instance (e.g. mastodon.social): ").strip().rstrip("/")
        # Strip a scheme PREFIX only — str.lstrip(chars) removes any leading char
        # in the set, which mangled hosts like "techhub.social" -> "echhub.social".
        for scheme in ("https://", "http://"):
            if raw.startswith(scheme):
                raw = raw[len(scheme):]
                break
        instance = raw
        api_base = f"https://{instance}"
        client_id, client_secret = Mastodon.create_app(
            "social-poster", api_base_url=api_base, scopes=["read", "write"]
        )
        m = Mastodon(client_id=client_id, client_secret=client_secret, api_base_url=api_base)
        try:
            handle = input("  email or handle: ").strip()
            pw = getpass.getpass("  password (hidden): ")
            token = m.log_in(handle, pw, scopes=["read", "write"])
        except Exception:
            url = m.auth_request_url(scopes=["read", "write"])
            print(f"  open: {url}")
            try:
                webbrowser.open(url)
            except Exception:
                pass
            code = input("  paste auth code: ").strip()
            token = m.log_in(code=code, scopes=["read", "write"])

        creds = {"instance": api_base, "client_id": client_id, "client_secret": client_secret, "access_token": token}
        self.session_path.write_text(json.dumps(creds), encoding="utf-8")
        os.chmod(self.session_path, 0o600)
        self.api = Mastodon(access_token=token, api_base_url=api_base)
        me = self.api.account_verify_credentials()
        print(f"  ✓ @{me['username']}@{instance}")

    def _do_load_session(self):
        if not self.session_path.exists():
            raise FileNotFoundError(self.session_path)
        creds = json.loads(self.session_path.read_text("utf-8"))
        self.api = Mastodon(access_token=creds["access_token"], api_base_url=creds["instance"])

    def whoami(self) -> str:
        me = self.api.account_verify_credentials()
        return f"@{me['username']} · followers={me['followers_count']} · following={me['following_count']}"

    def _do_post(self, content: CampaignContent, *, prefer_video: bool) -> PostResult:
        media_ids = []
        if prefer_video and content.video:
            m = self.api.media_post(str(content.video), mime_type="video/mp4")
            media_ids = [m["id"]]
        else:
            for p in content.slides[: self.MAX_CAROUSEL]:
                m = self.api.media_post(str(p), mime_type="image/png")
                media_ids.append(m["id"])
        status = self.api.status_post(content.caption, media_ids=media_ids)
        return PostResult.success(self.SHORT_NAME, str(status["id"]), status["url"])

    def _do_first_comment(self, media_id: str, text: str) -> None:
        self.api.status_post(text, in_reply_to_id=media_id, visibility="public")

    def _do_delete(self, media_id: str) -> bool:
        self.api.status_delete(media_id)
        return True
