"""Threads via the official Meta Threads API (REST)."""
from __future__ import annotations

import getpass
import json
import os
import time

import requests

from ..base import PlatformAdapter
from ..content import CampaignContent
from ..factory import register
from ..result import PostResult

API_BASE = "https://graph.threads.net/v1.0"


@register("th", display="Threads")
class Threads(PlatformAdapter):
    MAX_CAROUSEL = 10
    CAPTION_MAX = 500

    def __init__(self):
        super().__init__()
        self._cfg: dict = {}

    def _do_login(self):
        print(f"[{self.SHORT_NAME}] one-time setup")
        print("  developers.facebook.com → Threads API → long-lived token + user_id")
        user_id = input("  threads user_id (numeric): ").strip()
        token = getpass.getpass("  long-lived access token (hidden): ").strip()
        resp = requests.get(f"{API_BASE}/me", params={"fields": "username,name", "access_token": token}, timeout=20)
        resp.raise_for_status()
        me = resp.json()
        print(f"  ✓ @{me.get('username')}")
        self.session_path.write_text(json.dumps({"user_id": user_id, "access_token": token}), encoding="utf-8")
        os.chmod(self.session_path, 0o600)

    def _do_load_session(self):
        if not self.session_path.exists():
            raise FileNotFoundError(self.session_path)
        self._cfg = json.loads(self.session_path.read_text("utf-8"))

    def _api(self, method: str, path: str, **kw):
        kw.setdefault("params", {})["access_token"] = self._cfg["access_token"]
        r = requests.request(method, f"{API_BASE}{path}", timeout=60, **kw)
        r.raise_for_status()
        return r.json()

    def whoami(self) -> str:
        me = self._api("GET", "/me", params={"fields": "username,name"})
        return f"@{me.get('username')}"

    def _wait_container(self, container_id: str, timeout_s: int = 60) -> None:
        start = time.time()
        while time.time() - start < timeout_s:
            st = self._api("GET", f"/{container_id}", params={"fields": "status,error_message"})
            if st.get("status") == "FINISHED":
                return
            if st.get("status") == "ERROR":
                raise RuntimeError(f"container failed: {st}")
            time.sleep(2)
        raise TimeoutError(f"container {container_id} didn't finish in {timeout_s}s")

    def _do_post(self, content: CampaignContent, *, prefer_video: bool) -> PostResult:
        uid = self._cfg["user_id"]
        for p in content.slides[: self.MAX_CAROUSEL]:
            if not str(p).startswith(("http://", "https://")):
                return PostResult.failure(
                    self.SHORT_NAME,
                    "Threads API requires PUBLIC media URLs. Host slides on a CDN first.",
                )
        if prefer_video and content.video and not str(content.video).startswith(("http://", "https://")):
            return PostResult.failure(self.SHORT_NAME, "Threads needs public video URL")

        if prefer_video and content.video:
            container = self._api("POST", f"/{uid}/threads",
                                  params={"media_type": "VIDEO", "video_url": str(content.video), "text": content.caption})
        elif len(content.slides) > 1:
            children = []
            for p in content.slides[: self.MAX_CAROUSEL]:
                c = self._api("POST", f"/{uid}/threads",
                              params={"media_type": "IMAGE", "image_url": str(p), "is_carousel_item": "true"})
                children.append(c["id"])
            container = self._api("POST", f"/{uid}/threads",
                                  params={"media_type": "CAROUSEL", "children": ",".join(children), "text": content.caption})
        elif content.slides:
            container = self._api("POST", f"/{uid}/threads",
                                  params={"media_type": "IMAGE", "image_url": str(content.slides[0]), "text": content.caption})
        else:
            container = self._api("POST", f"/{uid}/threads", params={"media_type": "TEXT", "text": content.caption})

        self._wait_container(container["id"])
        pub = self._api("POST", f"/{uid}/threads_publish", params={"creation_id": container["id"]})
        username = self._api("GET", "/me", params={"fields": "username"})["username"]
        return PostResult.success(self.SHORT_NAME, pub["id"], f"https://www.threads.net/@{username}/post/{pub['id']}")

    def _do_first_comment(self, media_id: str, text: str) -> None:
        uid = self._cfg["user_id"]
        rc = self._api("POST", f"/{uid}/threads",
                       params={"media_type": "TEXT", "text": text, "reply_to_id": media_id})
        self._wait_container(rc["id"])
        self._api("POST", f"/{uid}/threads_publish", params={"creation_id": rc["id"]})
