"""Telegram via Telethon."""
from __future__ import annotations

import asyncio
import getpass
import json
import os

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from ..base import PlatformAdapter
from ..content import CampaignContent
from ..factory import register
from ..result import PostResult


@register("tg", display="Telegram")
class Telegram(PlatformAdapter):
    MAX_CAROUSEL = 10
    CAPTION_MAX = 1024

    def __init__(self):
        super().__init__()
        self.client: TelegramClient | None = None
        self._cfg: dict = {}

    def _session_file(self) -> str:
        return str(self.session_path.with_suffix(".session"))

    def _do_login(self):
        print(f"[{self.SHORT_NAME}] one-time login")
        api_id = int(input("  api_id (int from my.telegram.org): ").strip())
        api_hash = input("  api_hash: ").strip()
        phone = input("  phone (e.g. +421900000000): ").strip()
        target = input("  default target (chat id, @username, or empty = Saved Messages): ").strip() or "me"

        async def _login():
            c = TelegramClient(self._session_file(), api_id, api_hash)
            await c.connect()
            if not await c.is_user_authorized():
                await c.send_code_request(phone)
                code = input("  code from Telegram: ").strip()
                try:
                    await c.sign_in(phone, code)
                except SessionPasswordNeededError:
                    pw = getpass.getpass("  2FA password (hidden): ")
                    await c.sign_in(password=pw)
            me = await c.get_me()
            await c.disconnect()
            return me

        me = asyncio.run(_login())
        cfg = {"api_id": api_id, "api_hash": api_hash, "phone": phone, "target": target}
        self.session_path.write_text(json.dumps(cfg), encoding="utf-8")
        os.chmod(self.session_path, 0o600)
        os.chmod(self._session_file(), 0o600)
        print(f"  ✓ {me.first_name} (@{me.username or '—'})")

    def _do_load_session(self):
        if not self.session_path.exists():
            raise FileNotFoundError(self.session_path)
        self._cfg = json.loads(self.session_path.read_text("utf-8"))
        self.client = TelegramClient(self._session_file(), self._cfg["api_id"], self._cfg["api_hash"])

    def whoami(self) -> str:
        async def _w():
            await self.client.connect()
            me = await self.client.get_me()
            await self.client.disconnect()
            return me
        me = asyncio.run(_w())
        return f"{me.first_name} (@{me.username or '—'})"

    def _do_post(self, content: CampaignContent, *, prefer_video: bool) -> PostResult:
        target = self._cfg.get("target", "me")

        async def _send():
            await self.client.connect()
            try:
                if prefer_video and content.video:
                    msg = await self.client.send_file(target, str(content.video), caption=content.caption, supports_streaming=True)
                elif len(content.slides) > 1:
                    files = [str(p) for p in content.slides[: self.MAX_CAROUSEL]]
                    msg = await self.client.send_file(target, files, caption=content.caption)
                    if isinstance(msg, list):
                        msg = msg[0]
                elif content.slides:
                    msg = await self.client.send_file(target, str(content.slides[0]), caption=content.caption)
                elif content.video:
                    msg = await self.client.send_file(target, str(content.video), caption=content.caption)
                else:
                    msg = await self.client.send_message(target, content.caption)
                return msg
            finally:
                await self.client.disconnect()

        msg = asyncio.run(_send())
        url = f"https://t.me/{target.lstrip('@')}/{msg.id}" if isinstance(target, str) and target.startswith("@") else None
        return PostResult.success(self.SHORT_NAME, str(msg.id), url, target=target)

    def _do_first_comment(self, media_id: str, text: str) -> None:
        target = self._cfg.get("target", "me")
        async def _reply():
            await self.client.connect()
            try:
                await self.client.send_message(target, text, reply_to=int(media_id))
            finally:
                await self.client.disconnect()
        asyncio.run(_reply())
