#!/usr/bin/env python3
"""GroupMe conversations waiting on the founder, for the morning brief's Inbox.

Founder, 2026-09-03: everything on the board is connected and automated, nothing by hand.
GroupMe was one of the three inbox channels he named.

## Why this is a NEW reader and not a call into the one that exists

One of the consulting instance's client projects already carries a `groupme_pull.py`
that reads this API and already knows the two things that are easy to get wrong (below). Its own docstring says,
in capitals, ANALYSIS TOOL ONLY and must never become a production path: it pages whole histories to
JSONL for a client measurement. A morning brief that shells it would put a
client-analysis tool on a 07:40 schedule. So this borrows its KNOWLEDGE and not its code.
It is not named here because this repo is public and that path names a client.

The two things it knows, both of which cost that file a silent wrong answer once:

  1. DMs are a different endpoint. `/groups` does not carry them, `/chats` does. Reading
     only `/groups` excluded three live client conversations and nothing said so, because
     a channel you never fetch cannot show up as missing.
  2. The response key differs. `/groups/<id>/messages` returns `messages`,
     `/direct_messages` returns `direct_messages`. Reading the wrong key yields an empty
     page, which a pager reads as "history exhausted" and reports as a clean finish.

## What counts as waiting on him

The last message in a conversation is not his, and it landed inside the window. That is
all. No model call, no sentiment read: this is a cheap deterministic check that runs
inside the brief's 20s optional-section budget.

Credential: `~/.config/kipi/groupme-token` or `$GROUPME_TOKEN`, resolved via
`Path.home()`, never a literal home path.

OFF switch: a missing token file. `collect` returns None and the brief renders no
GroupMe section at all, exactly as `notion_board.py`'s missing page-id file does. Absent
is not an error and is not "nobody messaged you".
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.groupme.com/v3"
TOKEN_FILE = Path.home() / ".config" / "kipi" / "groupme-token"

#: How far back a conversation still counts as live. Matches the brief's mail section,
#: which the founder already reads as "since I last looked".
WINDOW_HOURS = 48
#: Conversations scanned per run. GroupMe returns them most-recent-first, so this is a
#: recency cut and not a sample. Bounded because this shares a 20s budget with the board.
MAX_CONVERSATIONS = 25
TIMEOUT_S = 6.0

#: The allowlist of GroupMe conversations worth reading. Founder-directed 2026-09-03,
#: verbatim: *"you're looking in too many channels. I only want you to look in the AI
#: chat channel, the other ones have nothing for me."*
#:
#: Machine-local and NOT in this repo, which is public: the ids name client
#: conversations, the same reason the sibling `groupme_pull.py` path is described here
#: and never written out. One id per line, `#` comments and blank lines ignored.
#:
#: THE FILE BEING ABSENT IS NOT AN EMPTY ALLOWLIST. A missing file means nobody has
#: chosen yet, so every conversation is read, which is the behaviour that shipped. An
#: EMPTY file is a choice and reads nothing. Collapsing the two would turn a lost
#: config file into a silently quiet section, which is the failure this brief exists to
#: not have.
CHANNELS_FILE = Path.home() / ".config" / "kipi" / "groupme-channels"


def load_allowlist(path=None) -> set | None:
    """The set of allowed conversation ids, or None when no choice is recorded.

    None and set() mean different things on purpose; see CHANNELS_FILE.
    """
    path = Path(path) if path else CHANNELS_FILE
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    ids = set()
    for line in raw.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            ids.add(line)
    return ids


def load_token() -> str | None:
    tok = (os.environ.get("GROUPME_TOKEN") or "").strip()
    if tok:
        return tok
    if TOKEN_FILE.exists():
        tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    return None


def _get(path: str, token: str, opener=None, **params):
    params["token"] = token
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    open_fn = opener or urllib.request.urlopen
    with open_fn(urllib.request.Request(url), timeout=TIMEOUT_S) as fh:
        return json.load(fh).get("response")


def _me(token: str, opener=None) -> str:
    return str((_get("/users/me", token, opener) or {}).get("user_id") or "")


def waiting(now: dt.datetime, token: str, opener=None) -> list[dict]:
    """Conversations whose newest message is not his, inside the window."""
    cutoff = (now - dt.timedelta(hours=WINDOW_HOURS)).timestamp()
    me = _me(token, opener)
    out = []

    allow = load_allowlist()

    groups = _get("/groups", token, opener, per_page=MAX_CONVERSATIONS) or []
    for g in groups:
        if allow is not None and str(g.get("id")) not in allow:
            continue
        meta = g.get("messages") or {}
        created = meta.get("last_message_created_at") or 0
        if created < cutoff:
            continue
        preview = meta.get("preview") or {}
        # THE PREVIEW HAS NO AUTHOR. Measured live 2026-09-03: its keys are exactly
        # nickname, text, image_url, attachments. The first draft of this function read
        # `preview["user_id"]`, got "" for every group, and the `sender != me` test
        # therefore dropped all four -- reporting a clean zero on a morning when three
        # groups were live. A nickname is not an id (it varies per group), so the author
        # is fetched from the message itself, and only for groups already inside the
        # window, which keeps this at a handful of calls rather than one per group.
        sender, unreadable = "", False
        try:
            msgs = (_get(f"/groups/{g.get('id')}/messages", token, opener, limit=1)
                    or {}).get("messages") or []
            if msgs:
                sender = str(msgs[0].get("user_id") or msgs[0].get("sender_id") or "")
            unreadable = False
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
            # One unreadable group must not void the others, and it must not be
            # mistaken for "he sent the last message" EITHER WAY. Codex finding
            # (minor), 2026-09-03: this set sender="" and fell through, so a group
            # whose author could not be read was rendered as a confirmed "waiting on
            # you". Unknown is now carried as unknown and says so in the row.
            sender, unreadable = "", True
        if sender == me:
            continue
        out.append({"channel": "group", "name": g.get("name") or "(unnamed group)",
                    "who": ("author unreadable" if unreadable
                            else preview.get("nickname") or "someone"),
                    "unreadable": unreadable,
                    "text": (preview.get("text") or "")[:160], "at": created})

    # /chats is the DM list. Its shape differs from /groups: the peer is `other_user`
    # and the newest message is `last_message`, not `messages.preview`.
    # DMs are skipped entirely once an allowlist exists. The docstring above records
    # the scar that reading only /groups once hid three live client DMs; that scar is
    # about a channel nobody CHOSE to exclude. An allowlist is the founder choosing,
    # and a chosen exclusion is not a silent one.
    chats = [] if allow is not None else (
        _get("/chats", token, opener, per_page=MAX_CONVERSATIONS) or [])
    for c in chats:
        last = c.get("last_message") or {}
        created = last.get("created_at") or c.get("updated_at") or 0
        sender = str(last.get("user_id") or last.get("sender_id") or "")
        if created >= cutoff and sender and sender != me:
            who = (c.get("other_user") or {}).get("name") or "someone"
            out.append({"channel": "dm", "name": who, "who": who,
                        "text": (last.get("text") or "")[:160], "at": created})

    out.sort(key=lambda r: r["at"], reverse=True)
    return out


def collect(now: dt.datetime, sources: dict, opener=None):
    """(rows, error), or None when no token exists. The registered entry point."""
    token = load_token()
    if not token:
        return None                      # OFF, not broken
    try:
        rows = waiting(now, token, opener)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        # Never a silent zero. A GroupMe outage must not read as "nobody messaged you".
        return [], f"GroupMe unreachable: {type(exc).__name__}: {exc}"
    if not rows:
        return [], None
    out = []
    for r in rows:
        text = " ".join((r["text"] or "").split())[:140]
        if r.get("unreadable"):
            out.append(f"{r['name']}: COULD NOT READ who sent the last message "
                       f"({text!r})")
        else:
            out.append(f"{r['name']}: {r['who']} said {text!r}")
    return out, None
