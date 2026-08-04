"""YouTube via the official Google API client."""
from __future__ import annotations

import os
import re

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from ..base import PlatformAdapter
from ..content import CampaignContent
from ..factory import register
from ..result import PostResult

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


@register("yt", display="YouTube")
class YouTube(PlatformAdapter):
    MAX_CAROUSEL = -1
    CAPTION_MAX = 5000

    def __init__(self):
        super().__init__()
        self.service = None
        self._client_secret = self.session_path.parent / "youtube-client.json"

    def _do_login(self):
        if not self._client_secret.exists():
            print(f"✗ missing {self._client_secret}")
            print("  console.cloud.google.com → enable YouTube Data API v3")
            print("  → create OAuth client (Desktop) → save downloaded JSON at the path above")
            raise FileNotFoundError(self._client_secret)
        flow = InstalledAppFlow.from_client_secrets_file(str(self._client_secret), SCOPES)
        creds = flow.run_local_server(port=0)
        self.session_path.write_text(creds.to_json(), encoding="utf-8")
        os.chmod(self.session_path, 0o600)
        self.service = build("youtube", "v3", credentials=creds)

    def _do_load_session(self):
        if not self.session_path.exists():
            raise FileNotFoundError(self.session_path)
        creds = Credentials.from_authorized_user_file(str(self.session_path), SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self.session_path.write_text(creds.to_json(), encoding="utf-8")
            else:
                raise RuntimeError("token expired without refresh — re-login")
        self.service = build("youtube", "v3", credentials=creds)

    def whoami(self) -> str:
        ch = self.service.channels().list(part="snippet,statistics", mine=True).execute()
        c = ch["items"][0]
        return f"{c['snippet']['title']} · subs={c['statistics']['subscriberCount']} · videos={c['statistics']['videoCount']}"

    def _do_post(self, content: CampaignContent, *, prefer_video: bool) -> PostResult:
        if not content.video:
            return PostResult.failure(self.SHORT_NAME, "youtube needs a .mp4")
        title = content.caption.split("\n", 1)[0][:100] or content.name
        description = content.caption[len(title):].strip() or content.caption
        tags = re.findall(r"#(\w+)", content.first_comment or content.caption)[:15]
        body = {
            "snippet": {"title": title, "description": description, "tags": tags, "categoryId": "22"},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
        }
        media = MediaFileUpload(str(content.video), chunksize=-1, resumable=True, mimetype="video/mp4")
        req = self.service.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            _, response = req.next_chunk()
        vid = response["id"]
        if content.thumbnail and content.thumbnail.exists():
            try:
                self.service.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(content.thumbnail))).execute()
            except HttpError:
                pass
        return PostResult.success(self.SHORT_NAME, vid, f"https://youtu.be/{vid}")

    def _do_first_comment(self, media_id: str, text: str) -> None:
        self.service.commentThreads().insert(
            part="snippet",
            body={"snippet": {"videoId": media_id, "topLevelComment": {"snippet": {"textOriginal": text}}}},
        ).execute()

    def _do_delete(self, media_id: str) -> bool:
        self.service.videos().delete(id=media_id).execute()
        return True
