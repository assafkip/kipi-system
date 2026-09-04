#!/usr/bin/env python3
"""Was this mail thread answered SOMEWHERE ELSE? Deterministic, no model call.

Founder, 2026-09-04, reading an Inbox of twelve rows he had already dealt with:
*"You're only looking if I replied in the thread, which is wrong, because as long as
I replied to that email address and the reply makes sense, then it should be fine.
And for people like [a retainer client], if I replied in the messages, that's fine."*

`collect_mail` asks a model for threads where he "has not replied yet", and a model
reading one thread can only answer THREAD-SCOPED. Two ways that is wrong, and both
were measured on his live data before this module was written:

  A reply in a DIFFERENT THREAD to the same person. He answers by starting a new
  mail rather than hitting reply, and the old thread stays open forever.

  A reply in a DIFFERENT CHANNEL. One retainer client emailed him 2026-08-05; he
  sent 36 messages in that client's group chat between 2026-08-18 and 2026-09-02.
  The email was answered on 18 August in the place that client actually talks. The
  board showed it as owed, 717 hours old.

## Why this is a deterministic post-filter and not a better prompt

The model cannot see the other threads or the chat, so no prompt fixes it. What
decides "answered" is a comparison of timestamps across sources that are all
already on disk, and a comparison is code. The model finds candidates; this
decides.

## The direction of the errors, which is the whole design

Answering here means REMOVING a row from his board. A wrong removal hides work he
owes someone, which is the failure this board exists to prevent; a wrong keep costs
him one glance. So every uncertainty resolves toward KEEPING the row:

  no counterpart address parsed  -> keep
  no inbound timestamp           -> keep
  cache unreadable               -> keep everything, and say so
  chat unreachable               -> keep everything, and say so

`filter_answered` therefore returns (rows, notes) and never raises.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

CONSULTING_ROOT = Path(os.environ.get(
    "KIPI_CONSULTING_ROOT", str(Path.home() / "projects" / "consulting")))
CACHE = CONSULTING_ROOT / "q-consult" / "output" / "thread-cache.json"
REGISTRY = CONSULTING_ROOT / "q-consult" / "my-project" / "clients.json"
CHANNELS_FILE = Path.home() / ".config" / "kipi" / "groupme-channels"

IDENTITIES = ("assaf@askconsulting.io", "assafkip@gmail.com")
_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _when(value):
    try:
        stamp = dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def _is_his(msg) -> bool:
    sender = str(msg.get("sender") or msg.get("from") or "").lower()
    return any(i in sender for i in IDENTITIES)


def _recipients(msg):
    out = set()
    for key in ("toRecipients", "to", "ccRecipients", "cc"):
        value = msg.get(key)
        items = value if isinstance(value, (list, tuple)) else [value]
        for item in items:
            out.update(a.lower() for a in _ADDRESS.findall(str(item or "")))
    return out


def his_last_outbound(cache) -> dict:
    """{address: when he last WROTE to it}, across every cached thread.

    Across threads on purpose: answering in a new mail instead of hitting reply is
    the first of the two defects, and a per-thread view cannot see it.
    """
    last = {}
    for tid, thread in (cache or {}).items():
        if tid == "_provenance" or not isinstance(thread, dict):
            continue
        for msg in thread.get("messages") or []:
            if not isinstance(msg, dict) or not _is_his(msg):
                continue
            when = _when(msg.get("date"))
            if not when:
                continue
            for addr in _recipients(msg):
                if last.get(addr) is None or when > last[addr]:
                    last[addr] = when
    return last


def client_of(address, registry) -> str | None:
    """The slug whose contacts carry this address, or None. Exact match only:
    a domain match would answer one client's mail with another's chat."""
    address = (address or "").lower()
    for rec in (registry or {}).get("clients", []):
        for contact in rec.get("contacts") or []:
            if str(contact.get("email") or "").lower() == address:
                return rec.get("slug")
    return None


def channel_slugs(path=None) -> dict:
    """{group_id: slug} for allowlist lines that name a client."""
    path = Path(path) if path else CHANNELS_FILE
    out = {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in raw.splitlines():
        line = line.split("#", 1)[0].strip()
        parts = line.split()
        if len(parts) >= 2:
            out[parts[0]] = parts[1]
    return out


#: Distinct days he must have spoken in a client's chat AFTER their mail before that
#: chat counts as having answered it.
#:
#: PRESENCE IS NOT A REPLY, and the first version of this got that wrong. It dropped a
#: mail the moment his LAST chat message postdated it, so for a client he talks to
#: daily every email older than this morning vanished -- including, in the reviewer's
#: example, a two-hour-old signature request and a twenty-day-overdue invoice. Talking
#: to someone at 10am is not evidence you dealt with what they sent at 9am.
#:
#: Three days is read off the case this rule was built from rather than picked: that
#: client mailed on 08-05 and he wrote in their chat on 15 separate days between 08-18
#: and 09-02. Sustained engagement across days is the thing that makes "I answered it
#: in the messages" true; a single message is not, and neither is a single day.
CHAT_DAYS_TO_ANSWER = 3


def filter_answered(threads, cache=None, registry=None, chat_days=None,
                    chat_last=None):
    """(kept, notes). `threads` are dicts with `id`, `from` and `age_hours`.

    `chat_days` is {slug: [dates he spoke in that client's chat]}, injected so this
    stays a pure function and so a chat outage is the caller's fact, not a silent
    pass here. `chat_last` is the older single-timestamp form and is accepted only
    so an old caller degrades to KEEPING rows rather than crashing; it never answers
    anything, because one timestamp cannot show sustained engagement.
    """
    notes = []
    if cache is None:
        try:
            cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return list(threads), [f"kept every thread: mail history unreadable "
                                   f"({type(exc).__name__})"]
    if registry is None:
        try:
            registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            registry = {}
            notes.append("no registry: chat replies could not be matched to clients")

    if not isinstance(cache, dict):
        return list(threads), notes + ["kept every thread: mail history is not a map"]
    if not isinstance(registry, dict):
        registry = {}
        notes.append("registry ignored: not a map")
    outbound = his_last_outbound(cache)
    chat_days = chat_days or {}
    if chat_last and not chat_days:
        notes.append("chat evidence ignored: caller passed the old single-timestamp "
                     "form, which cannot show sustained engagement")
    kept = []
    for th in threads:
        addr = None
        found = _ADDRESS.findall(str(th.get("from") or ""))
        if found:
            addr = found[0].lower()
        inbound = _when(th.get("inbound_at"))
        if inbound is None and isinstance(th.get("age_hours"), (int, float)):
            inbound = (dt.datetime.now(dt.timezone.utc)
                       - dt.timedelta(hours=float(th["age_hours"])))
        if not addr or inbound is None:
            kept.append(th)          # cannot judge it: keep it
            continue

        later = outbound.get(addr)
        if later and later > inbound:
            notes.append(f"{addr}: answered by mail {later.date()}, after their "
                         f"{inbound.date()}")
            continue

        slug = client_of(addr, registry)
        # `>=` so a chat message on the SAME DAY as their mail is counted as a chat
        # day. It is still nowhere near CHAT_DAYS_TO_ANSWER, so it cannot answer
        # anything; counting it is what makes the "presence is not a reply" note fire
        # on exactly the case the reviewer named (mail 09:00, chat 10:00).
        days = sorted({d for d in (chat_days.get(slug) or [])
                       if d and d >= inbound.date()}) if slug else []
        if len(days) >= CHAT_DAYS_TO_ANSWER:
            notes.append(f"{addr}: answered in {slug}'s chat on {len(days)} days "
                         f"since their {inbound.date()} (through {days[-1]})")
            continue
        if days:
            # Named rather than silent: he should be able to see that the chat was
            # looked at and did not clear this one, instead of wondering why one
            # mail from a client he talks to daily is still on the board.
            notes.append(f"{addr}: KEPT, only {len(days)} chat day(s) since their "
                         f"mail; presence is not a reply")
        kept.append(th)
    return kept, notes
