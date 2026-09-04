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
        "commitments": q / "my-project" / "commitments.jsonl",
        "clients": q / "my-project" / "clients.json",
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
#: The `*THE MOVE*` prefix is optional HERE TOO. Round 8 (major): only `_CLIENT_LINE`
#: had been taught it, so on a day whose top-ranked row is a reach-out -- which is what
#: the card looks like with no red clients -- this line did not match at all and every
#: person on it was dropped at exit 0. The sibling was hardened; this one was not, and
#: nothing in the file made that asymmetry visible.
_REACH_LINE = re.compile(
    r"^\s*(?:\*THE MOVE\*\s*)?📞\s*\*(?P<what>[^*]+)\*\s*(?P<rest>.*)$")
#: "     then: 🔥 Beta (fire) · 🔥 Gamma (fire)" -- EVERY remaining reach-out, packed
#: onto one indented line. Round 8 (major): this used to capture a single name, so a
#: card with three more people put one on the board and said nothing about the rest.
#: The tail is split on the card's own separator and each piece goes through the same
#: person extractor as the header line.
_THEN_LINE = re.compile(r"^\s+then:\s*(?P<rest>.+)$")
#: What the card puts between two people on a `then:` line.
_THEN_SEP = "·"
#: The producer's own tail on that line: "+3 more, lowest-scoring, on the board".
_MORE_SUMMARY = re.compile(r"^\+\s*\d+\s+more\b")
#: "— 🔥 Portant (fire, v1 CRM: ...)" -- the person, out of the reach-out header's tail.
#: A mail key built from sender+subject rather than a thread id. `collect_mail` uses
#: "<sender>|<subject>" only when the model returned no id; a real id carries none.
_FALLBACK_KEY = re.compile(r"^[^|]+\|")
#: `build_card`'s first line, always present. See `read_card` for why it decides.
_BOOK_HEADER = re.compile(r"\*Your book today\*")
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
            # The card puts every OTHER person to reach out on an indented "then:"
            # continuation line. Codex finding, 2026-09-03: this reader matched only
            # the header line, so the board claimed to be the full surface while the
            # second prospect never reached it. A dropped row is worse than a missing
            # section, because nothing says it is missing. Round 8 found the same
            # sentence still half true: the line was matched and then read as ONE
            # person, so three of four went missing just as quietly.
            for piece in m.group("rest").split(_THEN_SEP):
                # The producer ends this line with its own "+N more, lowest-scoring,
                # on the board" summary. Round 12 (major): the split handed that
                # summary to the person extractor, which produced a row named after
                # the sentence -- while the people it stands for still did not reach
                # the board. A count is not a contact.
                if _MORE_SUMMARY.match(piece.strip()):
                    continue
                who = _person_from_reach(piece)
                if who:
                    rows.append({"kind": "reach", "health": "📞", "name": who,
                                 "detail": "then, after the first"})
    if not rows:
        # ZERO ROWS IS TWO DIFFERENT FACTS and this used to call both a format change.
        # Round 12 (major): a day where every client is green or waiting on THEM emits
        # a card with a header and no client lines, which is correct output, and this
        # reported it broken -- a P0 alarm row on the board every quiet day, which is
        # exactly the wolf-cry that costs the real alert later.
        #
        # The discriminator is the producer's own header, which `build_card` always
        # writes. Header present and no rows is a quiet morning. No header either
        # means this reader and that writer really have drifted apart.
        if _BOOK_HEADER.search(text):
            return [], None
        return [], (f"{path.name} parsed to zero client lines and carries no book "
                    "header; the card format changed and this reader did not")
    return rows, None


def _days(then: str, now: dt.datetime):
    """Whole days from an ISO date/timestamp to `now`, or None if unparseable.
    A bad date returns None and the caller omits the phrase; it never renders 0,
    which would read as "today" and be a lie about how long he has been waiting."""
    try:
        d = dt.date.fromisoformat(str(then)[:10])
    except (TypeError, ValueError):
        return None
    return (now.date() - d).days


def read_my_side(now: dt.datetime, paths=None) -> tuple[dict, str | None]:
    """Per slug: WHEN he said the thing, what was due, and when he last touched them.

    ## Why this reader exists (founder, 2026-09-03)

    *"This is a learning from the [a retainer client] fiasco -- they said I wasn't doing
    things and I've actually been waiting on deliverables for weeks. So it needs to
    say when was the last thing delivered and what am I still waiting for and how
    long."* Scoped by him one message later to HIS side only.

    The card renders a promise but no DATE, so a row said "you said X -- not sent"
    with no way to tell a promise made yesterday from one made in July. A board that
    cannot say WHEN cannot settle an argument about whether he was slow.

    ## Facts, not a second verdict

    This reads two files the card also reads, and that is deliberate and is NOT the
    dual-derivation this module's docstring forbids. The forbidden thing is a second
    opinion about SEVERITY -- red/yellow/reach stays the card's call, and nothing here
    touches it. A date is a fact with one value; reading it twice cannot disagree.

    `clients.json` is read as a LOOKUP keyed by the names the card already chose,
    never enumerated: it is 162 rows of which ~150 are cold prospects, and walking it
    would put them all on the board.
    """
    paths = paths or _paths()
    out, errors = {}, []

    by_name = {}
    try:
        reg = json.loads(paths["clients"].read_text(encoding="utf-8"))
        for c in reg.get("clients") or []:
            slug = c.get("slug")
            if not slug:
                continue
            entry = {"last_touch": c.get("last_touch"), "slug": slug}
            by_name[str(c.get("name") or "").strip().lower()] = entry
            out[slug] = dict(entry)
    except FileNotFoundError:
        pass                     # no registry on this machine; see the note below
    except (OSError, ValueError) as exc:
        errors.append(f"registry unreadable ({type(exc).__name__})")

    try:
        for line in paths["commitments"].read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue          # one bad line never voids the book
            # OPEN only. A resolved promise is not something he still owes, and
            # showing it would recreate the "you did not do this" claim he is
            # defending against.
            if row.get("state") != "open" or not row.get("slug"):
                continue
            rec = out.setdefault(row["slug"], {"slug": row["slug"], "last_touch": None})
            said = row.get("extracted_at")
            prior = rec.get("said_on")
            if not prior or str(said)[:10] < str(prior)[:10]:
                rec["said_on"] = said        # the OLDEST open promise is the exposure
                rec["due"] = row.get("due")
    # A file that is ABSENT is not a file that is BROKEN. A machine with no commitment
    # book has no promises to report, which is a fact; a book that exists and cannot be
    # parsed or read is a failure that must be said out loud. Collapsing the two either
    # makes a bare checkout look broken every morning or hides a real read failure.
    # Same posture as groupme_inbox returning None with no token: OFF, not broken.
    except FileNotFoundError:
        pass
    except OSError as exc:
        errors.append(f"commitment book unreadable ({type(exc).__name__})")

    out["_by_name"] = by_name
    return out, ("; ".join(errors) if errors else None)


def my_side_phrase(rec: dict, now: dt.datetime) -> str:
    """"said 2026-08-18 (16d ago) - due 2026-08-31 - last touch 2026-08-22".

    Every part is omitted when its date is missing rather than rendered as unknown:
    a board line is read in two seconds and "due: none" costs a second for nothing.
    """
    bits = []
    said = rec.get("said_on")
    if said:
        n = _days(said, now)
        bits.append(f"said {str(said)[:10]}" + (f" ({n}d ago)" if n is not None else ""))
    if rec.get("due"):
        bits.append(f"due {str(rec['due'])[:10]}")
    touch = rec.get("last_touch")
    if touch:
        n = _days(touch, now)
        bits.append(f"last touch {str(touch)[:10]}" + (f" ({n}d)" if n is not None else ""))
    return " · ".join(bits)


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


#: How far ahead "coming up" reaches. A week, because the section is called This Week
#: and a due date further out is not this week's problem. Not a tuning knob: widening
#: it turns the section into a second Top of Mind.
WEEK_DAYS = 7


def _norm_key(text) -> str:
    """A promise reduced to a stable identity fragment: whitespace collapsed, cased
    down, bounded. Not a hash, so a key stays readable in the Notion row and a human
    can see which promise it belongs to."""
    return " ".join(str(text or "").split()).lower()[:80]


def read_week(now: dt.datetime, paths=None) -> tuple[list[dict], str | None, set]:
    """This Week: the GTM moves waiting on him, and deliverables coming due.

    Founder, 2026-09-03: *"This week should be this week's GTM moves and deliverables
    that are coming up."* Before this the section had NO source at all. It carried a
    description copied off a reference board describing a Sunday planning ritual he
    does not have, so it would have stayed empty forever while claiming to be "the
    plan".

    Two sources, both already on disk:

    - The GTM queue's founder-performer steps that are ready. `read_gtm` takes the
      top-ranked one for Top of Mind; this takes THE REST, so a step is never on the
      board twice. Measured 2026-09-03: 5 of 57 rows qualify, so this is a short list
      and not the whole plan dumped onto a second surface.
    - Open commitments whose due date lands inside the next `WEEK_DAYS`. An OVERDUE
      one is deliberately excluded: it is already red in Top of Mind, and showing it
      in both places teaches him the two sections mean the same thing.

    ## The third return value

    Which of the two sources answered THIS RUN, as the scopes they emit. Codex round 6
    (major): both scopes existed and neither was ever reported healthy, so the painter
    could not archive inside them and a delivered commitment sat on the board forever.
    Reported per SOURCE rather than per section, because the section has two of them and
    one being down says nothing about the other.

    A scope is healthy only when its source was READ. An absent commitment book is OFF
    rather than broken (no error row), and it is still not healthy: a file that is not
    there has said nothing about the rows written when it was, and nothing is not "they
    are gone" (the round-2 archive-the-lot scar).
    """
    paths = paths or _paths()
    out, errors, healthy = [], [], set()

    lead, gtm_err = read_gtm(paths)
    if gtm_err:
        errors.append(gtm_err)
    else:
        try:
            data = json.loads(paths["gtm"].read_text(encoding="utf-8"))
            rows = data.get("rows") if isinstance(data, dict) else data
            rows = list(rows.values()) if isinstance(rows, dict) else (rows or [])
            lead_id = (lead or {}).get("id")
            rest = [r for r in rows
                    if isinstance(r, dict)
                    and r.get("performer") == "founder"
                    and r.get("state") in ("ready", "surfaced", "blocked")
                    and r.get("id") != lead_id]
            rest.sort(key=lambda r: (r.get("rank") if isinstance(r.get("rank"), (int, float))
                                     else 10**6))
            for r in rest:
                out.append({
                    "title": r.get("action") or r.get("id"),
                    "key": f"gtm:{r.get('id')}",
                    "detail": r.get("done_looks_like") or "",
                    "source": "GTM queue", "scope": "week:gtm",
                    "priority": "P1" if r.get("state") == "ready" else "P2",
                    "domain": "GTM",
                    "done": r.get("done_looks_like") or DONE_GTM_FALLBACK,
                    "bucket_reason": "gtm-week"})
            healthy.add("week:gtm")       # only after the rows are actually built
        except (OSError, ValueError) as exc:
            errors.append(f"GTM queue unreadable ({type(exc).__name__})")

    horizon = now.date() + dt.timedelta(days=WEEK_DAYS)
    unreadable_lines = 0
    try:
        for line in paths["commitments"].read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                # ROUND 10 (major): this skipped the line and the scope was still
                # declared healthy below, which AUTHORISED the painter to archive the
                # row for the very deliverable the corrupt line described. A book we
                # could not read start to finish has not said those rows are gone.
                unreadable_lines += 1
                continue
            if row.get("state") != "open" or not row.get("due"):
                continue
            try:
                due = dt.date.fromisoformat(str(row["due"])[:10])
            except ValueError:
                continue          # a junk due date is not a deliverable this week
            if not (now.date() <= due <= horizon):
                continue          # overdue is Top of Mind's; further out is not this week
            left = (due - now.date()).days
            out.append({
                "title": f"{row.get('slug')}: {str(row.get('promise'))[:120]}",
                # The commitment's own id when it has one; otherwise the slug AND
                # the promise, because the slug alone is not an identity. Two open
                # deliverables for one client with no id both keyed `due:<slug>`,
                # so the second overwrote the first in `wanted` and the read-back
                # still reported ok -- it counts what it wrote, and the row was
                # already gone before the count. Same class as the inbox rows: an
                # id derived from too little is a collision, and a collision is a
                # silent deletion.
                #
                # `_norm_key` is NOT the rendered line. The detail carries a
                # countdown in days that changes every morning, and keying on it
                # would mint a new row daily. The promise text is what is stable.
                "key": (f"due:{row['id']}" if row.get("id")
                        else f"due:{row.get('slug')}:{_norm_key(row.get('promise'))}"),
                "detail": f"due {due.isoformat()} ({left}d)",
                "source": "State card", "scope": "week:due",
                "priority": "P0" if left <= 2 else "P1",
                "domain": "Consulting",
                "done": "you deliver it, or you move the date with them",
                "bucket_reason": "due-this-week"})
        if unreadable_lines:
            errors.append(f"{unreadable_lines} unreadable line(s) in the commitment "
                          "book; deliverable rows are kept rather than archived")
        else:
            healthy.add("week:due")       # the book was read start to finish
    # A file that is ABSENT is not a file that is BROKEN. A machine with no commitment
    # book has no promises to report, which is a fact; a book that exists and cannot be
    # parsed or read is a failure that must be said out loud. Collapsing the two either
    # makes a bare checkout look broken every morning or hides a real read failure.
    # Same posture as groupme_inbox returning None with no token: OFF, not broken.
    except FileNotFoundError:
        pass
    except OSError as exc:
        errors.append(f"commitment book unreadable ({type(exc).__name__})")

    return out, ("; ".join(errors) if errors else None), healthy


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


# `_VOLATILE` / `_stable` LIVED HERE AND ARE DELETED (PR #296, 2026-09-03).
#
# They scrubbed volatile tokens out of a rendered line so the line could be hashed
# into a board-row identity. Four Codex rounds each added one more pattern -- the
# health dot, "2h ago", a bare digit run that collapsed "invoice 4021" and
# "invoice 4022" into one row, and finally the `[2h]` the real mail producer emits,
# which the round-2 fix had never seen because the test drove a fixture instead.
#
# Every one of those is the same defect: an identity derived from PRESENTATION.
# Rendering changes, so the regex could only ever chase it, and each fix bought one
# round. Producers now emit `morning-brief.Row(line, key)` carrying the id they
# already had -- a Gmail thread id, a GroupMe conversation id -- and `buckets` refuses
# a row without one. `test_no_identity_is_derived_from_rendered_text` fails if this
# file ever grows a text-scrubbing identity again.

#: Priority from the STATE CARD'S OWN VERDICT, never a second judgement. The card
#: already decides severity per client every morning (state_card.py: red = an open
#: promise past due, yellow = due inside 48h, and so on) and `board_sync.HEALTH` turns
#: each into a job: "do today", "do this week", "reach out". Re-deriving urgency here
#: would be a second thing computing one truth, which is the defect the whole mirror
#: design exists to avoid (DEC-8/DEC-13, and the v1 CRM that died of hand-feeding).
#: So this is a TRANSLATION table, not a scoring rule: his card's dot, in Bloom's
#: P0-P3 vocabulary.
#: The scope carrying the "your book could not be read" row. Always healthy, because
#: this module always knows whether the alarm belongs; see `buckets`.
CARD_ALARM = "card:alarm"

PRIORITY_BY_HEALTH = {
    "🔴": "P0",    # do today: a promise he made, past due
    "🟠": "P0",    # answer them: a person is waiting on a reply
    "📞": "P1",    # reach out
    "🟡": "P1",    # do this week
    "🟢": "P3",    # nothing to do
    "⚪": "P3",    # their move
}

#: What FINISHING one of these looks like, in his own terms. Bloom's board carries a
#: a "Done when" line on every row and it is the half that makes one actionable:
#: a title says what the thing IS, a done signal says when to stop looking at it.
#: AUDHD rule A2 (next physical action) is the same requirement from the other side.
DONE_DEFAULT = "you act on it"
DONE_BY_KIND = {
    "client": "you send the thing you promised",
    "reach": "you send the message",
}
#: A GTM step whose plan text carries no "done looks like". Deliberately vague,
#: because inventing a specific completion test for a step nobody wrote one for would
#: be this module making up the plan.
DONE_GTM_FALLBACK = "the step is done, or you write down why it did not happen"
DONE_BY_SOURCE = {
    "Gmail": "you reply in the thread",
    "GroupMe": "you answer in the chat",
}

#: Size is DELIBERATELY not written. Bloom's board carries XS/S/M and nothing this
#: board reads knows how big a piece of work is: the state card measures urgency, not
#: effort, and the GTM queue carries no estimate. A size guessed by this module would
#: look like a measurement and be a fabrication, so the column stays empty until
#: something that actually knows fills it.


def buckets(now: dt.datetime, sources: dict, paths=None) -> dict:
    """The board's three buckets, for notion_board.py's row writer.

    Separate from `collect` on purpose. `collect` answers "what does the Slack line
    say"; this answers "what rows does the board hold". One shared read, two renderings,
    and neither one recomputes the other's verdict.
    """
    paths = paths or _paths()
    # Scopes that produced a set worth ARCHIVING AGAINST this run. Each adds itself only
    # after it answered cleanly. CARD_ALARM is the exception and is always healthy: this
    # function always reaches a verdict about the card, so it can always decide whether
    # the alarm row belongs, and a stuck alarm nobody can clear is its own defect.
    healthy = {CARD_ALARM}
    top, week = [], []

    beat, beat_err = read_heartbeat(now, paths)
    card_rows, card_err = ([], None) if beat_err else read_card(paths)
    card_problem = beat_err or card_err

    # A STALE CARD NO LONGER SILENCES THE SOURCES THAT DID ANSWER (round 9, major).
    #
    # The rule this is often mistaken for is round 2's, and that one stands: a source
    # that could not answer writes NOTHING, and its rows are neither refreshed nor
    # archived. What was wrong was the RADIUS. `collect` refused the whole paint on a
    # card problem, so a late 07:30 job also stopped Gmail and GroupMe rows -- sources
    # that answered perfectly well -- from reaching the board.
    #
    # And the abort was not even protecting him from stale client rows. Nothing
    # archives or overwrites them either way, so the board showed yesterday's clients
    # WITH no fresh mail. Per-scope gives him yesterday's clients, an alarm row saying
    # so, and today's mail.
    if card_problem:
        top.append({"title": "Your book: COULD NOT READ", "key": "card:error",
                    "detail": card_problem, "source": "State card", "scope": CARD_ALARM,
                    "priority": "P0", "domain": "Fleet",
                    "done": "the 07:30 state card writes a fresh one",
                    "bucket_reason": "error"})

    my_side, my_side_err = ({}, None) if card_problem else read_my_side(now, paths)
    by_name = my_side.pop("_by_name", {})
    if not card_problem and card_rows:
        # ZERO ROWS NEVER AUTHORISES ARCHIVING (round 14, major, against round 12's
        # own fix). Treating a quiet morning as healthy meant a format change that
        # happened to keep the `*Your book today*` header parsed to nothing, declared
        # the scope healthy, and archived EVERY client row on the board including the
        # ones he had pinned. Quiet and drifted look identical from here, so the board
        # keeps what it has and the reader says nothing either way: no alarm row on a
        # genuinely quiet day, no destruction on a drifted one.
        healthy.add("card")

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
                "priority": PRIORITY_BY_HEALTH.get(row["health"], "P2"),
                "domain": "Consulting",
                "done": DONE_BY_KIND.get(row["kind"], DONE_DEFAULT),
                "bucket_reason": row["health"]}
        # The dates his side of the story needs. Appended to the detail, never
        # replacing the promise: the promise in his own words is the evidence and
        # the dates are what make it an alibi.
        reg = by_name.get(row["name"].strip().lower())
        rec = dict(my_side.get(reg["slug"], {})) if reg else {}
        if reg:
            rec.setdefault("last_touch", reg.get("last_touch"))
        phrase = my_side_phrase(rec, now) if rec else ""
        if phrase:
            item["detail"] = f"{item['detail']}\n{phrase}" if item["detail"] else phrase
        # 🔴, 🟠 and 📞 are today. Everything else is this week. The split is the card's
        # own health verdict, not a rule invented here.
        #
        # 🟠 joined the today group in round 7 (minor): PRIORITY_BY_HEALTH calls it P0
        # "answer them: a person is waiting on a reply" while this line sent it to This
        # Week, so one module said today and not-today about the same row. The dot is
        # not emitted by `state_card.py`, the only producer this reads -- `board_sync`
        # uses it on the Clients board -- so this makes two tables in this file agree
        # rather than changing a live path. `_CLIENT_LINE` has always parsed it.
        (top if row["health"] in ("🔴", "🟠", "📞") else week).append(item)

    # The dates failing is reported ONCE, as its own row, never as a line stapled to
    # every client. A test proves this module still delivers with no registry in the
    # tree at all, and per-row noise would make that delivery look broken.
    if not my_side_err and not card_problem:
        # The apology row below is scoped `myside`, and until round 6 that scope was
        # never healthy, so the row outlived the outage it reported and nothing could
        # clear it. A source that recovered is what authorises clearing its own alarm.
        healthy.add("myside")
    if my_side_err:
        top.append({"title": "Promise dates: COULD NOT READ", "key": "myside:error",
                    "detail": my_side_err, "source": "State card", "scope": "myside",
                    "priority": "P1", "domain": "Fleet",
                    "done": "the commitment book and registry read again",
                    "bucket_reason": "error"})

    week_rows, week_err, week_healthy = read_week(now, paths)
    week.extend(week_rows)
    # Per SOURCE, not per section. Round 6 (major): `week:gtm` and `week:due` were
    # emitted by every run and never reported healthy, so the painter could not archive
    # inside them and a delivered commitment stayed on the board forever.
    healthy |= week_healthy
    if not week_err:
        healthy.add("week")            # clears this section's own COULD NOT READ row
    if week_err:
        week.append({"title": "This Week: COULD NOT READ", "key": "week:error",
                     "detail": week_err, "source": "GTM queue", "scope": "week",
                     "priority": "P1", "domain": "Fleet",
                     "done": "the GTM queue and commitment book read again",
                     "bucket_reason": "error"})

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
                    "scope": "gtm", "priority": "P1", "domain": "GTM",
                    # The queue writes what done looks like for most steps, so this
                    # row's signal is the plan's own words where they exist. A step
                    # that carries none still gets one: an empty Done signal column is
                    # the "field he forgot to fill" look this whole change removes,
                    # and every other row on the board has one.
                    "done": move.get("done_looks_like") or DONE_GTM_FALLBACK,
                    "bucket_reason": "gtm"})
    elif gtm_err:
        top.append({"title": "GTM: COULD NOT READ", "key": "gtm:error", "scope": "gtm",
                    "detail": gtm_err, "source": "GTM queue", "priority": "P1",
                    "domain": "Fleet", "done": "the GTM queue reads again",
                    "bucket_reason": "error"})

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
                          "priority": "P1", "domain": "Fleet",
                          "done": f"{label} reads again",
                          "bucket_reason": "error"})
            continue                      # scope deliberately NOT marked healthy
        # AN ID-LESS ANSWER DOES NOT AUTHORISE ARCHIVING (round 13, major). When the
        # model returns thread ids the key is the id; when it does not, the key falls
        # back to sender+subject. Both are stable in themselves, but they are DIFFERENT
        # ids for one thread, so a day where the model stops returning ids archives the
        # row he pinned and recreates it at "Not started". The rows still paint; what
        # is withheld is the authority to call the old ones gone.
        if not any(_FALLBACK_KEY.match(getattr(r, "key", "") or "") for r in rows):
            healthy.add(f"inbox:{label}")
        for row in rows:
            text = str(row)[:180]
            # THE END OF THE FOUR-ROUND LOOP. The key is the producer's own id
            # (morning-brief.Row.key: a Gmail thread id, a GroupMe conversation id),
            # never the rendered line. Rounds 1-4 of PR #296 were four patches to a
            # regex that scrubbed volatile tokens out of that line -- the health dot,
            # "2h ago", a digit run that collapsed two invoice numbers, the `[2h]` the
            # real producer emits -- and a fifth form was guaranteed because rendering
            # keeps changing and a regex can only chase it.
            #
            # An UNKEYED row is refused, loudly, rather than falling back to the text.
            # A fallback would be indistinguishable from the old behaviour on the day a
            # new producer forgets, which is exactly how this defect survived three
            # fixes: each one held for the fixture and not for the producer.
            key = getattr(row, "key", None)
            if not key:
                raise TypeError(
                    f"{label} produced an inbox row with no stable key: {text!r}. "
                    "Every inbox producer must emit morning-brief.Row(line, key); "
                    "keying on the rendered line is the PR #296 rounds 1-4 defect.")
            inbox.append({"title": text, "key": key, "detail": "",
                          "source": label, "scope": f"inbox:{label}",
                          # Inbox rows are things a person is waiting on. P2: below a
                          # client he owes something to and below a broken source, above
                          # anything merely scheduled. Not P0 -- an unread message is not
                          # by itself today's most important act, and a board where
                          # everything is urgent has no priority at all.
                          "priority": "P2", "domain": "Consulting",
                          "done": DONE_BY_SOURCE.get(label, DONE_DEFAULT),
                          "bucket_reason": "inbox"})

    return {"error": None,
            # NOT `error`. `error` means the painter must not write at all; a card
            # problem means one SCOPE has nothing to say. Callers report this, the
            # board carries the alarm row, and every other scope paints.
            "card_error": card_problem,
            "top_of_mind": top, "this_week": week, "inbox": inbox,
            # Which scopes produced a TRUSTWORTHY set this run. The painter archives
            # only inside these; see board_rows.paint. Codex round 2 (major): a
            # transient Gmail error replaced its rows with a single error row, and the
            # painter then archived every inbox row he had positioned.
            "healthy_scopes": healthy}
