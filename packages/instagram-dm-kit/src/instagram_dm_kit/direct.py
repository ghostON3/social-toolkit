"""Instagram Direct — group chats, inbound reading, media, comm-channel polling.

The *messaging* half of Instagram automation: read DM threads, send text/media,
poll a thread for only-new inbound, react/reply, and download shared reels,
posts, photos and voice notes. It loads an instagrapi session saved on disk
(see :mod:`instagram_dm_kit.login`), so no credentials live in this module.

Capabilities:

1. **Open a group chat / 1:1 channel** — :meth:`IgDirect.create_group`
   (instagrapi ``direct_thread_create`` + ``direct_thread_add_users``).
2. **Read & normalize what people send** — :meth:`IgDirect.read_thread`
   returns flat, JSON-friendly messages; :meth:`IgDirect.download_media` pulls
   the underlying file (resolving shared-reel *page* urls to real bytes).
3. **A two-way comm channel** — :meth:`IgDirect.poll` yields only *new* inbound
   messages since the last seen id, so a loop can react + reply.

:func:`normalize_message` is a pure function with no network, so the message
shape mapping is unit-tested offline against fixtures.
"""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Protocol, runtime_checkable


def default_session_path() -> Path:
    """Where the instagrapi session settings live.

    Override with ``IDK_SESSION``; defaults to
    ``~/.config/instagram-dm-kit/session.json``.
    """
    env = os.environ.get("IDK_SESSION")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".config" / "instagram-dm-kit" / "session.json"


SESSION_PATH = default_session_path()

# An instagrapi thread id is a ~39-digit (2**128-scale) integer; a web-URL id
# (`/direct/t/<key>`) is a much shorter messaging_thread_key / thread_v2_id
# (~15-19 digits). This threshold splits "already addressable" from "must resolve".
_THREAD_ID_MIN_DIGITS = 25

# item_type (instagrapi) → coarse kind we care about in a chat channel.
# Instagram increasingly wraps shares as "xma_*" (cross-app message attachments),
# so a shared reel arrives as `xma_clip`, a shared link as `xma_link`, etc.
_KIND_BY_ITEM_TYPE = {
    "text": "text",
    "raw_text": "text",
    "link": "link",
    "xma_link": "link",
    "clip": "video",          # a reel/clip shared into the DM
    "xma_clip": "video",      # reel/clip share (newer xma wrapper)
    "media": "media",         # uploaded photo or video
    "xma_media": "media",
    "visual_media": "visual", # ephemeral (view-once) photo/video
    "voice_media": "voice",
    "animated_media": "gif",
    "media_share": "post_share",
    "story_share": "story_share",
    "xma_story_share": "story_share",
    "reel_share": "reel_share",
    "xma_reel_share": "reel_share",
    "felix_share": "igtv_share",
    "xma_share": "external_share",
    "generic_xma": "external_share",
    "placeholder": "placeholder",
}

# message sub-nodes that may carry a downloadable/linkable asset
_ASSET_NODES = (
    "clip", "media", "visual_media", "voice_media", "media_share",
    "story_share", "reel_share", "felix_share", "animated_media",
    "xma_share", "generic_xma", "raw_xma",
)


def _to_dict(raw: Any) -> dict:
    """Accept a pydantic model, an object with __dict__, or a plain dict.

    Uses model_dump(mode="json") so pydantic HttpUrl fields come out as plain
    strings — instagrapi types those as Url objects, which would otherwise slip
    past every ``isinstance(..., str)`` url check.
    """
    if isinstance(raw, dict):
        return raw
    fn = getattr(raw, "model_dump", None)
    if callable(fn):
        try:
            return fn(mode="json")
        except Exception:
            try:
                return fn()
            except Exception:
                pass
    fn = getattr(raw, "dict", None)
    if callable(fn):
        try:
            return fn()
        except Exception:
            pass
    return dict(getattr(raw, "__dict__", {}) or {})


def _first_url(node: Any, _depth: int = 0) -> Optional[str]:
    """Best-effort: find the most downloadable URL inside a nested message node.

    Prefers video over image (so a clip/video survives), then any *_url string.
    Recurses through dicts/lists; bounded depth to stay cheap and total.
    """
    if _depth > 6 or node is None:
        return None
    node = _to_dict(node) if not isinstance(node, (dict, list, str)) else node

    if isinstance(node, str):
        return node if node.startswith("http") else None

    if isinstance(node, dict):
        # Strong preference order for a single best asset.
        for key in ("video_url", "video_versions", "playback_url"):
            v = node.get(key)
            url = _pluck(v)
            if url:
                return url
        # then images / thumbnails (image_versions2.candidates[].url is nested)
        for key in ("thumbnail_url", "url", "image_versions2", "candidates"):
            if key not in node:
                continue
            v = node[key]
            url = _pluck(v) or _first_url(v, _depth + 1)
            if url:
                return url
        # the reel/share thumbnail lives under preview_url
        for key in ("preview_url", "header_icon_url"):
            v = node.get(key)
            if isinstance(v, str) and v.startswith("http"):
                return v
        # recurse into the containers that hold real media
        for key in ("clip", "media", "visual_media", "video", "image",
                    "animated_media", "voice_media", "audio", "resources",
                    "xma_share", "generic_xma", "raw_xma"):
            if key in node:
                url = _first_url(node[key], _depth + 1)
                if url:
                    return url
        return None

    if isinstance(node, list):
        for item in node:
            url = _first_url(item, _depth + 1)
            if url:
                return url
    return None


def _pluck(v: Any) -> Optional[str]:
    if isinstance(v, str) and v.startswith("http"):
        return v
    if isinstance(v, list) and v:
        return _pluck(_to_dict(v[0]).get("url") if not isinstance(v[0], str) else v[0]) \
            or (v[0] if isinstance(v[0], str) and v[0].startswith("http") else None)
    if isinstance(v, dict):
        return v.get("url") if isinstance(v.get("url"), str) else None
    return None


# Quick comm-style: every inbound item can get an emoji reaction + a threaded
# reply so the human sees AT A GLANCE what was done with it and where it landed.
# disposition → (emoji, human label).
TRIAGE: dict[str, tuple[str, str]] = {
    "seen": ("👀", "seen"),
    "saved": ("📥", "saved"),
    "useful": ("⭐", "useful"),
    "knowledge": ("🧠", "filed to knowledge"),
    "task": ("🔁", "turned into task"),
    "done": ("✅", "processed"),
    "skip": ("🗑️", "skipped (noise)"),
    "question": ("❓", "need more"),
}


def triage_emoji(disposition: str) -> str:
    return TRIAGE.get(disposition, TRIAGE["seen"])[0]


def triage_line(
    disposition: str,
    what: Optional[str] = None,
    where: Optional[str] = None,
    note: Optional[str] = None,
) -> str:
    """Pure: build a one-line reply that records what happened to a message.

    e.g. triage_line("saved", "reel mrnotion.co", "inbox/x.mp4", "notion clone")
         → "📥 saved · reel mrnotion.co → inbox/x.mp4 · notion clone"
    """
    emoji, label = TRIAGE.get(disposition, TRIAGE["seen"])
    parts = [f"{emoji} {label}"]
    if what:
        parts.append(f"· {what}")
    if where:
        parts.append(f"→ {where}")
    if note:
        parts.append(f"· {note}")
    return " ".join(parts)


@runtime_checkable
class Record(Protocol):
    """The normalized 5-field shape the generic stages actually depend on.

    This is the seam between the IG *adapter* (``normalize_message`` →
    :class:`IgMessage`) and the source-agnostic stages (``harvest``, ``view``,
    ``understand``). A second source (a WhatsApp / Telegram export, say) only has
    to produce something that satisfies this Protocol — it never has to be an
    :class:`IgMessage`. Kept deliberately tiny: exactly the fields the generic
    code reads, nothing more.
    """

    id: str
    from_me: bool
    kind: str
    text: str
    media_url: Optional[str]
    timestamp: Optional[str]

    def as_dict(self) -> dict:  # noqa: D401 - protocol method
        ...


@dataclass
class IgMessage:
    id: str
    user_id: str
    from_me: bool
    timestamp: Optional[str]
    kind: str
    item_type: str
    text: str
    media_url: Optional[str]

    def as_dict(self) -> dict:
        return asdict(self)


# A browser Direct URL is https://www.instagram.com/direct/t/<messaging_thread_key>/
# — the trailing path segment is the id instagrapi addresses threads by. Pasting
# the whole URL (or any trailing-slash form) into a --thread arg must Just Work.
_THREAD_URL_RE = re.compile(r"/direct/t/([^/?#]+)")


def parse_thread_key(id_or_url: str) -> str:
    """Pure: reduce a thread id-or-URL to its bare key. Idempotent, no network.

    Accepts a raw thread id, a ``/direct/t/<key>`` web URL (with or without
    query/fragment/trailing slash), an ``@handle`` or a bare username. Returns
    the key untouched when it's already bare, so it's safe to call repeatedly.
    """
    s = str(id_or_url or "").strip()
    m = _THREAD_URL_RE.search(s)
    if m:
        return m.group(1).strip()
    if s.startswith("http"):
        # some other IG URL form — take the last non-empty path segment
        tail = [seg for seg in s.split("?")[0].split("#")[0].split("/") if seg]
        return tail[-1] if tail else s
    return s.rstrip("/")


def normalize_message(raw: Any) -> IgMessage:
    """Pure: map an instagrapi DirectMessage (or dict) into a flat IgMessage.

    No network. Safe on partial dicts (that's how the unit tests drive it).
    """
    d = _to_dict(raw)
    item_type = str(d.get("item_type") or "text")
    kind = _KIND_BY_ITEM_TYPE.get(item_type, "other")

    text = d.get("text") or ""
    if not text:
        # links/shares often carry their text/title elsewhere
        link = d.get("link")
        if isinstance(link, dict):
            text = link.get("text") or (link.get("link_context") or {}).get("link_url") or ""
        elif isinstance(link, str):
            text = link
    if not text:
        xma = d.get("xma_share") or d.get("generic_xma")
        if isinstance(xma, dict):
            text = (xma.get("title") or xma.get("header_title_text")
                    or xma.get("video_url") or xma.get("target_url") or "")

    media_url = None
    if kind in {"video", "media", "visual", "voice", "gif", "post_share",
                "story_share", "reel_share", "igtv_share", "external_share"}:
        # search the type-specific node, then every known asset node, then all
        media_url = _first_url(d.get(item_type))
        for node_key in _ASSET_NODES:
            if media_url:
                break
            if d.get(node_key):
                media_url = _first_url(d.get(node_key))
        media_url = media_url or _first_url(d)

    ts = d.get("timestamp")
    return IgMessage(
        id=str(d.get("id") or ""),
        user_id=str(d.get("user_id") or ""),
        from_me=bool(d.get("is_sent_by_viewer")),
        timestamp=str(ts) if ts is not None else None,
        kind=kind,
        item_type=item_type,
        text=text,
        media_url=media_url,
    )


class IgDirect:
    """Thin, rate-limit-aware wrapper over instagrapi's direct_* surface."""

    def __init__(self, session_path: Optional[Path] = None, delay_range=(2, 5)):
        # Imported lazily so importing this module (and running the offline
        # unit tests) never requires instagrapi or a session on disk.
        from instagrapi import Client  # noqa: WPS433

        self.session_path = Path(session_path or default_session_path())
        self.cl = Client()
        self.cl.delay_range = list(delay_range)
        if not self.session_path.exists():
            raise FileNotFoundError(
                f"no IG session at {self.session_path} — run `idk login` first"
            )
        self.cl.load_settings(self.session_path)

    # ---- identity -----------------------------------------------------------
    def whoami(self) -> dict:
        me = self.cl.account_info()
        return {"username": me.username, "pk": str(me.pk), "full_name": me.full_name}

    def resolve(self, usernames: Iterable[str]) -> dict[str, str]:
        """username → pk (str). Spaced out to respect rate limits."""
        out: dict[str, str] = {}
        for name in usernames:
            name = name.lstrip("@").strip()
            if not name:
                continue
            out[name] = str(self.cl.user_id_from_username(name))
        return out

    # ---- group / thread management -----------------------------------------
    def create_group(
        self,
        user_ids: list[int | str],
        title: str = "",
        first_message: Optional[str] = None,
    ) -> str:
        """Open a Direct channel with the given participants. Returns thread_id.

        Instagram only treats a thread as a *group* when there are ≥2 recipients
        (creator + 2 others = 3 total). With a single recipient this opens the
        1:1 DM thread instead (still a usable comm channel) — so the same call
        works for both "spin up a group" and "open a channel with this person".

        A non-empty ``title`` names a group. ``first_message`` seeds the thread
        so it is non-empty on arrival (required for the 1:1 path).
        """
        ids = [int(u) for u in user_ids]
        if len(ids) >= 2:
            thread_id = self.cl.direct_thread_create(ids, title=title or "")
            if title:
                try:
                    self.cl.direct_thread_update_title(int(thread_id), title)
                except Exception:
                    pass  # title at creation is enough; update is best-effort
            if first_message:
                self.cl.direct_send(first_message, thread_ids=[int(thread_id)])
            return str(thread_id)

        # single recipient → 1:1 channel via a seed message
        seed = first_message or "channel up"
        msg = self.cl.direct_send(seed, user_ids=ids)
        thread_id = str(getattr(msg, "thread_id", "") or "")
        if not thread_id:
            found = self.find_thread(ids)
            thread_id = found or ""
        return thread_id

    def add_users(self, thread_id: int | str, user_ids: list[int | str]) -> bool:
        return bool(
            self.cl.direct_thread_add_users(int(thread_id), [int(u) for u in user_ids])
        )

    def find_thread(self, user_ids: list[int | str]) -> Optional[str]:
        try:
            t = self.cl.direct_thread_by_participants([int(u) for u in user_ids])
            tid = (t or {}).get("thread_id") if isinstance(t, dict) else getattr(t, "id", None)
            return str(tid) if tid else None
        except Exception:
            return None

    def resolve_thread_id(self, id_or_url: str | int) -> str:
        """Resolve any thread reference to the numeric id instagrapi addresses.

        Accepts (and never crashes on): a numeric thread id, a browser
        ``/direct/t/<key>`` web URL, a bare ``messaging_thread_key``, an
        ``@handle`` or a username. The common case (numeric id, possibly pasted
        as a web URL) resolves with **zero** network calls — the URL is stripped
        and returned. Non-numeric keys are looked up: first as a username
        (→ pk → 1:1 thread), then by scanning open threads for a matching
        v2/thread key. This is the guard that stops ``int(<web-thread-key>)``
        from crashing or silently addressing the wrong thread.
        """
        key = parse_thread_key(str(id_or_url))
        if key.isdigit():
            # An instagrapi thread id is a ~39-digit (2**128-scale) integer; a
            # web-URL id (`/direct/t/<key>`) is a much shorter messaging_thread_key
            # / thread_v2_id (~15-19 digits). Only the long form is addressable
            # as-is — the short numeric form MUST be resolved, or it silently
            # addresses the wrong thread / crashes downstream.
            if len(key) >= _THREAD_ID_MIN_DIGITS:
                return key
            resolved = self._resolve_web_key(key)
            if resolved:
                return resolved
            return key  # fail honestly downstream rather than guess

        handle = key.lstrip("@")
        # 1) username → pk → the 1:1 thread with that person
        try:
            pk = self.cl.user_id_from_username(handle)
            found = self.find_thread([pk])
            if found:
                return found
        except Exception:
            pass
        # 2) scan open threads for a matching id / thread_v2 key
        try:
            for t in self.cl.direct_threads(amount=100):
                candidates = {
                    str(getattr(t, "id", "") or ""),
                    str(getattr(t, "thread_v2_id", "") or ""),
                }
                if key in candidates:
                    return str(t.id)
        except Exception:
            pass
        # nothing matched — return the key so the caller fails honestly (a bad
        # thread id) rather than us guessing wrong.
        return key

    def _resolve_web_key(self, key: str) -> Optional[str]:
        """Map a short numeric web id (thread_v2_id / messaging_thread_key) to the
        real instagrapi thread_id by scanning the raw inbox.

        The parsed ``DirectThread`` object drops ``messaging_thread_key`` (and
        often ``thread_v2_id``), so match against the raw private-inbox JSON,
        which carries both. Paginates until the key is found or the inbox ends.
        """
        cursor = None
        for _ in range(25):
            params = {
                "visual_message_return_type": "unseen",
                "thread_message_limit": "1",
                "limit": "20",
            }
            if cursor:
                params["cursor"] = cursor
            try:
                inbox = self.cl.private_request("direct_v2/inbox/", params=params).get("inbox", {})
            except Exception:
                return None
            for t in inbox.get("threads", []):
                if key in {str(t.get("thread_v2_id")), str(t.get("messaging_thread_key"))}:
                    tid = t.get("thread_id")
                    return str(tid) if tid else None
            cursor = inbox.get("oldest_cursor")
            if not inbox.get("has_older") or not cursor:
                break
        return None

    def _tid(self, thread_id: int | str) -> int:
        """Resolve then int-cast a thread reference (guards non-numeric keys)."""
        return int(self.resolve_thread_id(thread_id))

    # ---- sending ------------------------------------------------------------
    def send(self, thread_id: int | str, text: str) -> str:
        msg = self.cl.direct_send(text, thread_ids=[self._tid(thread_id)])
        return str(getattr(msg, "id", ""))

    def send_media(self, thread_id: int | str, path: str | Path) -> str:
        p = Path(path)
        suffix = p.suffix.lower()
        tid = self._tid(thread_id)
        if suffix in {".mp4", ".mov", ".webm"}:
            msg = self.cl.direct_send_video(p, thread_ids=[tid])
        else:
            msg = self.cl.direct_send_photo(p, thread_ids=[tid])
        return str(getattr(msg, "id", ""))

    # ---- feedback (quick comm-style) ---------------------------------------
    def react(self, thread_id: int | str, message_id: int | str, emoji: str = "👀") -> bool:
        """Drop an emoji reaction on a specific message."""
        return bool(
            self.cl.direct_send_reaction(self._tid(thread_id), int(message_id), emoji=emoji)
        )

    def _find_raw(self, thread_id: int | str, message_id: int | str, amount: int = 30):
        target = str(message_id)
        for m in self.cl.direct_messages(self._tid(thread_id), amount=amount):
            if str(getattr(m, "id", "")) == target:
                return m
        return None

    def reply(self, thread_id: int | str, text: str, reply_to_id: int | str | None = None,
              raw_msg=None) -> str:
        """Send a threaded reply to a message (or a plain message if not found)."""
        reply_to = raw_msg
        if reply_to is None and reply_to_id is not None:
            reply_to = self._find_raw(thread_id, reply_to_id)
        msg = self.cl.direct_send(text, thread_ids=[self._tid(thread_id)], reply_to_message=reply_to)
        return str(getattr(msg, "id", ""))

    def acknowledge(
        self,
        thread_id: int | str,
        message_id: int | str,
        disposition: str = "seen",
        what: Optional[str] = None,
        where: Optional[str] = None,
        note: Optional[str] = None,
        emoji: Optional[str] = None,
        raw_msg=None,
    ) -> dict:
        """React + threaded-reply in one shot — the standard 'what I did' ack.

        Reaction = the disposition's emoji (or an override); reply = the
        :func:`triage_line`. Reaction failure never blocks the reply.
        """
        react_emoji = emoji or triage_emoji(disposition)
        reacted = False
        try:
            reacted = self.react(thread_id, message_id, react_emoji)
        except Exception:
            reacted = False
        line = triage_line(disposition, what=what, where=where, note=note)
        reply_id = self.reply(thread_id, line, reply_to_id=message_id, raw_msg=raw_msg)
        return {"reacted": reacted, "emoji": react_emoji, "reply": line, "reply_id": reply_id}

    # ---- reading ------------------------------------------------------------
    def list_threads(self, amount: int = 20) -> list[dict]:
        threads = self.cl.direct_threads(amount=amount)
        return [
            {
                "thread_id": str(t.id),
                "title": t.thread_title,
                "is_group": bool(getattr(t, "is_group", False)),
                "users": [{"username": u.username, "pk": str(u.pk)} for u in t.users],
                "last_activity_at": str(getattr(t, "last_activity_at", "")),
            }
            for t in threads
        ]

    def read_thread(self, thread_id: int | str, amount: int = 20) -> list[IgMessage]:
        msgs = self.cl.direct_messages(self._tid(thread_id), amount=amount)
        return [normalize_message(m) for m in msgs]

    def poll(self, thread_id: int | str, since_id: Optional[str], amount: int = 20) -> list[IgMessage]:
        """Return only inbound (not-from-me) messages newer than ``since_id``.

        ``since_id`` is the last id already processed; pass None for the first
        run. Messages come newest-first from IG; we return oldest-first so a
        consumer processes them in order.
        """
        msgs = self.read_thread(thread_id, amount=amount)
        fresh: list[IgMessage] = []
        for m in msgs:  # newest-first
            if since_id and m.id == since_id:
                break
            fresh.append(m)
        fresh.reverse()  # oldest-first
        return [m for m in fresh if not m.from_me]

    def download_media(self, msg: IgMessage, dest_dir: str | Path) -> Optional[str]:
        """Download a message's media to ``dest_dir``. Returns local path or None.

        Shared reels/posts arrive as an ``instagram.com/reel|p|tv/…`` *page* url,
        not a CDN file — those are resolved to a media pk and pulled with
        instagrapi (real bytes). Direct CDN urls are fetched straight.
        """
        if not msg.media_url:
            return None
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        url = msg.media_url

        is_share_page = "instagram.com/" in url and any(
            seg in url for seg in ("/reel/", "/p/", "/tv/", "/reels/")
        )
        if is_share_page:
            # CDN video bytes routinely exceed instagrapi's default read timeout,
            # so bump it and retry transient network failures before giving up.
            prev_timeout = getattr(self.cl, "request_timeout", None)
            try:
                self.cl.request_timeout = max(int(prev_timeout or 0), 30)
            except Exception:
                pass
            last_err: Optional[Exception] = None
            try:
                for attempt in range(3):
                    try:
                        pk = self.cl.media_pk_from_url(url)
                        info = self.cl.media_info(pk)
                        mt = getattr(info, "media_type", 2)
                        if mt == 1:
                            path = self.cl.photo_download(pk, folder=dest)
                        elif mt == 8:
                            path = self.cl.album_download(pk, folder=dest)
                        else:  # 2 = video / clip
                            path = self.cl.clip_download(pk, folder=dest)
                        return str(path)
                    except Exception as e:  # noqa: BLE001 — classified below
                        last_err = e
                        time.sleep(2 * (attempt + 1))
            finally:
                if prev_timeout is not None:
                    self.cl.request_timeout = prev_timeout
            # Exhausted retries: surface the real cause instead of a silent None
            # (could be a CDN read timeout, rate limit, or a private/deleted share).
            print(
                f"download_media: share fetch failed after retries: "
                f"{type(last_err).__name__}: {last_err}",
                file=sys.stderr,
            )
            return None

        import urllib.request

        ext = ".mp4" if msg.kind in {"video", "reel_share", "igtv_share"} else (
            ".m4a" if msg.kind == "voice" else ".jpg"
        )
        out = dest / f"ig_{msg.id or int(time.time())}{ext}"
        urllib.request.urlretrieve(url, out)  # noqa: S310 (trusted IG cdn)
        return str(out)

    # ---- live comm channel --------------------------------------------------
    def watch(
        self,
        thread_id: int | str,
        *,
        interval: int = 8,
        amount: int = 20,
        download: Optional[str | Path] = None,
    ) -> Iterator[IgMessage]:
        """Yield each *new* inbound message on a thread, forever (Ctrl-C to stop).

        Seeds ``since_id`` with the current newest message so only messages that
        arrive *after* the watch starts are yielded, polls every ``interval``
        seconds, and (when ``download`` is a dir) side-loads media before
        yielding — setting ``msg.media_url`` stays, plus the file lands on disk.
        This is the reusable loop the ``idk watch`` CLI consumes; any non-CLI
        caller gets the same behaviour without copy-pasting the loop.
        """
        tid = self.resolve_thread_id(thread_id)
        seed = self.read_thread(tid, amount=1)
        since = seed[0].id if seed else None
        while True:
            for m in self.poll(tid, since, amount=amount):
                if download and m.media_url:
                    self.download_media(m, download)
                yield m
                since = m.id
            time.sleep(max(3, interval))
