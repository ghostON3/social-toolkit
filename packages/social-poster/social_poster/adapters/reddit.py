"""Reddit via PRAW."""
from __future__ import annotations

import getpass
import json
import os
import time

import praw

from ..base import PlatformAdapter
from ..content import CampaignContent
from ..factory import register
from ..result import PostResult


@register("rd", display="Reddit")
class Reddit(PlatformAdapter):
    MAX_CAROUSEL = 20
    CAPTION_MAX = 40000

    def __init__(self):
        super().__init__()
        self.r: praw.Reddit | None = None
        self._cfg: dict = {}

    def _do_login(self):
        print(f"[{self.SHORT_NAME}] one-time login")
        print("  create an app at https://www.reddit.com/prefs/apps (type: script)")
        client_id = input("  client_id: ").strip()
        client_secret = getpass.getpass("  client_secret (hidden): ").strip()
        username = input("  username: ").strip()
        password = getpass.getpass("  password (hidden): ").strip()
        sub = input("  default subreddit (e.g. u_yourname for profile, or test): ").strip() or f"u_{username}"

        creds = {
            "client_id": client_id,
            "client_secret": client_secret,
            "username": username,
            "password": password,
            "user_agent": f"social-poster:{username}:v0.2",
            "default_subreddit": sub,
        }
        r = praw.Reddit(**{k: v for k, v in creds.items() if k != "default_subreddit"})
        me = r.user.me()
        print(f"  ✓ u/{me.name}")
        self.session_path.write_text(json.dumps(creds), encoding="utf-8")
        os.chmod(self.session_path, 0o600)

    def _do_load_session(self):
        if not self.session_path.exists():
            raise FileNotFoundError(self.session_path)
        self._cfg = json.loads(self.session_path.read_text("utf-8"))
        self.r = praw.Reddit(**{k: v for k, v in self._cfg.items() if k != "default_subreddit"})

    def whoami(self) -> str:
        me = self.r.user.me()
        return f"u/{me.name} · link_karma={me.link_karma} · comment_karma={me.comment_karma}"

    def _do_post(self, content: CampaignContent, *, prefer_video: bool) -> PostResult:
        title = content.caption.split("\n", 1)[0][:300] or content.name
        sub = self.r.subreddit(self._cfg.get("default_subreddit", f"u_{self._cfg['username']}"))
        if prefer_video and content.video:
            sub_obj = sub.submit_video(
                title=title,
                video_path=str(content.video),
                thumbnail_path=str(content.thumbnail) if content.thumbnail else None,
                timeout=120,
            )
        elif len(content.slides) > 1:
            images = [{"image_path": str(p)} for p in content.slides[: self.MAX_CAROUSEL]]
            sub_obj = sub.submit_gallery(title=title, images=images)
        elif content.slides:
            sub_obj = sub.submit_image(title=title, image_path=str(content.slides[0]))
        elif content.video:
            sub_obj = sub.submit_video(title=title, video_path=str(content.video))
        else:
            sub_obj = sub.submit(title=title, selftext=content.caption)
        return PostResult.success(self.SHORT_NAME, sub_obj.id, f"https://reddit.com{sub_obj.permalink}")

    def _do_first_comment(self, media_id: str, text: str) -> None:
        time.sleep(2)
        self.r.submission(id=media_id).reply(text)

    def _do_delete(self, media_id: str) -> bool:
        self.r.submission(id=media_id).delete()
        return True
