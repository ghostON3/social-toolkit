# instagram-dm-kit

**Read, send and *harvest* Instagram Direct messages from Python.** Turn the
reels, posts and links you forward into a DM into a structured knowledge corpus —
the shape a RAG / LLM pipeline actually wants.

Built on [instagrapi](https://github.com/subzeroid/instagrapi). One session on
disk, no credentials in code, a clean CLI (`idk`) and a small importable API.

```bash
pip install instagram-dm-kit
idk login                                   # once — mints a session
idk threads                                 # find your thread id
idk corpus --thread <id> --out corpus.jsonl # → knowledge corpus
```

### Already signed in in your browser? Skip the password.

If Chrome (or Chromium/Brave/Edge/Firefox) is logged in to
`https://www.instagram.com/direct/inbox/`, reuse that session — no password,
no 2FA challenge, no device re-verification:

```bash
pip install 'instagram-dm-kit[browser]'
idk connect                                  # auto-detects the logged-in profile
idk connect --browser brave                  # a different browser
idk connect --profile "Profile 1"            # a specific Chrome profile
idk connect --cookie-file ~/.config/google-chrome/Default/Cookies
idk connect --sessionid <sessionid>           # paste it yourself, no browser read
idk threads                                  # ...and everything else works unchanged
```

`connect` pulls the `sessionid` cookie out of the browser, validates it against
Instagram, and writes the same session file `idk login` would — so `read`,
`harvest`, `corpus`, `watch`, etc. are identical afterward. The `sessionid` is a
full-account bearer token; it only leaves your machine inside instagrapi's own
calls to Instagram and lands on disk in the usual session file.

## Why

Most people use a DM thread (to themselves, or a small group) as a *save-for-later
feed*: a reel here, a link there, a photo, a voice note. That stream is trapped in
the app and impossible to query. `instagram-dm-kit` gets it out as clean JSON.

- **`idk harvest`** → one JSON record per message (id, kind, text, media url, ts) —
  the full normalized log, ideal for archival and media download.
- **`idk corpus`** → JSONL of `{"type":"user","content":<text>}` lines — drops bare
  reel-author handles so only substantive prose (captions, link descriptions, your
  own notes) becomes knowledge. Feed it straight into an embedding/RAG pipeline.

## Capabilities

| Command | What it does |
|---|---|
| `idk login` | Mint + persist an instagrapi session (`IDK_USER`/`IDK_PASS`/`IDK_2FA` for automation) |
| `idk connect` | Mint a session from an **already-logged-in browser** (`--browser`/`--profile`/`--cookie-file`/`--sessionid`) — no password |
| `idk whoami` | Confirm the acting account |
| `idk threads` | List DM threads (id, title, participants, last activity) |
| `idk resolve <user>` | `@username → pk` |
| `idk read --thread <id> [--download ./inbox]` | Read + normalize messages, optionally download media |
| `idk watch --thread <id>` | Poll a thread, emit only **new** inbound (a two-way bot loop) |
| `idk send / send-media / react / reply / ack` | Outbound: text, media, reactions, threaded replies, triage acks |
| `idk harvest --thread <id> --out records.jsonl` | Full normalized message log → JSONL |
| `idk corpus --thread <id> --out corpus.jsonl` | Knowledge corpus (prose only) → JSONL |

### Media that "just works"

Shared reels/posts arrive as an `instagram.com/reel/…` **page** url, not a file.
`download_media` resolves those to a media pk and pulls the real bytes (with a
bumped timeout + retries), and fetches direct CDN urls straight. Photos, videos,
albums and voice notes are all handled.

## Library use

```python
from instagram_dm_kit import IgDirect
from instagram_dm_kit.harvest import to_corpus_lines

ig = IgDirect()                                  # loads the saved session
msgs = ig.read_thread("<thread_id>", amount=50)
corpus = to_corpus_lines(msgs)                   # ready for ingestion
```

`normalize_message`, `to_records`, `to_corpus_lines`, `triage_line` are **pure
functions** — no network — so they're unit-tested offline and trivial to reuse.

## The message shape

```jsonc
{
  "id": "328686...",
  "user_id": "12345",
  "from_me": false,
  "timestamp": "2026-06-18T21:34:09",
  "kind": "video",            // text|link|video|media|voice|gif|*_share|other
  "item_type": "xma_clip",    // raw instagrapi type
  "text": "creator caption …",
  "media_url": "https://www.instagram.com/reel/…/"
}
```

## Install (dev)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q          # offline tests, no session/network needed
```

## Notes & etiquette

- This uses the **private** mobile API via instagrapi — not an official Meta API.
  Respect rate limits (the client spaces calls out by default), read Instagram's
  ToS, and use it on accounts/threads you own. You are responsible for your usage.
- Sessions and any harvested `*.jsonl` / `inbox/` are git-ignored by default. Never
  commit a session file.

## License

MIT © ghostON3
