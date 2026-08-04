"""Facebook Page via the Graph API (requests).

Post-shaped adapter: a Facebook Page feed behaves like Instagram — single
photo, photo album (carousel-ish), or video, each with a caption. Mirrors the
Instagram adapter's shape so the facade fan-out treats it identically.

Auth model: a long-lived Page access token + page id, captured once at login
and saved to the session file. No interactive OAuth dance here (that needs a
browser redirect); the user pastes a token they already minted in the Graph API
Explorer or via their own app. Honest about what it needs.
"""
from __future__ import annotations

import getpass
import json
import os

import requests

from ..base import PlatformAdapter
from ..content import CampaignContent
from ..decorators import retry
from ..factory import register
from ..result import PostResult

GRAPH = "https://graph.facebook.com/v21.0"


@register("fb", display="Facebook Page")
class Facebook(PlatformAdapter):
    MAX_CAROUSEL = 10
    CAPTION_MAX = 63206  # Facebook's post body limit
    SUPPORTS_VIDEO = True
    SUPPORTS_COMMENTS = True

    def __init__(self):
        super().__init__()
        self._cfg: dict = {}

    @property
    def _token(self) -> str:
        return self._cfg["page_token"]

    @property
    def _page_id(self) -> str:
        return self._cfg["page_id"]

    def _do_login(self):
        print(f"[{self.SHORT_NAME}] one-time login")
        page_id = input("  page id: ").strip()
        page_token = getpass.getpass("  page access token (hidden): ").strip()
        # Verify the token before persisting.
        r = requests.get(f"{GRAPH}/{page_id}", params={"fields": "name", "access_token": page_token})
        r.raise_for_status()
        name = r.json().get("name", page_id)
        self._cfg = {"page_id": page_id, "page_token": page_token}
        self.session_path.write_text(json.dumps(self._cfg), encoding="utf-8")
        os.chmod(self.session_path, 0o600)
        print(f"  ✓ {name}")

    def _do_load_session(self):
        if not self.session_path.exists():
            raise FileNotFoundError(self.session_path)
        self._cfg = json.loads(self.session_path.read_text("utf-8"))

    def whoami(self) -> str:
        r = requests.get(
            f"{GRAPH}/{self._page_id}",
            params={"fields": "name,fan_count", "access_token": self._token},
        )
        r.raise_for_status()
        d = r.json()
        return f"{d.get('name', self._page_id)} · likes={d.get('fan_count', '?')}"

    @retry(times=2, on=(requests.RequestException,), backoff=5)
    def _do_post(self, content: CampaignContent, *, prefer_video: bool) -> PostResult:
        if prefer_video and content.video:
            return self._post_video(content)
        if len(content.slides) > 1:
            return self._post_album(content)
        if content.slides:
            return self._post_photo(content, content.slides[0])
        if content.video:
            return self._post_video(content)
        # text-only status
        r = requests.post(
            f"{GRAPH}/{self._page_id}/feed",
            data={"message": content.caption, "access_token": self._token},
        )
        r.raise_for_status()
        pid = r.json()["id"]
        return PostResult.success(self.SHORT_NAME, pid, self._permalink(pid))

    def _post_photo(self, content: CampaignContent, path) -> PostResult:
        with open(path, "rb") as fh:
            r = requests.post(
                f"{GRAPH}/{self._page_id}/photos",
                data={"caption": content.caption, "access_token": self._token},
                files={"source": fh},
            )
        r.raise_for_status()
        d = r.json()
        pid = d.get("post_id") or d["id"]
        return PostResult.success(self.SHORT_NAME, pid, self._permalink(pid))

    def _post_album(self, content: CampaignContent) -> PostResult:
        # Upload each photo unpublished, then attach to a single feed post.
        media_ids: list[str] = []
        for path in content.slides[: self.MAX_CAROUSEL]:
            with open(path, "rb") as fh:
                r = requests.post(
                    f"{GRAPH}/{self._page_id}/photos",
                    data={"published": "false", "access_token": self._token},
                    files={"source": fh},
                )
            r.raise_for_status()
            media_ids.append(r.json()["id"])
        attached = {f"attached_media[{i}]": json.dumps({"media_fbid": mid}) for i, mid in enumerate(media_ids)}
        r = requests.post(
            f"{GRAPH}/{self._page_id}/feed",
            data={"message": content.caption, "access_token": self._token, **attached},
        )
        r.raise_for_status()
        pid = r.json()["id"]
        return PostResult.success(self.SHORT_NAME, pid, self._permalink(pid))

    def _post_video(self, content: CampaignContent) -> PostResult:
        with open(content.video, "rb") as fh:
            r = requests.post(
                f"{GRAPH}/{self._page_id}/videos",
                data={"description": content.caption, "access_token": self._token},
                files={"source": fh},
            )
        r.raise_for_status()
        vid = r.json()["id"]
        return PostResult.success(self.SHORT_NAME, vid, self._permalink(vid))

    def _do_first_comment(self, media_id: str, text: str) -> None:
        r = requests.post(
            f"{GRAPH}/{media_id}/comments",
            data={"message": text, "access_token": self._token},
        )
        r.raise_for_status()

    def _do_delete(self, media_id: str) -> bool:
        r = requests.delete(f"{GRAPH}/{media_id}", params={"access_token": self._token})
        r.raise_for_status()
        return bool(r.json().get("success", True))

    def _permalink(self, post_id: str) -> str:
        return f"https://facebook.com/{post_id}"
