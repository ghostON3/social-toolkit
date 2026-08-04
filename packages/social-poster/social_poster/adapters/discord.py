"""Discord via webhook URL."""
from __future__ import annotations

import getpass
import json
import os

import requests

from ..base import PlatformAdapter
from ..content import CampaignContent
from ..factory import register
from ..result import PostResult


@register("dc", display="Discord")
class Discord(PlatformAdapter):
    MAX_CAROUSEL = 10
    SUPPORTS_COMMENTS = False
    CAPTION_MAX = 2000

    def __init__(self):
        super().__init__()
        self._cfg: dict = {}

    def _do_login(self):
        print(f"[{self.SHORT_NAME}] webhook setup")
        print("  Channel settings → Integrations → Webhooks → New Webhook → Copy URL")
        url = getpass.getpass("  webhook URL (hidden): ").strip()
        self.session_path.write_text(json.dumps({"webhook_url": url}), encoding="utf-8")
        os.chmod(self.session_path, 0o600)

    def _do_load_session(self):
        if not self.session_path.exists():
            raise FileNotFoundError(self.session_path)
        self._cfg = json.loads(self.session_path.read_text("utf-8"))

    def whoami(self) -> str:
        return f"webhook {self._cfg['webhook_url'][:60]}…"

    def _do_post(self, content: CampaignContent, *, prefer_video: bool) -> PostResult:
        url = self._cfg["webhook_url"]
        attachments = [content.video] if (prefer_video and content.video) else list(content.slides[: self.MAX_CAROUSEL])

        files = {}
        try:
            for i, p in enumerate(attachments):
                mime = "video/mp4" if p.suffix.lower() == ".mp4" else "image/png"
                files[f"files[{i}]"] = (p.name, open(p, "rb"), mime)

            data = {"content": content.caption}
            resp = requests.post(url, data={"payload_json": json.dumps(data)}, files=files, timeout=120)
            resp.raise_for_status()
            msg = resp.json()
            channel_id = msg.get("channel_id")
            mid = msg.get("id")
            jump = f"https://discord.com/channels/@me/{channel_id}/{mid}" if channel_id and mid else None

            # Follow-up message instead of native comment
            if content.first_comment:
                requests.post(url, json={"content": self.truncate(content.first_comment)}, timeout=30)

            return PostResult.success(self.SHORT_NAME, mid, jump)
        finally:
            for v in files.values():
                try:
                    v[1].close()
                except Exception:
                    pass
