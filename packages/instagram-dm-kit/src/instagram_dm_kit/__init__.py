"""instagram-dm-kit — read, send, harvest & understand Instagram Direct messages.

Two halves hang off one seam — the normalized :class:`Record` / :class:`IgMessage`
shape:

- **messaging** (needs a live session): :class:`IgDirect` — connect/login, read a
  thread, send/react/reply, ``watch`` a thread live, download shared media.
- **understanding** (local models): :func:`understand_reel` / :func:`understand_thread`
  — download → whisper speech-gate → qwen3-vl vision → structured record.

The pure stages — :func:`normalize_message`, :func:`to_records`,
:func:`to_corpus_lines`, :func:`is_substantive`, the ``view`` helpers — import
with **zero** instagrapi/session. Heavy deps are optional extras
(``[live]`` = instagrapi, ``[understand]`` = faster-whisper, ``[browser]`` =
browser-cookie3); nothing here is imported eagerly, so ``import instagram_dm_kit``
works with none of them installed.

    from instagram_dm_kit import (
        IgDirect, IgMessage, Record, normalize_message,   # messaging + seam
        resolve_thread_id, parse_thread_key,               # thread-id resolution
        to_records, to_corpus_lines, is_substantive,       # harvest (pure)
        build_view, clean_url, primary_url,                # view (pure)
        understand_reel, understand_thread,                # understanding
        login, connect, sessionid_from_browser,            # auth
    )
"""

from .connect import connect, sessionid_from_browser
from .direct import (
    IgDirect,
    IgMessage,
    Record,
    default_session_path,
    normalize_message,
    parse_thread_key,
    triage_emoji,
    triage_line,
)
from .harvest import author_and_caption, is_substantive, to_corpus_lines, to_records
from .login import login
from .understand import ReelUnderstanding, understand_reel, understand_thread
from .view import build_view, clean_url, first_line, primary_url, render_markdown

__version__ = "0.1.0"


def resolve_thread_id(id_or_url, *, ig=None):
    """Module-level convenience → :meth:`IgDirect.resolve_thread_id`.

    Pass an existing ``ig`` (an :class:`IgDirect`) to reuse a session; otherwise
    one is constructed from the default session path. Any form the method
    accepts works: numeric id, ``/direct/t/`` web URL, ``@handle``, username.
    """
    return (ig or IgDirect()).resolve_thread_id(id_or_url)


__all__ = [
    # messaging + seam
    "IgDirect",
    "IgMessage",
    "Record",
    "normalize_message",
    "resolve_thread_id",
    "parse_thread_key",
    "triage_emoji",
    "triage_line",
    "default_session_path",
    # harvest (pure)
    "to_records",
    "to_corpus_lines",
    "is_substantive",
    "author_and_caption",
    # view (pure)
    "build_view",
    "render_markdown",
    "clean_url",
    "first_line",
    "primary_url",
    # understanding
    "understand_reel",
    "understand_thread",
    "ReelUnderstanding",
    # auth
    "login",
    "connect",
    "sessionid_from_browser",
    "__version__",
]
