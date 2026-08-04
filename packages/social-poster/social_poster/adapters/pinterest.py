"""Pinterest via official API v5."""
from __future__ import annotations

import base64
import getpass
import json
import os

import requests

from ..base import PlatformAdapter
from ..content import CampaignContent
from ..factory import register
from ..result import PostResult

API_BASE = "https://api.pinterest.com/v5"


@register("pin", display="Pinterest")
class Pinterest(PlatformAdapter):
    MAX_CAROUSEL = -1
    SUPPORTS_COMMENTS = False
    CAPTION_MAX = 800

    def __init__(self):
        super().__init__()
        self._cfg: dict = {}

    def _do_login(self):
        print(f"[{self.SHORT_NAME}] one-time setup")
        token = getpass.getpass("  access_token (hidden): ").strip()
        try:
            r = requests.get(f"{API_BASE}/boards", headers={"Authorization": f"Bearer {token}"}, timeout=20)
            r.raise_for_status()
            for b in r.json().get("items", [])[:10]:
                print(f"    {b['id']}  {b['name']}")
        except Exception as e:
            print(f"  (could not list boards: {e})")
        board_id = input("  default board id: ").strip()
        self.session_path.write_text(json.dumps({"access_token": token, "board_id": board_id}), encoding="utf-8")
        os.chmod(self.session_path, 0o600)

    def _do_load_session(self):
        if not self.session_path.exists():
            raise FileNotFoundError(self.session_path)
        self._cfg = json.loads(self.session_path.read_text("utf-8"))

    def whoami(self) -> str:
        r = requests.get(f"{API_BASE}/user_account",
                         headers={"Authorization": f"Bearer {self._cfg['access_token']}"}, timeout=20)
        if r.ok:
            d = r.json()
            return f"@{d.get('username')} · followers={d.get('follower_count')} · pins={d.get('pin_count')}"
        return "(unable to fetch)"

    def _do_post(self, content: CampaignContent, *, prefer_video: bool) -> PostResult:
        if not content.slides:
            return PostResult.failure(self.SHORT_NAME, "pinterest needs an image")
        pin_image = content.slides[0]
        if str(pin_image).startswith(("http://", "https://")):
            media_source = {"source_type": "image_url", "url": str(pin_image)}
        else:
            with open(pin_image, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            media_source = {"source_type": "image_base64", "content_type": "image/png", "data": b64}
        title = content.caption.split("\n", 1)[0][:100] or content.name
        body = {
            "board_id": self._cfg["board_id"],
            "title": title,
            "description": content.caption,
            "media_source": media_source,
        }
        r = requests.post(
            f"{API_BASE}/pins",
            headers={"Authorization": f"Bearer {self._cfg['access_token']}", "Content-Type": "application/json"},
            json=body, timeout=120,
        )
        r.raise_for_status()
        pin = r.json()
        return PostResult.success(self.SHORT_NAME, pin.get("id"), f"https://pinterest.com/pin/{pin.get('id')}")
