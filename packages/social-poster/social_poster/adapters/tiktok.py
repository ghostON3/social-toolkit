"""TikTok via official Content Posting API."""
from __future__ import annotations

import getpass
import json
import os

import requests

from ..base import PlatformAdapter
from ..content import CampaignContent
from ..factory import register
from ..result import PostResult

API_BASE = "https://open.tiktokapis.com"


@register("tt", display="TikTok")
class TikTok(PlatformAdapter):
    MAX_CAROUSEL = -1
    SUPPORTS_COMMENTS = False
    CAPTION_MAX = 2200

    def __init__(self):
        super().__init__()
        self._cfg: dict = {}

    def _do_login(self):
        print(f"[{self.SHORT_NAME}] one-time setup")
        print("  prereq: developers.tiktok.com Content Posting API approval")
        token = getpass.getpass("  access_token (hidden): ").strip()
        open_id = input("  open_id: ").strip()
        self.session_path.write_text(json.dumps({"access_token": token, "open_id": open_id}), encoding="utf-8")
        os.chmod(self.session_path, 0o600)

    def _do_load_session(self):
        if not self.session_path.exists():
            raise FileNotFoundError(self.session_path)
        self._cfg = json.loads(self.session_path.read_text("utf-8"))

    def whoami(self) -> str:
        return f"open_id={self._cfg['open_id'][:8]}…"

    def _do_post(self, content: CampaignContent, *, prefer_video: bool) -> PostResult:
        if not content.video:
            return PostResult.failure(self.SHORT_NAME, "tiktok needs a .mp4 (no carousel via this adapter)")
        if not str(content.video).startswith(("http://", "https://")):
            return PostResult.failure(
                self.SHORT_NAME,
                "TikTok PULL_FROM_URL needs a public video URL; host the .mp4 first.",
            )
        body = {
            "post_info": {
                "title": content.caption[:150],
                "description": content.caption,
                "privacy_level": "SELF_ONLY",
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {"source": "PULL_FROM_URL", "video_url": str(content.video)},
        }
        headers = {"Authorization": f"Bearer {self._cfg['access_token']}", "Content-Type": "application/json"}
        r = requests.post(f"{API_BASE}/v2/post/publish/video/init/", json=body, headers=headers, timeout=120)
        r.raise_for_status()
        publish_id = r.json().get("data", {}).get("publish_id")
        return PostResult.success(
            self.SHORT_NAME, publish_id, f"https://www.tiktok.com/@/video/{publish_id}",
            note="TikTok processes async — poll /post/publish/status/fetch/",
        )
