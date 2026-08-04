"""Twitter / X via twikit (RE'd)."""
from __future__ import annotations

import asyncio
import getpass
import json
import os

from twikit import Client

from ..base import PlatformAdapter
from ..content import CampaignContent
from ..factory import register
from ..result import PostResult


@register("x", display="Twitter / X")
class Twitter(PlatformAdapter):
    MAX_CAROUSEL = 4
    CAPTION_MAX = 280

    def __init__(self):
        super().__init__()
        self.cl: Client | None = None

    def _cookie_path(self):
        return self.session_path.with_suffix(".cookies.json")

    def _do_login(self):
        print(f"[{self.SHORT_NAME}] login (fragile — X often throws challenges)")
        username = input("  username (without @): ").strip()
        email = input("  email: ").strip()
        password = getpass.getpass("  password (hidden): ")

        async def _login():
            c = Client(language="en-US")
            await c.login(auth_info_1=username, auth_info_2=email, password=password)
            c.save_cookies(str(self._cookie_path()))
            os.chmod(self._cookie_path(), 0o600)
            return await c.user()

        me = asyncio.run(_login())
        self.session_path.write_text(json.dumps({"username": username}), encoding="utf-8")
        os.chmod(self.session_path, 0o600)
        print(f"  ✓ @{me.screen_name}")

    def _do_load_session(self):
        if not self.session_path.exists() or not self._cookie_path().exists():
            raise FileNotFoundError(self.session_path)
        self.cl = Client(language="en-US")
        self.cl.load_cookies(str(self._cookie_path()))

    def whoami(self) -> str:
        async def _w():
            me = await self.cl.user()
            return f"@{me.screen_name} · followers={me.followers_count} · following={me.following_count}"
        return asyncio.run(_w())

    def _do_post(self, content: CampaignContent, *, prefer_video: bool) -> PostResult:
        async def _post():
            media_ids = []
            if prefer_video and content.video:
                media_ids.append(await self.cl.upload_media(str(content.video), wait_for_completion=True))
            else:
                for p in content.slides[: self.MAX_CAROUSEL]:
                    media_ids.append(await self.cl.upload_media(str(p), wait_for_completion=True))
            tweet = await self.cl.create_tweet(text=content.caption, media_ids=media_ids)
            return tweet

        tweet = asyncio.run(_post())
        return PostResult.success(
            self.SHORT_NAME, str(tweet.id), f"https://x.com/{tweet.user.screen_name}/status/{tweet.id}"
        )

    def _do_first_comment(self, media_id: str, text: str) -> None:
        async def _reply():
            await self.cl.create_tweet(text=text, reply_to=media_id)
        asyncio.run(_reply())

    def _do_delete(self, media_id: str) -> bool:
        async def _del():
            await self.cl.delete_tweet(media_id)
            return True
        return asyncio.run(_del())
