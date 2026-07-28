#!/usr/bin/env python3
"""Collapse duplicate-template issues into one issue per family.

WHY THIS EXISTS

Measured on the ASK board 2026-07-28 (`q-system/output/triage-applied-2026-07-28.log`,
106 issues classified): 56 issues triaged `batch`, and 49 of those 56 are the same
machine-filed template repeated -- 23 near-identical job-migration issues, the
CAP-0n rule family, and a handful of other scanner output. The triage reasons say
it outright ("First of five identical CAP-0n rule issues", "Runs the identical
script as ASK-156").

So a ~200-issue board is not 200 pieces of work. It is roughly 20 real changes
wearing 200 hats. The lever is collapsing duplicates, not throughput.

WHY COLLAPSE AND NOT "JUST CLOSE THEM"

Closing 49 issues deletes the record of what each one actually named. Some carry a
distinct path or job label that the family fix has to cover, and a family fix that
silently drops one member's target is exactly how a job stays dark. So: ONE
surviving issue per family whose description enumerates EVERY member's specific
target, and every absorbed issue closed with a comment pointing at the survivor.
`survivor_block()` builds the union; `test-linear-collapse.sh` asserts the union
rather than a sample, because a sample assertion passes on the bug.

THE ROSTER IS THE ONE ARTIFACT, SO TWO RULES PROTECT IT (PR #35 review)

1. The roster is read back and MERGED, never rebuilt. Production feeds
   `detect_families()` from `fetch_open()`, so a second pass cannot see the
   members the first pass closed. Rebuilding from the open members deleted their
   rows while their pointer comments still said "enumerated in <survivor>" --
   the survivor stopped naming the very targets it inherited. `family_rows()`
   merges `parse_block_rows()` of the existing block with this pass's members,
   and the roster only ever grows.
2. Nothing reads the roster as issue content. `strip_block()` removes the block
   before `member_targets()` / `producer()` look at a description. Without it
   the survivor ingested its own roster on pass 2, and the 20-target cap evicted
   the survivor's real target from its own row.

WHY THE DETECTOR IS DETERMINISTIC AND STRICT

No model call. Two issues collapse only when their titles normalise to the
BYTE-IDENTICAL template and they carry the same kipi-key namespace (see
`producer()` for what that namespace really is, and its residual). That under-
collapses in the tail (a hand-edited title drops out of its family) and that is
the safe direction: under-collapse leaves an issue on the board for a human to
look at, over-collapse closes real distinct work behind a fix that never covers
it. `is_collapsible_template()` refuses a template with no literal content, so
two titles that are nothing but identifiers cannot collide into a family.

WHY DRY BY DEFAULT

Same reason as `linear-triage.py`: Linear objects are permanent, `mcp__linear__
*delete*` is blocked by `~/.claude/hooks/destructive-op-deny.sh`, and an agent
cannot set ALLOW_DESTRUCTIVE=1 for itself. Closing is reversible; 49 wrong
comments are not. The first run prints the plan and writes nothing.

WHY THE RECORD IS APPENDED PER ISSUE, NOT AT THE END

sp-b5dcf944: `linear-triage.py --apply` died mid-run on 2026-07-28 after closing
32 issues and left no audit file at all, because the verdict file was written
after the loop. Here every write appends its record and fsyncs before the next
write starts, so a run that dies at issue 20 still says what happened to issues
1..20. `test-linear-collapse.sh` drives a fake writer that FAILS the suite if a
close happens before its own record is on disk.

EXIT CODES -- this script never lies about failure
  0  ran; every family in the plan was fully applied (or it was a dry run)
  1  usage error (including --apply under the offline fixture seam)
  9  the pass is not complete. Three ways in: a write raised; a step reported
     something other than a real write (`incomplete_steps`); or the preflight
     refused to start because the team has no canceled-type state to close
     absorbed issues into. Partial results are printed and the audit file holds
     every write that did land, but the exit code says the pass is incomplete.
     A family counts as applied only when every one of its recorded steps says
     it happened -- "the loop did not raise" is not evidence.

Usage:
  linear-collapse.py                          # dry, prints the plan
  linear-collapse.py --apply                  # writes: survivor DoR, comments, closes
  linear-collapse.py --min-family 5           # only collapse families this big
  linear-collapse.py --out path.jsonl         # override the audit file location
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent

# Delimits the block this script owns inside the survivor's description. Every
# rewrite replaces what is BETWEEN these markers and never touches a byte outside
# them: the survivor is a real issue somebody wrote, not a scratch object.
BLOCK_OPEN = "<!-- kipi-collapse-family -->"
BLOCK_CLOSE = "<!-- /kipi-collapse-family -->"

# Written into every comment posted on an absorbed issue. A second pass finds it
# and skips the comment, so re-running cannot stack 49 duplicate comments on
# permanent objects.
ABSORB_MARKER = "<!-- kipi-collapse-absorbed -->"

DEFAULT_AUDIT = "q-system/output/linear-collapse-{date}.jsonl"

# Linear WorkflowState.type values that mean the issue is already off the board.
CLOSED_STATE_TYPES = ("completed", "canceled")

ISSUES_Q = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}}},first:250,after:$a){
  nodes{id identifier title description createdAt
        state{name type} project{name}
        comments{nodes{id body}}}
  pageInfo{hasNextPage endCursor}}}"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- template normalisation ------------------------------------------------
# The whole detector rests on this function, so it is deliberately boring: a
# token is VARIABLE if it carries any mark of an identifier, and everything else
# is literal sentence. `com.cole/content-brain`, `CAP-01`, `linear-tracked` and
# `anti-misclassification:` are all variable; `migrate`, `rule`, `execution` and
# `guardrails` are the sentence that makes two issues the same issue.

# Internal hyphen counts, because the CAP family varies ONLY in a hyphenated rule
# name ("CAP-01 rule anti-misclassification: ..." vs "... audhd-interaction: ...").
# Without it those five never group and the largest easy win on the board is
# invisible. It also swallows constant hyphenated words like `linear-tracked`,
# which is harmless: they are swallowed identically in every member.
VARIABLE_MARK_RE = re.compile(r"[./_:@]|\d|(?<=[a-z0-9])-(?=[a-z0-9])")

# Stripped from the ENDS of a token only. Internal punctuation is the signal.
TOKEN_EDGE = " \t()[]{}\"'`,;.!?*"

# Function words carry no discriminating power, so they do not count toward the
# literal-content floor below. Without this, "migrate <x> to <x>" would read as
# having two literal words when it has one real one.
STOPWORDS = {"a", "an", "and", "the", "to", "for", "of", "in", "on", "off", "at",
             "with", "from", "by", "or", "its", "it", "this", "that", "is",
             "are", "be", "as", "into", "so", "no", "not", "all", "any"}

# A template needs enough shape to mean something. "<x>" matches every
# identifier-only title on the board; collapsing on it would be a collision, not
# a family. Two literal words in a four-token sentence is the floor both real
# families clear ("migrate <x> to <x> execution", "<x> rule <x> <x> guardrails").
MIN_TEMPLATE_TOKENS = 4
MIN_LITERAL_WORDS = 2

KIPI_KEY_RE = re.compile(r"kipi-key:\s*([^\s/]+)/")

# launchd labels (`com.cole/content-brain`, `com.assaf/competitive-analysis:morning`)
# and backticked repo paths. These are the "specific target" the survivor's DoR
# must enumerate -- the thing that goes dark if the family fix skips a member.
JOB_LABEL_RE = re.compile(r"\bcom\.[A-Za-z0-9][A-Za-z0-9._:/-]*")
PATH_RE = re.compile(r"`(~?[A-Za-z0-9_./-]+\.(?:py|sh|md|json|yml|yaml|plist))`")
MAX_TARGETS_PER_ISSUE = 20


def title_template(title: str) -> str:
    """The title with every identifier replaced by `<x>`.

    Two issues are the same issue iff this string matches exactly. Exact match,
    not similarity: a similarity threshold is a knob nobody can calibrate before
    it has already closed the wrong issue.
    """
    out = []
    for raw in re.split(r"\s+", (title or "").strip().lower()):
        tok = raw.strip(TOKEN_EDGE)
        if not tok:
            continue
        out.append("<x>" if VARIABLE_MARK_RE.search(tok) else tok)
    return " ".join(out)


def literal_words(template: str) -> list:
    return [t for t in template.split() if t != "<x>" and t not in STOPWORDS]


def is_collapsible_template(template: str) -> bool:
    """False for a template too generic to identify a family."""
    tokens = template.split()
    return (len(tokens) >= MIN_TEMPLATE_TOKENS
            and len(literal_words(template)) >= MIN_LITERAL_WORDS)


def strip_block(description: str | None) -> str:
    """The description WITHOUT the roster block this script owns.

    One description, two readers, and they must never be confused: everything
    OUTSIDE the markers is what the issue itself says (this function), everything
    INSIDE them is what a previous pass recorded (`parse_block_rows`).

    PR #35 review finding 1: `member_targets` read the whole string, so on the
    second pass the survivor ingested the roster the FIRST pass wrote -- every
    other member's target read back as its own -- and MAX_TARGETS_PER_ISSUE then
    evicted the survivor's real target from its own row. The roster exists to
    stop exactly that kind of target going dark, so it must not cause it.
    """
    desc = description or ""
    start = desc.find(BLOCK_OPEN)
    end = desc.find(BLOCK_CLOSE)
    if start != -1 and end != -1 and end > start:
        return desc[:start] + desc[end + len(BLOCK_CLOSE):]
    return desc


def producer(issue: dict) -> str:
    """The kipi-key NAMESPACE (first path segment), or "" if a human filed it.

    Part of the family key: two namespaces emitting the same sentence are two
    families, and one fix does not cover both.

    Known residual (sp-ab2d1067, PR #35 review finding 4): a namespace is only
    sometimes a scanner. On the real ledger 122 of 188 issues resolve to a REPO
    (`kipi-system/`, `cole-gtm/`) and only 36 to a scanner (`job-migration/`).
    Inside one repo namespace, different scanners share a bucket and the title
    template is the only thing separating them -- `is_collapsible_template()`
    and byte-exact template equality carry that weight, not this function.
    `test-linear-collapse.sh` pins both halves so the residual cannot drift
    silently.
    """
    m = KIPI_KEY_RE.search(strip_block(issue.get("description")))
    return m.group(1) if m else ""


def issue_number(identifier: str) -> int:
    m = re.search(r"-(\d+)$", identifier or "")
    return int(m.group(1)) if m else 10 ** 9


def all_targets(issue: dict) -> list:
    """Every distinct thing this issue names, uncapped: job labels, then paths.

    Read from the title AND the description MINUS the block this script owns.
    The title matters because the job-migration family carries its only
    distinguishing token there. The block must be excluded because it names
    every OTHER member's target -- see `strip_block`.
    """
    text = (issue.get("title") or "") + "\n" + strip_block(issue.get("description"))
    out: list = []
    for hit in JOB_LABEL_RE.findall(text) + PATH_RE.findall(text):
        if hit not in out:
            out.append(hit)
    return out


def member_targets(issue: dict) -> list:
    """`all_targets` capped, because one row cannot be unbounded.

    The cap used to be reachable by accident (the roster read itself back into
    this list); with the block stripped, only an issue that genuinely names more
    than 20 labels and paths reaches it. sp-d3fd8070 tracks making that case
    visible in the roster instead of silently truncated.
    """
    return all_targets(issue)[:MAX_TARGETS_PER_ISSUE]


def detect_families(issues: list, min_family: int = 2) -> list:
    """Group issues into families. Returns [] when nothing is duplicated.

    The survivor is the lowest-numbered member, always. Deterministic on purpose:
    a survivor that moves between passes makes the pointer comments on already-
    absorbed issues point at the wrong place.
    """
    groups: dict = {}
    for issue in issues:
        template = title_template(issue.get("title"))
        if not is_collapsible_template(template):
            continue
        groups.setdefault((producer(issue), template), []).append(issue)

    families = []
    for (prod, template), members in sorted(groups.items()):
        if len(members) < max(2, min_family):
            continue
        members = sorted(members, key=lambda i: issue_number(i["identifier"]))
        families.append({
            "producer": prod,
            "template": template,
            "members": members,
            "survivor": members[0],
            "absorbed": members[1:],
        })
    # Biggest family first: it is the biggest reduction in board size, and if a
    # run is interrupted the work that landed is the work that mattered most.
    families.sort(key=lambda f: (-len(f["members"]), f["survivor"]["identifier"]))
    return families


# --- the text this script writes -------------------------------------------

ROW_SPLIT_RE = re.compile(r"(?<!\\)\|")
THIS_ISSUE = " (this issue)"
NO_TARGET = "_(no explicit target)_"


def _cells(line: str) -> list:
    """The cells of one markdown table row, un-escaping the pipes we escaped."""
    parts = ROW_SPLIT_RE.split(line)
    return [p.strip().replace("\\|", "|") for p in parts[1:-1]]


def parse_block_rows(description: str | None) -> list:
    """The rows a PREVIOUS pass wrote, read back out of the survivor's block.

    Reads only INSIDE the markers -- the mirror of `strip_block`, which reads only
    outside them. Returns [] when there is no block yet.
    """
    desc = description or ""
    start = desc.find(BLOCK_OPEN)
    end = desc.find(BLOCK_CLOSE)
    if start == -1 or end == -1 or end < start:
        return []
    rows = []
    for line in desc[start:end].splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) != 3 or cells[0] == "issue" or set(cells[0]) <= set("-: "):
            continue                                   # header and separator rows
        ident = cells[0]
        if ident.endswith(THIS_ISSUE):
            ident = ident[:-len(THIS_ISSUE)]
        targets = [t.strip("` ") for t in cells[2].split(",")
                   if t.strip("` ") and not t.strip().startswith("_(")]
        rows.append({"identifier": ident, "title": cells[1], "targets": targets})
    return rows


def family_rows(family: dict, prior_rows=()) -> list:
    """This pass's members MERGED with the rows a previous pass already wrote.

    PR #35 review finding 2. Production only ever feeds `detect_families()` from
    `fetch_open()`, so a resumed pass CANNOT see the members the previous pass
    closed. Rebuilding the table from the current family alone deleted their rows
    -- while their pointer comments still said "enumerated in <survivor>, so the
    family fix has to cover it". The roster only ever grows: a row is the record
    of an issue that was closed against this one, and closing it is precisely why
    the row must outlive it.

    A member seen in THIS pass wins over its prior row (its title or targets may
    have been edited since). Ordered by issue number so a rewrite is a diff, not
    a reshuffle.
    """
    rows = {r["identifier"]: dict(r) for r in prior_rows}
    for m in family["members"]:
        rows[m["identifier"]] = {"identifier": m["identifier"],
                                 "title": m.get("title") or "",
                                 "targets": member_targets(m)}
    return sorted(rows.values(), key=lambda r: issue_number(r["identifier"]))


def survivor_block(family: dict, ts: str | None = None, prior_rows=()) -> str:
    """The roster that makes the collapse safe: every member, every target.

    This is the artifact the DoR of ASK-226 is about. If a member's target is
    missing here, the family fix will not cover it, the issue that named it is
    closed, and nothing on the board remembers it existed. `prior_rows` is what
    an earlier pass recorded; it is merged in, never replaced.
    """
    ts = ts or _now()
    survivor = family["survivor"]["identifier"]
    merged = family_rows(family, prior_rows)
    rows = []
    for r in merged:
        cell = ", ".join("`%s`" % t for t in r["targets"]) if r["targets"] else NO_TARGET
        label = r["identifier"] + (THIS_ISSUE if r["identifier"] == survivor else "")
        rows.append("| %s | %s | %s |" % (label, (r["title"] or "").replace("|", "\\|"), cell))

    return "\n".join([
        BLOCK_OPEN,
        "## Collapsed family — %d issues, one change" % len(merged),
        "",
        "These %d issues are the same machine-filed template with a different "
        "target in each. They are ONE change, not %d. Every member's specific "
        "target is enumerated below; a fix that covers the shape but skips one "
        "of these rows leaves that target dark, which is the whole reason these "
        "were collapsed instead of closed."
        % (len(merged), len(merged)),
        "",
        "| issue | title | target(s) |",
        "|---|---|---|",
        *rows,
        "",
        "kipi-key namespace: `%s`. Title template: `%s`."
        % (family["producer"] or "(human)", family["template"]),
        "",
        "<sub>`linear-collapse.py` %s. The absorbed issues are closed with a "
        "comment pointing here. Wrong call? Reopen any of them — nothing was "
        "deleted.</sub>" % ts,
        BLOCK_CLOSE,
    ])


def absorb_comment(family: dict, member: dict, ts: str | None = None,
                   roster_size: int | None = None) -> str:
    ts = ts or _now()
    targets = member_targets(member)
    mine = ", ".join("`%s`" % t for t in targets) if targets else "this issue's target"
    # The family size a member is told it belongs to is the ROSTER size, not the
    # size of this pass. On a resumed pass this pass sees only what is still open,
    # and a comment that says "one of 3" about a family of 5 is a permanent
    # miscount on a permanent object.
    size = roster_size if roster_size is not None else len(family["members"])
    return "\n".join([
        ABSORB_MARKER,
        "**Collapsed into %s** — one of %d template-identical issues filed by "
        "`%s`." % (family["survivor"]["identifier"], size,
                   family["producer"] or "a human"),
        "",
        "%s is enumerated in %s, so the family fix has to cover it. Closing here "
        "is bookkeeping, not a decision to skip the work."
        % (mine, family["survivor"]["identifier"]),
        "",
        "<sub>`linear-collapse.py` %s. If the family fix does not cover this "
        "target, reopen this issue — that is what the pointer is for.</sub>" % ts,
    ])


def splice_block(description: str, block: str) -> str:
    """Put `block` into `description`, replacing a previous one if present.

    Never edits a byte outside the markers. Returns the input unchanged when the
    block is already exactly right, so the caller can skip the write entirely.
    """
    desc = description or ""
    start = desc.find(BLOCK_OPEN)
    end = desc.find(BLOCK_CLOSE)
    if start != -1 and end != -1 and end > start:
        return desc[:start] + block + desc[end + len(BLOCK_CLOSE):]
    return (desc.rstrip() + "\n\n" + block) if desc.strip() else block


# The block's footer stamp is the ONLY part that changes on a pass that found
# nothing new, so the write decision has to ignore it.
STAMP_RE = re.compile(r"^<sub>`linear-collapse\.py` .*$", re.M)


def block_is_current(description: str | None, block: str) -> bool:
    """True when splicing `block` in would change nothing but the timestamp.

    Without this, every resumed pass rewrites the survivor's description forever
    -- a permanent object mutated to say the same thing with a newer clock.
    """
    desc = description or ""
    return STAMP_RE.sub("", splice_block(desc, block)) == STAMP_RE.sub("", desc)


# --- writing ---------------------------------------------------------------

def already_absorbed(issue: dict) -> bool:
    for c in ((issue.get("comments") or {}).get("nodes") or []):
        if ABSORB_MARKER in (c.get("body") or ""):
            return True
    return False


def is_closed(issue: dict) -> bool:
    return ((issue.get("state") or {}).get("type") or "") in CLOSED_STATE_TYPES


def append_record(audit_path: str, record: dict) -> dict:
    """One JSON line, flushed and fsynced BEFORE the caller writes anything else.

    sp-b5dcf944. The point is not tidiness: a run that dies at issue 20 of 49
    must still be able to say what happened to the first 20 permanent objects it
    touched. Batching this to the end is how that record was lost once already.
    """
    if audit_path:
        with open(audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    return record


class LinearWriter:
    """The only thing here that mutates a permanent Linear object."""

    def __init__(self, ls, close_state_id: str | None):
        self.ls = ls
        self.close_state_id = close_state_id

    def write_survivor_block(self, issue: dict, block: str) -> str:
        desc = issue.get("description") or ""
        new = splice_block(desc, block)
        if new == desc:
            return "dor-unchanged"
        self.ls.graphql(self.ls.ISSUE_UPDATE,
                        {"id": issue["id"], "input": {"description": new}})
        return "dor-written"

    def add_comment(self, issue: dict, body: str) -> str:
        self.ls.graphql(self.ls.COMMENT_CREATE,
                        {"input": {"issueId": issue["id"], "body": body}})
        return "comment-added"

    def close_issue(self, issue: dict) -> str:
        # 'canceled', never 'completed': marking an absorbed issue Done would
        # claim work was finished that nobody did, and that lie outlives the board.
        if not self.close_state_id:
            # PR #35 review finding 3: this used to RETURN "NOT-CLOSED (...)".
            # apply_family recorded the string as an outcome and main() counted
            # the family applied anyway, so a run that commented "collapsed" on
            # every absorbed issue and closed none printed "1/1 applied" and
            # exited 0. main() now refuses before the first write; this raise is
            # the backstop for any other caller.
            raise RuntimeError(
                "no canceled-type workflow state on this team, so %s cannot be "
                "closed. Refusing to leave a permanent 'collapsed' comment "
                "behind a close that cannot happen." % issue.get("identifier"))
        self.ls.graphql(self.ls.ISSUE_UPDATE,
                        {"id": issue["id"], "input": {"stateId": self.close_state_id}})
        return "closed"


# Every outcome that means the step actually did its job. Anything else is a step
# that did not happen, and `incomplete_steps` makes main() say so.
OK_OUTCOMES = ("dor-written", "dor-unchanged", "comment-added", "already-present",
               "closed", "already-closed")


def incomplete_steps(records: list) -> list:
    """[[issue, step, outcome], ...] for every step that did not do its job.

    The completion count is driven by what the records SAY happened, not by "the
    loop did not raise" (PR #35 review finding 3). A writer that reports a
    non-write is now a non-zero exit, whatever the reason it reports.
    """
    return [[r["issue"], r["step"], r["outcome"]] for r in records
            if r.get("outcome") not in OK_OUTCOMES]


def apply_family(family: dict, writer, audit_path: str, ts: str | None = None) -> list:
    """Write one family. Survivor roster first, then per member: comment, close.

    The order is the contract. A close with no pointer is an orphan: the issue is
    off the board and nothing links it to the survivor that inherited its target.
    So the comment always precedes the close, and each step's record hits disk
    before the next step runs.
    """
    ts = ts or _now()
    survivor = family["survivor"]
    # Read the previous pass's roster BEFORE writing over it. `family_size` is
    # what this pass can see (fetch_open hides what an earlier pass closed);
    # `roster_size` is the whole family the survivor now carries. Recording only
    # the first would make the audit file understate every resumed pass.
    prior_rows = parse_block_rows(survivor.get("description"))
    roster_size = len(family_rows(family, prior_rows))
    base = {"ts": ts, "survivor": survivor["identifier"],
            "template": family["template"], "producer": family["producer"],
            "family_size": len(family["members"]), "roster_size": roster_size}
    records = []

    block = survivor_block(family, ts, prior_rows)
    # The skip lives here, not in the writer: a test double that had to reproduce
    # it would be asserting its own logic instead of this file's.
    if block_is_current(survivor.get("description"), block):
        out = "dor-unchanged"
    else:
        out = writer.write_survivor_block(survivor, block)
    records.append(append_record(audit_path, dict(
        base, issue=survivor["identifier"], step="survivor-dor", outcome=out)))

    for member in family["absorbed"]:
        # Resume, do not skip: a member commented by a run that died before its
        # close must still get closed, or it stays open forever behind a pointer
        # that says it was collapsed.
        if already_absorbed(member):
            records.append(append_record(audit_path, dict(
                base, issue=member["identifier"], step="commented",
                outcome="already-present")))
        else:
            out = writer.add_comment(
                member, absorb_comment(family, member, ts, roster_size))
            records.append(append_record(audit_path, dict(
                base, issue=member["identifier"], step="commented", outcome=out)))

        if is_closed(member):
            records.append(append_record(audit_path, dict(
                base, issue=member["identifier"], step="closed",
                outcome="already-closed")))
        else:
            out = writer.close_issue(member)
            records.append(append_record(audit_path, dict(
                base, issue=member["identifier"], step="closed", outcome=out)))
    return records


# --- fetching --------------------------------------------------------------

def fetch_open(ls, team_id: str, project: str | None) -> list:
    issues, after = [], None
    while True:
        page = ls.graphql(ISSUES_Q, {"t": team_id, "a": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    out = [i for i in issues if not is_closed(i)]
    if project:
        out = [i for i in out if ((i.get("project") or {}).get("name") or "") == project]
    return out


def closed_state_id(ls, team_id: str) -> str | None:
    states = (((ls.graphql(ls.TEAM_STATES_QUERY, {"teamId": team_id}) or {})
               .get("team") or {}).get("states") or {}).get("nodes") or []
    for s in states:
        if s.get("type") == "canceled":
            return s["id"]
    return None


def load_issues(args):
    """(issues, ls, team_id). KIPI_COLLAPSE_FIXTURE is the offline seam.

    Same shape as KIPI_GH in linear-triage.py: the suite drives the real entry
    point with real argv and no network, so "dry run writes nothing" is asserted
    against the shipped code path rather than a reimplementation of it.
    """
    fixture = os.environ.get("KIPI_COLLAPSE_FIXTURE")
    if fixture:
        if args.apply:
            # There is no client behind the fixture, so --apply used to die in
            # closed_state_id() with `NoneType has no attribute graphql`. A
            # traceback is not a refusal: say what the seam is and exit 1.
            print("KIPI_COLLAPSE_FIXTURE is a read-only offline seam and cannot "
                  "--apply: there is no Linear connection behind it. Unset it to "
                  "write against the real board.", file=sys.stderr)
            raise SystemExit(1)
        return json.loads(Path(fixture).read_text()), None, None
    ls = _load(HERE / "linear-sync.py", "ls")
    team_id = ls.graphql('query{teams(filter:{key:{eq:"%s"}}){nodes{id}}}' % args.team,
                         {})["teams"]["nodes"][0]["id"]
    project = None if args.project == "all" else args.project
    return fetch_open(ls, team_id, project), ls, team_id


# --- main ------------------------------------------------------------------

def print_plan(families: list, total: int) -> None:
    absorbed = sum(len(f["absorbed"]) for f in families)
    print("%d open issue(s) scanned; %d family/families found covering %d issue(s)."
          % (total, len(families), sum(len(f["members"]) for f in families)))
    print("collapsing them takes the open count from %d to %d.\n"
          % (total, total - absorbed))
    for f in families:
        print("FAMILY  %-10s survivor, %d absorbed   template: %s"
              % (f["survivor"]["identifier"], len(f["absorbed"]), f["template"]))
        print("        kipi-key namespace: %s" % (f["producer"] or "(human)"))
        for m in f["members"]:
            targets = member_targets(m)
            mark = "SURVIVOR" if m is f["survivor"] else "absorb  "
            print("        %s %-10s %s" % (mark, m["identifier"],
                                           ", ".join(targets) or "(no explicit target)"))
        # What an earlier pass already collapsed into this survivor. The plan
        # would otherwise read as "this family is 3" for a family of 5, because
        # fetch_open() cannot show the two that pass closed.
        seen = {m["identifier"] for m in f["members"]}
        carried = [r for r in parse_block_rows(f["survivor"].get("description"))
                   if r["identifier"] not in seen]
        for r in carried:
            print("        kept     %-10s %s   (closed by an earlier pass)"
                  % (r["identifier"], ", ".join(r["targets"]) or "(no explicit target)"))
        if carried:
            print("        roster after this pass: %d row(s)" % (len(seen) + len(carried)))
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--team", default="ASK", help="Linear team key (default ASK)")
    ap.add_argument("--project", default="kipi-system",
                    help="only this project, or 'all' (default kipi-system)")
    ap.add_argument("--apply", action="store_true",
                    help="WRITE: survivor roster, absorb comments, close absorbed")
    ap.add_argument("--min-family", type=int, default=2,
                    help="smallest family to collapse (default 2)")
    ap.add_argument("--out", default="", help="audit JSONL path (default under q-system/output/)")
    args = ap.parse_args()

    issues, ls, team_id = load_issues(args)
    if not issues:
        print("no open issues to scan")
        return 0

    families = detect_families(issues, min_family=args.min_family)
    if not families:
        print("%d open issue(s) scanned; no duplicate-template family found."
              % len(issues))
        return 0

    print_plan(families, len(issues))

    if not args.apply:
        print("dry run — nothing was written. Re-run with --apply to collapse.")
        print("Read the roster above first: --apply closes %d permanent Linear "
              "objects." % sum(len(f["absorbed"]) for f in families))
        return 0

    # Preflight before the FIRST write, not per close. Every absorbed issue gets
    # a permanent "collapsed into X" comment immediately before its close; if the
    # close can never happen, those comments are a lie this script cannot retract.
    close_id = closed_state_id(ls, team_id)
    if not close_id:
        print("REFUSED: team %s has no canceled-type workflow state, so absorbed "
              "issues cannot be closed. Nothing was written. Commenting "
              "'collapsed' on %d permanent issues that then stay open is worse "
              "than not running." % (args.team,
                                     sum(len(f["absorbed"]) for f in families)),
              file=sys.stderr)
        return 9

    audit = args.out or str(REPO / DEFAULT_AUDIT.format(
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d")))
    Path(audit).parent.mkdir(parents=True, exist_ok=True)
    writer = LinearWriter(ls, close_id)

    done, partial, failed = 0, [], None
    try:
        for f in families:
            records = apply_family(f, writer, audit)
            bad = incomplete_steps(records)
            if bad:
                partial.append((f["survivor"]["identifier"], bad))
                print("PARTIAL %s: %d step(s) did not land"
                      % (f["survivor"]["identifier"], len(bad)))
                continue
            done += 1
            print("applied %s (+%d absorbed)" % (f["survivor"]["identifier"],
                                                 len(f["absorbed"])))
    except Exception as exc:  # noqa: BLE001 -- reported, never swallowed
        failed = "%s: %s" % (type(exc).__name__, exc)

    print("\naudit -> %s" % audit)
    if failed:
        print("INCOMPLETE: %d/%d family/families applied before the run stopped "
              "(%s). Every write that landed is in the audit file; re-running is "
              "safe and resumes." % (done, len(families), failed), file=sys.stderr)
        return 9
    if partial:
        # done is the count of families every step of which reported a real
        # write. A family with one dead step is not applied, and printing N/N
        # here was the half of finding 3 that needed no strange input to fire.
        print("INCOMPLETE: %d/%d family/families applied; %d had step(s) that "
              "did not land:" % (done, len(families), len(partial)), file=sys.stderr)
        for ident, bad in partial:
            for issue_id, step, outcome in bad:
                print("  %-10s %-12s %s" % (issue_id, step, outcome), file=sys.stderr)
        return 9
    print("%d/%d family/families applied." % (done, len(families)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
