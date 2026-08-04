"""Instagram via instagrapi."""
from __future__ import annotations

import getpass
import os
import time

from instagrapi import Client
from instagrapi.exceptions import (
    ChallengeRequired,
    FeedbackRequired,
    PleaseWaitFewMinutes,
    RateLimitError,
    TwoFactorRequired,
)

from ..base import PlatformAdapter
from ..content import CampaignContent
from ..decorators import retry
from ..factory import register
from ..result import PostResult


@register("ig", display="Instagram")
class Instagram(PlatformAdapter):
    MAX_CAROUSEL = 10
    CAPTION_MAX = 2200

    def __init__(self):
        super().__init__()
        self.cl = Client()
        self.cl.delay_range = [2, 5]

    def _do_login(self):
        print(f"[{self.SHORT_NAME}] one-time login")
        username = input("  username: ").strip()
        password = getpass.getpass("  password (hidden): ")
        try:
            self.cl.login(username, password)
        except TwoFactorRequired:
            code = input("  2FA code: ").strip()
            self.cl.login(username, password, verification_code=code)
        except ChallengeRequired:
            print("  challenge required — approve on phone and re-run")
            raise
        self.cl.dump_settings(self.session_path)
        os.chmod(self.session_path, 0o600)

    def _do_load_session(self):
        if not self.session_path.exists():
            raise FileNotFoundError(self.session_path)
        self.cl.load_settings(self.session_path)

    def whoami(self) -> str:
        me = self.cl.user_info(self.cl.user_id)
        return f"@{me.username} · followers={me.follower_count} · following={me.following_count}"

    @retry(times=2, on=(PleaseWaitFewMinutes, RateLimitError), backoff=10)
    def _do_post(self, content: CampaignContent, *, prefer_video: bool) -> PostResult:
        try:
            if prefer_video and content.video:
                m = self.cl.clip_upload(
                    path=content.video,
                    caption=content.caption,
                    thumbnail=content.thumbnail if content.thumbnail and content.thumbnail.exists() else None,
                )
                return PostResult.success(self.SHORT_NAME, m.id, f"https://instagram.com/reel/{m.code}/")
            if len(content.slides) > 1:
                m = self.cl.album_upload(paths=list(content.slides[: self.MAX_CAROUSEL]), caption=content.caption)
                return PostResult.success(self.SHORT_NAME, m.id, f"https://instagram.com/p/{m.code}/")
            if content.slides:
                m = self.cl.photo_upload(path=content.slides[0], caption=content.caption)
                return PostResult.success(self.SHORT_NAME, m.id, f"https://instagram.com/p/{m.code}/")
            if content.video:
                m = self.cl.clip_upload(path=content.video, caption=content.caption)
                return PostResult.success(self.SHORT_NAME, m.id, f"https://instagram.com/reel/{m.code}/")
            return PostResult.failure(self.SHORT_NAME, "nothing to post")
        except (FeedbackRequired,) as e:
            return PostResult.failure(self.SHORT_NAME, f"{type(e).__name__}: {e}")

    def _do_first_comment(self, media_id: str, text: str) -> None:
        time.sleep(2)
        self.cl.media_comment(media_id, text)

    def _do_delete(self, media_id: str) -> bool:
        return bool(self.cl.media_delete(media_id))
