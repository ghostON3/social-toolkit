"""``idk`` — command-line interface for instagram-dm-kit.

    idk login                                   # mint a session (once)
    idk connect                                 # ...or reuse a logged-in browser
    idk whoami
    idk threads
    idk resolve <user> [<user> ...]
    idk read    --thread <id> [--amount N] [--download ./inbox]
    idk watch   --thread <id> [--interval 8] [--download ./inbox]
    idk send    --thread <id> --text "hi"
    idk send-media --thread <id> --file clip.mp4
    idk react   --thread <id> --message <id> [--emoji 👀]
    idk reply   --thread <id> --text "..." [--to <message id>]
    idk ack     --thread <id> --message <id> --as saved --what "..." --where "..."
    idk harvest --thread <id> [--amount N] [--out records.jsonl]   # full log
    idk corpus  --thread <id> [--amount N] [--out corpus.jsonl]    # knowledge corpus
    idk view    --records records.jsonl --out ./view              # browsable md + links
    idk understand --thread <id> [--limit N] [--retry-errors]     # local-model reel understanding
    idk understand --url <reel-url>                               # understand one reel

A ``--thread`` accepts a raw thread id OR a pasted ``/direct/t/<key>`` web URL
OR an ``@handle`` — it is resolved to the real thread id, so a web-URL never
crashes the ``int()`` cast. Every acting subcommand reuses the saved session;
nothing here stores
credentials. Drive it by hand or wire it into a loop / ingestion pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional


def _ig():
    from .direct import IgDirect

    return IgDirect()


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _resolve_users(ig, users: list[str]) -> list[str]:
    """Accept a mix of @usernames and raw numeric pks → list of pk strings."""
    names = [u for u in users if not u.lstrip().isdigit()]
    pks = [u for u in users if u.lstrip().isdigit()]
    if names:
        pks.extend(ig.resolve(names).values())
    return pks


def _write_lines(lines: list[str], out: Optional[str]) -> None:
    payload = "".join(f"{ln}\n" for ln in lines)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print(f"# wrote {len(lines)} line(s) → {out}", file=sys.stderr)
        print(out)
    else:
        sys.stdout.write(payload)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="idk", description="instagram-dm-kit")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login")

    p = sub.add_parser("connect", help="mint a session from an already-logged-in browser")
    p.add_argument("--browser", default="chrome",
                   help="chrome|chromium|brave|edge|firefox (default: chrome)")
    p.add_argument("--profile", default=None,
                   help="Chromium profile dir name, e.g. 'Default' or 'Profile 1'")
    p.add_argument("--cookie-file", default=None,
                   help="path to a specific browser Cookies DB (overrides --browser/--profile)")
    p.add_argument("--sessionid", default=None,
                   help="paste a sessionid directly instead of reading the browser")

    sub.add_parser("whoami")
    sub.add_parser("threads")

    p = sub.add_parser("resolve")
    p.add_argument("users", nargs="+")

    p = sub.add_parser("group-create")
    p.add_argument("--users", required=True, help="comma-separated @usernames or pks")
    p.add_argument("--title", default="")
    p.add_argument("--message", default=None)

    p = sub.add_parser("add")
    p.add_argument("--thread", required=True)
    p.add_argument("--users", required=True)

    p = sub.add_parser("send")
    p.add_argument("--thread", required=True)
    p.add_argument("--text", required=True)

    p = sub.add_parser("send-media")
    p.add_argument("--thread", required=True)
    p.add_argument("--file", required=True)

    p = sub.add_parser("react")
    p.add_argument("--thread", required=True)
    p.add_argument("--message", required=True)
    p.add_argument("--emoji", default="👀")

    p = sub.add_parser("reply")
    p.add_argument("--thread", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--to", default=None, help="message id to thread-reply to")

    p = sub.add_parser("ack")
    p.add_argument("--thread", required=True)
    p.add_argument("--message", required=True)
    p.add_argument("--as", dest="disposition", default="seen",
                   help="seen|saved|useful|knowledge|task|done|skip|question")
    p.add_argument("--what", default=None)
    p.add_argument("--where", default=None)
    p.add_argument("--note", default=None)
    p.add_argument("--emoji", default=None, help="override the disposition emoji")

    p = sub.add_parser("read")
    p.add_argument("--thread", required=True)
    p.add_argument("--amount", type=int, default=20)
    p.add_argument("--download", default=None, help="dir to download media into")

    p = sub.add_parser("watch")
    p.add_argument("--thread", required=True)
    p.add_argument("--interval", type=int, default=8)
    p.add_argument("--amount", type=int, default=20)
    p.add_argument("--download", default=None)

    p = sub.add_parser("harvest", help="full normalized log → JSONL")
    p.add_argument("--thread", required=True)
    p.add_argument("--amount", type=int, default=40)
    p.add_argument("--out", default=None)
    p.add_argument("--include-from-me", action="store_true")

    p = sub.add_parser("corpus", help="knowledge corpus (prose only) → JSONL")
    p.add_argument("--thread", required=True)
    p.add_argument("--amount", type=int, default=40)
    p.add_argument("--out", default=None)
    p.add_argument("--include-from-me", action="store_true")
    p.add_argument("--keep-thin", action="store_true", help="keep bare author handles too")

    p = sub.add_parser("view", help="records.jsonl → browsable markdown + links table")
    p.add_argument("--records", required=True, help="path to a harvested records.jsonl")
    p.add_argument("--out", default="view", help="output dir (default: ./view)")

    p = sub.add_parser(
        "understand",
        help="local-model reel understanding (download→whisper→qwen3-vl→JSONL)",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--thread", help="thread id / web-URL / @handle to understand")
    g.add_argument("--url", help="a single reel web-URL or pk to understand")
    p.add_argument("--limit", type=int, default=None, help="cap #reels (thread mode)")
    p.add_argument("--out", default="understanding.jsonl",
                   help="JSONL sink (resumable; thread mode)")
    p.add_argument("--media-dir", default="media", help="where bytes/frames land")
    p.add_argument("--vision-model", default="qwen3-vl:8b")
    p.add_argument("--whisper-size", default="base")
    p.add_argument("--ollama-url", default=None, help="override /api/chat endpoint")
    p.add_argument("--retry-errors", action="store_true",
                   help="re-run ids previously marked with an error")

    args = ap.parse_args(argv)

    if args.cmd == "login":
        from .login import login

        _print(login())
        return 0

    if args.cmd == "connect":
        from .connect import connect

        cookie_file = args.cookie_file
        if not cookie_file and args.profile:
            import os as _os
            cookie_file = _os.path.expanduser(
                f"~/.config/google-chrome/{args.profile}/Cookies"
            )
        _print(connect(
            browser=args.browser,
            cookie_file=cookie_file,
            sessionid=args.sessionid,
        ))
        return 0

    if args.cmd == "whoami":
        _print(_ig().whoami())
        return 0

    if args.cmd == "resolve":
        _print(_ig().resolve(args.users))
        return 0

    if args.cmd == "threads":
        _print(_ig().list_threads())
        return 0

    if args.cmd == "group-create":
        ig = _ig()
        pks = _resolve_users(ig, [u for u in args.users.split(",") if u.strip()])
        tid = ig.create_group(pks, title=args.title, first_message=args.message)
        _print({"thread_id": tid, "participants": pks, "title": args.title})
        return 0

    if args.cmd == "add":
        ig = _ig()
        pks = _resolve_users(ig, [u for u in args.users.split(",") if u.strip()])
        _print({"ok": ig.add_users(args.thread, pks), "added": pks})
        return 0

    if args.cmd == "send":
        _print({"sent": _ig().send(args.thread, args.text)})
        return 0

    if args.cmd == "send-media":
        _print({"sent": _ig().send_media(args.thread, args.file)})
        return 0

    if args.cmd == "react":
        _print({"reacted": _ig().react(args.thread, args.message, args.emoji)})
        return 0

    if args.cmd == "reply":
        _print({"sent": _ig().reply(args.thread, args.text, reply_to_id=args.to)})
        return 0

    if args.cmd == "ack":
        _print(_ig().acknowledge(
            args.thread, args.message, disposition=args.disposition,
            what=args.what, where=args.where, note=args.note, emoji=args.emoji,
        ))
        return 0

    if args.cmd == "read":
        ig = _ig()
        msgs = ig.read_thread(args.thread, amount=args.amount)
        out = []
        for m in msgs:
            row = m.as_dict()
            if args.download and m.media_url:
                row["downloaded"] = ig.download_media(m, args.download)
            out.append(row)
        _print(out)
        return 0

    if args.cmd == "watch":
        ig = _ig()
        print(f"# watching thread {args.thread} (interval {args.interval}s) — Ctrl-C to stop",
              file=sys.stderr)
        for m in ig.watch(
            args.thread, interval=args.interval, amount=args.amount,
            download=args.download,
        ):
            _print(m.as_dict())

    if args.cmd in {"harvest", "corpus"}:
        from .harvest import to_corpus_lines, to_records

        ig = _ig()
        msgs = ig.read_thread(args.thread, amount=args.amount)
        if args.cmd == "harvest":
            records = to_records(msgs, include_from_me=args.include_from_me)
            _write_lines([json.dumps(r, ensure_ascii=False) for r in records], args.out)
        else:
            lines = to_corpus_lines(
                msgs, include_from_me=args.include_from_me, keep_thin=args.keep_thin,
            )
            _write_lines(lines, args.out)
        return 0

    if args.cmd == "view":
        from .view import build_view

        _print(build_view(args.records, args.out))
        return 0

    if args.cmd == "understand":
        from .understand import understand_reel, understand_thread

        ig = _ig()
        cfg = {
            "media_dir": args.media_dir,
            "vision_model": args.vision_model,
            "whisper_size": args.whisper_size,
        }
        if args.ollama_url:
            cfg["ollama_url"] = args.ollama_url
        if args.url:
            _print(understand_reel(args.url, ig=ig, **cfg).as_dict())
            return 0
        n = 0
        for rec in understand_thread(
            args.thread, ig=ig, out_path=args.out, limit=args.limit,
            retry_errors=args.retry_errors, **cfg,
        ):
            n += 1
            tag = f"ERR {rec.error}" if rec.error else (
                "speech" if rec.transcript and not rec.vision else "vision"
            )
            print(f"[{n}] {rec.id} — {tag}", file=sys.stderr)
        print(f"# wrote {n} record(s) → {args.out}", file=sys.stderr)
        print(args.out)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
