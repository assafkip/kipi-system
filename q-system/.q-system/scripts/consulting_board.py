#!/usr/bin/env python3
"""The consulting half of the morning brief: clients, the GTM move, the inbox.

Founder, 2026-09-03, on finding the board full of builds and Sana's Linear queue:
*"This isn't -- I'm not looking for this to be a build dashboard, but a consulting
dashboard."* Then, on how to get there: *"copy it but everyting needs to be actually
connected fully and is automated so its not done by hand"*.

## MIRROR, never a second derivation. This is the whole design.

`consulting/q-consult/pipeline/state_card.py` already computes what he asked for, every
morning at 07:30 PT: which clients are red, what he promised each of them in his own
words, who to reach out to. `gtm-queue.json` already carries the one GTM move. This
module READS those OUTPUTS. It does not open `clients.json`, it does not import
`pipeline`, and it never recomputes a verdict.

The rejected alternative was a `collect_clients` that read the registry itself. Two
reasons it is struck, and the second is the expensive one:

  1. `clients.json` is 162 rows, of which ~150 are cold hunt-list prospects with no rate
     and no next_touch. A flat read puts 150 dead rows on his morning board.
  2. Two things deriving one truth is how the v1 Notion CRM died. His own verdict on it:
     "died because it was hand-fed". The fleet rule that came out of that (DEC-8/DEC-13,
     `gtm_board.py`, `board_sync.py`) is that the board is a MIRROR and one writer owns
     the computed state. A second derivation is a second writer wearing a reader's coat.

## STALENESS IS AN ERROR, never a quiet mirror

The card is written at 07:30 and this runs after it. If the heartbeat's date is not
today, this returns an ERROR naming the age rather than rendering yesterday's clients as
though they were this morning's. A mirror whose source is stale and which still looks
fresh is worse than a blank section: he would act on it.

That is the same law the rest of this brief already lives under -- an empty section and a
broken section are different facts -- applied to a third case the fixed four never had,
which is a section whose source is READABLE and WRONG.

## The cross-repo boundary

kipi-system reads the consulting instance's output FILES. It never imports `pipeline`,
which is the same boundary `consulting/q-consult/pipeline/tests/test_boundary.py` holds
in the other direction. `CONSULTING_ROOT` is resolved from `$KIPI_CONSULTING_ROOT` or
from `Path.home()`, never a literal home path (the content tripwire refuses one).

OFF switch: a missing consulting instance. `collect` returns None when the q-consult
directory is absent, so this renders no section at all rather than four COULD NOT READ
lines. The skeleton ships to instances that have no consulting book, and a fleet-wide
script must be silent on a machine the feature does not apply to.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")

#: How many client lines reach the brief. The card itself carries every red row; the
#: Slack section is a summary and the Notion board is the full surface. 6 is the count
#: that fits the founder's screen without scrolling, measured against the 2026-09-03 card
#: (7 red). A withheld count is always printed rather than the rest being dropped silently.
MAX_CLIENT_ROWS = 6


def consulting_root() -> Path:
    return Path(os.environ.get("KIPI_CONSULTING_ROOT")
                or Path.home() / "projects" / "consulting")


def _paths(root: Path | None = None) -> dict:
    root = root or consulting_root()
    q = root / "q-consult"
    return {
        "card": q / "output" / "today-card.md",
        "heartbeat": q / "output" / "ask-crm-state-card-heartbeat.json",
        "gtm": q / "my-project" / "gtm-queue.json",
    }


# A card line is one client's state, written by state_card.py in his own words, e.g.
#   🔴 *Alice* · you said "..." — not sent
#   📞 *2 to reach out* — 🔥 Portant (fire, ...)
# The emoji is the health verdict and is NOT re-derived here: it is the card's.
# The `*THE MOVE*` prefix on the top-ranked row is why this does not anchor the emoji
# to line start. It cost the first smoke run its most important client: Alice was rank 1,
# carried the prefix, and silently did not parse while six lesser rows did. A parser that
# drops the FIRST row is worse than one that drops none, because the gap is invisible.
_CLIENT_LINE = re.compile(
    r"^\s*(?:\*THE MOVE\*\s*)?(?P<health>🔴|🟡|🟢|⚪|🟠)\s*\*(?P<name>[^*]+)\*"
    r"\s*·\s*(?P<rest>.+)$")
_REACH_LINE = re.compile(r"^\s*📞\s*\*(?P<what>[^*]+)\*\s*(?P<rest>.*)$")
#: "     then: 🔥 nicest.ai (fire)" -- the second reach-out, on its own indented line.
_THEN_LINE = re.compile(r"^\s+then:\s*(?:[^\w\s]\s*)*(?P<who>[^(]+?)\s*(?:\(|$)")
#: "— 🔥 Portant (fire, v1 CRM: ...)" -- the person, out of the reach-out header's tail.
_REACH_WHO = re.compile(r"^[^A-Za-z0-9]*(?P<who>[A-Za-z0-9][^(:]*?)\s*(?:\(|:|$)")


def _person_from_reach(rest: str):
    """The NAME out of a reach-out line's tail, or None when there is none."""
    m = _REACH_WHO.match((rest or "").lstrip("—- ").strip())
    who = (m.group("who").strip() if m else "")
    return who or None


def read_card(paths=None) -> tuple[list[dict], str | None]:
    """The card's client lines, parsed but never re-judged. (rows, error)."""
    paths = paths or _paths()
    path = paths["card"]
    if not path.exists():
        return [], f"no state card at {path.name}; the 07:30 job has not written one"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], f"could not read {path.name}: {exc}"

    rows = []
    for line in text.splitlines():
        m = _CLIENT_LINE.match(line)
        if m:
            rows.append({"kind": "client", "health": m.group("health"),
                         "name": m.group("name").strip(), "detail": m.group("rest").strip()})
            continue
        m = _REACH_LINE.match(line)
        if m:
            # The BOLD part is a count ("2 to reach out"); the PERSON is in the rest,
            # after the dash. Codex round 2 (major): keying on the count meant every
            # different person inherited one Notion row, its status and the bucket he
            # had dragged it to. A row's identity has to be the thing, not the tally.
            who = _person_from_reach(m.group("rest"))
            if who:
                rows.append({"kind": "reach", "health": "📞", "name": who,
                             "detail": m.group("rest").strip()})
            continue
        m = _THEN_LINE.match(line)
        if m:
            # The card puts the SECOND person to reach out on an indented "then:"
            # continuation line. Codex finding, 2026-09-03: this reader matched only
            # the header line, so the board claimed to be the full surface while the
            # second prospect never reached it. A dropped row is worse than a missing
            # section, because nothing says it is missing.
            rows.append({"kind": "reach", "health": "📞",
                         "name": m.group("who").strip(), "detail": "then, after the first"})
    if not rows:
        # A card that exists and parses to nothing is a FORMAT change, not a quiet
        # morning. state_card.py always emits at least the book line, so zero parsed
        # rows means this reader and that writer have drifted apart.
        return [], (f"{path.name} parsed to zero client lines; the card format changed "
                    "and this reader did not")
    return rows, None


def read_heartbeat(now: dt.datetime, paths=None) -> tuple[dict, str | None]:
    """The card's freshness and counts. Refuses a stale heartbeat loudly."""
    paths = paths or _paths()
    path = paths["heartbeat"]
    if not path.exists():
        return {}, f"no state-card heartbeat at {path.name}"
    try:
        beat = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, f"could not read {path.name}: {exc}"

    if beat.get("crash"):
        return beat, f"the 07:30 state card crashed: {beat['crash']}"

    stamped = (beat.get("card") or {}).get("date")
    today = now.astimezone(PT).date().isoformat()
    if stamped != today:
        return beat, (f"the state card is from {stamped}, not {today}. "
                      "Showing it as today's book would be wrong, so it is withheld")
    return beat, None


def read_gtm(paths=None) -> tuple[dict | None, str | None]:
    """The ONE GTM action, from the queue's own ranking. Never re-ranked here."""
    paths = paths or _paths()
    path = paths["gtm"]
    if not path.exists():
        return None, f"no GTM queue at {path.name}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"could not read {path.name}: {exc}"

    rows = data.get("rows") if isinstance(data, dict) else data
    # `rows` is a DICT keyed by step id ("1.1"), not a list. Measured, not assumed:
    # the first draft of this reader typed `isinstance(rows, list)` and reported
    # COULD NOT READ against a perfectly good queue.
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        return None, f"{path.name} carries no rows"

    # The card surfaces only what needs HIM. `gtm_queue`'s own rule: a `founder`
    # performer, in a state that is not already worked. `mechanism` rows are the
    # machine's and belong in Sana's queue, never on his morning board.
    live = [r for r in rows
            if isinstance(r, dict)
            and r.get("performer") == "founder"
            and r.get("state") in ("ready", "surfaced", "blocked")]
    if not live:
        return None, None          # nothing waiting on him is not an error
    live.sort(key=lambda r: (r.get("rank") if isinstance(r.get("rank"), (int, float))
                             else 10**6))
    return live[0], None


def collect(now: dt.datetime, sources: dict, paths=None):
    """(rows, error) for the brief's consulting section. The registered entry point."""
    paths = paths or _paths()
    if not paths["card"].parent.parent.exists():
        return None                       # OFF: no consulting instance on this machine
    beat, beat_err = read_heartbeat(now, paths)
    if beat_err:
        return [], beat_err

    card_rows, card_err = read_card(paths)
    if card_err:
        return [], card_err

    rows = []
    counts = (beat.get("card") or {}).get("counts") or {}
    if counts:
        rows.append(f"book: {counts.get('red', 0)} owed, {counts.get('reach', 0)} to reach out")

    shown = card_rows[:MAX_CLIENT_ROWS]
    for row in shown:
        rows.append(f"{row['health']} {row['name']} · {row['detail']}")
    withheld = len(card_rows) - len(shown)
    if withheld:
        # Never a silent trim. The count is the founder's cue that the board has more.
        rows.append(f"...and {withheld} more on the board")

    move, gtm_err = read_gtm(paths)
    if gtm_err:
        # A missing GTM move does not void the clients. It is named and the section
        # still delivers, which is the partial-delivery posture the reddit lane learned.
        rows.append(f"GTM: COULD NOT READ ({gtm_err})")
    elif move:
        rows.append(f"GTM: {move.get('action') or move.get('id')}")

    return rows, None


#: Tokens that change while the THING does not: ages, counts, times, dates. Stripped
#: before an inbox row's identity is hashed. Codex round 2 (major): the id was the
#: rendered row, so "2h ago" -> "3h ago" minted a new id, archived the row he had
#: positioned and created a replacement in the default bucket. Same defect class as the
#: health dot in round 1, at a call site the round-1 fix did not reach.
#: Round 3 (minor): the trailing `|\d+` stripped EVERY digit run, so "invoice 4021"
#: and "invoice 4022" collapsed to one board row. Only digits bound to a time unit, a
#: clock time or a date are volatile; a bare number is usually the identifying part.
_VOLATILE = re.compile(r"\b\d+\s*(?:secs?|mins?|hours?|days?|weeks?)\b"
                       r"|\b\d+\s*[smhdw]\s+ago\b"
                       r"|\b\d{1,2}:\d{2}\b"
                       r"|\b\d{4}-\d{2}-\d{2}\b"
                       r"|\bago\b", re.I)


def _stable(text: str) -> str:
    """`text` with every volatile token removed, for use as an identity."""
    return " ".join(_VOLATILE.sub("", text or "").split()).lower()[:160]


def buckets(now: dt.datetime, sources: dict, paths=None) -> dict:
    """The board's three buckets, for notion_board.py's row writer.

    Separate from `collect` on purpose. `collect` answers "what does the Slack line
    say"; this answers "what rows does the board hold". One shared read, two renderings,
    and neither one recomputes the other's verdict.
    """
    paths = paths or _paths()
    beat, beat_err = read_heartbeat(now, paths)
    if beat_err:
        return {"error": beat_err, "top_of_mind": [], "this_week": [], "inbox": [],
                "healthy_scopes": set()}

    card_rows, card_err = read_card(paths)
    if card_err:
        return {"error": card_err, "top_of_mind": [], "this_week": [], "inbox": [],
                "healthy_scopes": set()}

    # Scopes that produced a set worth ARCHIVING AGAINST this run. Declared HERE, above
    # every producer, because each one adds itself only after it answered cleanly.
    # "card" is unconditional: a card failure returns early, above this line.
    healthy = {"card"}
    top, week = [], []
    for row in card_rows:
        # `key` is what the row id is hashed from and it carries NO health dot.
        # Codex finding (major), 2026-09-03: the id was hashed from `title`, which
        # embeds the emoji, so a client going red -> green minted a new id. The next
        # unattended paint then archived the row he had dragged and created a
        # replacement in a computed bucket, silently undoing his move. The whole
        # "his drag always wins" promise depended on an id that does not move.
        # KIND-NAMESPACED. Round 3 (major): both a client row and a reach-out row are
        # named for the person, so keying on the name alone made them one row -- the
        # reach-out action was silently dropped and read-back still said ok, because
        # `wanted` had already collapsed them before the count was taken. Two different
        # things about one person are two rows.
        item = {"title": f"{row['health']} {row['name']}",
                "key": f"{row['kind']}:{row['name']}",
                "detail": row["detail"], "source": "State card", "scope": "card",
                "bucket_reason": row["health"]}
        # 🔴 and 📞 are today. Everything else is this week. The split is the card's
        # own health verdict, not a rule invented here.
        (top if row["health"] in ("🔴", "📞") else week).append(item)

    move, gtm_err = read_gtm(paths)
    if not gtm_err:
        # Round 3 (major): "gtm" was unconditionally healthy, so an unreadable
        # gtm-queue.json still authorised archiving inside that scope -- the painter
        # deleted the GTM row he had positioned and recreated it in a computed bucket.
        # The same reasoning the inbox scopes already had; it just was not applied here.
        healthy.add("gtm")
    if move:
        top.append({"title": move.get("action") or move.get("id"),
                    "key": f"gtm:{move.get('id')}",   # the step id, stable across rewordings
                    "detail": move.get("done_looks_like") or "", "source": "GTM queue",
                    "scope": "gtm",
                    "bucket_reason": "gtm"})
    elif gtm_err:
        top.append({"title": "GTM: COULD NOT READ", "key": "gtm:error", "scope": "gtm",
                    "detail": gtm_err, "source": "GTM queue", "bucket_reason": "error"})

    inbox = []
    # Gmail and GroupMe only. Codex finding (major), 2026-09-03: this asked for a
    # "slack" source too, and `collect_all` registers no Slack producer, so that
    # channel was silently absent forever while the docs claimed three. An unwired
    # channel named in code reads as coverage. Wiring a Slack collector is real work
    # and is not smuggled in here; when it exists it is one tuple entry.
    for key, label in (("mail", "Gmail"), ("groupme", "GroupMe")):
        got = sources.get(key)
        if not got:
            continue
        rows, err = got
        if err:
            inbox.append({"title": f"{label}: COULD NOT READ", "key": f"{label}:error",
                          "detail": err, "source": label, "scope": f"inbox:{label}",
                          "bucket_reason": "error"})
            continue                      # scope deliberately NOT marked healthy
        healthy.add(f"inbox:{label}")
        for row in rows:
            text = str(row)[:180]
            inbox.append({"title": text, "key": f"{label}:{_stable(text)}", "detail": "",
                          "source": label, "scope": f"inbox:{label}",
                          "bucket_reason": "inbox"})

    return {"error": None, "top_of_mind": top, "this_week": week, "inbox": inbox,
            # Which scopes produced a TRUSTWORTHY set this run. The painter archives
            # only inside these; see board_rows.paint. Codex round 2 (major): a
            # transient Gmail error replaced its rows with a single error row, and the
            # painter then archived every inbox row he had positioned.
            "healthy_scopes": healthy}
