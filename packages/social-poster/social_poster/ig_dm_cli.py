"""CLI for the Instagram Direct / group-chat capability (:mod:`ig_direct`).

    ig-dm whoami
    ig-dm resolve handle_one handle_two
    ig-dm group-create --users handle_one --title "my group" --message "channel up"
    ig-dm add --thread <id> --users someoneelse
    ig-dm send --thread <id> --text "hi"
    ig-dm send-media --thread <id> --file clip.mp4
    ig-dm threads
    ig-dm read --thread <id> [--amount 20] [--download ./inbox]
    ig-dm watch --thread <id> [--interval 8] [--download ./inbox]

Every acting subcommand uses the saved bot session; nothing here stores
credentials. Designed to be driven by hand or wired into a loop / the Elo OS.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Optional


def _ig():
    from .ig_direct import IgDirect

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


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="ig-dm", description="Instagram Direct / group-chat")
    sub = ap.add_subparsers(dest="cmd", required=True)

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

    args = ap.parse_args(argv)

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
        # seed since_id with the current newest so we only react to NEW inbound
        seed = ig.read_thread(args.thread, amount=1)
        since = seed[0].id if seed else None
        print(f"# watching thread {args.thread} (interval {args.interval}s) — Ctrl-C to stop",
              file=sys.stderr)
        while True:
            fresh = ig.poll(args.thread, since, amount=args.amount)
            for m in fresh:
                row = m.as_dict()
                if args.download and m.media_url:
                    row["downloaded"] = ig.download_media(m, args.download)
                _print(row)
                since = m.id
            time.sleep(max(3, args.interval))

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
