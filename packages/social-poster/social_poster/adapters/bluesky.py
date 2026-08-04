"""Bluesky via the official atproto Python SDK."""
from __future__ import annotations

import getpass
import json
import os
from pathlib import Path

from atproto import Client, client_utils, models

from ..base import PlatformAdapter
from ..content import CampaignContent
from ..factory import register
from ..result import PostResult


@register("bsky", display="Bluesky")
class Bluesky(PlatformAdapter):
    MAX_CAROUSEL = 4
    SUPPORTS_COMMENTS = False    # Bluesky has replies, not native comments
    CAPTION_MAX = 300

    def __init__(self):
        super().__init__()
        self.cl = Client()
        self._creds_path = self.session_path.with_suffix(".creds.json")

    def _do_login(self):
        print(f"[{self.SHORT_NAME}] login (use a Bluesky APP password)")
        handle = input("  handle (e.g. you.bsky.social): ").strip()
        app_pw = getpass.getpass("  app password (hidden): ")
        profile = self.cl.login(handle, app_pw)
        sess = self.cl.export_session_string()
        self.session_path.write_text(sess, encoding="utf-8")
        self._creds_path.write_text(json.dumps({"handle": handle, "app_password": app_pw}), encoding="utf-8")
        for p in (self.session_path, self._creds_path):
            os.chmod(p, 0o600)
        print(f"  ✓ @{profile.handle}")

    def _do_load_session(self):
        if self.session_path.exists():
            try:
                self.cl.login(session_string=self.session_path.read_text("utf-8").strip())
                return
            except Exception:
                pass
        if not self._creds_path.exists():
            raise FileNotFoundError(self.session_path)
        creds = json.loads(self._creds_path.read_text("utf-8"))
        self.cl.login(creds["handle"], creds["app_password"])
        self.session_path.write_text(self.cl.export_session_string(), encoding="utf-8")
        os.chmod(self.session_path, 0o600)

    def whoami(self) -> str:
        me = self.cl.me
        try:
            prof = self.cl.app.bsky.actor.get_profile({"actor": me.handle})
            return f"@{me.handle} · followers={prof.followers_count} · following={prof.follows_count}"
        except Exception:
            return f"@{me.handle}"

    def _do_post(self, content: CampaignContent, *, prefer_video: bool) -> PostResult:
        if prefer_video and content.video:
            return self._post_video(content)
        if content.slides:
            return self._post_images(content)
        if content.video:
            return self._post_video(content)
        return PostResult.failure(self.SHORT_NAME, "nothing to post")

    def _post_images(self, content: CampaignContent) -> PostResult:
        images = []
        for p in content.slides[: self.MAX_CAROUSEL]:
            with open(p, "rb") as f:
                blob = self.cl.com.atproto.repo.upload_blob(f.read())
            images.append(models.AppBskyEmbedImages.Image(alt="", image=blob.blob))
        embed = models.AppBskyEmbedImages.Main(images=images)
        record = models.AppBskyFeedPost.Record(
            text=content.caption,
            embed=embed,
            created_at=client_utils.get_current_time_iso(),
        )
        resp = self.cl.com.atproto.repo.create_record(
            data=models.ComAtprotoRepoCreateRecord.Data(
                repo=self.cl.me.did,
                collection="app.bsky.feed.post",
                record=record,
            )
        )
        rkey = resp.uri.split("/")[-1]
        return PostResult.success(
            self.SHORT_NAME, resp.uri, f"https://bsky.app/profile/{self.cl.me.handle}/post/{rkey}"
        )

    def _post_video(self, content: CampaignContent) -> PostResult:
        with open(content.video, "rb") as f:
            blob = self.cl.com.atproto.repo.upload_blob(f.read())
        embed = models.AppBskyEmbedVideo.Main(video=blob.blob, alt="")
        record = models.AppBskyFeedPost.Record(
            text=content.caption,
            embed=embed,
            created_at=client_utils.get_current_time_iso(),
        )
        resp = self.cl.com.atproto.repo.create_record(
            data=models.ComAtprotoRepoCreateRecord.Data(
                repo=self.cl.me.did,
                collection="app.bsky.feed.post",
                record=record,
            )
        )
        rkey = resp.uri.split("/")[-1]
        return PostResult.success(
            self.SHORT_NAME, resp.uri, f"https://bsky.app/profile/{self.cl.me.handle}/post/{rkey}"
        )

    def _do_delete(self, media_id: str) -> bool:
        parts = media_id.split("/")
        collection = parts[-2]
        rkey = parts[-1]
        self.cl.com.atproto.repo.delete_record(
            data=models.ComAtprotoRepoDeleteRecord.Data(
                repo=self.cl.me.did,
                collection=collection,
                rkey=rkey,
            )
        )
        return True
